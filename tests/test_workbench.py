"""用一个假的飞书把「建表 → 读图 → 确认出图 → 验收重做」整条流程跑一遍。"""

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
        self.tables = {}   # table_id -> {"name", "fields": {name: type}, "rows": {rid: fields}}
        self.files = {}
        self.shared = []

    def _id(self, p):
        return f"{p}{next(self.ids)}"

    def create_base(self, name, folder=""):
        tid = self._id("tbl")
        self.tables[tid] = {"name": "数据表", "fields": {"文本": 1}, "rows": {}}
        return {"app_token": "app1", "url": "https://example/base/app1"}

    def list_tables(self, app):
        return [{"table_id": k, "name": v["name"]} for k, v in self.tables.items()]

    def create_table(self, app, name, fields):
        for fd in fields:
            if fd["type"] == schema.LINK:
                assert fd["property"]["table_id"] in self.tables
        tid = self._id("tbl")
        self.tables[tid] = {"name": name, "fields": {fd["field_name"]: fd["type"] for fd in fields}, "rows": {}}
        return tid

    def delete_table(self, app, tid):
        del self.tables[tid]

    def _check(self, tid, fields):
        for k in fields:
            if k not in self.tables[tid]["fields"]:
                raise FeishuError(f"没有栏目 {k}")

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
        types = self.tables[tid]["fields"]
        res = {}
        for k, v in fields.items():
            if types[k] == schema.TEXT and isinstance(v, str):
                res[k] = [{"type": "text", "text": v}]
            elif types[k] == schema.LINK:
                res[k] = {"link_record_ids": list(v)}
            elif types[k] == schema.ATTACHMENT:
                res[k] = [{"file_token": a["file_token"], "name": a["file_token"]} for a in v]
            else:
                res[k] = v
        return res

    def search_records(self, app, tid, filter_=None):
        rows = []
        for rid, f in self.tables[tid]["rows"].items():
            if filter_:
                want = [c["value"][0] for c in filter_["conditions"]]
                if f.get("状态") not in want:
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
    def tid(self, name):
        return next(k for k, v in self.tables.items() if v["name"] == name)

    def rows(self, name):
        return self.tables[self.tid(name)]["rows"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    fs = FakeFeishu()
    info = setup_base.build_base(fs, CFG, "测试", demo=True, emails=["a@b.com"])
    cfg = {**CFG, "feishu": {"app_token": info["app_token"]},
           "worker": {**CFG["worker"], "save_dir": str(tmp_path)}}
    return fs, worker.Worker(cfg, fs), monkeypatch


def demo_task(fs):
    return next(iter(fs.rows(schema.T_TASK).items()))


def test_setup_creates_tables_and_seeds(env):
    fs, _, _ = env
    names = {v["name"] for v in fs.tables.values()}
    assert names == {n for n, _ in schema.TABLES}   # 默认空表已删掉
    assert len(fs.rows(schema.T_MODEL)) == len(schema.MODEL_ROWS)
    assert len(fs.rows(schema.T_SIZE)) == len(schema.SIZE_ROWS)
    assert fs.shared == [("email", "a@b.com")]
    rid, task = demo_task(fs)
    assert task["状态"] == schema.S_DRAFT and task["参考图1"]


def test_full_flow(env):
    fs, w, mp = env
    rid, task = demo_task(fs)
    # 给黑色款放白底图
    vid = task["颜色款"][0]
    fs.rows(schema.T_VARIANT)[vid]["白底产品图"] = [{"file_token": fs.upload_attachment("", "w.png", png())}]

    seen = {}

    def fake_read(cfg, name, system, text, images):
        seen["read"] = (text, len(images))
        return {"画面描述": "街头站姿", "图上文字": "无", "建议": "保留姿势", "英文文案": "Breezy Elegance",
                "模特描述": "Caucasian woman, blonde", "出图说明": "Street style photo of the model walking."}

    def fake_gen(cfg, name, prompt, images, width, height, n):
        seen["gen"] = (prompt, len(images), width, height, n)
        return [png(1024, 1536, "blue") for _ in range(n)]

    mp.setattr(models, "read_images", fake_read)
    mp.setattr(models, "generate", fake_gen)

    # 1. 提交读图
    fs.rows(schema.T_TASK)[rid]["状态"] = schema.S_READ
    assert w.run_once() == 1
    t = fs.rows(schema.T_TASK)[rid]
    assert t["状态"] == schema.S_REVIEW
    assert t["AI·优化后英文文案"] == "Breezy Elegance"
    assert "Model: Caucasian woman, blonde" in t["出图说明（英文）"]
    text, n_img = seen["read"]
    assert "主图·场景上身" in text and "参考图1（竞品），只参考：姿势、场景/背景、光线/色调" in text
    assert n_img == 2  # 白底图 + 参考图

    # 2. 审核后确认出图
    t["状态"] = schema.S_GENERATE
    assert w.run_once() == 1
    t = fs.rows(schema.T_TASK)[rid]
    assert t["状态"] == schema.S_ACCEPT and t["出图次数"] == 1
    assert len(t["生成结果"]) == 2
    out = fs.files[t["生成结果"][0]["file_token"]]
    assert Image.open(io.BytesIO(out)).size == (1569, 2560)   # 按「主图·竖版」裁好
    assert imaging.has_synthetic_tag(out)
    prompt, n_img, *_ = seen["gen"]
    assert "NO text" in prompt and "Crop the frame at the chin" in prompt
    assert n_img == 2  # 白底图 + 参考图（金发模特还没有定妆照）

    # 3. 验收不满意，写意见重新出图
    t["验收意见"] = "裤子颜色再深一点"
    t["状态"] = schema.S_REDO
    w.run_once()
    t = fs.rows(schema.T_TASK)[rid]
    assert t["状态"] == schema.S_ACCEPT and t["出图次数"] == 2
    assert "裤子颜色再深一点" in seen["gen"][0]


def test_generate_without_product_image_reports_error(env):
    fs, w, mp = env
    rid, t = demo_task(fs)
    t["出图说明（英文）"] = "A photo."
    t["状态"] = schema.S_GENERATE
    w.run_once()
    assert t["状态"] == schema.S_ERROR
    assert "白底产品图" in t["出错信息"]


def test_generate_without_instruction_reports_error(env):
    fs, w, _ = env
    rid, t = demo_task(fs)
    t["状态"] = schema.S_GENERATE
    w.run_once()
    assert t["状态"] == schema.S_ERROR and "出图说明" in t["出错信息"]


def test_aplus_is_landscape_and_under_2mb(env):
    fs, w, mp = env
    rid, t = demo_task(fs)
    fs.rows(schema.T_VARIANT)[t["颜色款"][0]]["白底产品图"] = [{"file_token": fs.upload_attachment("", "w.png", png())}]
    t.update({"图片类型": "A+·首屏大图", "出图说明（英文）": "Hero banner.", "状态": schema.S_GENERATE, "出几张": "1"})
    mp.setattr(models, "generate", lambda *a: [png(1536, 1024)])
    w.run_once()
    out = fs.files[t["生成结果"][0]["file_token"]]
    assert Image.open(io.BytesIO(out)).size == (1464, 600)
    assert len(out) <= 2 * 1024 * 1024


def test_closest_ratio():
    assert models.closest_ratio(1569, 2560, models.GEMINI_RATIOS) == "9:16"
    assert models.closest_ratio(1464, 600, models.GEMINI_RATIOS) == "21:9"
    assert models.closest_ratio(1569, 2560, models.OPENAI_SIZES) == "1024x1536"


def test_parse_json_tolerates_wrapping():
    assert models.parse_json('好的：\n```json\n{"a": 1}\n```') == {"a": 1}
    assert models.parse_json('前面 {"a": 2} 后面') == {"a": 2}
