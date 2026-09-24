"""读 config.toml；密钥从环境变量取。"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

HERE = Path(__file__).parent


def load(path: str | os.PathLike | None = None) -> dict:
    p = Path(path) if path else HERE / "config.toml"
    if not p.exists():
        p = HERE / "config.example.toml"
    with open(p, "rb") as fh:
        return tomllib.load(fh)


def secret(env_name: str) -> str:
    return os.environ.get(env_name, "") if env_name else ""


def feishu_client(cfg: dict):
    from .feishu import Feishu
    fs = cfg["feishu"]
    return Feishu(secret(fs.get("app_id_env", "FEISHU_APP_ID")),
                  secret(fs.get("app_secret_env", "FEISHU_APP_SECRET")),
                  fs.get("base_url", "https://open.feishu.cn"))
