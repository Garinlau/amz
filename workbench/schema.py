"""多维表格的结构（表名、栏目、选项、说明文字）和预置数据。建表程序和出图程序都从这里取名字。"""

# ---------- 飞书字段类型 ----------
TEXT, NUMBER, SINGLE, MULTI, CHECKBOX, USER, ATTACHMENT, LINK, MODIFIED_TIME = 1, 2, 3, 4, 7, 11, 17, 18, 1002

# ---------- 表名 ----------
T_GUIDE = "使用说明"
T_TASK = "作图任务"
T_PRODUCT = "产品"
T_VARIANT = "颜色款"
T_MODEL = "模特库"
T_SIZE = "尺寸规格"

# ---------- 作图任务的状态 ----------
# 带 ▶ / ✅ / ↻ 的由人选，其余由程序改
S_DRAFT = "填写中"
S_READ = "▶ 提交读图"
S_READING = "AI 读图中"
S_REVIEW = "待审核"
S_GENERATE = "▶ 确认出图"
S_GENERATING = "AI 出图中"
S_ACCEPT = "待验收"
S_PASS = "✅ 通过"
S_REDO = "↻ 重新出图"
S_ERROR = "⚠ 出错"
STATUSES = [S_DRAFT, S_READ, S_READING, S_REVIEW, S_GENERATE, S_GENERATING, S_ACCEPT, S_PASS, S_REDO, S_ERROR]

# ---------- 图片类型 ----------
MAIN_TYPES = [
    "主图·白底（第1张）", "主图·场景上身", "主图·细节特写", "主图·面料质感", "主图·坐姿",
    "主图·街拍", "主图·搭配推荐", "主图·四宫格", "主图·正面", "主图·背面", "主图·尺码展示",
]
APLUS_TYPES = ["A+·首屏大图", "A+·细节", "A+·多色展示", "A+·场景"]
STORY_TYPES = ["品牌故事"]
IMAGE_TYPES = MAIN_TYPES + APLUS_TYPES + STORY_TYPES

REF_PURPOSES = ["姿势", "构图/机位", "场景/背景", "光线/色调", "穿搭/配饰", "画面布局", "模特气质"]

FACE_OPTIONS = ["不露脸（裁到下巴以下）", "露脸"]


def _opts(names):
    return {"options": [{"name": n, "color": i % 54} for i, n in enumerate(names)]}


def f(name, type_, desc="", prop=None, link=None, multiple=True):
    """一个栏目。link=目标表名（建表时换成 table_id）。"""
    d = {"field_name": name, "type": type_}
    if prop:
        d["property"] = prop
    if desc:
        d["description"] = {"disable_sync": True, "text": desc}
    if link:
        d["_link"] = link
        d["_multiple"] = multiple
    return d


NUM = {"formatter": "0"}

# 建表顺序：被关联的表放前面。每张表第一个栏目是“主栏目”（必须是文本）。
TABLES = [
    (T_GUIDE, [
        f("步骤", TEXT),
        f("谁来做", SINGLE, prop=_opts(["运营", "AI 自动", "审核人"])),
        f("在哪张表", TEXT),
        f("怎么做", TEXT),
    ]),
    (T_SIZE, [
        f("名称", TEXT, "如：主图·竖版"),
        f("宽", NUMBER, "像素", NUM),
        f("高", NUMBER, "像素", NUM),
        f("默认用于", MULTI, "作图任务里没选尺寸时，按图片类型自动用这里勾了的规格", _opts(IMAGE_TYPES)),
        f("说明", TEXT),
    ]),
    (T_MODEL, [
        f("名称", TEXT, "如：金发白人"),
        f("族裔", SINGLE, prop=_opts(["白人", "拉美裔", "非裔", "东亚", "南亚", "中东", "混血"])),
        f("肤色", SINGLE, prop=_opts(["白皙", "浅", "小麦", "棕", "深"])),
        f("发色", SINGLE, prop=_opts(["金色", "浅棕", "棕色", "黑色", "红色"])),
        f("发型", TEXT, "如：及肩微卷"),
        f("身材", SINGLE, prop=_opts(["纤细", "标准", "丰满/大码"])),
        f("年龄段", SINGLE, prop=_opts(["20-25", "25-35", "35-45", "45+"])),
        f("英文描述", TEXT, "给 AI 看的模特描述。改这里就能改这个模特的样子"),
        f("定妆照", ATTACHMENT, "同一个模特的满意出图拖进来一张，之后出图都照这张脸和身材，保证一套图是同一个人"),
        f("启用", CHECKBOX),
    ]),
    (T_PRODUCT, [
        f("产品名", TEXT, "如：弯刀蕾丝阔腿裤"),
        f("品类", SINGLE, prop=_opts(["上衣", "卫衣", "裤子", "裙子", "连衣裙", "外套", "套装", "其它"])),
        f("父ASIN", TEXT),
        f("竞品链接", TEXT, "一行一个"),
        f("卖点（英文）", TEXT, "一行一个，如：Elastic Waist / Side Pockets / Lace Hem"),
        f("材质", TEXT, "如：71% Rayon, 29% Nylon"),
        f("尺码表", ATTACHMENT),
        f("备注", TEXT),
    ]),
    (T_VARIANT, [
        f("名称", TEXT, "产品+颜色，如：阔腿裤-黑色"),
        f("产品", LINK, link=T_PRODUCT, multiple=False),
        f("颜色（英文）", TEXT, "如：Black"),
        f("白底产品图", ATTACHMENT, "我们自己的白底图，正面/背面/细节都可以放。出图时衣服以这里为准"),
        f("主推色", CHECKBOX, "A+ 用主推色"),
        f("固定模特", LINK, "这个颜色的整套图用同一个模特", link=T_MODEL, multiple=False),
    ]),
    (T_TASK, [
        f("任务名", TEXT, "随便起个好找的名字，如：阔腿裤-黑色-主图2"),
        f("状态", SINGLE,
          "带 ▶ ✅ ↻ 的由你来选，其余是程序自动改的。"
          "填好后选「▶ 提交读图」；看完 AI 写的出图说明后选「▶ 确认出图」；"
          "出图后选「✅ 通过」或写好验收意见再选「↻ 重新出图」", _opts(STATUSES)),
        f("产品", LINK, "选了颜色款可以不填", link=T_PRODUCT, multiple=False),
        f("颜色款", LINK, "主图选一个颜色；A+ 可以多选", link=T_VARIANT),
        f("图片类型", SINGLE, prop=_opts(IMAGE_TYPES)),
        f("主图第几张", NUMBER, "只有主图要填，1 = 第一张白底图", NUM),
        f("尺寸", LINK, "不选就按图片类型自动选。A+ 的电脑端和手机端尺寸不同，要各建一行任务", link=T_SIZE, multiple=False),
        f("参考图1", ATTACHMENT, "竞品图，只放一张（放多张只用第一张）"),
        f("参考图1·参考什么", MULTI, "只学勾选的这几项，其它不照搬", _opts(REF_PURPOSES)),
        f("参考图2", ATTACHMENT, "可不填；只放一张"),
        f("参考图2·参考什么", MULTI, prop=_opts(REF_PURPOSES)),
        f("模特", LINK, "不选就用颜色款里定的固定模特", link=T_MODEL, multiple=False),
        f("模特要改什么", TEXT, "如：换成金发；姿势微调；左右镜像"),
        f("露脸", SINGLE, "不选 = 不露脸", _opts(FACE_OPTIONS)),
        f("场景", TEXT, "如：街拍、海边、公园、咖啡店"),
        f("其它要求", TEXT),
        f("出几张", SINGLE, "不选 = 1 张；出多张可以挑", _opts(["1", "2", "4"])),
        f("AI·参考图画面描述", TEXT, "AI 读图后自动填，可以改"),
        f("AI·参考图上的文字", TEXT, "AI 把参考图上的字原样读出来"),
        f("AI·建议", TEXT, "AI 建议哪些保留、哪些删、哪些改"),
        f("AI·优化后英文文案", TEXT, "给后期排版用，不会画进图里"),
        f("出图说明（英文）", TEXT, "最重要的一栏：出图就按这段来。AI 先写好，你审核时直接改"),
        f("读图模型", SINGLE, "不选用默认"),
        f("出图模型", SINGLE, "不选用默认"),
        f("生成结果", ATTACHMENT, "程序放进来的图"),
        f("选用的图", ATTACHMENT, "验收时把满意的图拖到这里"),
        f("验收意见", TEXT, "要重新出图时写在这里，AI 会照着改"),
        f("审核人", USER),
        f("出错信息", TEXT, "程序自动填"),
        f("出图次数", NUMBER, "程序自动填", NUM),
        f("最后更新", MODIFIED_TIME),
    ]),
]

# ---------- 预置数据 ----------

GUIDE_ROWS = [
    {"步骤": "0. 准备产品", "谁来做": "运营", "在哪张表": "产品、颜色款",
     "怎么做": "新产品先在「产品」表加一行；每个颜色在「颜色款」表加一行，上传我们自己的白底产品图，选好固定模特。"},
    {"步骤": "1. 填需求", "谁来做": "运营", "在哪张表": "作图任务",
     "怎么做": "每张要出的图加一行：选产品、颜色款、图片类型；放参考图并勾选「参考什么」；需要的话写模特要改什么、场景。状态保持「填写中」。"},
    {"步骤": "2. 提交读图", "谁来做": "运营", "在哪张表": "作图任务",
     "怎么做": "填好后把状态改成「▶ 提交读图」。AI 大约 1 分钟内读完，状态会变成「待审核」。"},
    {"步骤": "3. 审核", "谁来做": "审核人", "在哪张表": "作图任务",
     "怎么做": "看 AI 写的画面描述、建议和「出图说明（英文）」，直接在格子里改。没问题就把状态改成「▶ 确认出图」。"},
    {"步骤": "4. 出图", "谁来做": "AI 自动", "在哪张表": "作图任务",
     "怎么做": "程序按出图说明出图，结果放进「生成结果」，状态变成「待验收」。图上不会有任何文字。"},
    {"步骤": "5. 验收", "谁来做": "审核人", "在哪张表": "作图任务",
     "怎么做": "满意：把选中的图拖到「选用的图」，状态改成「✅ 通过」。不满意：在「验收意见」写要改什么，状态改成「↻ 重新出图」。"},
    {"步骤": "出错了怎么办", "谁来做": "运营", "在哪张表": "作图任务",
     "怎么做": "状态变成「⚠ 出错」时看「出错信息」。改好后重新选「▶ 提交读图」或「▶ 确认出图」即可。"
               "如果超过 10 分钟还停在「AI 读图中」或「AI 出图中」，说明后台程序中途停了，重新选一次 ▶ 就行。"},
    {"步骤": "A+ 怎么做", "谁来做": "运营", "在哪张表": "作图任务",
     "怎么做": "A+ 的电脑端（1464×600）和手机端（600×450）比例差很多，要建两行任务，分别在「尺寸」里选。"},
]

MAIN_RULE = "主图白底图：纯白背景(255,255,255)，模特站立，只出现在售商品，衣服占画面85%以上，无文字无标志。其它主图可以有场景。"

SIZE_ROWS = [
    {"名称": "主图·竖版", "宽": 1569, "高": 2560, "默认用于": MAIN_TYPES,
     "说明": "和下载的竞品图一样大。" + MAIN_RULE},
    {"名称": "主图·官方3:4", "宽": 1600, "高": 2134, "默认用于": [],
     "说明": "亚马逊服装指南建议的比例（备选）。" + MAIN_RULE},
    {"名称": "A+·电脑端", "宽": 1464, "高": 600, "默认用于": APLUS_TYPES, "说明": "高级 A+ 全图模块，2MB 以内"},
    {"名称": "A+·手机端", "宽": 600, "高": 450, "默认用于": [], "说明": "高级 A+ 全图模块手机版，要单独出一张"},
    {"名称": "A+·标准模块", "宽": 970, "高": 600, "默认用于": [], "说明": "普通 A+ 图片模块"},
    {"名称": "品牌故事·电脑端", "宽": 1464, "高": 625, "默认用于": STORY_TYPES, "说明": ""},
    {"名称": "品牌故事·手机端", "宽": 463, "高": 625, "默认用于": [], "说明": ""},
]

MODEL_ROWS = [
    {"名称": "金发白人", "族裔": "白人", "肤色": "白皙", "发色": "金色", "发型": "长发微卷", "身材": "纤细", "年龄段": "25-35",
     "英文描述": "Caucasian woman in her late 20s, fair skin, long softly wavy blonde hair, slim figure, natural makeup", "启用": True},
    {"名称": "棕发白人", "族裔": "白人", "肤色": "浅", "发色": "浅棕", "发型": "及肩直发", "身材": "标准", "年龄段": "25-35",
     "英文描述": "Caucasian woman around 30, light skin, shoulder-length straight light brown hair, average build, natural makeup", "启用": True},
    {"名称": "拉美裔黑发", "族裔": "拉美裔", "肤色": "小麦", "发色": "黑色", "发型": "长直发", "身材": "标准", "年龄段": "25-35",
     "英文描述": "Latina woman of Mexican descent in her late 20s, warm tan skin, long straight black hair, average build, natural makeup", "启用": True},
    {"名称": "拉美裔棕发", "族裔": "拉美裔", "肤色": "小麦", "发色": "棕色", "发型": "长发大波浪", "身材": "丰满/大码", "年龄段": "25-35",
     "英文描述": "Latina woman of Mexican descent around 30, olive skin, long dark brown wavy hair, curvy figure, natural makeup", "启用": True},
    {"名称": "非裔", "族裔": "非裔", "肤色": "深", "发色": "黑色", "发型": "自然卷", "身材": "标准", "年龄段": "25-35",
     "英文描述": "African American woman in her late 20s, deep brown skin, natural curly black hair, average build, natural makeup", "启用": True},
    {"名称": "东亚", "族裔": "东亚", "肤色": "浅", "发色": "黑色", "发型": "长直发", "身材": "纤细", "年龄段": "20-25",
     "英文描述": "East Asian woman in her mid 20s, light skin, long straight black hair, slim figure, natural makeup", "启用": True},
    {"名称": "混血", "族裔": "混血", "肤色": "棕", "发色": "棕色", "发型": "中长卷发", "身材": "标准", "年龄段": "25-35",
     "英文描述": "mixed-race woman around 30, light brown skin, medium-length curly brown hair, average build, natural makeup", "启用": True},
]
