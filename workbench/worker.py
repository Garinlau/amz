"""后台程序：每隔一会儿看一次「作图任务」表，处理「▶ 提交读图」「▶ 确认出图」「↻ 重新出图」的行。

用法：
    python -m workbench.worker          # 一直跑
    python -m workbench.worker --once   # 只看一轮（调试用）
"""

from __future__ import annotations

import argparse
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
    """给运营看的错误，原样写进「出错信息」。"""


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

    # ---------- 读表 ----------

    def _record(self, table: str, record_id: str) -> dict:
        return self.fs.get_record(self.app, self.tables[table], record_id)["fields"]

    def _linked(self, table: str, value) -> list[dict]:
        return [self._record(table, rid) for rid in link_ids(value)]

    def _download(self, atts, limit: int = 99) -> list[bytes]:
        return [self.fs.download_attachment(a) for a in (atts or [])[:limit]]

    def pending(self, statuses: list[str]) -> list[dict]:
        cond = [{"field_name": "状态", "operator": "is", "value": [s]} for s in statuses]
        return self.fs.search_records(self.app, self.tables[schema.T_TASK],
                                      {"conjunction": "or", "conditions": cond})

    def set(self, record_id: str, fields: dict) -> None:
        self.fs.update_record(self.app, self.tables[schema.T_TASK], record_id, fields)

    # ---------- 把一行任务整理成要用的信息 ----------

    def collect(self, f: dict, need_product_images: bool) -> dict:
        image_type = text_of(f.get("图片类型"))
        if not image_type:
            raise TaskError("「图片类型」还没选")
        products = self._linked(schema.T_PRODUCT, f.get("产品"))
        variants = self._linked(schema.T_VARIANT, f.get("颜色款"))
        if not products and variants:
            products = self._linked(schema.T_PRODUCT, variants[0].get("产品"))
        if not products:
            raise TaskError("「产品」还没选")
        p = products[0]

        # 尺寸：任务里选了就用，没选按图片类型找默认
        sizes = self._linked(schema.T_SIZE, f.get("尺寸"))
        if not sizes:
            sizes = [r["fields"] for r in self.fs.search_records(self.app, self.tables[schema.T_SIZE])
                     if image_type in options_of(r["fields"].get("默认用于"))]
        if not sizes:
            raise TaskError(f"「尺寸规格」表里没有默认用于「{image_type}」的尺寸，请在任务里手动选一个尺寸")
        width, height = int(float(text_of(sizes[0].get("宽")) or 0)), int(float(text_of(sizes[0].get("高")) or 0))
        if width <= 0 or height <= 0:
            raise TaskError("选中的尺寸没填宽或高")

        # 模特：任务里选了就用，没选用颜色款的固定模特
        model_rows = self._linked(schema.T_MODEL, f.get("模特"))
        if not model_rows:
            for v in variants:
                model_rows = self._linked(schema.T_MODEL, v.get("固定模特"))
                if model_rows:
                    break
        model = model_rows[0] if model_rows else {}

        # 图片：我们的白底图 → 参考图 → 定妆照
        images, zh, en = [], [], []
        if need_product_images:
            for v in variants:
                for img in self._download(v.get("白底产品图"), MAX_PRODUCT_IMAGES):
                    images.append(img)
                    color = text_of(v.get("颜色（英文）")) or text_of(v.get("名称"))
                    zh.append(f"我们的产品白底图（{color}）")
                    en.append(f"PRODUCT image — our garment in {color}. Reproduce this garment exactly.")
            if not images:
                raise TaskError("选的颜色款里还没有「白底产品图」，出图时衣服没有依据。请先在「颜色款」表上传")
        for i in (1, 2):
            refs = self._download(f.get(f"参考图{i}"), 1)
            if refs:
                what = options_of(f.get(f"参考图{i}·参考什么"))
                images += refs
                zh.append(f"参考图{i}（竞品），只参考：{'、'.join(what) or '整体风格'}")
                en.append(f"STYLE REFERENCE {i} — borrow only: {', '.join(what) or 'overall mood'}. "
                          "Do not copy its person, face, garment or text.")
        face_ref = self._download(model.get("定妆照"), 1)
        if face_ref and need_product_images:
            images += face_ref
            zh.append("模特定妆照")
            en.append("MODEL REFERENCE — keep the same face, skin tone, hair and body as this person.")

        return {
            "product_name": text_of(p.get("产品名")),
            "category": text_of(p.get("品类")),
            "selling_points": text_of(p.get("卖点（英文）")),
            "material": text_of(p.get("材质")),
            "colors": "、".join(text_of(v.get("颜色（英文）")) for v in variants),
            "image_type": image_type,
            "width": width, "height": height,
            "model_desc": text_of(model.get("英文描述")),
            "model_change": text_of(f.get("模特要改什么")),
            "face": text_of(f.get("露脸")) or schema.FACE_OPTIONS[0],
            "scene": text_of(f.get("场景")),
            "extra": text_of(f.get("其它要求")),
            "images": images, "labels_zh": zh, "labels_en": en,
            "instruction": text_of(f.get("出图说明（英文）")),
            "feedback": text_of(f.get("验收意见")) if text_of(f.get("状态")) == schema.S_REDO else "",
            "n": int(text_of(f.get("出几张")) or 1),
        }

    # ---------- 读图 ----------

    def do_read(self, rec: dict) -> None:
        rid, f = rec["record_id"], rec["fields"]
        self.set(rid, {"状态": schema.S_READING, "出错信息": ""})
        t = self.collect(f, need_product_images=False)
        # 读图时也把白底图给模型看，方便它描述我们的衣服；没有也不拦
        product_imgs, labels = [], []
        for v in self._linked(schema.T_VARIANT, f.get("颜色款")):
            for img in self._download(v.get("白底产品图"), 2):
                product_imgs.append(img)
                labels.append(f"我们的产品白底图（{text_of(v.get('颜色（英文）'))}）")
        t["image_labels"] = labels + t["labels_zh"]
        images = product_imgs + t["images"]
        if not images and not t["extra"] and not t["scene"]:
            raise TaskError("没有参考图，也没写场景和其它要求，AI 没东西可读")
        out = models.read_images(self.cfg, text_of(f.get("读图模型")), prompts.READ_SYSTEM,
                                 prompts.read_user_text(t), images)
        instruction = str(out.get("出图说明", "")).strip()
        if not instruction:
            raise TaskError("读图模型没写出图说明，请重新提交读图或换个读图模型")
        model_desc = str(out.get("模特描述", "")).strip()
        if model_desc:
            instruction += f"\n\nModel: {model_desc}"
        self.set(rid, {
            "AI·参考图画面描述": str(out.get("画面描述", "")),
            "AI·参考图上的文字": str(out.get("图上文字", "")),
            "AI·建议": str(out.get("建议", "")),
            "AI·优化后英文文案": str(out.get("英文文案", "")),
            "出图说明（英文）": instruction,
            "状态": schema.S_REVIEW,
        })

    # ---------- 出图 ----------

    def do_generate(self, rec: dict) -> None:
        rid, f = rec["record_id"], rec["fields"]
        if not text_of(f.get("出图说明（英文）")).strip():
            raise TaskError("「出图说明（英文）」是空的。请先选「▶ 提交读图」让 AI 写，或自己写好再确认出图")
        self.set(rid, {"状态": schema.S_GENERATING, "出错信息": ""})
        t = self.collect(f, need_product_images=True)
        t["image_labels"] = [f"Image {i + 1}: {label}" for i, label in enumerate(t["labels_en"])]
        # 出图说明里已经带了 AI 写的模特描述，就不再重复
        if "Model:" in t["instruction"]:
            t["model_desc"] = ""
        prompt = prompts.generation_prompt(t)
        raw = models.generate(self.cfg, text_of(f.get("出图模型")), prompt, t["images"],
                              t["width"], t["height"], t["n"])

        tag = self.tag_synthetic and t["image_type"] not in prompts.NO_PERSON_TYPES
        max_bytes = 2 * 1024 * 1024 if t["image_type"] in SMALL_FILE_TYPES else 0
        count = int(float(text_of(f.get("出图次数")) or 0)) + 1
        name = text_of(f.get("任务名")) or rid
        folder = self.save_dir / rid
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"第{count}次-提示词.txt").write_text(prompt, encoding="utf-8")

        tokens = []
        for i, img in enumerate(raw, 1):
            jpg = imaging.to_jpeg(imaging.fit(img, t["width"], t["height"]), tag, max_bytes)
            fname = f"{name}-第{count}次-{i}.jpg".replace("/", "-")
            (folder / fname).write_bytes(jpg)
            tokens.append({"file_token": self.fs.upload_attachment(self.app, fname, jpg)})
        self.set(rid, {"生成结果": tokens, "状态": schema.S_ACCEPT, "出图次数": count})

    # ---------- 主循环 ----------

    def run_once(self) -> int:
        done = 0
        for statuses, handler in (([schema.S_READ], self.do_read),
                                  ([schema.S_GENERATE, schema.S_REDO], self.do_generate)):
            for rec in self.pending(statuses):
                name = text_of(rec["fields"].get("任务名")) or rec["record_id"]
                log.info("处理 %s（%s）", name, text_of(rec["fields"].get("状态")))
                try:
                    handler(rec)
                    done += 1
                except (TaskError, models.ModelError) as e:
                    self._fail(rec["record_id"], str(e))
                except Exception as e:  # noqa: BLE001  一行出错不影响其它行
                    log.error("处理 %s 出错\n%s", name, traceback.format_exc())
                    self._fail(rec["record_id"], f"程序出错：{e}")
        return done

    def _fail(self, rid: str, msg: str) -> None:
        log.warning("失败：%s", msg)
        try:
            self.set(rid, {"状态": schema.S_ERROR, "出错信息": msg[:2000]})
        except Exception:  # noqa: BLE001
            log.error("连写出错信息都失败了\n%s", traceback.format_exc())


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
