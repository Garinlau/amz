"""读图、翻译、出图用的提示词。改措辞就改这里。"""

from __future__ import annotations

from . import schema

# 每种图片类型的拍法要点（英文，给模型看）
TYPE_GUIDE = {
    "白底主图": "Amazon MAIN image. Pure white seamless background (RGB 255,255,255). Model standing upright, front view, "
            "relaxed natural pose. Only the product for sale is prominent. Garment fills at least 85% of the frame.",
    "场景上身": "Lifestyle on-model photo in a real-world setting that shows how the garment looks when worn and styled.",
    "细节特写": "Close-up detail shots of the garment's key features (e.g. waistband, pockets, hem, collar, cuffs).",
    "面料质感": "Macro close-up of the fabric showing texture, softness and drape. No person needed.",
    "坐姿": "Model sitting naturally in a lifestyle setting; the garment stays clearly visible.",
    "街拍": "Street-style candid photo, outdoor urban setting, natural walking or standing pose.",
    "搭配推荐": "Full styled outfit: pair the garment with matching bag, jewelry, shoes and hat if suitable.",
    "四宫格": "A 2x2 grid of four lifestyle photos of the same model wearing the garment in different scenes, "
           "with thin white gutters between the panels.",
    "正面": "Front view of the model wearing the garment, clean simple background.",
    "背面": "Back view of the model wearing the garment, clean simple background.",
    "尺码展示": "Model wearing the garment standing straight on a clean light background, leaving empty space on one "
            "side for a size chart to be added later.",
    "A+首屏大图": "Wide banner lifestyle hero image featuring the model in the hero color; leave calm empty space for "
              "headline text to be added later.",
    "A+细节": "Wide banner combining the garment's key details in a clean, well-organized layout.",
    "A+多色展示": "Wide banner showing the garment in several colors, one outfit per color, consistent lighting.",
    "A+场景": "Wide banner lifestyle scene with the model wearing the garment.",
    "品牌故事背景": "Wide brand-story background image, lifestyle mood, with calm empty space for text.",
}

NO_PERSON_TYPES = {"面料质感"}

READ_SYSTEM = """你是亚马逊服装图片的美术指导。运营会给你：竞品参考图、我们自己的白底产品图（可能没有）、以及这张图的需求。
你的任务是读懂参考图，为我们的产品写一份出图说明。注意：
1. 衣服必须是我们白底图里的那件，颜色、面料、花边、版型都不能变；参考图只学运营勾选的那几项。
2. 同一份说明会给这个产品的所有颜色共用，所以不要写死衣服颜色，用 "the garment" 指代。
3. 最终图片上不能有任何文字、字母、数字、标志、水印。
4. 模特按指定的模特设定来写，不要照搬参考图里的人。
只回复一个 JSON，不要多余的话，格式：
{
  "画面描述": "用中文描述参考图的画面：模特、姿势、机位、背景、光线、配饰、布局",
  "图上文字": "参考图上所有文字原样列出，一行一条；没有就写 无",
  "建议": "用中文写：哪些保留、哪些删掉、哪些要改，以及理由，分条写",
  "英文文案": "如果这张图后期要加字，给出优化后的英文文案（标题/卖点），一行一条；不需要就写 无",
  "出图说明中文": "用中文写一段完整、具体的出图说明：画面内容、模特与姿势、服装穿着方式、场景、光线、机位与构图。不要写任何要出现在图上的文字",
  "出图说明英文": "上面中文说明的英文版，意思完全一致"
}"""

TRANSLATE_SYSTEM = """把用户给的中文出图说明翻译成英文，给图片生成模型使用。
要求：意思完全一致，不增不减；具体、画面感强；不要加任何解释。只回复一个 JSON：{"英文": "..."}"""


def read_user_text(t: dict) -> str:
    lines = [
        f"产品：{t['product_name']}（{t['category']}）",
        f"卖点：{t['selling_points'] or '无'}",
        f"材质：{t['material'] or '无'}",
        f"图位：{t['slot']}；图片类型：{t['image_type']}；拍法要点：{TYPE_GUIDE.get(t['image_type'], '')}",
        f"尺寸：{t['width']}×{t['height']}（{orientation_zh(t)}）",
        f"模特设定：{t['model_desc'] or '未指定，请按美国站常见女模特来写'}",
        f"这张图模特要改的地方：{t['model_change'] or '无'}",
        f"露脸：{t['face']}",
        f"场景：{t['scene'] or '按参考图'}",
        f"其它要求：{t['extra'] or '无'}",
        "",
        "下面的图片依次是：",
    ]
    lines += [f"- {label}" for label in t["image_labels"]]
    return "\n".join(lines)


def orientation_zh(t):
    return "竖图" if t["height"] > t["width"] else "横图" if t["width"] > t["height"] else "方图"


def orientation_en(t):
    return "portrait" if t["height"] > t["width"] else "landscape" if t["width"] > t["height"] else "square"


def generation_prompt(t: dict) -> str:
    rules = [
        "Photorealistic high-end e-commerce fashion photography, sharp focus, accurate true-to-life color.",
        "ABSOLUTELY NO text, letters, numbers, logos, watermarks, badges, icons or graphic overlays anywhere in the image.",
        f"Compose for a {t['width']}x{t['height']} {orientation_en(t)} canvas.",
    ]
    if t["image_type"] == schema.WHITE_MAIN:
        rules.append(TYPE_GUIDE[schema.WHITE_MAIN])
    if t["face"] == schema.FACE_OPTIONS[0] and t["image_type"] not in NO_PERSON_TYPES:
        rules.append("Crop the frame at the chin so the model's face is not visible.")

    parts = [
        t["instruction"].strip(),
        "",
        f"Model: {t['model_desc']}" if t["model_desc"] else "",
        f"Change for this image: {t['model_change']}" if t["model_change"] else "",
        "",
        "Input images, in order:",
        *[f"- {label}" for label in t["image_labels"]],
        "",
        "The garment must be EXACTLY the product shown in the PRODUCT images: same color, fabric, texture, "
        "pattern, lace, stitching, silhouette, length and every detail. Do not redesign it. "
        "From STYLE REFERENCE images, borrow ONLY the aspects listed; never copy the reference person, face, garment, "
        "logos or any text.",
        "",
        "Rules:",
        *[f"- {r}" for r in rules],
    ]
    if t.get("feedback"):
        parts += ["", f"Reviewer's change request for this attempt (must follow): {t['feedback']}"]
    text = "\n".join(parts)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.strip()
