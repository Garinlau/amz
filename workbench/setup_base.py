"""一键创建作图工作台的多维表格（7 张表 + 预置数据 + 常用视图）。

用法（在能连上飞书、并设置了 FEISHU_APP_ID / FEISHU_APP_SECRET 的电脑上）：
    python -m workbench.setup_base --share-email 你的飞书邮箱 [--folder 云盘文件夹token] [--demo]
    python -m workbench.setup_base --dry-run      # 只打印会建哪些表和栏目，不连飞书

建好后还要在飞书里手动加按钮和自动化，步骤见 docs/飞书手动设置.md。
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from . import config, schema
from .feishu import FeishuError, link_ids, text_of
from .worker import make_slots

ROOT = Path(__file__).resolve().parent.parent


def model_options(cfg: dict, section: str) -> dict:
    names = ["默认"] + list((cfg.get(section) or {}).get("models", {}).keys())
    return schema._opts(names)


def build_fields(table: str, fields: list[dict], table_ids: dict, cfg: dict) -> list[dict]:
    out = []
    for fd in fields:
        fd = copy.deepcopy(fd)
        link = fd.pop("_link", None)
        multiple = fd.pop("_multiple", True)
        if link:
            fd["property"] = {"table_id": table_ids[link], "multiple": multiple}
        if fd["field_name"] == "读图模型":
            fd["property"] = model_options(cfg, "vision")
        if fd["field_name"] == "出图模型":
            fd["property"] = model_options(cfg, "image")
        out.append(fd)
    return out


def create_table(fs, app: str, name: str, fields: list[dict]) -> str:
    """先整表一起建；不行就先建主栏目，再逐个补其它栏目（飞书不认栏目说明时去掉说明）。"""
    try:
        return fs.create_table(app, name, fields)
    except FeishuError as e:
        print(f"  整表创建失败（{e}），改为逐个栏目创建")
    first = {k: v for k, v in fields[0].items() if k != "description"}
    tid = fs.create_table(app, name, [first])
    for fd in fields[1:]:
        try:
            fs.create_field(app, tid, fd)
        except FeishuError:
            fs.create_field(app, tid, {k: v for k, v in fd.items() if k != "description"})
    return tid


def create_views(fs, app: str, tids: dict) -> list[str]:
    """尽量把常用视图建好；飞书接口设不上的（比如看板分组）返回给用户手动设。"""
    todo = []
    for table, name, vtype, filters, visible in schema.VIEWS:
        tid = tids[table]
        try:
            vid = fs.create_view(app, tid, name, vtype)
        except FeishuError as e:
            todo.append(f"「{table}」表新建视图「{name}」（{vtype}）：{e}")
            continue
        fields = {fd["field_name"]: fd for fd in fs.list_fields(app, tid)}
        prop = {}
        if filters:
            conds = []
            for fname, values in filters.items():
                fd = fields[fname]
                opts = {o["name"]: o["id"] for o in (fd.get("property") or {}).get("options", [])}
                conds.append({"field_id": fd["field_id"], "operator": "is",
                              "value": json.dumps([opts[v] for v in values if v in opts])})
            prop["filter_info"] = {"conjunction": "and", "conditions": conds}
        if visible:
            prop["hidden_fields"] = [fd["field_id"] for n, fd in fields.items() if n not in visible]
        if prop:
            try:
                fs.update_view(app, tid, vid, prop)
            except FeishuError as e:
                todo.append(f"「{table}」表的视图「{name}」筛选/隐藏栏目没设上，请手动设：{e}")
        if vtype == "kanban":
            todo.append(f"「{table}」表的视图「{name}」：请手动设为按「状态」分组")
    return todo


def seed_rows() -> dict:
    return {
        schema.T_GUIDE: schema.GUIDE_ROWS,
        schema.T_SIZE: schema.SIZE_ROWS,
        schema.T_TEMPLATE: schema.TEMPLATE_ROWS,
        schema.T_MODEL: schema.MODEL_ROWS,
    }


def add_demo(fs, app: str, tids: dict) -> None:
    """放一个示例产品（阔腿裤），建好图位和两个颜色，方便看表格好不好用。"""
    model_id = next((r["record_id"] for r in fs.search_records(app, tids[schema.T_MODEL])
                     if "金发" in text_of(r["fields"].get("名称"))), None)
    product = {"产品名": "弯刀蕾丝阔腿裤（示例）", "品类": "裤子",
               "卖点（英文）": "Elastic Drawstring Waist\nSide Pockets\nLace Hem\nSoft Lightweight Fabric",
               "材质": "71% Rayon, 29% Nylon", "露脸": schema.FACE_OPTIONS[0]}
    if model_id:
        product["模特"] = [model_id]
    pid = fs.create_records(app, tids[schema.T_PRODUCT], [product])[0]["record_id"]
    msg = make_slots(fs, app, tids, pid, "阔腿裤")
    fs.update_record(app, tids[schema.T_PRODUCT], pid, {"程序提示": msg})
    fs.create_records(app, tids[schema.T_COLOR], [
        {"名称": f"阔腿裤-{zh}", "产品": [pid], "颜色（英文）": en, "主推色": zh == "蓝色", "状态": schema.C_DRAFT}
        for zh, en in [("黑色", "Black"), ("蓝色", "Blue")]
    ])
    ref = ROOT / "briefs/pants-lace-wide-leg/images/s03-1.png"
    if ref.exists():
        slot2 = next(r for r in fs.search_records(app, tids[schema.T_SLOT])
                     if text_of(r["fields"].get("图位")) == "主图2" and pid in link_ids(r["fields"].get("产品")))
        tok = fs.upload_attachment(app, ref.name, ref.read_bytes())
        fs.update_record(app, tids[schema.T_SLOT], slot2["record_id"], {
            "参考图1": [{"file_token": tok}], "参考图1·参考什么": ["姿势", "场景/背景", "光线/色调"], "场景": "街拍"})


def build_base(fs, cfg: dict, name: str, folder: str = "", demo: bool = False,
               emails=(), openids=()) -> dict:
    app = fs.create_base(name, folder)
    app_token = app["app_token"]
    print(f"已创建多维表格：{app.get('url', '')}")
    default_tables = [t["table_id"] for t in fs.list_tables(app_token)]

    tids: dict[str, str] = {}
    for tname, fields in schema.TABLES:
        print(f"建表：{tname}")
        tids[tname] = create_table(fs, app_token, tname, build_fields(tname, fields, tids, cfg))

    for tid in default_tables:
        try:
            fs.delete_table(app_token, tid)
        except FeishuError as e:
            print(f"  删除默认空表失败，可手动删：{e}")

    for tname, rows in seed_rows().items():
        fs.create_records(app_token, tids[tname], rows)
        print(f"预置数据：{tname} {len(rows)} 行")

    todo = create_views(fs, app_token, tids)

    if demo:
        add_demo(fs, app_token, tids)
        print("已放入示例产品（阔腿裤）")

    for email in emails:
        fs.add_collaborator(app_token, "email", email)
        print(f"已加协作者：{email}")
    for oid in openids:
        fs.add_collaborator(app_token, "openid", oid)
        print(f"已加协作者：{oid}")
    return {"app_token": app_token, "url": app.get("url", ""), "tables": tids, "manual_todo": todo}


def main() -> None:
    ap = argparse.ArgumentParser(description="创建作图工作台多维表格")
    ap.add_argument("--name", default="亚马逊作图工作台")
    ap.add_argument("--folder", default="", help="放到哪个云盘文件夹（文件夹 token，可不填）")
    ap.add_argument("--share-email", action="append", default=[], help="建好后加为协作者的飞书账号邮箱，可多次填写")
    ap.add_argument("--share-openid", action="append", default=[], help="按 open_id 加协作者，可多次填写")
    ap.add_argument("--demo", action="store_true", help="放一个示例产品")
    ap.add_argument("--config")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    cfg = config.load(args.config)

    if args.dry_run:
        fake_ids = {name: f"<{name}>" for name, _ in schema.TABLES}
        for name, fields in schema.TABLES:
            print(f"\n【{name}】")
            for fd in build_fields(name, fields, fake_ids, cfg):
                desc = (fd.get("description") or {}).get("text", "")
                print(f"  - {fd['field_name']}  (类型 {fd['type']})  {desc}")
        return

    fs = config.feishu_client(cfg)
    info = build_base(fs, cfg, args.name, args.folder, args.demo, args.share_email, args.share_openid)
    (Path(__file__).parent / "base.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成。请把 app_token = \"{info['app_token']}\" 填进 workbench/config.toml 的 [feishu] 里。")
    print("接下来按 docs/飞书手动设置.md 加按钮和自动化（约 10 分钟）。")
    for item in info["manual_todo"]:
        print(f"  还要手动设：{item}")
    if not (args.share_email or args.share_openid):
        print("提醒：表格现在只有机器人自己能看，记得用 --share-email 加人，或在飞书里让机器人分享给你。")


if __name__ == "__main__":
    main()
