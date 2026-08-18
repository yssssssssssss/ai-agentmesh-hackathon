"""
report_template.py — 生成 PRD 可行性分析 HTML 报告

用法:
    1. 先跑 crop_screenshots.py 把总图裁成子图
    2. 修改 CONFIG 里的字段:PRD 标题、子图列表、verdict 等级、6 个 section 内容
    3. python3 report_template.py
    4. 输出 ~/Desktop/<title>-PRD可行性分析.html (单文件 ~1MB,可直接发送)

骨架说明:
    HTML 包含 6 个 section,每个 section 用对应的 builder 函数填充
    所有 CSS 内联,所有图片 base64 内嵌,零外部依赖
"""

import base64
import os
import sys
from pathlib import Path

# ===== CONFIG 区(每次分析改这里) =====
CONFIG = {
    "title": "看赚高TGI用户1元红包",        # 文件名前缀
    "header_h1": "PRD 可行性分析",
    "header_sub": "【增长】看赚高TGI用户 1元红包角标透出",
    "header_meta": [
        "需求方:刘铭珊(Sandy)",
        "分析维度:业务逻辑 · 方案评估 · 数据预估 · 优化方向",
        "2026-06-30",
    ],

    # 综合评级:A+/A/B+/B/C+/C/D
    "verdict_score": "C+",
    "verdict_color": "#ff7d00",   # 与 score 对应: A 绿 / B 蓝 / C 橙 / D 红
    "verdict_headline": "需求方向值得做,但有 N 个业务逻辑硬伤需要修复",
    "verdict_items": [
        ("pass", "✓ 圈人合理"),
        ("pass", "✓ 数据支撑充分"),
        ("warn", "! 收益存在选择偏差"),
        ("fail", "✗ 路径过重"),
    ],

    # 截图素材目录(crop_screenshots.py 的输出)
    "asset_dir": os.getenv("PRD_ASSET_DIR", str(Path.cwd() / "prd-feasibility-assets")),
    "image_keys": [
        "01_homepage", "02_popup", "03_panel",
        "04_cashout", "05_popup2", "06_success", "07_guide"
    ],
}


def load_images(asset_dir, keys):
    """读取所有 _jpg.jpg 转 base64"""
    imgs = {}
    for k in keys:
        path = f"{asset_dir}/{k}_jpg.jpg"
        if not os.path.exists(path):
            print(f"⚠ 缺图: {path}")
            continue
        with open(path, "rb") as f:
            imgs[k] = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
    return imgs


# ===== 完整 CSS 样式 =====
CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f6f8; color: #1d2129; line-height: 1.6; padding: 24px 16px 80px; }
.container { max-width: 1180px; margin: 0 auto; }
.header { background: linear-gradient(135deg, #165DFF 0%, #4080FF 100%); color: #fff; padding: 32px 36px; border-radius: 16px; margin-bottom: 24px; box-shadow: 0 8px 24px rgba(22,93,255,0.18); }
.header h1 { font-size: 22px; margin-bottom: 6px; }
.header .sub { font-size: 14px; opacity: 0.9; margin-bottom: 12px; }
.header .meta { font-size: 12px; opacity: 0.78; display: flex; flex-wrap: wrap; gap: 16px; }
.verdict { display: flex; align-items: stretch; gap: 16px; margin-bottom: 24px; }
.verdict-score { background: #fff; border-radius: 14px; padding: 24px 28px; display: flex; flex-direction: column; align-items: center; justify-content: center; box-shadow: 0 2px 8px rgba(0,0,0,0.04); min-width: 130px; }
.verdict-score .ring { width: 76px; height: 76px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 26px; font-weight: 700; margin-bottom: 6px; }
.verdict-score .label { font-size: 11px; color: #86909c; }
.verdict-detail { flex: 1; background: #fff; border-radius: 14px; padding: 18px 22px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); }
.verdict-detail h3 { font-size: 14px; color: #1d2129; margin-bottom: 8px; }
.verdict-detail .items { display: flex; flex-wrap: wrap; gap: 6px; }
.verdict-item { padding: 5px 12px; border-radius: 8px; font-size: 12px; }
.vi-pass { background: #e8f7eb; color: #00b42a; }
.vi-warn { background: #fff7e8; color: #ff7d00; }
.vi-fail { background: #ffece8; color: #f53f3f; }
.nav { display: flex; flex-wrap: wrap; gap: 6px; background: #fff; padding: 10px; border-radius: 12px; margin-bottom: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); position: sticky; top: 8px; z-index: 50; }
.nav a { flex: 1; min-width: 100px; text-align: center; padding: 7px 5px; font-size: 11px; color: #4e5969; text-decoration: none; border-radius: 8px; }
.nav a:hover { background: #f2f3f5; color: #165DFF; }
.nav a .num { display: block; font-weight: 700; font-size: 13px; color: #165DFF; }
.section { background: #fff; border-radius: 14px; padding: 26px 30px; margin-bottom: 18px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); }
.section h2 { font-size: 17px; padding-bottom: 12px; margin-bottom: 16px; border-bottom: 2px solid #f2f3f5; display: flex; align-items: center; gap: 10px; }
.section h2 .badge { background: #165DFF; color: #fff; width: 24px; height: 24px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; }
.section h3 { font-size: 13px; margin: 14px 0 8px; padding-left: 10px; border-left: 3px solid #165DFF; }
.section p { font-size: 13px; color: #4e5969; margin-bottom: 8px; }
.section ul, .section ol { padding-left: 18px; }
.section li { font-size: 13px; color: #4e5969; margin-bottom: 4px; }
.alert { border-radius: 10px; padding: 14px 16px; margin: 10px 0; font-size: 12px; line-height: 1.7; }
.alert-danger { background: #fff0f0; border-left: 4px solid #f53f3f; color: #5c2020; }
.alert-warn { background: #fff7e8; border-left: 4px solid #ff7d00; color: #5c3317; }
.alert-info { background: #e8f3ff; border-left: 4px solid #165DFF; color: #1d3557; }
.alert-success { background: #e8f7eb; border-left: 4px solid #00b42a; color: #1d4028; }
.alert-title { font-weight: 700; margin-bottom: 4px; font-size: 13px; }
table { width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 12px; }
thead { background: #f7f8fa; }
th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid #e5e6eb; vertical-align: top; }
.tag { display: inline-block; padding: 2px 7px; border-radius: 10px; font-size: 10px; font-weight: 600; }
.tag-pass { background: #e8f7eb; color: #00b42a; }
.tag-warn { background: #fff7e8; color: #ff7d00; }
.tag-fail { background: #ffece8; color: #f53f3f; }
.hi-flow { display: flex; flex-wrap: nowrap; gap: 12px; margin: 16px 0; overflow-x: auto; padding-bottom: 8px; }
.hi-step { flex: 0 0 200px; display: flex; flex-direction: column; }
.hi-screen-wrap { position: relative; border-radius: 14px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1); border: 2px solid #e5e6eb; background: #fff; }
.hi-screen-wrap.good { border-color: #00b42a; }
.hi-screen-wrap.warn { border-color: #ff7d00; }
.hi-screen-wrap.danger { border-color: #f53f3f; }
.hi-screen-wrap img { width: 100%; display: block; }
.hi-step-num { position: absolute; top: 8px; left: 8px; background: rgba(22,93,255,0.95); color: #fff; width: 26px; height: 26px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; z-index: 2; }
.hi-step-num.good { background: rgba(0,180,42,0.95); }
.hi-step-num.warn { background: rgba(255,125,0,0.95); }
.hi-step-num.danger { background: rgba(245,63,63,0.95); }
.hi-tag-overlay { position: absolute; top: 8px; right: 8px; padding: 3px 8px; border-radius: 10px; font-size: 10px; font-weight: 700; color: #fff; z-index: 2; }
.hi-tag-overlay.good { background: rgba(0,180,42,0.95); }
.hi-tag-overlay.warn { background: rgba(255,125,0,0.95); }
.hi-tag-overlay.danger { background: rgba(245,63,63,0.95); }
.hi-annotation { background: #f7f8fa; padding: 8px 10px; border-radius: 0 0 10px 10px; font-size: 11px; line-height: 1.5; }
.hi-anno-title { font-size: 11px; font-weight: 700; margin-bottom: 3px; }
.hi-anno-title.good { color: #00b42a; }
.hi-anno-title.warn { color: #ff7d00; }
.hi-anno-title.danger { color: #f53f3f; }
.hi-anno-body { color: #4e5969; font-size: 10px; }
.hi-arrow { display: flex; align-items: center; justify-content: center; flex: 0 0 20px; color: #c9cdd4; font-size: 22px; }
.reasoning { background: #fafbfc; border: 1px solid #e5e6eb; border-radius: 8px; padding: 10px 12px; margin: 8px 0; }
.reasoning .why-title { font-size: 11px; font-weight: 700; color: #165DFF; margin-bottom: 4px; }
.reasoning .why-body { font-size: 12px; color: #4e5969; line-height: 1.7; }
.reasoning .why-body strong { color: #1d2129; }
.scheme-box { border: 1px solid #e5e6eb; border-radius: 12px; margin: 14px 0; overflow: hidden; }
.scheme-head { padding: 12px 16px; display: flex; align-items: center; gap: 10px; }
.scheme-head.conservative { background: linear-gradient(135deg, #165DFF, #4080FF); color: #fff; }
.scheme-head.aggressive { background: linear-gradient(135deg, #f53f3f, #ff6b6b); color: #fff; }
.scheme-head .icon { font-size: 18px; }
.scheme-head .title { font-size: 14px; font-weight: 600; flex: 1; }
.scheme-head .tag-scheme { background: rgba(255,255,255,0.25); padding: 2px 8px; border-radius: 10px; font-size: 10px; }
.scheme-body { padding: 16px 18px; background: #fff; }
.data-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin: 12px 0; }
.data-card { background: #f7f8fa; border-radius: 10px; padding: 14px; border: 1px solid #e5e6eb; }
.data-card .metric { font-size: 22px; font-weight: 700; margin-bottom: 4px; }
.data-card .metric.up { color: #00b42a; }
.data-card .metric.down { color: #f53f3f; }
.data-card .metric.neutral { color: #ff7d00; }
.data-card .label { font-size: 11px; color: #86909c; }
.data-card .note { font-size: 10px; color: #4e5969; margin-top: 4px; line-height: 1.5; }
.discuss { background: #fafbfc; border: 1px dashed #c9cdd4; border-radius: 12px; padding: 18px 20px; margin: 14px 0; }
.discuss-title { font-size: 14px; font-weight: 600; margin-bottom: 10px; }
.discuss-vs { display: grid; grid-template-columns: 1fr auto 1fr; gap: 12px; }
.discuss-option { background: #fff; border-radius: 10px; padding: 14px; border: 1px solid #e5e6eb; }
.discuss-option.preferred { border-color: #00b42a; border-width: 2px; }
.discuss-option .t { font-size: 12px; font-weight: 600; margin-bottom: 6px; }
.discuss-option.preferred .t::after { content: " ✓ 推荐"; color: #00b42a; font-weight: 700; }
.discuss-option ul { padding-left: 14px; }
.discuss-option li { font-size: 11px; margin-bottom: 3px; }
.discuss-vs-center { display: flex; align-items: center; font-size: 14px; color: #86909c; font-weight: 700; padding-top: 30px; }
.compare-imgs { display: flex; gap: 14px; margin: 14px 0; flex-wrap: wrap; }
.compare-imgs > div { flex: 1; min-width: 200px; max-width: 280px; }
.compare-imgs img { width: 100%; border-radius: 10px; border: 2px solid #e5e6eb; }
.compare-imgs .danger img { border-color: #f53f3f; }
.compare-imgs .good img { border-color: #00b42a; }
.compare-imgs .caption { font-size: 11px; padding: 6px; text-align: center; }
.compare-imgs .caption.danger-cap { color: #f53f3f; }
.compare-imgs .caption.good-cap { color: #00b42a; font-weight: 600; }
.footer { text-align: center; font-size: 11px; color: #86909c; margin-top: 30px; padding: 20px 0; }
@media (max-width: 720px) {
  .verdict { flex-direction: column; }
  .nav { position: static; }
  .discuss-vs { grid-template-columns: 1fr; }
  .discuss-vs-center { padding: 0; }
  .hi-flow { flex-direction: column; }
  .hi-step { flex: 0 0 auto; max-width: 320px; margin: 0 auto; }
  .hi-arrow { transform: rotate(90deg); padding: 8px 0; }
}
"""


# ===== HTML 骨架(用 .format() 填充) =====
HTML_SKELETON = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{title} · PRD 可行性分析</title>
<style>{css}</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>{header_h1}</h1>
    <div class="sub">{header_sub}</div>
    <div class="meta">{header_meta}</div>
  </div>

  <div class="verdict">
    <div class="verdict-score">
      <div class="ring" style="border: 6px solid {verdict_color}; color: {verdict_color};">{verdict_score}</div>
      <div class="label">综合可行性</div>
    </div>
    <div class="verdict-detail">
      <h3>{verdict_headline}</h3>
      <div class="items">{verdict_items}</div>
    </div>
  </div>

  <div class="nav">
    <a href="#s1"><span class="num">1</span>逻辑硬伤</a>
    <a href="#s2"><span class="num">2</span>方案评估</a>
    <a href="#s3"><span class="num">3</span>双方案</a>
    <a href="#s4"><span class="num">4</span>数据预估</a>
    <a href="#s5"><span class="num">5</span>专题探讨</a>
    <a href="#s6"><span class="num">6</span>整体结论</a>
  </div>

  <!-- Section 1: 业务逻辑硬伤 -->
  <div class="section" id="s1">
    <h2><span class="badge">1</span>业务逻辑硬伤 · 这些事影响需求成败</h2>
    {section1_content}
  </div>

  <!-- Section 2: 方案逐步评估(含高保真流程) -->
  <div class="section" id="s2">
    <h2><span class="badge">2</span>PRD 原方案 · 高保真流程逐步评估</h2>
    {section2_content}
  </div>

  <!-- Section 3: 双方案 -->
  <div class="section" id="s3">
    <h2><span class="badge">3</span>优化方向 · 两套候选方案</h2>
    {section3_content}
  </div>

  <!-- Section 4: 数据预估 -->
  <div class="section" id="s4">
    <h2><span class="badge">4</span>上线后数据预估 · 哪些会涨、哪些会跌</h2>
    {section4_content}
  </div>

  <!-- Section 5: 专题探讨 -->
  <div class="section" id="s5">
    <h2><span class="badge">5</span>专题探讨</h2>
    {section5_content}
  </div>

  <!-- Section 6: 整体结论(注意:以需求为中心,不以使用者为中心) -->
  <div class="section" id="s6">
    <h2><span class="badge">6</span>整体结论 · 让这个需求真正跑通的关键</h2>
    {section6_content}
  </div>

  <div class="footer">PRD 可行性分析 · 高保真流程版 · {date}</div>
</div>
<script>
  document.querySelectorAll(".nav a").forEach(a => {{
    a.addEventListener("click", e => {{
      e.preventDefault();
      const t = document.querySelector(a.getAttribute("href"));
      if (t) t.scrollIntoView({{behavior:"smooth", block:"start"}});
    }});
  }});
</script>
</body>
</html>"""


# ===== Builder 辅助函数(按 section 拼内容) =====

def build_hi_flow_step(step_num, color, tag_label, img_b64, title, body):
    """单个高保真流程屏(数字+标签+截图+注解)"""
    return f"""<div class="hi-step">
  <div class="hi-screen-wrap {color}">
    <div class="hi-step-num {color}">{step_num}</div>
    <div class="hi-tag-overlay {color}">{tag_label}</div>
    <img src="{img_b64}" alt="step {step_num}">
  </div>
  <div class="hi-annotation">
    <div class="hi-anno-title {color}">{title}</div>
    <div class="hi-anno-body">{body}</div>
  </div>
</div>"""


def build_reasoning_box(why_body_html):
    """硬伤下方的"为什么这是个问题"推理框"""
    return f"""<div class="reasoning">
  <div class="why-title">为什么这是个问题?</div>
  <div class="why-body">{why_body_html}</div>
</div>"""


def build_data_card(metric, label, note, kind="up"):
    """数据预估卡片,kind=up/down/neutral"""
    return f"""<div class="data-card">
  <div class="metric {kind}">{metric}</div>
  <div class="label">{label}</div>
  <div class="note">{note}</div>
</div>"""


# ===== 主入口 =====

def generate(config=CONFIG, sections=None):
    """sections 是一个 dict: {section1_content, section2_content, ...}"""
    if sections is None:
        sections = {f"section{i}_content": f"<p>TODO: Section {i} content</p>" for i in range(1, 7)}

    verdict_items_html = "".join(
        f'<div class="verdict-item vi-{k}">{v}</div>' for k, v in config["verdict_items"]
    )

    html = HTML_SKELETON.format(
        title=config["title"],
        css=CSS,
        header_h1=config["header_h1"],
        header_sub=config["header_sub"],
        header_meta="".join(f"<span>{m}</span>" for m in config["header_meta"]),
        verdict_score=config["verdict_score"],
        verdict_color=config["verdict_color"],
        verdict_headline=config["verdict_headline"],
        verdict_items=verdict_items_html,
        date=config["header_meta"][-1] if config["header_meta"] else "",
        **sections,
    )

    out_path = os.path.expanduser(f"~/Desktop/{config['title']}-PRD可行性分析.html")
    with open(out_path, "w") as f:
        f.write(html)
    print(f"Generated: {out_path}")
    print(f"Size: {os.path.getsize(out_path)/1024:.1f} KB")
    return out_path


if __name__ == "__main__":
    # 示例:加载图片 + 生成空骨架(实际使用时各 section_content 由 skill 主流程填充)
    imgs = load_images(CONFIG["asset_dir"], CONFIG["image_keys"])
    print(f"Loaded {len(imgs)} images")
    generate(CONFIG)
