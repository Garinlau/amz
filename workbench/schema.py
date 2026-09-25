"""多维表格的结构（表名、栏目、选项、说明文字）和预置数据。建表程序和后台程序都从这里取名字。

结构：
    产品（一个产品一行）
      ├─ 图位（这个产品每张图的设计：参考图、AI 读图、出图说明。每张图只设计、审核一次）
      └─ 颜色套图（一个颜色一行：用这个颜色的白底图，把所有已确认的主图图位一次出齐）
    A+ 和品牌故事所有颜色共用一套，直接在「图位」那一行出图。
"""

# ---------- 飞书字段类型 ----------
TEXT, NUMBER, SINGLE, MULTI, CHECKBOX, USER, ATTACHMENT, LINK = 1, 2, 3, 4, 7, 11, 17, 18
CREATED_TIME, MODIFIED_TIME, CREATED_BY = 1001, 1002, 1003

# ---------- 表名 ----------
T_GUIDE = "使用说明"
T_PRODUCT = "产品"
T_SLOT = "图位"
T_COLOR = "颜色套图"
T_MODEL = "模特库"
T_SIZE = "尺寸规格"
T_TEMPLATE = "套图模板"

# ---------- 图位 ----------
MAIN_SLOTS = [f"主图{i}" for i in range(1, 10)]           # 亚马逊最多 9 张
APLUS_SLOTS = [f"A+模块{i}" for i in range(1, 8)]         # 高级 A+ 最多 7 个模块
STORY_SLOTS = ["品牌故事"]
SLOTS = MAIN_SLOTS + APLUS_SLOTS + STORY_SLOTS

# ---------- 图片类型 ----------
MAIN_TYPES = [
    "白底主图", "场景上身", "细节特写", "面料质感", "坐姿", "街拍", "搭配推荐", "四宫格", "正面", "背面", "尺码展示",
]
APLUS_TYPES = ["A+首屏大图", "A+细节", "A+多色展示", "A+场景"]
STORY_TYPES = ["品牌故事背景"]
IMAGE_TYPES = MAIN_TYPES + APLUS_TYPES + STORY_TYPES
WHITE_MAIN = "白底主图"

REF_PURPOSES = ["姿势", "构图/机位", "场景/背景", "光线/色调", "穿搭/配饰", "画面布局", "模特气质"]
FACE_OPTIONS = ["不露脸（裁到下巴以下）", "露脸"]

# ---------- 状态 ----------
# 图位（设计）：主图走到「已确认」为止；A+ / 品牌故事继续在这一行出图、验收
D_DRAFT = "未开始"
D_READ_Q = "读图排队"
D_READING = "AI 读图中"
D_REVIEW = "待审核"
D_OK = "已确认"
D_GEN_Q = "出图排队"
D_GENERATING = "AI 出图中"
D_ACCEPT = "待验收"
D_REDO_Q = "重做排队"
D_PASS = "已通过"
D_ERROR = "出错"
SLOT_STATUSES = [D_DRAFT, D_READ_Q, D_READING, D_REVIEW, D_OK, D_GEN_Q, D_GENERATING, D_ACCEPT, D_REDO_Q, D_PASS, D_ERROR]

# 颜色套图
C_DRAFT = "未开始"
C_GEN_Q = "出图排队"
C_GENERATING = "AI 出图中"
C_ACCEPT = "待验收"
C_REDO_Q = "重做排队"
C_PASS = "已通过"
C_ERROR = "出错"
COLOR_STATUSES = [C_DRAFT, C_GEN_Q, C_GENERATING, C_ACCEPT, C_REDO_Q, C_PASS, C_ERROR]

# 产品上的指令（按钮写入，程序做完清空）
P_MAKE_SLOTS = "生成图位"
P_READ_ALL = "整套读图"
PRODUCT_COMMANDS = [P_MAKE_SLOTS, P_READ_ALL]

# ---------- 按钮（在飞书里手动加，见 docs/飞书手动设置.md） ----------
# (表, 按钮名, 点了之后把哪个栏目改成什么)
BUTTONS = [
    (T_PRODUCT, "生成图位", "指令", P_MAKE_SLOTS),
    (T_PRODUCT, "整套读图", "指令", P_READ_ALL),
    (T_SLOT, "读图", "状态", D_READ_Q),
    (T_SLOT, "确认", "状态", D_OK),
    (T_SLOT, "A+出图", "状态", D_GEN_Q),
    (T_SLOT, "A+重做", "状态", D_REDO_Q),
    (T_SLOT, "A+通过", "状态", D_PASS),
    (T_COLOR, "出整套图", "状态", C_GEN_Q),
    (T_COLOR, "重做选中的图", "状态", C_REDO_Q),
    (T_COLOR, "通过", "状态", C_PASS),
]


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
AUTO = "程序自动填，不用改"

# 颜色套图里每个主图图位一栏结果
MAIN_RESULT_FIELDS = [f"{s}结果" for s in MAIN_SLOTS]

# 建表顺序：被关联的表放前面。每张表第一个栏目是“主栏目”（必须是文本）。
TABLES = [
    (T_GUIDE, [
        f("步骤", TEXT),
        f("在哪张表", TEXT),
        f("怎么做", TEXT),
    ]),
    (T_SIZE, [
        f("名称", TEXT, "如：主图·竖版"),
        f("宽", NUMBER, "像素", NUM),
        f("高", NUMBER, "像素", NUM),
        f("默认用于", MULTI, "图位里没选尺寸时，按图片类型自动用这里勾了的规格", _opts(IMAGE_TYPES)),
        f("说明", TEXT),
    ]),
    (T_TEMPLATE, [
        f("图位", TEXT, "点产品上的「生成图位」时，按这张表给产品建图位"),
        f("图片类型", SINGLE, prop=_opts(IMAGE_TYPES)),
        f("默认要求", TEXT, "会带到新建的图位里，可以再改"),
        f("启用", CHECKBOX, "不勾的不会建"),
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
        f("定妆照", ATTACHMENT, "把这个模特满意的一张出图拖进来，之后出图都照这张脸和身材，保证整套图是同一个人"),
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
        f("模特", LINK, "整个产品用同一个模特，所有颜色、所有图都用她", link=T_MODEL, multiple=False),
        f("露脸", SINGLE, "不选 = 不露脸", _opts(FACE_OPTIONS)),
        f("备注", TEXT),
        f("指令", SINGLE, "点「生成图位」「整套读图」按钮时自动写入，程序做完会清空", _opts(PRODUCT_COMMANDS)),
        f("程序提示", TEXT, AUTO),
    ]),
    (T_SLOT, [
        f("名称", TEXT, "程序自动起名：产品-图位，如：阔腿裤-主图2"),
        f("产品", LINK, link=T_PRODUCT, multiple=False),
        f("图位", SINGLE, "主图1 就是亚马逊的第一张图", _opts(SLOTS)),
        f("图片类型", SINGLE, prop=_opts(IMAGE_TYPES)),
        f("状态", SINGLE, "由按钮和程序改，不用手动选", _opts(SLOT_STATUSES)),
        # —— 运营填写 ——
        f("参考图1", ATTACHMENT, "竞品图，只放一张（放多张只用第一张）"),
        f("参考图1·参考什么", MULTI, "只学勾选的这几项，其它不照搬", _opts(REF_PURPOSES)),
        f("参考图2", ATTACHMENT, "可不填；只放一张"),
        f("参考图2·参考什么", MULTI, prop=_opts(REF_PURPOSES)),
        f("场景", TEXT, "如：街拍、海边、公园、咖啡店"),
        f("模特要改什么", TEXT, "只对这张图生效，如：姿势改成坐姿；左右镜像"),
        f("其它要求", TEXT),
        f("尺寸", LINK, "不选就按图片类型自动选", link=T_SIZE, multiple=False),
        f("出几张", SINGLE, "不选 = 1 张；出多张可以挑", _opts(["1", "2", "4"])),
        # —— AI 读图 ——
        f("AI·参考图画面描述", TEXT, "AI 读图后自动填，可以改"),
        f("AI·参考图上的文字", TEXT, "AI 把参考图上的字原样读出来"),
        f("AI·建议", TEXT, "AI 建议哪些保留、哪些删、哪些改"),
        f("AI·优化后英文文案", TEXT, "给后期排版用，不会画进图里"),
        f("出图说明（中文）", TEXT, "审核时看这一栏、改这一栏。确认后程序会按它更新英文版"),
        f("出图说明（英文）", TEXT, "真正交给出图模型的内容，由程序根据中文版生成"),
        f("英文版依据", TEXT, "程序内部用：记录英文版是按哪一版中文翻的，中文改了就重新翻"),
        f("读图模型", SINGLE, "不选用默认"),
        f("出图模型", SINGLE, "不选用默认"),
        # —— A+ / 品牌故事在这里出图 ——
        f("A+成品", ATTACHMENT, "只有 A+ 和品牌故事用：出图结果放这里（所有颜色共用）"),
        f("A+验收意见", TEXT, "A+ 要重做时写在这里，再点「A+重做」"),
        f("程序提示", TEXT, AUTO),
        f("最后更新", MODIFIED_TIME),
    ]),
    (T_COLOR, [
        f("名称", TEXT, "产品-颜色，如：阔腿裤-黑色。不填程序会自动补"),
        f("产品", LINK, link=T_PRODUCT, multiple=False),
        f("颜色（英文）", TEXT, "如：Black"),
        f("白底产品图", ATTACHMENT, "我们自己的白底图，正面/背面/细节都可以放。出图时衣服以这里为准"),
        f("主推色", CHECKBOX, "A+ 用主推色出图"),
        f("换模特", LINK, "一般不用填。只有这个颜色想换模特时才选", link=T_MODEL, multiple=False),
        f("状态", SINGLE, "由按钮和程序改，不用手动选", _opts(COLOR_STATUSES)),
        *[f(name, ATTACHMENT, AUTO if i else "白底主图，程序出图后放这里") for i, name in enumerate(MAIN_RESULT_FIELDS)],
        f("要重做的图", MULTI, "勾上不满意的图位，写好验收意见，再点「重做选中的图」", _opts(MAIN_SLOTS)),
        f("验收意见", TEXT, "要改什么写在这里，AI 会照着改"),
        f("程序提示", TEXT, AUTO),
        f("出图次数", NUMBER, AUTO, NUM),
        f("创建人", CREATED_BY),
        f("最后更新", MODIFIED_TIME),
    ]),
]

# ---------- 视图（建表程序会尝试自动建；筛选建不上的会提示手动设） ----------
# (表, 视图名, 类型, {栏目: [值]} 筛选, 只显示这些栏目（None=全部）)
VIEWS = [
    (T_SLOT, "待审核", "grid", {"状态": [D_REVIEW]},
     ["名称", "图位", "图片类型", "参考图1", "参考图1·参考什么", "参考图2", "AI·参考图画面描述", "AI·建议",
      "出图说明（中文）", "状态"]),
    (T_SLOT, "A+待验收", "gallery", {"状态": [D_ACCEPT]}, None),
    (T_COLOR, "待验收", "gallery", {"状态": [C_ACCEPT]}, None),
    (T_COLOR, "进度看板", "kanban", None, None),
]

# ---------- 预置数据 ----------

GUIDE_ROWS = [
    {"步骤": "1. 建产品", "在哪张表": "产品",
     "怎么做": "加一行，填产品名、卖点、材质，选一个模特。然后点这一行的「生成图位」按钮，程序会按「套图模板」自动建好主图1~8、A+ 等图位。"},
    {"步骤": "2. 加颜色", "在哪张表": "颜色套图",
     "怎么做": "每个颜色加一行，选产品，上传我们自己的白底产品图。"},
    {"步骤": "3. 放参考图", "在哪张表": "图位",
     "怎么做": "在「按产品分组」视图里找到这个产品，每个图位放竞品参考图，勾选「参考什么」，需要的话写场景和要求。"},
    {"步骤": "4. 读图", "在哪张表": "产品 或 图位",
     "怎么做": "点产品上的「整套读图」一次读完所有图位；也可以在单个图位上点「读图」。AI 读完后状态变成「待审核」。"},
    {"步骤": "5. 审核", "在哪张表": "图位（待审核视图）",
     "怎么做": "看 AI 的描述和建议，直接改「出图说明（中文）」。没问题点「确认」。每张图只审核一次，所有颜色共用。"},
    {"步骤": "6. 出主图", "在哪张表": "颜色套图",
     "怎么做": "点某个颜色的「出整套图」，程序把已确认的主图图位全部出齐，放进「主图1结果」~「主图9结果」。建议先出主推色，看满意了再出其它颜色。"},
    {"步骤": "7. 验收", "在哪张表": "颜色套图（待验收视图）",
     "怎么做": "满意点「通过」。不满意：在「要重做的图」勾上图位，写「验收意见」，点「重做选中的图」，只重做勾选的那几张。"},
    {"步骤": "8. A+ 和品牌故事", "在哪张表": "图位",
     "怎么做": "所有颜色共用一套。确认后在那一行点「A+出图」，结果在「A+成品」。不满意写「A+验收意见」再点「A+重做」。"},
    {"步骤": "出错了", "在哪张表": "任意",
     "怎么做": "状态变成「出错」时看「程序提示」，改好后再点一次对应按钮。超过 10 分钟还停在「AI … 中」，说明后台程序停了，再点一次按钮即可。"},
]

MAIN_RULE = "白底主图：纯白背景(255,255,255)，模特站立，只出现在售商品，衣服占画面85%以上，无文字无标志。其它主图可以有场景。"

SIZE_ROWS = [
    {"名称": "主图·竖版", "宽": 1569, "高": 2560, "默认用于": MAIN_TYPES, "说明": "和下载的竞品图一样大。" + MAIN_RULE},
    {"名称": "主图·官方3:4", "宽": 1600, "高": 2134, "默认用于": [], "说明": "亚马逊服装指南建议的比例（备选）。" + MAIN_RULE},
    {"名称": "A+·电脑端", "宽": 1464, "高": 600, "默认用于": APLUS_TYPES, "说明": "高级 A+ 全图模块，2MB 以内"},
    {"名称": "A+·手机端", "宽": 600, "高": 450, "默认用于": [], "说明": "高级 A+ 全图模块的手机版图片，需要时单独建一个图位"},
    {"名称": "A+·标准模块", "宽": 970, "高": 600, "默认用于": [], "说明": "普通 A+ 图片模块"},
    {"名称": "品牌故事·电脑端", "宽": 1464, "高": 625, "默认用于": STORY_TYPES, "说明": ""},
    {"名称": "品牌故事·手机端", "宽": 463, "高": 625, "默认用于": [], "说明": ""},
]

TEMPLATE_ROWS = [
    {"图位": "主图1", "图片类型": "白底主图", "默认要求": "白底，模特站立，展示半身，体现版型", "启用": True},
    {"图位": "主图2", "图片类型": "场景上身", "默认要求": "真实场景上身图，展示产品特色和穿搭", "启用": True},
    {"图位": "主图3", "图片类型": "细节特写", "默认要求": "展示所有卖点细节", "启用": True},
    {"图位": "主图4", "图片类型": "面料质感", "默认要求": "展示面料柔软、质感", "启用": True},
    {"图位": "主图5", "图片类型": "街拍", "默认要求": "街拍场景，可以加坐姿", "启用": True},
    {"图位": "主图6", "图片类型": "搭配推荐", "默认要求": "整套搭配：包、首饰、鞋子，必要时加帽子", "启用": True},
    {"图位": "主图7", "图片类型": "四宫格", "默认要求": "买家秀四宫格：公园、街拍、居家、咖啡店", "启用": True},
    {"图位": "主图8", "图片类型": "尺码展示", "默认要求": "模特站直，一侧留空给尺码表", "启用": True},
    {"图位": "A+模块1", "图片类型": "A+首屏大图", "默认要求": "主推色场景大图，留出放标题的位置", "启用": True},
    {"图位": "A+模块2", "图片类型": "A+细节", "默认要求": "细节展示", "启用": True},
    {"图位": "A+模块3", "图片类型": "A+多色展示", "默认要求": "不同颜色的整套穿搭", "启用": True},
    {"图位": "品牌故事", "图片类型": "品牌故事背景", "默认要求": "左侧人物场景图", "启用": True},
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


def is_aplus(slot: str) -> bool:
    return slot in APLUS_SLOTS or slot in STORY_SLOTS
