"""Render trusted report Markdown as a self-contained, script-free HTML document."""

from __future__ import annotations

from collections.abc import Sequence
from html import escape

from markdown_it import MarkdownIt
from markdown_it.renderer import EnvType, OptionsDict
from markdown_it.token import Token

_REPORT_CSS = """
:root {
  color-scheme: light;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC",
    "Microsoft YaHei", "Noto Sans SC", sans-serif;
  color: #28312d;
  background: #e9e7e0;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: #e9e7e0; }
a { color: #0b715b; text-underline-offset: 3px; }
a:hover { color: #075846; }
.report-toolbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 64px;
  padding: 10px max(20px, calc((100vw - 960px) / 2));
  color: #dce8e3;
  background: #101612;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.report-toolbar__context { min-width: 0; }
.report-toolbar__eyebrow {
  margin: 0 0 2px;
  color: #6ee7bd;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.report-toolbar__title {
  overflow: hidden;
  margin: 0;
  color: #edf5f1;
  font-size: 14px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.report-toolbar__actions { display: flex; flex: none; align-items: center; gap: 8px; }
.report-action {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  padding: 0 14px;
  border-radius: 9px;
  color: #dce8e3;
  background: rgba(255, 255, 255, 0.06);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}
.report-action--primary { color: #08271f; background: #54e6bb; }
.report-shell { width: min(100% - 32px, 960px); margin: 32px auto 64px; }
.report-document {
  overflow-wrap: anywhere;
  padding: 56px clamp(28px, 7vw, 84px) 72px;
  background: #fffefb;
  box-shadow: 0 24px 70px -42px rgba(22, 31, 27, 0.55);
}
.report-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0 0 28px;
  padding-bottom: 18px;
  border-bottom: 1px solid #dedbd3;
  color: #69716c;
  font-size: 12px;
}
.report-meta span { padding: 5px 9px; border-radius: 999px; background: #f1efe8; }
.report-document h1,
.report-document h2,
.report-document h3,
.report-document h4 { color: #18231e; text-wrap: balance; }
.report-document h1 { margin: 0 0 30px; font-size: 36px; line-height: 1.24; }
.report-document h2 {
  margin: 42px 0 14px;
  padding-top: 4px;
  font-size: 23px;
  line-height: 1.35;
  border-top: 1px solid #e5e1d8;
}
.report-document h3 { margin: 28px 0 10px; font-size: 18px; line-height: 1.45; }
.report-document h4 { margin: 22px 0 8px; font-size: 15px; line-height: 1.55; }
.report-document p,
.report-document li { font-size: 15px; line-height: 1.82; }
.report-document p { margin: 12px 0; text-wrap: pretty; }
.report-document ul,
.report-document ol { margin: 12px 0; padding-left: 24px; }
.report-document li + li { margin-top: 5px; }
.report-document blockquote {
  margin: 20px 0;
  padding: 12px 16px;
  color: #53615a;
  background: #f2f5f1;
  border-radius: 8px;
}
.report-document code {
  padding: 2px 5px;
  border-radius: 4px;
  color: #155e4b;
  background: #edf4f0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.9em;
}
.report-document pre {
  overflow-x: auto;
  margin: 18px 0;
  padding: 16px;
  border-radius: 9px;
  color: #e6ede9;
  background: #17201c;
  line-height: 1.65;
}
.report-document pre code { padding: 0; color: inherit; background: transparent; }
.report-document table {
  display: block;
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  margin: 22px 0 28px;
  border-collapse: collapse;
  font-size: 13px;
  line-height: 1.6;
  -webkit-overflow-scrolling: touch;
}
.report-document th,
.report-document td {
  min-width: 132px;
  padding: 10px 12px;
  text-align: left;
  vertical-align: top;
  border: 1px solid #d9d6cd;
}
.report-document th { color: #20372e; background: #edf3ef; font-weight: 700; }
.report-document tr:nth-child(even) td { background: #faf9f5; }
.report-document hr { margin: 34px 0; border: 0; border-top: 1px solid #dedbd3; }
.report-document img { display: block; max-width: 100%; height: auto; margin: 20px auto; }
@media (max-width: 640px) {
  .report-toolbar { align-items: flex-start; padding: 10px 14px; }
  .report-toolbar__context { display: none; }
  .report-toolbar__actions { width: 100%; justify-content: space-between; }
  .report-shell { width: 100%; margin: 0; }
  .report-document { padding: 32px 20px 56px; box-shadow: none; }
  .report-document h1 { font-size: 29px; }
  .report-document h2 { margin-top: 34px; font-size: 21px; }
}
@media print {
  :root, body { background: #fff; }
  .report-toolbar { display: none; }
  .report-shell { width: 100%; margin: 0; }
  .report-document { padding: 0; box-shadow: none; }
  .report-document table { display: table; overflow: visible; }
  .report-document thead { display: table-header-group; }
  .report-document tr, .report-document blockquote { break-inside: avoid; }
  .report-document a { color: inherit; text-decoration: none; }
}
""".strip()


def _markdown() -> MarkdownIt:
    renderer = MarkdownIt(
        "commonmark",
        {"html": False, "linkify": False, "typographer": False},
    ).enable(["table", "strikethrough"])

    def render_link_open(
        tokens: Sequence[Token],
        index: int,
        options: OptionsDict,
        env: EnvType,
    ) -> str:
        token = tokens[index]
        href = token.attrGet("href") or ""
        if href.startswith(("http://", "https://")):
            token.attrSet("target", "_blank")
            token.attrSet("rel", "noopener noreferrer")
        return renderer.renderer.renderToken(tokens, index, options, env)

    renderer.renderer.rules["link_open"] = render_link_open
    return renderer


def render_report_html(
    *,
    title: str,
    markdown: str,
    status_label: str,
    back_href: str | None,
    download_href: str | None,
) -> str:
    """Return one portable HTML document with no scripts or external styles."""

    body = _markdown().render(markdown)
    safe_title = escape(title, quote=True)
    safe_status = escape(status_label, quote=True)
    toolbar = ""
    if back_href is not None and download_href is not None:
        safe_back_href = escape(back_href, quote=True)
        safe_download_href = escape(download_href, quote=True)
        toolbar = f"""
  <header class="report-toolbar">
    <div class="report-toolbar__context">
      <p class="report-toolbar__eyebrow">AgentMesh report</p>
      <p class="report-toolbar__title">{safe_title}</p>
    </div>
    <nav class="report-toolbar__actions" aria-label="报告操作">
      <a class="report-action" href="{safe_back_href}">返回对话</a>
      <a class="report-action report-action--primary" href="{safe_download_href}" download>下载 HTML</a>
    </nav>
  </header>"""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src https: http: data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'; script-src 'none'">
  <meta name="referrer" content="no-referrer">
  <title>{safe_title}</title>
  <style>{_REPORT_CSS}</style>
</head>
<body>
{toolbar}
  <main class="report-shell">
    <article class="report-document">
      <p class="report-meta"><span>{safe_status}</span><span>HTML 阅读版</span></p>
      {body}
    </article>
  </main>
</body>
</html>
"""
