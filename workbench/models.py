"""读图模型和出图模型的调用。换模型只改 config.toml。"""

from __future__ import annotations

import base64
import json
import re

import requests

from .config import secret

TIMEOUT = 300


class ModelError(RuntimeError):
    pass


def _data_url(img: bytes) -> str:
    mime = "image/png" if img[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(img).decode()}"


def _pick(cfg: dict, section: str, name: str) -> tuple[str, dict]:
    sec = cfg.get(section) or {}
    name = name if name and name != "默认" else sec.get("default", "")
    models = sec.get("models") or {}
    if name not in models:
        raise ModelError(f"设置里没有叫「{name}」的{'读图' if section == 'vision' else '出图'}模型")
    return name, models[name]


# ---------- 读图 ----------

def read_images(cfg: dict, name: str, system: str, user_text: str, images: list[bytes]) -> dict:
    """用能看图的模型读参考图，要求它回一段 JSON。"""
    name, m = _pick(cfg, "vision", name)
    content = [{"type": "text", "text": user_text}]
    content += [{"type": "image_url", "image_url": {"url": _data_url(i)}} for i in images]
    body = {
        "model": m["model"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
        "temperature": 0.4,
    }
    headers = {"Authorization": f"Bearer {secret(m.get('api_key_env', ''))}"}
    r = requests.post(f"{m['base_url'].rstrip('/')}/chat/completions", json=body, headers=headers, timeout=TIMEOUT)
    if r.status_code != 200:
        raise ModelError(f"读图模型 {name} 出错（HTTP {r.status_code}）：{r.text[:300]}")
    text = r.json()["choices"][0]["message"]["content"]
    if isinstance(text, list):
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    return parse_json(text)


def parse_json(text: str) -> dict:
    """模型有时会把 JSON 包在 ``` 里或前后加话，这里把它抠出来。"""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    try:
        return json.loads(raw)
    except ValueError:
        raise ModelError(f"读图模型没按要求返回 JSON：{text[:300]}")


# ---------- 出图 ----------

GEMINI_RATIOS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]
OPENAI_SIZES = ["1024x1024", "1024x1536", "1536x1024"]


def closest_ratio(w: int, h: int, choices: list[str]) -> str:
    target = w / h

    def ratio(c):
        a, b = re.split(r"[:x]", c)
        return int(a) / int(b)

    return min(choices, key=lambda c: abs(ratio(c) - target))


def generate(cfg: dict, name: str, prompt: str, images: list[bytes], width: int, height: int, n: int) -> list[bytes]:
    name, m = _pick(cfg, "image", name)
    kind = m.get("kind", "openai_images")
    if kind == "gemini":
        return [_gemini(m, prompt, images, width, height) for _ in range(n)]
    if kind == "openai_images":
        return _openai_images(m, prompt, images, width, height, n)
    raise ModelError(f"不认识的出图模型类型：{kind}")


def _gemini(m: dict, prompt: str, images: list[bytes], w: int, h: int) -> bytes:
    parts = [{"text": prompt}]
    for img in images:
        mime = "image/png" if img[:4] == b"\x89PNG" else "image/jpeg"
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(img).decode()}})
    image_cfg = {"aspectRatio": closest_ratio(w, h, GEMINI_RATIOS)}
    if m.get("image_size"):
        image_cfg["imageSize"] = m["image_size"]
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": image_cfg}}
    url = f"{m.get('base_url', 'https://generativelanguage.googleapis.com/v1beta').rstrip('/')}/models/{m['model']}:generateContent"
    r = requests.post(url, json=body, headers={"x-goog-api-key": secret(m.get("api_key_env", ""))}, timeout=TIMEOUT)
    if r.status_code != 200:
        raise ModelError(f"出图模型出错（HTTP {r.status_code}）：{r.text[:300]}")
    for cand in r.json().get("candidates", []):
        for p in cand.get("content", {}).get("parts", []):
            data = (p.get("inlineData") or p.get("inline_data") or {}).get("data")
            if data:
                return base64.b64decode(data)
    raise ModelError(f"出图模型没有返回图片：{r.text[:300]}")


def _openai_images(m: dict, prompt: str, images: list[bytes], w: int, h: int, n: int) -> list[bytes]:
    base = m["base_url"].rstrip("/")
    headers = {"Authorization": f"Bearer {secret(m.get('api_key_env', ''))}"}
    size = m.get("size") or closest_ratio(w, h, OPENAI_SIZES)
    data = {"model": m["model"], "prompt": prompt, "n": str(n), "size": size}
    if images:
        files = [("image[]", (f"ref{i}.png", img, "image/png")) for i, img in enumerate(images)]
        r = requests.post(f"{base}/images/edits", data=data, files=files, headers=headers, timeout=TIMEOUT)
    else:
        r = requests.post(f"{base}/images/generations", json={**data, "n": n}, headers=headers, timeout=TIMEOUT)
    if r.status_code != 200:
        raise ModelError(f"出图模型出错（HTTP {r.status_code}）：{r.text[:300]}")
    out = []
    for item in r.json().get("data", []):
        if item.get("b64_json"):
            out.append(base64.b64decode(item["b64_json"]))
        elif item.get("url"):
            out.append(requests.get(item["url"], timeout=TIMEOUT).content)
    if not out:
        raise ModelError("出图模型没有返回图片")
    return out
