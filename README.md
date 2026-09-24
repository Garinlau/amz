# 亚马逊作图工作台

用飞书多维表格收集运营需求 → 大模型读图写作图说明 → 人工审核 → 生图模型出图。先用服装跑通。

## 目录

- `briefs/` 每个产品的作图方案，已经拆成大模型好读的格式
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
