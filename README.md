# 亚马逊作图工作台

用飞书多维表格收集运营需求 → 大模型读图写作图说明 → 人工审核 → 生图模型出图。先用服装跑通。

## 目录

- `workbench/` 工作台程序
  - `setup_base.py` 一键创建飞书多维表格（6 张表 + 预置模特、尺寸、使用说明）
  - `worker.py` 后台程序：读图、出图，结果写回表格
  - `schema.py` 表格结构（表名、栏目、选项、说明文字都在这里改）
  - `prompts.py` 读图和出图用的提示词
  - `config.example.toml` 模型和飞书设置模板
- `docs/design.md` 设计草案：多维表格结构、流程、亚马逊图片要求（待确认）
- `briefs/` 以前的作图方案（参考素材用），已经拆成大模型好读的格式
  - `brief.md` 每页的文字、表格和图片清单
  - `slides/` 每页整页截图
  - `images/` PPT 里放的原图（竞品参考图等）
  - `source.pptx` 原始 PPT
- `tools/pptx_to_md.py` 把 PPT 拆成上面这种格式的小程序

## 拆一个新的 PPT

```bash
pip install -r tools/requirements.txt
python tools/pptx_to_md.py 方案.pptx -o briefs/产品名 --title "女装-xx-xx 作图方案"
```

整页截图要用到 LibreOffice（需包含 Impress 组件）。没装的话会跳过截图，只导出文字和原图；
装在非默认位置时用 `--soffice 路径` 指定。

## 部署工作台（局域网电脑上）

```bash
pip install -r workbench/requirements.txt
cp workbench/config.example.toml workbench/config.toml   # 改里面的模型地址

# 飞书机器人的编号和密钥放环境变量，不要写进文件
export FEISHU_APP_ID=...
export FEISHU_APP_SECRET=...

python -m workbench.setup_base --dry-run                        # 先看看会建哪些表
python -m workbench.setup_base --share-email 你的飞书邮箱 --demo  # 真正创建，打印出 app_token
# 把 app_token 填进 config.toml，再设置各模型的密钥环境变量，然后启动：
python -m workbench.worker
```

机器人需要开通「多维表格」和「云文档」相关权限。

测试：`python -m pytest -q tests`
