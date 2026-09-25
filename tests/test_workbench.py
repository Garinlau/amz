"""用一个假的飞书把整条流程跑一遍：
建表 → 生成图位 → 整套读图 → 审核（改中文）→ 确认 → 颜色出整套图 → 选图重做 → A+ 出图。"""

import io
import itertools

import pytest
from PIL import Image

from workbench import imaging, models, schema, setup_base, worker
from workbench.feishu import FeishuError

CFG = {
    "feishu": {"app_token": ""},
    "worker": {"poll_seconds": 1, "save_dir": "", "tag_synthetic_people": True},
    "vision": {"default": "grok", "models": {"grok": {}}},
    "image": {"default": "nano-banana", "models": {"nano-banana": {}, "gpt-image-local": {}}},
}


def png(w=64, h=64, color="red"):
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "PNG")
    return b.getvalue()


class FakeFeishu:
    """按飞书返回值的样子模拟：文本栏读出来是分段列表，关联栏是 link_record_ids。"""

    def __init__(self):
        self.ids = itertools.count(1)
        self.tables = {}   # table_id -> {"name", "fields": {name: field}, "rows": {rid: fields}, "views": []}
        self.files = {}
        self.shared = []

    def _id(self, p):
        return f"{p}{next(self.ids)}"

    def create_base(self, name, folder=""):
        self.tables[self._id("tbl")] = {"name": "数据表", "fields": {"文本": {"type": 1}}, "rows": {}, "views": []}
        return {"app_token": "app1", "url": "https://example/base/app1"}

    def list_tables(self, app):
        return [{"table_id": k, "name": v["name"]} for k, v in self.tables.items()]

    def create_table(self, app, name, fields):
        stored = {}
        for fd in fields:
            if fd["type"] == schema.LINK:
                assert fd["property"]["table_id"] in self.tables
            fd = dict(fd, field_id=self._id("fld"))
            if "options" in (fd.get("property") or {}):
                fd["property"] = {"options": [dict(o, id=self._id("opt")) for o in fd["property"]["options"]]}
            stored[fd["field_name"]] = fd
        tid = self._id("tbl")
        self.tables[tid] = {"name": name, "fields": stored, "rows": {}, "views": []}
        return tid

    def delete_table(self, app, tid):
        del self.tables[tid]

    def list_fields(self, app, tid):
        return list(self.tables[tid]["fields"].values())

    def create_view(self, app, tid, name, vtype="grid"):
        self.tables[tid]["views"].append({"name": name, "type": vtype})
        return self._id("vew")

    def update_view(self, app, tid, vid, prop):
        self.tables[tid]["views"][-1]["prop"] = prop

    def _check(self, tid, fields):
        for k, v in fields.items():
            fd = self.tables[tid]["fields"].get(k)
            if not fd:
                raise FeishuError(f"没有栏目 {k}")
            opts = [o["name"] for o in (fd.get("property") or {}).get("options", [])]
            vals = v if isinstance(v, list) else [v]
            if opts and fd["type"] in (schema.SINGLE, schema.MULTI):
                bad = [x for x in vals if x is not None and x not in opts]
                assert not bad, f"{k} 没有选项 {bad}"

    def create_records(self, app, tid, rows):
        out = []
        for r in rows:
            self._check(tid, r)
            rid = self._id("rec")
            self.tables[tid]["rows"][rid] = dict(r)
            out.append({"record_id": rid, "fields": r})
        return out

    def update_record(self, app, tid, rid, fields):
        self._check(tid, fields)
        self.tables[tid]["rows"][rid].update(fields)

    def _out(self, tid, fields):
        res = {}
        for k, v in fields.items():
            if v is None:
                continue
            t = self.tables[tid]["fields"][k]["type"]
            if t == schema.TEXT and isinstance(v, str):
                res[k] = [{"type": "text", "text": v}]
            elif t == schema.LINK:
                res[k] = {"link_record_ids": list(v)}
            elif t == schema.ATTACHMENT:
                res[k] = [{"file_token": a["file_token"], "name": a["file_token"]} for a in v]
            else:
                res[k] = v
        return res

    def search_records(self, app, tid, filter_=None):
        rows = []
        for rid, f in self.tables[tid]["rows"].items():
            if filter_ and not any(f.get(c["field_name"]) == c["value"][0] for c in filter_["conditions"]):
                continue
            rows.append({"record_id": rid, "fields": self._out(tid, f)})
        return rows

    def get_record(self, app, tid, rid):
        return {"record_id": rid, "fields": self._out(tid, self.tables[tid]["rows"][rid])}

    def upload_attachment(self, app, name, content):
        tok = self._id("file")
        self.files[tok] = content
        return tok

    def download_attachment(self, att):
        return self.files[att["file_token"]]

    def add_collaborator(self, token, member_type, member_id, perm="full_access"):
        self.shared.append((member_type, member_id))

    # 小工具
    def rows(self, name):
        return next(v for v in self.tables.values() if v["name"] == name)["rows"]

    def find(self, table, **kw):
        return next((rid, r) for rid, r in self.rows(table).items() if all(r.get(k) == v for k, v in kw.items()))


@pytest.fixture
def env(tmp_path, monkeypatch):
    fs = FakeFeishu()
    info = setup_base.build_base(fs, CFG, "测试", demo=True, emails=["a@b.com"])
    cfg = {**CFG, "feishu": {"app_token": info["app_token"]},
           "worker": {**CFG["worker"], "save_dir": str(tmp_path)}}
    calls = {"read": [], "gen": []}

    def fake_read(cfg, name, system, text, images):
        calls["read"].append((system, text, len(images)))
        if system == worker.prompts.TRANSLATE_SYSTEM:
            return {"英文": "EN:" + text}
        return {"画面描述": "街头站姿", "图上文字": "无", "建议": "保留姿势", "英文文案": "Breezy Elegance",
                "出图说明中文": "模特在街头行走", "出图说明英文": "Model walking on the street."}

    def fake_gen(cfg, name, prompt, images, width, height, n):
        calls["gen"].append((prompt, len(images), width, height, n))
        return [png(1024, 1536, "blue") for _ in range(n)]

    monkeypatch.setattr(models, "read_images", fake_read)
    monkeypatch.setattr(models, "generate", fake_gen)
    return fs, worker.Worker(cfg, fs), calls, info


def test_setup_creates_tables_views_and_demo(env):
    fs, _, _, info = env
    assert {v["name"] for v in fs.tables.values()} == {n for n, _ in schema.TABLES}
    assert len(fs.rows(schema.T_TEMPLATE)) == len(schema.TEMPLATE_ROWS)
    assert fs.shared == [("email", "a@b.com")]
    # 示例产品已按模板建好 12 个图位
    assert len(fs.rows(schema.T_SLOT)) == len(schema.TEMPLATE_ROWS)
    # 视图：待审核的筛选用的是选项编号
    views = {v["name"]: v for t in fs.tables.values() for v in t["views"]}
    assert set(views) == {n for _, n, *_ in schema.VIEWS}
    assert "filter_info" in views["待审核"]["prop"] and "hidden_fields" in views["待审核"]["prop"]
    assert any("看板" in x for x in info["manual_todo"])


def test_make_slots_does_not_duplicate(env):
    fs, w, _, _ = env
    pid, _ = fs.find(schema.T_PRODUCT, 品类="裤子")
    fs.rows(schema.T_PRODUCT)[pid]["指令"] = schema.P_MAKE_SLOTS
    w.run_once()
    p = fs.rows(schema.T_PRODUCT)[pid]
    assert p["指令"] is None and "已建 0 个图位" in p["程序提示"]
    assert len(fs.rows(schema.T_SLOT)) == len(schema.TEMPLATE_ROWS)


def test_full_flow(env):
    fs, w, calls, _ = env
    pid, _ = fs.find(schema.T_PRODUCT, 品类="裤子")
    black_id, black = fs.find(schema.T_COLOR, 名称="阔腿裤-黑色")
    black["白底产品图"] = [{"file_token": fs.upload_attachment("", "w.png", png())}]
    s2_id, s2 = fs.find(schema.T_SLOT, 图位="主图2")
    s1_id, s1 = fs.find(schema.T_SLOT, 图位="主图1")

    # 1. 整套读图：有参考图/要求的图位都进排队（模板带了默认要求，所以都会读）
    fs.rows(schema.T_PRODUCT)[pid]["指令"] = schema.P_READ_ALL
    w.run_once()
    assert s2["状态"] == schema.D_REVIEW
    assert s2["出图说明（中文）"] == "模特在街头行走" and s2["AI·优化后英文文案"] == "Breezy Elegance"
    system, text, n_img = next(c for c in calls["read"] if "主图2" in c[1])
    assert "参考图1（竞品），只参考：姿势、场景/背景、光线/色调" in text
    assert n_img == 2   # 白底图 + 参考图

    # 2. 审核：只确认主图1、主图2；主图2 改了中文说明
    s2["出图说明（中文）"] = "模特坐在咖啡店门口台阶上"
    s1["状态"] = schema.D_OK
    s2["状态"] = schema.D_OK

    # 3. 黑色出整套图：只出已确认的两个，其余在提示里列出
    black["状态"] = schema.C_GEN_Q
    w.run_once()
    assert black["状态"] == schema.C_ACCEPT and black["出图次数"] == 1
    assert black["主图1结果"] and black["主图2结果"] and "主图3结果" not in black
    assert "还没审核确认、没有出图：主图3" in black["程序提示"]
    out = fs.files[black["主图2结果"][0]["file_token"]]
    assert Image.open(io.BytesIO(out)).size == (1569, 2560)
    assert imaging.has_synthetic_tag(out)
    # 改过的中文被重新翻译成英文再出图
    assert s2["出图说明（英文）"] == "EN:模特坐在咖啡店门口台阶上"
    p2 = next(c[0] for c in calls["gen"] if "咖啡店" in c[0])
    assert "NO text" in p2 and "Crop the frame at the chin" in p2 and "Caucasian woman" in p2

    # 4. 只重做主图2
    n_before = len(calls["gen"])
    black["要重做的图"] = ["主图2"]
    black["验收意见"] = "裤子颜色再深一点"
    black["状态"] = schema.C_REDO_Q
    w.run_once()
    assert len(calls["gen"]) == n_before + 1
    assert "裤子颜色再深一点" in calls["gen"][-1][0]
    assert black["状态"] == schema.C_ACCEPT and black["要重做的图"] == [] and black["出图次数"] == 2

    # 5. A+ 首屏：在图位那一行出，用主推色（蓝色）；蓝色没白底图时报错
    a1_id, a1 = fs.find(schema.T_SLOT, 图位="A+模块1")
    a1["状态"] = schema.D_GEN_Q
    w.run_once()
    assert a1["状态"] == schema.D_ERROR and "白底产品图" in a1["程序提示"]
    _, blue = fs.find(schema.T_COLOR, 名称="阔腿裤-蓝色")
    blue["白底产品图"] = [{"file_token": fs.upload_attachment("", "b.png", png(color="navy"))}]
    a1["状态"] = schema.D_GEN_Q
    w.run_once()
    assert a1["状态"] == schema.D_ACCEPT
    out = fs.files[a1["A+成品"][0]["file_token"]]
    assert Image.open(io.BytesIO(out)).size == (1464, 600) and len(out) <= 2 * 1024 * 1024
    assert "navy" not in calls["gen"][-1][0]  # 用的是图片，不是颜色名


def test_color_without_white_image_reports_error(env):
    fs, w, _, _ = env
    _, black = fs.find(schema.T_COLOR, 名称="阔腿裤-黑色")
    black["状态"] = schema.C_GEN_Q
    w.run_once()
    assert black["状态"] == schema.C_ERROR and "白底产品图" in black["程序提示"]


def test_redo_without_selection_reports_error(env):
    fs, w, _, _ = env
    _, black = fs.find(schema.T_COLOR, 名称="阔腿裤-黑色")
    black["白底产品图"] = [{"file_token": fs.upload_attachment("", "w.png", png())}]
    black["状态"] = schema.C_REDO_Q
    w.run_once()
    assert black["状态"] == schema.C_ERROR and "要重做的图" in black["程序提示"]


def test_main_slot_generate_button_is_redirected(env):
    fs, w, _, _ = env
    _, s1 = fs.find(schema.T_SLOT, 图位="主图1")
    s1["状态"] = schema.D_GEN_Q
    w.run_once()
    assert s1["状态"] == schema.D_OK and "颜色套图" in s1["程序提示"]


def test_closest_ratio():
    assert models.closest_ratio(1569, 2560, models.GEMINI_RATIOS) == "9:16"
    assert models.closest_ratio(1464, 600, models.GEMINI_RATIOS) == "21:9"
    assert models.closest_ratio(1569, 2560, models.OPENAI_SIZES) == "1024x1536"


def test_parse_json_tolerates_wrapping():
    assert models.parse_json('好的：\n```json\n{"a": 1}\n```') == {"a": 1}
    assert models.parse_json('前面 {"a": 2} 后面') == {"a": 2}
