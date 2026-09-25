"""后台程序：每隔一会儿看一次表格，处理按钮写进来的活。

    产品.指令 = 生成图位 / 整套读图
    图位.状态 = 读图排队                   → AI 读图，写出图说明 → 待审核
    图位.状态 = 出图排队 / 重做排队（A+）  → 出 A+ / 品牌故事 → 待验收
    颜色套图.状态 = 出图排队 / 重做排队    → 用这个颜色的白底图出齐已确认的主图 → 待验收

用法：
    python -m workbench.worker          # 一直跑
    python -m workbench.worker --once   # 只看一轮（调试用）
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import time
import traceback
from pathlib import Path

from . import config, imaging, models, prompts, schema
from .feishu import link_ids, options_of, text_of

log = logging.getLogger("workbench")

MAX_PRODUCT_IMAGES = 4
SMALL_FILE_TYPES = set(schema.APLUS_TYPES + schema.STORY_TYPES)  # A+ / 品牌故事单张 2MB 以内


class TaskError(Exception):
    """给运营看的错误，原样写进「程序提示」。"""


def zh_hash(text: str) -> str:
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:12]


class Worker:
    def __init__(self, cfg: dict, fs=None):
        self.cfg = cfg
        self.fs = fs or config.feishu_client(cfg)
        self.app = cfg["feishu"].get("app_token") or ""
        if not self.app:
            raise SystemExit("config.toml 里的 [feishu] app_token 还没填，先运行建表程序")
        self.tables = {t["name"]: t["table_id"] for t in self.fs.list_tables(self.app)}
        missing = [n for n, _ in schema.TABLES if n not in self.tables]
        if missing:
            raise SystemExit(f"多维表格里缺少这些表：{missing}")
        wk = cfg.get("worker", {})
        self.save_dir = Path(wk.get("save_dir", "output"))
        self.tag_synthetic = wk.get("tag_synthetic_people", True)

    # ---------- 读写表格的小工具 ----------

    def rows(self, table: str, filter_: dict | None = None) -> list[dict]:
        return self.fs.search_records(self.app, self.tables[table], filter_)

    def by_status(self, table: str, field: str, values: list[str]) -> list[dict]:
        cond = [{"field_name": field, "operator": "is", "value": [v]} for v in values]
        return self.rows(table, {"conjunction": "or", "conditions": cond})

    def get(self, table: str, record_id: str) -> dict:
        return self.fs.get_record(self.app, self.tables[table], record_id)["fields"]

    def linked(self, table: str, value) -> list[dict]:
        return [self.get(table, rid) for rid in link_ids(value)]

    def set(self, table: str, record_id: str, fields: dict) -> None:
        self.fs.update_record(self.app, self.tables[table], record_id, fields)

    def download(self, atts, limit: int = 99) -> list[bytes]:
        return [self.fs.download_attachment(a) for a in (atts or [])[:limit]]

    def product_slots(self, product_id: str) -> list[dict]:
        return [r for r in self.rows(schema.T_SLOT) if product_id in link_ids(r["fields"].get("产品"))]

    def product_colors(self, product_id: str) -> list[dict]:
        return [r for r in self.rows(schema.T_COLOR) if product_id in link_ids(r["fields"].get("产品"))]

    # ---------- 产品上的指令 ----------

    def do_product(self, rec: dict) -> None:
        pid, f = rec["record_id"], rec["fields"]
        cmd = text_of(f.get("指令"))
        if cmd == schema.P_MAKE_SLOTS:
            msg = make_slots(self.fs, self.app, self.tables, pid, text_of(f.get("产品名")))
        elif cmd == schema.P_READ_ALL:
            queued, no_ref = [], []
            for s in self.product_slots(pid):
                sf = s["fields"]
                if text_of(sf.get("状态")) not in (schema.D_DRAFT, schema.D_ERROR, ""):
                    continue
                slot = text_of(sf.get("图位"))
                if not (sf.get("参考图1") or sf.get("参考图2") or text_of(sf.get("场景")) or text_of(sf.get("其它要求"))):
                    no_ref.append(slot)
                    continue
                self.set(schema.T_SLOT, s["record_id"], {"状态": schema.D_READ_Q, "程序提示": ""})
                queued.append(slot)
            msg = f"已提交读图：{'、'.join(queued) or '无'}。"
            if no_ref:
                msg += f"没有参考图也没写要求，先跳过：{'、'.join(no_ref)}。"
            msg += "（已经读过、审核过的图位不会重读，要重读请在那一行点「读图」）"
        else:
            msg = f"不认识的指令：{cmd}"
        self.set(schema.T_PRODUCT, pid, {"指令": None, "程序提示": msg})

    # ---------- 把一个图位整理成要用的信息 ----------

    def slot_spec(self, sf: dict, product: dict, model: dict) -> dict:
        slot = text_of(sf.get("图位"))
        image_type = text_of(sf.get("图片类型"))
        if not image_type:
            raise TaskError(f"{slot or '这个图位'}还没选「图片类型」")
        sizes = self.linked(schema.T_SIZE, sf.get("尺寸"))
        if not sizes:
            sizes = [r["fields"] for r in self.rows(schema.T_SIZE)
                     if image_type in options_of(r["fields"].get("默认用于"))]
        if not sizes:
            raise TaskError(f"「尺寸规格」表里没有默认用于「{image_type}」的尺寸，请在图位里手动选一个尺寸")
        width = int(float(text_of(sizes[0].get("宽")) or 0))
        height = int(float(text_of(sizes[0].get("高")) or 0))
        if width <= 0 or height <= 0:
            raise TaskError("选中的尺寸没填宽或高")

        refs, labels_zh, labels_en = [], [], []
        for i in (1, 2):
            got = self.download(sf.get(f"参考图{i}"), 1)
            if got:
                what = options_of(sf.get(f"参考图{i}·参考什么"))
                refs += got
                labels_zh.append(f"参考图{i}（竞品），只参考：{'、'.join(what) or '整体风格'}")
                labels_en.append(f"STYLE REFERENCE {i} — borrow only: {', '.join(what) or 'overall mood'}. "
                                 "Do not copy its person, face, garment or text.")
        return {
            "slot": slot,
            "product_name": text_of(product.get("产品名")),
            "category": text_of(product.get("品类")),
            "selling_points": text_of(product.get("卖点（英文）")),
            "material": text_of(product.get("材质")),
            "image_type": image_type,
            "width": width, "height": height,
            "model_desc": text_of(model.get("英文描述")),
            "model_change": text_of(sf.get("模特要改什么")),
            "face": text_of(product.get("露脸")) or schema.FACE_OPTIONS[0],
            "scene": text_of(sf.get("场景")),
            "extra": text_of(sf.get("其它要求")),
            "refs": refs, "ref_labels_zh": labels_zh, "ref_labels_en": labels_en,
            "n": int(text_of(sf.get("出几张")) or 1),
            "vision": text_of(sf.get("读图模型")),
            "painter": text_of(sf.get("出图模型")),
        }

    def product_of(self, fields: dict) -> tuple[str, dict]:
        ids = link_ids(fields.get("产品"))
        if not ids:
            raise TaskError("「产品」还没选")
        return ids[0], self.get(schema.T_PRODUCT, ids[0])

    def model_of(self, product: dict, color: dict | None = None) -> dict:
        rows = self.linked(schema.T_MODEL, (color or {}).get("换模特")) or self.linked(schema.T_MODEL, product.get("模特"))
        return rows[0] if rows else {}

    # ---------- 读图 ----------

    def do_read(self, rec: dict) -> None:
        rid, sf = rec["record_id"], rec["fields"]
        self.set(schema.T_SLOT, rid, {"状态": schema.D_READING, "程序提示": ""})
        pid, product = self.product_of(sf)
        t = self.slot_spec(sf, product, self.model_of(product))
        # 读图时也给模型看一眼我们的白底图（主推色优先），方便它描述衣服；没有也不拦
        product_imgs, labels = [], []
        colors = sorted((c for c in self.product_colors(pid) if c["fields"].get("白底产品图")),
                        key=lambda r: not r["fields"].get("主推色"))
        if colors:
            product_imgs = self.download(colors[0]["fields"].get("白底产品图"), 2)
            labels = ["我们的产品白底图"] * len(product_imgs)
        t["image_labels"] = labels + t["ref_labels_zh"]
        images = product_imgs + t["refs"]
        if not t["refs"] and not t["extra"] and not t["scene"]:
            raise TaskError("没有参考图，也没写场景和其它要求，AI 没东西可读")
        out = models.read_images(self.cfg, t["vision"], prompts.READ_SYSTEM, prompts.read_user_text(t), images)
        zh = str(out.get("出图说明中文", "")).strip()
        en = str(out.get("出图说明英文", "")).strip()
        if not zh or not en:
            raise TaskError("读图模型没写出图说明，请再点一次「读图」或换个读图模型")
        self.set(schema.T_SLOT, rid, {
            "AI·参考图画面描述": str(out.get("画面描述", "")),
            "AI·参考图上的文字": str(out.get("图上文字", "")),
            "AI·建议": str(out.get("建议", "")),
            "AI·优化后英文文案": str(out.get("英文文案", "")),
            "出图说明（中文）": zh,
            "出图说明（英文）": en,
            "英文版依据": zh_hash(zh),
            "状态": schema.D_REVIEW,
        })

    def english_instruction(self, rid: str, sf: dict, vision: str) -> str:
        """审核人改的是中文；中文变了就重新翻成英文再用。"""
        zh = text_of(sf.get("出图说明（中文）")).strip()
        en = text_of(sf.get("出图说明（英文）")).strip()
        if not zh and not en:
            raise TaskError(f"{text_of(sf.get('图位'))}的出图说明是空的，请先读图")
        if zh and zh_hash(zh) != text_of(sf.get("英文版依据")).strip():
            out = models.read_images(self.cfg, vision, prompts.TRANSLATE_SYSTEM, zh, [])
            en = str(out.get("英文", "")).strip()
            if not en:
                raise TaskError("把中文出图说明翻成英文时失败了，请再试一次")
            self.set(schema.T_SLOT, rid, {"出图说明（英文）": en, "英文版依据": zh_hash(zh)})
        return en

    # ---------- 出图（公共部分） ----------

    def paint(self, t: dict, product_imgs: list[bytes], product_labels: list[str], model: dict,
              instruction: str, feedback: str, file_stem: str, folder: Path) -> list[dict]:
        images, labels = list(product_imgs), list(product_labels)
        images += t["refs"]
        labels += t["ref_labels_en"]
        face = self.download(model.get("定妆照"), 1)
        if face:
            images += face
            labels.append("MODEL REFERENCE — keep the same face, skin tone, hair and body as this person.")
        t = {**t, "instruction": instruction, "feedback": feedback,
             "image_labels": [f"Image {i + 1}: {x}" for i, x in enumerate(labels)]}
        prompt = prompts.generation_prompt(t)
        raw = models.generate(self.cfg, t["painter"], prompt, images, t["width"], t["height"], t["n"])

        tag = self.tag_synthetic and t["image_type"] not in prompts.NO_PERSON_TYPES
        max_bytes = 2 * 1024 * 1024 if t["image_type"] in SMALL_FILE_TYPES else 0
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{file_stem}-提示词.txt").write_text(prompt, encoding="utf-8")
        tokens = []
        for i, img in enumerate(raw, 1):
            jpg = imaging.to_jpeg(imaging.fit(img, t["width"], t["height"]), tag, max_bytes)
            name = f"{file_stem}-{i}.jpg".replace("/", "-")
            (folder / name).write_bytes(jpg)
            tokens.append({"file_token": self.fs.upload_attachment(self.app, name, jpg)})
        return tokens

    def white_images(self, color_fields: dict) -> tuple[list[bytes], list[str]]:
        color = text_of(color_fields.get("颜色（英文）")) or text_of(color_fields.get("名称"))
        imgs = self.download(color_fields.get("白底产品图"), MAX_PRODUCT_IMAGES)
        return imgs, [f"PRODUCT image — our garment in {color}. Reproduce this garment exactly."] * len(imgs)

    # ---------- 颜色套图：出整套主图 ----------

    def do_color(self, rec: dict) -> None:
        cid, cf = rec["record_id"], rec["fields"]
        redo = text_of(cf.get("状态")) == schema.C_REDO_Q
        pid, product = self.product_of(cf)
        color_name = text_of(cf.get("颜色（英文）"))
        name = text_of(cf.get("名称")) or f"{text_of(product.get('产品名'))}-{color_name}"
        self.set(schema.T_COLOR, cid, {"状态": schema.C_GENERATING, "程序提示": "", "名称": name})

        product_imgs, product_labels = self.white_images(cf)
        if not product_imgs:
            raise TaskError("这个颜色还没上传「白底产品图」，出图时衣服没有依据")
        slots = {text_of(s["fields"].get("图位")): s for s in self.product_slots(pid)}
        main = [s for s in schema.MAIN_SLOTS if s in slots]
        if not main:
            raise TaskError("这个产品还没有主图图位，请先在「产品」表点「生成图位」")
        if redo:
            targets = [s for s in options_of(cf.get("要重做的图")) if s in slots]
            if not targets:
                raise TaskError("点「重做选中的图」之前，先在「要重做的图」里勾上要重做的图位")
            feedback = text_of(cf.get("验收意见"))
        else:
            targets, feedback = main, ""

        model = self.model_of(product, cf)
        count = int(float(text_of(cf.get("出图次数")) or 0)) + 1
        folder = self.save_dir / name
        done, skipped, failed = [], [], []
        for slot in targets:
            srec = slots[slot]
            sf = srec["fields"]
            if text_of(sf.get("状态")) not in (schema.D_OK, schema.D_PASS):
                skipped.append(slot)
                continue
            try:
                t = self.slot_spec(sf, product, model)
                en = self.english_instruction(srec["record_id"], sf, t["vision"])
                tokens = self.paint(t, product_imgs, product_labels, model, en, feedback,
                                    f"{name}-{slot}-第{count}次", folder)
                self.set(schema.T_COLOR, cid, {f"{slot}结果": tokens})   # 出一张放一张，边出边能看
                done.append(slot)
            except (TaskError, models.ModelError) as e:
                failed.append(f"{slot}：{e}")

        notes = [f"本次出图：{'、'.join(done) or '无'}"]
        if skipped:
            notes.append(f"还没审核确认、没有出图：{'、'.join(skipped)}")
        if failed:
            notes.append("出错：\n" + "\n".join(failed))
        fields = {"程序提示": "\n".join(notes), "出图次数": count,
                  "状态": schema.C_ACCEPT if done else schema.C_ERROR}
        if redo and done:
            fields["要重做的图"] = [s for s in options_of(cf.get("要重做的图")) if s not in done]
        self.set(schema.T_COLOR, cid, fields)

    # ---------- A+ / 品牌故事：在图位那一行出图 ----------

    def do_aplus(self, rec: dict) -> None:
        rid, sf = rec["record_id"], rec["fields"]
        slot = text_of(sf.get("图位"))
        redo = text_of(sf.get("状态")) == schema.D_REDO_Q
        if not schema.is_aplus(slot):
            self.set(schema.T_SLOT, rid, {"状态": schema.D_OK,
                                          "程序提示": "主图在「颜色套图」表里按颜色出图，这里不用点出图"})
            return
        self.set(schema.T_SLOT, rid, {"状态": schema.D_GENERATING, "程序提示": ""})
        pid, product = self.product_of(sf)
        model = self.model_of(product)
        t = self.slot_spec(sf, product, model)
        colors = self.product_colors(pid)
        if t["image_type"] != "A+多色展示":
            colors = [c for c in colors if c["fields"].get("主推色")] or colors[:1]
        imgs, labels = [], []
        for c in colors:
            a, b = self.white_images(c["fields"])
            imgs += a[:2]
            labels += b[:2]
        if not imgs:
            raise TaskError("这个产品的颜色款还没上传白底产品图（A+ 用主推色）")
        en = self.english_instruction(rid, sf, t["vision"])
        count = len(sf.get("A+成品") or []) + 1
        tokens = self.paint(t, imgs, labels, model, en, text_of(sf.get("A+验收意见")) if redo else "",
                            f"{text_of(sf.get('名称')) or slot}-第{count}次", self.save_dir / text_of(product.get("产品名")))
        self.set(schema.T_SLOT, rid, {"A+成品": tokens, "状态": schema.D_ACCEPT})

    # ---------- 主循环 ----------

    JOBS = [
        (schema.T_PRODUCT, "指令", schema.PRODUCT_COMMANDS, "do_product", None),
        (schema.T_SLOT, "状态", [schema.D_READ_Q], "do_read", schema.D_ERROR),
        (schema.T_SLOT, "状态", [schema.D_GEN_Q, schema.D_REDO_Q], "do_aplus", schema.D_ERROR),
        (schema.T_COLOR, "状态", [schema.C_GEN_Q, schema.C_REDO_Q], "do_color", schema.C_ERROR),
    ]

    def run_once(self) -> int:
        done = 0
        for table, field, values, handler, err_status in self.JOBS:
            for rec in self.by_status(table, field, values):
                label = text_of(rec["fields"].get("名称") or rec["fields"].get("产品名")) or rec["record_id"]
                log.info("处理 %s / %s（%s）", table, label, text_of(rec["fields"].get(field)))
                try:
                    getattr(self, handler)(rec)
                    done += 1
                except (TaskError, models.ModelError) as e:
                    self._fail(table, rec["record_id"], err_status, str(e))
                except Exception as e:  # noqa: BLE001  一行出错不影响其它行
                    log.error("处理 %s 出错\n%s", label, traceback.format_exc())
                    self._fail(table, rec["record_id"], err_status, f"程序出错：{e}")
        return done

    def _fail(self, table: str, rid: str, err_status: str | None, msg: str) -> None:
        log.warning("失败：%s", msg)
        fields = {"程序提示": msg[:2000]}
        if err_status:
            fields["状态"] = err_status
        else:
            fields["指令"] = None
        try:
            self.set(table, rid, fields)
        except Exception:  # noqa: BLE001
            log.error("连写出错信息都失败了\n%s", traceback.format_exc())


def make_slots(fs, app: str, tables: dict, product_id: str, product_name: str) -> str:
    """按「套图模板」给产品建图位；已经有的图位不重复建。"""
    tid = tables[schema.T_SLOT]
    existing = {text_of(r["fields"].get("图位")) for r in fs.search_records(app, tid)
                if product_id in link_ids(r["fields"].get("产品"))}
    rows = []
    for r in fs.search_records(app, tables[schema.T_TEMPLATE]):
        tf = r["fields"]
        slot = text_of(tf.get("图位"))
        if not tf.get("启用") or not slot or slot in existing:
            continue
        rows.append({"名称": f"{product_name}-{slot}", "产品": [product_id], "图位": slot,
                     "图片类型": text_of(tf.get("图片类型")) or None, "状态": schema.D_DRAFT,
                     "其它要求": text_of(tf.get("默认要求"))})
    rows = [{k: v for k, v in r.items() if v is not None} for r in rows]
    if rows:
        fs.create_records(app, tid, rows)
    msg = f"已建 {len(rows)} 个图位：{'、'.join(r['图位'] for r in rows) or '无'}"
    if existing:
        msg += f"（已存在、没重复建：{'、'.join(sorted(existing))}）"
    return msg


def main() -> None:
    ap = argparse.ArgumentParser(description="作图工作台后台程序")
    ap.add_argument("--config")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = config.load(args.config)
    w = Worker(cfg)
    poll = int(cfg.get("worker", {}).get("poll_seconds", 30))
    log.info("开始工作，每 %s 秒看一次表格", poll)
    while True:
        try:
            w.run_once()
        except Exception:  # noqa: BLE001  网络抖动等，下一轮再来
            log.error("这一轮出错\n%s", traceback.format_exc())
        if args.once:
            break
        time.sleep(poll)


if __name__ == "__main__":
    main()
