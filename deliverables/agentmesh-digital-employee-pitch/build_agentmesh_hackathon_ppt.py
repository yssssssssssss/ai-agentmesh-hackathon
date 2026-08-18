#!/usr/bin/env python3
"""Build the AgentMesh hackathon pitch deck as an editable PPTX.

The environment does not require python-pptx. We reuse an existing 16:9 PPTX
package as the container and replace slide XML with DrawingML shapes/text.
"""

from __future__ import annotations

import html
import shutil
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "deliverables/bbs-collaboration-roadshow/AgentMesh-BBS-协作图投资路演.pptx"
FALLBACK_SOURCE = ROOT / "deliverables/twinmesh-hackathon/TwinMesh-hackathon-roadshow.pptx"
TARGET = ROOT / "deliverables/agentmesh-digital-employee-pitch/AgentMesh-10分钟黑客松项目介绍.pptx"

EMU = 914400
SLIDE_W = 12192000
SLIDE_H = 6858000

BG = "08111F"
PANEL = "111827"
PANEL2 = "172033"
TEXT = "F8FAFC"
MUTED = "94A3B8"
LINE = "334155"
BLUE = "60A5FA"
BLUE_D = "1D4ED8"
PURPLE = "A78BFA"
PURPLE_D = "6D28D9"
GREEN = "34D399"
GREEN_D = "047857"
ORANGE = "FB923C"
ORANGE_D = "C2410C"
RED = "F87171"
RED_D = "B91C1C"
YELLOW = "FBBF24"


def emu(v: float) -> int:
    return int(v * EMU)


def esc(value: str) -> str:
    return html.escape(value, quote=True)


class SlideBuilder:
    def __init__(self) -> None:
        self.shape_id = 2
        self.items: list[str] = []
        self.rect(0, 0, 13.3334, 7.5, BG, BG)
        self.rect(0.05, 0.05, 13.233, 7.4, None, LINE, radius="roundRect", line_w=9000)

    def next_id(self) -> int:
        value = self.shape_id
        self.shape_id += 1
        return value

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: str | None = PANEL,
        line: str | None = LINE,
        *,
        radius: str = "roundRect",
        line_w: int = 16000,
        text: str | None = None,
        size: int = 18,
        color: str = TEXT,
        bold: bool = False,
        align: str = "ctr",
        valign: str = "mid",
        margin: float = 0.08,
    ) -> None:
        spid = self.next_id()
        fill_xml = f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else "<a:noFill/>"
        line_xml = (
            f'<a:ln w="{line_w}"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>'
            if line
            else "<a:ln><a:noFill/></a:ln>"
        )
        tx = self._text_body(text or "", size=size, color=color, bold=bold, align=align, valign=valign, margin=margin) if text else ""
        self.items.append(
            f"""
            <p:sp>
              <p:nvSpPr><p:cNvPr id="{spid}" name="Shape {spid}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
              <p:spPr>
                <a:xfrm><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>
                <a:prstGeom prst="{radius}"><a:avLst/></a:prstGeom>
                {fill_xml}
                {line_xml}
              </p:spPr>
              {tx}
            </p:sp>
            """
        )

    def text(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        value: str,
        *,
        size: int = 18,
        color: str = TEXT,
        bold: bool = False,
        align: str = "l",
        valign: str = "top",
        margin: float = 0.05,
    ) -> None:
        self.rect(x, y, w, h, None, None, radius="rect", text=value, size=size, color=color, bold=bold, align=align, valign=valign, margin=margin)

    def line(self, x1: float, y1: float, x2: float, y2: float, color: str = LINE, width: int = 18000, arrow: bool = False) -> None:
        spid = self.next_id()
        x = min(x1, x2)
        y = min(y1, y2)
        w = abs(x2 - x1) or 0.01
        h = abs(y2 - y1) or 0.01
        flip_h = ' flipH="1"' if x2 < x1 else ""
        flip_v = ' flipV="1"' if y2 < y1 else ""
        arrow_xml = '<a:tailEnd type="triangle"/>' if arrow else ""
        self.items.append(
            f"""
            <p:cxnSp>
              <p:nvCxnSpPr><p:cNvPr id="{spid}" name="Connector {spid}"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>
              <p:spPr>
                <a:xfrm{flip_h}{flip_v}><a:off x="{emu(x)}" y="{emu(y)}"/><a:ext cx="{emu(w)}" cy="{emu(h)}"/></a:xfrm>
                <a:prstGeom prst="straightConnector1"><a:avLst/></a:prstGeom>
                <a:ln w="{width}"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill>{arrow_xml}</a:ln>
              </p:spPr>
            </p:cxnSp>
            """
        )

    def header(self, no: str, kicker: str, title: str, subtitle: str) -> None:
        self.rect(0.55, 0.42, 1.0, 0.36, PURPLE_D, PURPLE_D, text=no, size=13, bold=True)
        self.text(1.68, 0.39, 4.8, 0.45, kicker, size=12, color=MUTED, bold=True)
        self.text(0.55, 0.82, 9.5, 0.55, title, size=28, bold=True)
        self.text(0.58, 1.38, 10.7, 0.42, subtitle, size=13, color=MUTED)

    def cue(self, value: str) -> None:
        self.rect(0.55, 6.72, 12.25, 0.46, PANEL2, LINE, radius="roundRect", text=f"口播提示：{value}", size=11, color=MUTED, align="l", margin=0.12)

    def bullets(self, x: float, y: float, w: float, h: float, items: list[str], *, size: int = 16, color: str = TEXT) -> None:
        self.text(x, y, w, h, "\n".join(f"• {item}" for item in items), size=size, color=color, align="l")

    def _text_body(
        self,
        value: str,
        *,
        size: int,
        color: str,
        bold: bool,
        align: str,
        valign: str,
        margin: float,
    ) -> str:
        anchor = {"top": "t", "mid": "mid", "bottom": "b"}.get(valign, "t")
        paragraphs = value.split("\n") or [""]
        p_xml = []
        for paragraph in paragraphs:
            p_xml.append(
                f"""
                <a:p>
                  <a:pPr algn="{align}"/>
                  <a:r>
                    <a:rPr lang="zh-CN" sz="{size * 100}" b="{1 if bold else 0}">
                      <a:solidFill><a:srgbClr val="{color}"/></a:solidFill>
                      <a:latin typeface="Microsoft YaHei"/>
                      <a:ea typeface="Microsoft YaHei"/>
                    </a:rPr>
                    <a:t>{esc(paragraph)}</a:t>
                  </a:r>
                </a:p>
                """
            )
        return (
            f"""
            <p:txBody>
              <a:bodyPr wrap="square" anchor="{anchor}" lIns="{emu(margin)}" rIns="{emu(margin)}" tIns="{emu(margin)}" bIns="{emu(margin)}"/>
              <a:lstStyle/>
              {''.join(p_xml)}
            </p:txBody>
            """
        )

    def xml(self) -> bytes:
        body = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
      {''.join(self.items)}
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>
"""
        return body.encode("utf-8")


def add_relay(slide: SlideBuilder, x: float, y: float, labels: list[tuple[str, str, str]], colors: list[str]) -> None:
    card_w = 2.25
    gap = 0.18
    for i, (icon, title, desc) in enumerate(labels):
        cx = x + i * (card_w + gap)
        slide.rect(cx, y, card_w, 2.15, PANEL, colors[i], radius="roundRect", line_w=18000)
        slide.text(cx + 0.12, y + 0.16, 0.55, 0.45, icon, size=24, align="c")
        slide.text(cx + 0.14, y + 0.72, card_w - 0.28, 0.35, title, size=16, bold=True, align="c")
        slide.text(cx + 0.20, y + 1.16, card_w - 0.4, 0.72, desc, size=10, color=MUTED, align="c")
        if i < len(labels) - 1:
            slide.line(cx + card_w + 0.02, y + 1.08, cx + card_w + gap - 0.02, y + 1.08, MUTED, width=15000, arrow=True)


def slide_1() -> bytes:
    s = SlideBuilder()
    s.text(0.72, 0.62, 3.0, 0.35, "HACKATHON PITCH", size=13, color=MUTED, bold=True)
    s.text(0.72, 1.05, 9.2, 1.05, "AgentMesh", size=48, bold=True)
    s.text(0.78, 2.02, 9.6, 0.72, "团队数字员工网络：会协作、会记忆、有治理", size=27, color=TEXT, bold=True)
    s.text(0.82, 2.95, 8.5, 0.55, "把个人 AI 助手升级成团队可用的数字员工体系，让资料、数据、风险和记忆围绕同一条工作链路接力。", size=15, color=MUTED)
    add_relay(
        s,
        0.82,
        3.85,
        [
            ("🔎", "找资料", "相似项目 / 外部资料 / 文档来源"),
            ("📊", "查数据", "点击率 / 转化率 / 业务指标"),
            ("🛡️", "审风险", "素材授权 / Prompt 注入 / 高危工具"),
            ("🧠", "沉淀记忆", "个人 / 项目 / 团队三级资产"),
            ("🤝", "Agent 互助", "供需信号 / 自动匹配 / 贡献记录"),
        ],
        [BLUE, GREEN, ORANGE, PURPLE, RED],
    )
    s.cue("开场先讲一句话定位，不急着讲技术。重点是“不是一个 ChatBot，而是一组数字员工”。")
    return s.xml()


def slide_2() -> bytes:
    s = SlideBuilder()
    s.header("02", "真实痛点 / 使用场景", "团队每天都在损失三样最贵的东西", "信息在流动，但没有沉淀；AI 能力在增强，但过程缺少治理。")
    cards = [
        ("经验流失", "去年 618 家电会场做过什么方案，效果如何？\n现状：翻聊天记录，运气不好就重新踩坑。", BLUE),
        ("多源割裂", "指标在 BI，竞品资料在外部搜索，风险规则在法务文档。\n一个问题要开好几个系统。", PURPLE),
        ("审批黑洞", "AI 能帮忙产出，但素材授权、批量抓取、内网访问谁确认？\n很多团队只能靠邮件和口头约定。", ORANGE),
    ]
    for i, (title, desc, color) in enumerate(cards):
        x = 0.72 + i * 4.08
        s.rect(x, 2.05, 3.72, 3.75, PANEL, color, line_w=18000)
        s.text(x + 0.25, 2.34, 3.15, 0.42, title, size=21, bold=True)
        s.text(x + 0.25, 3.05, 3.1, 1.75, desc, size=15, color=MUTED)
        s.rect(x + 0.25, 5.2, 1.1, 0.32, color, color, text=f"痛点 {i + 1}", size=10, bold=True)
    s.cue("用三个真实场景代入，不抽象讲效率低。评委会更容易理解为什么这个项目值得做。")
    return s.xml()


def slide_3() -> bytes:
    s = SlideBuilder()
    s.header("03", "整体架构", "一个聊天入口，背后是一套可治理的 Agent 协作系统", "用户只看见 Workspace，后台通过 Personal Agent、专业 Agent、Blackboard 和记忆系统完成任务。")
    layers = [
        (0.9, 2.0, 11.5, 0.62, "React / Vite 前端：Workspace、Knowledge、Insights、Collaboration、Market", BLUE),
        (0.9, 2.85, 11.5, 0.62, "FastAPI 路由层：chat、memory、market、blackboard、inbox、users", PURPLE),
        (0.9, 3.7, 11.5, 0.95, "Agent 协作引擎：Personal Agent 调度 Research / Data / Risk Agent", GREEN),
        (0.9, 4.9, 11.5, 0.62, "Blackboard：request、evidence、risk、decision、handoff、memory_candidate", ORANGE),
        (0.9, 5.75, 11.5, 0.62, "SQLite Store + 外部 Provider：O2、Web、Data、LLM、文档解析", RED),
    ]
    for x, y, w, h, text, color in layers:
        s.rect(x, y, w, h, PANEL, color, text=text, size=16, bold=True, align="l", margin=0.18)
    for y in [2.62, 3.47, 4.65, 5.52]:
        s.line(6.65, y, 6.65, y + 0.22, MUTED, arrow=True)
    s.cue("强调 Blackboard 是协作账本，不是普通论坛。能力扩展、权限和审计都在这条链路上。")
    return s.xml()


def slide_4() -> bytes:
    s = SlideBuilder()
    s.header("04", "10 分钟演示路线", "按真实工作链路演，不按功能菜单背说明书", "个人能力拓展、记忆沉淀、Agent 互助和项目价值，是整场演示的四个抓手。")
    steps = [
        ("0:00", "真实痛点", "经验流失、多源割裂、审批黑洞"),
        ("1:20", "整体架构", "chat-first + 多 Agent + Blackboard"),
        ("2:30", "个人能力", "$research / $data / $risk"),
        ("4:00", "记忆系统", "个人、项目、团队三级记忆"),
        ("6:30", "Agent 互助", "发布信号、自动匹配、贡献记录"),
        ("8:20", "项目价值", "工程可信度与下一步"),
    ]
    for i, (time, title, desc) in enumerate(steps):
        x = 0.72 + i * 2.02
        s.rect(x, 2.28, 1.72, 0.48, PURPLE_D if i in [0, 2, 4] else BLUE_D, None, text=time, size=15, bold=True)
        s.line(x + 0.86, 2.78, x + 0.86, 3.24, MUTED, arrow=True)
        s.rect(x, 3.28, 1.72, 1.85, PANEL, [BLUE, PURPLE, GREEN, ORANGE, RED, YELLOW][i], text=title, size=16, bold=True)
        s.text(x + 0.12, 4.35, 1.48, 0.48, desc, size=9, color=MUTED, align="c")
    s.cue("告诉评委接下来会看真实页面和真实链路，不是只讲概念。")
    return s.xml()


def slide_5() -> bytes:
    s = SlideBuilder()
    s.header("05", "个人能力拓展", "$ skill 让个人能力变成可审计工作流", "普通聊天默认私有；用户明确输入 $ skill 后，系统才进入任务、证据、审计和记忆链路。")
    s.rect(5.55, 2.55, 2.25, 1.55, "2563EB", "60A5FA", radius="ellipse", text="Personal\nAgent", size=22, bold=True)
    caps = [
        (1.0, 2.15, "资料能力", "$research.request\n带来源调研结果", BLUE),
        (9.9, 2.15, "风险能力", "$risk.review\n高风险进入 Inbox", ORANGE),
        (1.0, 4.75, "数据能力", "$data.query\n指标查询和证据帖", GREEN),
        (9.9, 4.75, "沉淀能力", "$note.save\n$memory.propose", PURPLE),
    ]
    for x, y, title, desc, color in caps:
        s.rect(x, y, 2.55, 1.36, PANEL, color, text=f"{title}\n{desc}", size=14, bold=True)
        s.line(6.65, 3.34, x + 1.28, y + 0.68, color, width=20000, arrow=True)
    s.rect(4.05, 5.25, 5.15, 0.7, PANEL2, LINE, text="答案带 Sources，风险有 Inbox，过程进 Audit", size=17, bold=True)
    s.cue("现场演示 Workspace 输入 $system.info，再演 $research、$data、$risk 中的 1 到 2 个。")
    return s.xml()


def slide_6() -> bytes:
    s = SlideBuilder()
    s.header("06", "能力调用流程", "调研、数据、风险分别由不同 Agent 处理，最后回到一个回答里", "这页用来回答评委的技术追问：入口、路由、证据、风险、人审和记忆如何串起来。")
    steps = [
        ("用户", "输入 $research / $data / $risk", BLUE),
        ("Skill Registry", "解析 ChatSkillSpec", PURPLE),
        ("Personal Agent", "创建任务并调度", GREEN),
        ("专业 Agent", "返回证据和来源", ORANGE),
        ("Inbox / Memory", "人审或沉淀", RED),
        ("回答", "带来源 + workflow trace", YELLOW),
    ]
    for i, (title, desc, color) in enumerate(steps):
        x = 0.75 + i * 2.03
        s.rect(x, 2.52, 1.65, 1.35, PANEL, color, text=f"{title}\n{desc}", size=12, bold=True)
        if i < len(steps) - 1:
            s.line(x + 1.67, 3.2, x + 2.0, 3.2, MUTED, arrow=True)
    s.rect(1.1, 4.7, 11.1, 0.95, PANEL2, LINE, text="高风险或可疑内容不会直接喂给模型，会先创建待确认项；正常证据写入 Sources 和短期记忆。", size=17, bold=True)
    s.cue("讲清楚显式 $ skill 的好处：不靠隐式猜意图，权限和审计边界清楚。")
    return s.xml()


def slide_7() -> bytes:
    s = SlideBuilder()
    s.header("07", "记忆模块", "三级记忆把工作内容变成可治理的资产", "Layer 管沉淀深度，Scope 管谁能看；团队记忆必须经过候选和接受流程。")
    s.rect(1.2, 4.95, 6.0, 0.82, "1D4ED8", BLUE, text="个人记忆：short_term\n今天做了什么、个人笔记、工作流结果", size=15, bold=True)
    s.rect(1.75, 3.8, 4.9, 0.82, "047857", GREEN, text="项目记忆：mid_term / long_term\n阶段总结、项目归档、召回索引", size=15, bold=True)
    s.rect(2.35, 2.65, 3.7, 0.82, "B91C1C", RED, text="团队记忆：TEAM_ACCEPTED\n审核后的共享知识资产", size=15, bold=True)
    s.line(7.65, 4.2, 8.6, 4.2, ORANGE, arrow=True)
    s.rect(8.85, 2.55, 3.15, 2.55, PANEL, ORANGE, text="审核闸门\nlead / admin 接受\n\n状态治理\nproposed / accepted\ndisputed / expired\ndeprecated", size=17, bold=True)
    s.rect(1.2, 1.95, 5.98, 0.32, PANEL2, LINE, text="检索融合：FTS5 + vector + RRF，结果带来源引用", size=13, color=MUTED, bold=True)
    s.cue("这页是技术纵深重点。不要把记忆讲成“存知识”，要讲分层、治理、检索、提炼。")
    return s.xml()


def slide_8() -> bytes:
    s = SlideBuilder()
    s.header("08", "记忆如何流动", "从一次工作流，到团队可复用知识，再到 LearnedSkill", "有价值的内容逐级收敛；重复成功的工作模式会被提炼为可复用 Skill。")
    flow = [
        ("$ skill 工作流", BLUE),
        ("个人短期记忆", BLUE),
        ("每日摘要", GREEN),
        ("项目中期记忆", GREEN),
        ("长期归档", ORANGE),
        ("团队候选", ORANGE),
        ("团队接受", RED),
    ]
    for i, (title, color) in enumerate(flow):
        x = 0.65 + i * 1.78
        s.rect(x, 2.35, 1.38, 0.95, PANEL, color, text=title, size=12, bold=True)
        if i < len(flow) - 1:
            s.line(x + 1.4, 2.82, x + 1.73, 2.82, MUTED, arrow=True)
    s.rect(0.85, 4.15, 5.35, 1.55, PANEL2, PURPLE, text="Skill 提炼\n同类成功工作流 >= 3 次\n→ 提出 LearnedSkill 草稿\n→ 用户激活 / 分享 / 废弃", size=17, bold=True)
    s.rect(7.0, 4.15, 5.35, 1.55, PANEL2, BLUE, text="演示动作\nKnowledge 接受候选记忆\nInsights 看短中长期统计\n必要时打开代码证明 skill_extractor.py", size=17, bold=True)
    s.cue("如 Insights 中某些卡片还是参考数据，要如实说明，逻辑和测试已经在代码里。")
    return s.xml()


def slide_9() -> bytes:
    s = SlideBuilder()
    s.header("09", "Agent 互助市场", "知识不只被动搜索，还能主动流动", "用户 opt-in 后，个人 Agent 发布需求信号，其他 Agent 扫描匹配并给出抽象答案。")
    s.rect(5.55, 3.08, 2.25, 1.5, "6D28D9", PURPLE, radius="ellipse", text="我\nPersonal Agent", size=21, bold=True)
    nodes = [
        (1.25, 2.0, "同事 A\n有相关经验", BLUE),
        (9.9, 2.0, "同事 B\n正在求助", GREEN),
        (1.35, 5.05, "同事 C\n提供数据线索", ORANGE),
        (9.85, 5.05, "同事 D\n需要风险建议", RED),
        (5.55, 1.45, "BBS / Market\n信号与匹配", YELLOW),
    ]
    for x, y, label, color in nodes:
        s.rect(x, y, 2.25, 0.85, PANEL, color, text=label, size=13, bold=True)
        s.line(6.67, 3.82, x + 1.12, y + 0.43, color, width=20000, arrow=True)
    s.rect(4.1, 5.55, 5.1, 0.52, PANEL2, LINE, text="采纳后记录 ContributionPoint，并写回 MemoryRelation", size=15, bold=True)
    s.cue("强调默认不是全员广播，用户 opt-in 才参与；返回的是抽象答案，不是原始记忆。")
    return s.xml()


def slide_10() -> bytes:
    s = SlideBuilder()
    s.header("10", "互助市场演示链路", "agent-1 发布信号，agent-2 扫描匹配，采纳后记录贡献", "演示前提前触发 publish_all_signals(store) 和 scout_all(store)，不要在台上等待 worker。")
    steps = [
        ("1", "加入市场", "用户 opt-in", BLUE),
        ("2", "发布信号", "publish_all_signals", PURPLE),
        ("3", "自动匹配", "scout_all", GREEN),
        ("4", "代答返回", "marketplace_match", ORANGE),
        ("5", "采纳贡献", "ContributionPoint", RED),
    ]
    for i, (num, title, desc, color) in enumerate(steps):
        x = 0.9 + i * 2.35
        s.rect(x, 2.2, 0.62, 0.62, color, color, radius="ellipse", text=num, size=20, bold=True)
        s.rect(x - 0.28, 3.1, 1.95, 1.5, PANEL, color, text=f"{title}\n{desc}", size=14, bold=True)
        if i < len(steps) - 1:
            s.line(x + 1.7, 3.85, x + 2.05, 3.85, MUTED, arrow=True)
    s.rect(1.2, 5.32, 10.9, 0.55, PANEL2, LINE, text="Collaboration 看组织级看板，Market 看“我”的个人视角时间线。", size=16, bold=True)
    s.cue("这一段讲“流动资产”。贡献点已记录，但排行榜和兑换规则仍是下一步。")
    return s.xml()


def slide_11() -> bytes:
    s = SlideBuilder()
    s.header("11", "项目价值", "把工作过程变成可积累、可复用、可激励的团队资产", "AgentMesh 的价值不在多一个入口，而在把能力、记忆、协作和治理连成飞轮。")
    center_x, center_y = 5.65, 3.25
    s.rect(center_x, center_y, 2.15, 1.28, "2563EB", BLUE, radius="ellipse", text="团队 AI\n工作大脑", size=20, bold=True)
    items = [
        (5.55, 1.9, "做事\nchat + skill", BLUE),
        (9.05, 2.75, "沉淀\n个人 / 项目记忆", GREEN),
        (8.05, 5.05, "审核\n团队知识资产", ORANGE),
        (3.0, 5.05, "互助\nAgent 市场", PURPLE),
        (2.1, 2.75, "激励\n贡献记录", RED),
    ]
    for x, y, text, color in items:
        s.rect(x, y, 2.05, 0.82, PANEL, color, text=text, size=14, bold=True)
        s.line(center_x + 1.08, center_y + 0.64, x + 1.02, y + 0.41, color, width=19000, arrow=True)
    s.rect(0.86, 6.05, 11.7, 0.42, PANEL2, LINE, text="通用 ChatBot 只能聊；企业知识库只能搜；AgentMesh 把团队工作链路变成可治理的 AI 协作系统。", size=13, bold=True)
    s.cue("用这一页收束差异化。不要夸成全自动企业操作系统，讲“已打通的 MVP 链路”。")
    return s.xml()


def slide_12() -> bytes:
    s = SlideBuilder()
    s.header("12", "收尾与演示红线", "每一句“已完成”都要经得起现场追问", "黑客松路演要有野心，也要诚实。真实边界讲清楚，可信度反而更高。")
    s.rect(0.8, 2.0, 5.75, 3.75, PANEL, GREEN, text="现场演示检查\n\n• demo 模式服务可启动\n• $system.info 能看到技能和模型\n• Knowledge 候选记忆可接受\n• Market 有提前触发的真实匹配\n• 测试收集结果：551 tests collected", size=16, bold=True, align="l", margin=0.22)
    s.rect(6.85, 2.0, 5.75, 3.75, PANEL, ORANGE, text="诚实边界\n\n• 当前是可信内网 MVP\n• 单 Workspace、SQLite、本地 session\n• O2 / Web / Data Provider 依赖演示机凭证\n• ContributionPoint 已记录，排行榜和兑换规则还没做", size=16, bold=True, align="l", margin=0.22)
    s.rect(1.15, 6.05, 11.05, 0.48, PURPLE_D, PURPLE_D, text="AgentMesh：安全、可审计、会协作、会记忆的团队数字员工体系。", size=18, bold=True)
    s.cue("最后 10 秒直接收口：每个阶段都有 Agent 接力，每一步都有来源和审计，经验不会散。")
    return s.xml()


SLIDE_BUILDERS = [
    slide_1,
    slide_2,
    slide_3,
    slide_4,
    slide_5,
    slide_6,
    slide_7,
    slide_8,
    slide_9,
    slide_10,
    slide_11,
    slide_12,
]


def main() -> int:
    source = SOURCE if SOURCE.exists() else FALLBACK_SOURCE
    if not source.exists():
        print(f"Missing source deck: {source}", file=sys.stderr)
        return 1

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, TARGET)

    with zipfile.ZipFile(TARGET, "r") as source_zip:
        files = {name: source_zip.read(name) for name in source_zip.namelist()}

    for index, builder in enumerate(SLIDE_BUILDERS, start=1):
        path = f"ppt/slides/slide{index}.xml"
        if path not in files:
            print(f"Missing slide slot in template: {path}", file=sys.stderr)
            return 1
        files[path] = builder()

    with zipfile.ZipFile(TARGET, "w", compression=zipfile.ZIP_DEFLATED) as target_zip:
        for name, payload in files.items():
            target_zip.writestr(name, payload)

    bad = None
    with zipfile.ZipFile(TARGET, "r") as target_zip:
        bad = target_zip.testzip()
        for index in range(1, len(SLIDE_BUILDERS) + 1):
            ET.fromstring(target_zip.read(f"ppt/slides/slide{index}.xml"))
    if bad:
        print(f"Corrupt file in pptx: {bad}", file=sys.stderr)
        return 1

    print(TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
