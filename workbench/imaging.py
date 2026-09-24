"""出图后处理：裁成目标尺寸、写入亚马逊要求的 AI 人物标记、控制文件大小。"""

from __future__ import annotations

import io

from PIL import Image

SYNTHETIC_TAG = "contains-synthetic-performer"

XMP_TEMPLATE = (
    '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
    "<dc:subject><rdf:Bag><rdf:li>{tag}</rdf:li></rdf:Bag></dc:subject>"
    "</rdf:Description></rdf:RDF></x:xmpmeta>"
    '<?xpacket end="w"?>'
)


def fit(img_bytes: bytes, width: int, height: int) -> Image.Image:
    """按目标比例从中间裁，再缩放到目标尺寸。"""
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    target = width / height
    w, h = im.size
    if w / h > target:  # 太宽，裁左右
        nw = round(h * target)
        im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    elif w / h < target:  # 太高，裁上下（偏上保留，避免裁掉头肩）
        nh = round(w / target)
        top = min((h - nh) // 3, h - nh)
        im = im.crop((0, top, w, top + nh))
    return im.resize((width, height), Image.LANCZOS)


def to_jpeg(im: Image.Image, tag_synthetic: bool, max_bytes: int = 0) -> bytes:
    xmp = XMP_TEMPLATE.format(tag=SYNTHETIC_TAG).encode("utf-8") if tag_synthetic else b""
    for quality in (92, 88, 84, 80, 75, 70, 65, 60):
        buf = io.BytesIO()
        kw = {"format": "JPEG", "quality": quality, "optimize": True}
        if xmp:
            kw["xmp"] = xmp
        im.save(buf, **kw)
        if not max_bytes or buf.tell() <= max_bytes:
            break
    return buf.getvalue()


def has_synthetic_tag(jpeg: bytes) -> bool:
    return SYNTHETIC_TAG.encode() in jpeg
