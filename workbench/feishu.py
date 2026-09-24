"""飞书开放平台接口的最小封装：多维表格读写 + 附件上传下载。

密钥从环境变量读（默认 FEISHU_APP_ID / FEISHU_APP_SECRET），不写进任何文件。
"""

from __future__ import annotations

import time

import requests


class FeishuError(RuntimeError):
    pass


class Feishu:
    def __init__(self, app_id: str, app_secret: str, base_url: str = "https://open.feishu.cn", timeout: int = 60):
        if not app_id or not app_secret:
            raise FeishuError("缺少飞书应用编号或密钥（环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET）")
        self.app_id, self.app_secret = app_id, app_secret
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self._token, self._token_exp = "", 0.0
        self.http = requests.Session()

    # ---------- 基础 ----------

    def token(self) -> str:
        if time.time() < self._token_exp - 300:
            return self._token
        r = self.http.post(
            f"{self.base}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=self.timeout,
        )
        d = r.json()
        if d.get("code") != 0:
            raise FeishuError(f"获取飞书令牌失败：{d.get('msg')}")
        self._token = d["tenant_access_token"]
        self._token_exp = time.time() + int(d.get("expire", 7200))
        return self._token

    def call(self, method: str, path: str, body: dict | None = None, params: dict | None = None,
             files: dict | None = None, data: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.token()}"}
        for attempt in range(4):
            r = self.http.request(method, f"{self.base}{path}", headers=headers, params=params,
                                  json=body if files is None else None, files=files, data=data,
                                  timeout=self.timeout)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** attempt)
                continue
            try:
                d = r.json()
            except ValueError:
                raise FeishuError(f"{method} {path} 返回的不是 JSON（HTTP {r.status_code}）")
            if d.get("code") == 0:
                return d.get("data") or {}
            # 1254290 等是频率限制
            if d.get("code") in (1254290, 1254291, 99991400) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise FeishuError(f"{method} {path} 失败：{d.get('code')} {d.get('msg')}")
        raise FeishuError(f"{method} {path} 多次重试仍失败")

    # ---------- 多维表格 ----------

    def create_base(self, name: str, folder_token: str = "") -> dict:
        body = {"name": name}
        if folder_token:
            body["folder_token"] = folder_token
        return self.call("POST", "/open-apis/bitable/v1/apps", body)["app"]

    def list_tables(self, app: str) -> list[dict]:
        return self._paged("GET", f"/open-apis/bitable/v1/apps/{app}/tables")

    def create_table(self, app: str, name: str, fields: list[dict]) -> str:
        d = self.call("POST", f"/open-apis/bitable/v1/apps/{app}/tables",
                      {"table": {"name": name, "default_view_name": "全部", "fields": fields}})
        return d["table_id"]

    def delete_table(self, app: str, table_id: str) -> None:
        self.call("DELETE", f"/open-apis/bitable/v1/apps/{app}/tables/{table_id}")

    def list_fields(self, app: str, table_id: str) -> list[dict]:
        return self._paged("GET", f"/open-apis/bitable/v1/apps/{app}/tables/{table_id}/fields")

    def create_field(self, app: str, table_id: str, field: dict) -> dict:
        return self.call("POST", f"/open-apis/bitable/v1/apps/{app}/tables/{table_id}/fields", field)["field"]

    def update_field(self, app: str, table_id: str, field_id: str, field: dict) -> dict:
        return self.call("PUT", f"/open-apis/bitable/v1/apps/{app}/tables/{table_id}/fields/{field_id}", field)["field"]

    def search_records(self, app: str, table_id: str, filter_: dict | None = None) -> list[dict]:
        body = {"automatic_fields": False}
        if filter_:
            body["filter"] = filter_
        return self._paged("POST", f"/open-apis/bitable/v1/apps/{app}/tables/{table_id}/records/search", body)

    def get_record(self, app: str, table_id: str, record_id: str) -> dict:
        return self.call("GET", f"/open-apis/bitable/v1/apps/{app}/tables/{table_id}/records/{record_id}")["record"]

    def create_records(self, app: str, table_id: str, rows: list[dict]) -> list[dict]:
        out = []
        for i in range(0, len(rows), 500):
            d = self.call("POST", f"/open-apis/bitable/v1/apps/{app}/tables/{table_id}/records/batch_create",
                          {"records": [{"fields": r} for r in rows[i:i + 500]]})
            out += d.get("records", [])
        return out

    def update_record(self, app: str, table_id: str, record_id: str, fields: dict) -> dict:
        return self.call("PUT", f"/open-apis/bitable/v1/apps/{app}/tables/{table_id}/records/{record_id}",
                         {"fields": fields})

    # ---------- 附件 ----------

    def upload_attachment(self, app: str, name: str, content: bytes) -> str:
        """传图到这个多维表格，返回 file_token，再写进附件栏。"""
        d = self.call(
            "POST", "/open-apis/drive/v1/medias/upload_all",
            files={"file": (name, content)},
            data={"file_name": name, "parent_type": "bitable_image", "parent_node": app, "size": str(len(content))},
        )
        return d["file_token"]

    def download_attachment(self, att: dict) -> bytes:
        url = att.get("url") or f"{self.base}/open-apis/drive/v1/medias/{att['file_token']}/download"
        r = self.http.get(url, headers={"Authorization": f"Bearer {self.token()}"}, timeout=self.timeout)
        if r.status_code != 200:
            raise FeishuError(f"下载附件 {att.get('name')} 失败（HTTP {r.status_code}）")
        return r.content

    # ---------- 权限 ----------

    def add_collaborator(self, token: str, member_type: str, member_id: str, perm: str = "full_access") -> None:
        """member_type: email / openid / userid / openchat / opendepartmentid"""
        self.call("POST", f"/open-apis/drive/v1/permissions/{token}/members",
                  {"member_type": member_type, "member_id": member_id, "perm": perm},
                  params={"type": "bitable", "need_notification": "true"})

    # ---------- 内部 ----------

    def _paged(self, method: str, path: str, body: dict | None = None) -> list[dict]:
        items, page = [], None
        while True:
            params = {"page_size": 100 if "records" not in path else 500}
            if page:
                params["page_token"] = page
            d = self.call(method, path, body if method == "POST" else None, params=params)
            items += d.get("items") or []
            if not d.get("has_more"):
                return items
            page = d.get("page_token")


# ---------- 读出来的格子值 → 普通值 ----------

def text_of(v) -> str:
    """文本栏读出来可能是字符串，也可能是 [{"text": ..}, ..] 这样的分段。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        return str(v.get("text") or v.get("name") or "")
    if isinstance(v, list):
        return "".join(text_of(x) for x in v)
    return str(v)


def link_ids(v) -> list[str]:
    """关联栏读出来是 {"link_record_ids": [...]} 或 [{"record_ids": [...]}, ..]。"""
    if not v:
        return []
    if isinstance(v, dict):
        return list(v.get("link_record_ids") or v.get("record_ids") or [])
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, dict):
                out += x.get("record_ids") or x.get("link_record_ids") or []
        return out
    return []


def options_of(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        return [v]
    return [text_of(x) for x in v]
