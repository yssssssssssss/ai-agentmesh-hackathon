---
name: leader-report
harness-version: 0
description: "一键生成领导汇报页。读取知识库的最新进度数据，生成可在浏览器直接编辑、 导出为 PDF 的 HTML 汇报页。语言面向无技术背景的管理层，屏蔽所有技术术语。 调用示例：\n  /leader-report\n  /leader-report\
  \ --note \"本周重点：完成了国补系列3个案例录入\"\n"
user-invocable: true
triggers:
- 生成汇报
- 整理周报
- 写汇报
allowed-tools:
- Bash
- Read
- Write
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/huangliu-design/product-details/JD-ProductDetails-web/brain-frontend/public/design-kb/skills/leader-report/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 一键生成领导汇报页。读取知识库的最新进度数据，生成可在浏览器直接编辑、 导出为 PDF 的 HTML 汇报页。语言面向无技术背景的管理层，屏蔽所有技术术语。 调用示例： /leader-report…
disable-model-invocation: true
---

# /leader-report · 一键生成领导汇报页

## 工作目录

执行本 skill 前，请先定位到仓库中的 `JD-ProductDetails-web/brain-frontend/` 目录，
所有路径均以此为根目录。

## 这个 Skill 做什么

读取知识库当前状态，生成一份领导 3 分钟能看懂的进度汇报页：

- 自动统计历史案例数量、最近录入内容、待办事项
- 从 CHANGELOG 提取本阶段关键进展
- 支持附加一句话背景说明（`--note`）
- 生成可编辑的 HTML，所有文字可点击修改，一键导出 PDF

## 调用方式

```
/leader-report
/leader-report --note "本周重点：XXX"
```

---

## 执行流程

### Step 1：读取知识库数据

依次读取以下文件，提取关键数据：

**`public/design-kb/knowledge/INDEX.md`**
- 历史案例总数（统计所有 `| ` 开头的数据行数）
- 按功能区统计案例分布（`##` 标题下的分组）

**`public/design-kb/knowledge/CHANGELOG.md`**
- 最近 3 条变更记录（最新的 3 个 `## 日期` 区块）
- 从每条中提取：日期、新增案例名称、新增关键词数量

**`public/design-kb/knowledge/TODO.md`**
- 待补充项总数
- 涉及的案例名称列表

**`public/design-kb/knowledge/progress-notes.md`**（可选，不存在则跳过）
- 读取最近一条备注，作为「本阶段亮点」

**`--note` 参数**（如有）
- 直接作为本次汇报的「本阶段背景」，覆盖 progress-notes.md

---

### Step 2：将技术数据翻译为管理层语言

翻译规则（严格执行，报告中不得出现以下技术词汇）：

| 技术说法 | 翻译为 |
|---|---|
| Skill / MCP / Git / GitHub | 不提，或说「工具」 |
| reasoning.md / CHANGELOG / INDEX | 不提具体文件名 |
| Claude Code / Cursor / Agent | 「AI 助手」 |
| knowledge base / INDEX | 「历史案例库」 |
| TODO / frontmatter | 「待完善内容」 |
| commit / push / deploy | 不提 |
| 录入 Case | 「整理历史案例」 |
| 知识库更新 | 「案例库更新」 |
| component-naming | 不提 |

核心叙事逻辑：
- **是什么**：我们在建一个「设计经验库」，把团队过去踩过的坑、做过的决策整理成结构化的知识
- **有什么用**：设计师接到新需求时，AI 助手能自动检索历史经验，给出有依据的建议，减少重复犯错
- **现在到哪了**：已经整理了 N 个历史案例，覆盖 X 个业务场景，系统已能正常运转
- **接下来做什么**：继续积累案例，目标达到足够数量后推广给全组

---

### Step 3：生成 HTML 汇报页

输出路径：`reports/leader-report-[YYYY-MM-DD].html`

如果 `reports/` 目录不存在，先用 Bash 创建：`mkdir -p reports`

将 Step 1 读取到的真实数据填入下方 HTML 模板中对应的占位符，然后将完整 HTML 写入文件。

**占位符说明：**
- `{{案例总数}}` → INDEX.md 中统计到的案例数量
- `{{本阶段新增}}` → CHANGELOG 最近一次记录中新增的案例数
- `{{待完善项数}}` → TODO.md 中的待补充项总数
- `{{汇报日期}}` → 今天的日期，格式 YYYY-MM-DD
- `{{最近进展1/2/3}}` → CHANGELOG 最近 3 条，翻译为管理层语言，每条不超过 2 句
- `{{本阶段亮点}}` → progress-notes.md 最近一条，或 --note 参数内容；无则填「系统运转正常，持续积累案例中」

**HTML 模板：**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>设计知识库系统 · 进度汇报</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",sans-serif;background:#F5F4F0;color:#1a1a1a}
.page{max-width:720px;margin:0 auto;padding:2.5rem 2rem 4rem}
.report-title{font-size:22px;font-weight:500;color:#1a1a1a;margin-bottom:4px}
.report-sub{font-size:14px;color:#888;margin-bottom:.75rem}
.section-label{font-size:11px;font-weight:500;letter-spacing:.08em;text-transform:uppercase;color:#aaa;margin-bottom:10px;margin-top:2rem}
.divider{border:none;border-top:.5px solid #e5e5e5;margin:2rem 0}
.edit-hint{font-size:11px;color:#bbb;margin-bottom:1.5rem;display:flex;align-items:center;gap:6px}
.edit-dot{width:6px;height:6px;border-radius:50%;background:#7F77DD;flex-shrink:0}
.arch{display:flex;flex-direction:column}
.arch-layer{display:flex;align-items:stretch}
.arch-badge{writing-mode:vertical-rl;font-size:11px;font-weight:500;color:#888;background:#eeecea;border:.5px solid #ddd;border-right:none;border-radius:6px 0 0 6px;padding:12px 6px;min-width:28px;display:flex;align-items:center;justify-content:center}
.arch-row{flex:1;display:flex;gap:6px;border:.5px solid #ddd;border-radius:0 6px 6px 0;padding:10px;background:#fff;margin-bottom:6px}
.arch-layer:last-child .arch-row{margin-bottom:0}
.arch-chip{flex:1;border-radius:6px;padding:8px 10px;font-size:12px;font-weight:500;min-width:0}
.chip-sub{font-size:11px;font-weight:400;margin-top:2px;opacity:.8;display:block}
.chip-gray{background:#F1EFE8;color:#444441;border:.5px solid #B4B2A9}
.chip-purple{background:#EEEDFE;color:#3C3489;border:.5px solid #AFA9EC}
.chip-teal{background:#E1F5EE;color:#085041;border:.5px solid #5DCAA5}
.chip-amber{background:#FAEEDA;color:#633806;border:.5px solid #EF9F27}
.chip-coral{background:#FAECE7;color:#712B13;border:.5px solid #F0997B}
.flow-arrow{text-align:center;color:#ccc;font-size:16px;margin:2px 0 2px 34px}
.stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.stat{background:#eeecea;border-radius:8px;padding:12px 14px;text-align:center}
.stat-num{font-size:24px;font-weight:500;color:#1a1a1a;line-height:1}
.stat-label{font-size:11px;color:#888;margin-top:4px}
.timeline{display:flex;flex-direction:column}
.trow{display:flex;align-items:stretch}
.tday{font-size:11px;font-weight:500;color:#888;min-width:52px;padding-top:13px;flex-shrink:0}
.ttrack{display:flex;flex-direction:column;align-items:center;flex-shrink:0}
.tdot{width:12px;height:12px;border-radius:50%;border:2px solid;margin-top:15px;flex-shrink:0}
.tline{width:2px;flex:1;min-height:8px}
.dot-done{border-color:#1D9E75;background:#E1F5EE}
.dot-partial{border-color:#BA7517;background:#FAEEDA}
.dot-new{border-color:#7F77DD;background:#EEEDFE}
.dot-todo{border-color:#aaa;background:#eeecea}
.line-done{background:#9FE1CB}
.line-partial{background:#FAC775}
.line-new{background:#CECBF6}
.line-todo{background:#ddd}
.tcard{flex:1;margin:8px 0 8px 12px;background:#fff;border:.5px solid #e5e5e5;border-radius:10px;padding:10px 12px}
.tcard-title{font-size:13px;font-weight:500;color:#1a1a1a;margin-bottom:4px}
.tcard-body{font-size:12px;color:#888;line-height:1.5}
.mtag{display:inline-block;font-size:10px;font-weight:500;padding:1px 7px;border-radius:8px;margin-left:6px;vertical-align:middle}
.tag-done{background:#E1F5EE;color:#085041}
.tag-partial{background:#FAEEDA;color:#633806}
.tag-new{background:#EEEDFE;color:#3C3489}
.tag-todo{background:#eeecea;color:#666}
.insight{background:#eeecea;border-left:3px solid #7F77DD;border-radius:0 6px 6px 0;padding:10px 14px;font-size:13px;color:#666;line-height:1.6;margin-top:1rem}
.skill-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.skill-card{background:#fff;border:.5px solid #e5e5e5;border-radius:10px;padding:10px 12px}
.skill-name{font-size:13px;font-weight:500;color:#1a1a1a;margin-bottom:4px}
.skill-desc{font-size:11px;color:#888;line-height:1.4}
.roadmap{display:flex;flex-direction:column;gap:6px}
.roadmap-row{display:flex;align-items:stretch}
.roadmap-badge{font-size:11px;font-weight:500;color:#888;background:#eeecea;border:.5px solid #ddd;border-right:none;border-radius:6px 0 0 6px;padding:10px;min-width:60px;display:flex;align-items:center;justify-content:center;text-align:center;line-height:1.3}
.roadmap-chips{flex:1;display:flex;gap:6px;border:.5px solid #ddd;border-radius:0 6px 6px 0;padding:8px 10px;background:#fff}
.roadmap-chip{flex:1;border-radius:6px;padding:8px 10px;font-size:12px;font-weight:500}
.roadmap-chip .chip-sub{font-size:11px;font-weight:400;margin-top:2px;opacity:.8;display:block}
[contenteditable]{outline:none;cursor:text}
[contenteditable]:hover{background:rgba(127,119,221,.07);border-radius:3px}
[contenteditable]:focus{background:rgba(127,119,221,.12);border-radius:3px}
.export-btn{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:500;padding:7px 16px;border:.5px solid #ddd;border-radius:6px;background:#fff;cursor:pointer;color:#444;margin-top:2rem}
.export-btn:hover{background:#f5f5f5}
@media print{body{background:#fff}.edit-hint,.export-btn{display:none!important}.page{padding:1rem}}
</style>
</head>
<body>
<div class="page">

<div class="edit-hint"><span class="edit-dot"></span>所有文字均可点击编辑，修改后即时生效</div>

<p class="report-title" contenteditable>设计知识库系统 · 进度汇报</p>
<p class="report-sub" contenteditable>目标：让 AI 在设计师提交新需求时，快速给出有据可查的设计建议</p>
<p class="report-sub" contenteditable style="color:#aaa;font-size:12px">汇报日期：{{汇报日期}}</p>

<p class="section-label">当前进展</p>
<div class="stat-grid">
  <div class="stat"><div class="stat-num" contenteditable>{{案例总数}}</div><div class="stat-label" contenteditable>已整理历史案例</div></div>
  <div class="stat"><div class="stat-num" contenteditable>{{本阶段新增}}</div><div class="stat-label" contenteditable>本阶段新增</div></div>
  <div class="stat"><div class="stat-num" contenteditable>{{待完善项数}}</div><div class="stat-label" contenteditable>待完善内容</div></div>
  <div class="stat"><div class="stat-num" contenteditable>正常</div><div class="stat-label" contenteditable>系统运转状态</div></div>
</div>

<hr class="divider">

<p class="section-label">系统架构 — 五层模型</p>
<div class="arch">
  <div class="arch-layer">
    <div class="arch-badge" contenteditable>输入层</div>
    <div class="arch-row">
      <div class="arch-chip chip-gray"><span contenteditable>设计稿</span><span class="chip-sub" contenteditable>在线设计工具 / 截图</span></div>
      <div class="arch-chip chip-gray"><span contenteditable>产品需求文档</span><span class="chip-sub" contenteditable>PRD / BRD</span></div>
      <div class="arch-chip chip-gray"><span contenteditable>线上链接</span><span class="chip-sub" contenteditable>设计系统 / 文档站</span></div>
    </div>
  </div>
  <div class="flow-arrow">↓</div>
  <div class="arch-layer">
    <div class="arch-badge" contenteditable>知识层</div>
    <div class="arch-row">
      <div class="arch-chip chip-purple"><span contenteditable>历史案例文档</span><span class="chip-sub" contenteditable>每个案例的设计决策 + 背景 + 教训</span></div>
      <div class="arch-chip chip-purple"><span contenteditable>组件命名表</span><span class="chip-sub" contenteditable>统一各角色对同一组件的不同叫法</span></div>
    </div>
  </div>
  <div class="flow-arrow">↓</div>
  <div class="arch-layer">
    <div class="arch-badge" contenteditable>索引层</div>
    <div class="arch-row">
      <div class="arch-chip chip-teal"><span contenteditable>案例库目录</span><span class="chip-sub" contenteditable>按功能区 / 组件 / 关键词分类的索引</span></div>
      <div class="arch-chip chip-teal"><span contenteditable>相关性标签</span><span class="chip-sub" contenteditable>每个案例打标，方便快速检索</span></div>
    </div>
  </div>
  <div class="flow-arrow">↓</div>
  <div class="arch-layer">
    <div class="arch-badge" contenteditable>回答层</div>
    <div class="arch-row">
      <div class="arch-chip chip-amber"><span contenteditable>AI 回答模板</span><span class="chip-sub" contenteditable>六章结构，控制输出稳定性</span></div>
      <div class="arch-chip chip-amber"><span contenteditable>检索指令</span><span class="chip-sub" contenteditable>告诉 AI 如何检索、引用、格式化</span></div>
    </div>
  </div>
  <div class="flow-arrow">↓</div>
  <div class="arch-layer">
    <div class="arch-badge" contenteditable>迭代层</div>
    <div class="arch-row">
      <div class="arch-chip chip-coral"><span contenteditable>回答质量评估</span><span class="chip-sub" contenteditable>记录多余 / 缺失的信息</span></div>
      <div class="arch-chip chip-coral"><span contenteditable>案例库更新机制</span><span class="chip-sub" contenteditable>新案例完成后自动反哺文档</span></div>
      <div class="arch-chip chip-coral"><span contenteditable>版本管理</span><span class="chip-sub" contenteditable>所有变更可追溯、可回退</span></div>
    </div>
  </div>
</div>

<hr class="divider">

<p class="section-label">本阶段做了什么</p>
<div class="timeline">
  <div class="trow">
    <div class="tday" contenteditable>进展1</div>
    <div class="ttrack"><div class="tdot dot-done"></div><div class="tline line-done"></div></div>
    <div class="tcard">
      <div class="tcard-title" contenteditable>{{最近进展1标题}} <span class="mtag tag-done">已完成</span></div>
      <div class="tcard-body" contenteditable>{{最近进展1描述}}</div>
    </div>
  </div>
  <div class="trow">
    <div class="tday" contenteditable>进展2</div>
    <div class="ttrack"><div class="tdot dot-done"></div><div class="tline line-done"></div></div>
    <div class="tcard">
      <div class="tcard-title" contenteditable>{{最近进展2标题}} <span class="mtag tag-done">已完成</span></div>
      <div class="tcard-body" contenteditable>{{最近进展2描述}}</div>
    </div>
  </div>
  <div class="trow">
    <div class="tday" contenteditable>进展3</div>
    <div class="ttrack"><div class="tdot dot-done"></div></div>
    <div class="tcard">
      <div class="tcard-title" contenteditable>{{最近进展3标题}} <span class="mtag tag-done">已完成</span></div>
      <div class="tcard-body" contenteditable>{{最近进展3描述}}</div>
    </div>
  </div>
</div>

<hr class="divider">

<p class="section-label">超出预期的部分</p>
<div class="insight" contenteditable>{{本阶段亮点}}</div>

<hr class="divider">

<p class="section-label">下一步计划</p>
<div class="timeline">
  <div class="trow">
    <div class="tday" contenteditable>本周</div>
    <div class="ttrack"><div class="tdot dot-partial"></div><div class="tline line-partial"></div></div>
    <div class="tcard">
      <div class="tcard-title" contenteditable>继续整理历史案例 <span class="mtag tag-partial">进行中</span></div>
      <div class="tcard-body" contenteditable>目标积累 5–10 个案例，覆盖促销、价格、腰带、弹窗等主要场景，让 AI 有足够的历史依据可以引用</div>
    </div>
  </div>
  <div class="trow">
    <div class="tday" contenteditable>本周</div>
    <div class="ttrack"><div class="tdot dot-todo"></div><div class="tline line-todo"></div></div>
    <div class="tcard">
      <div class="tcard-title" contenteditable>用真实新需求验证效果 <span class="mtag tag-todo">待做</span></div>
      <div class="tcard-body" contenteditable>提交一个当前正在做的新设计需求，测试 AI 能否准确找到相关历史案例并给出有依据的建议</div>
    </div>
  </div>
  <div class="trow">
    <div class="tday" contenteditable>下周</div>
    <div class="ttrack"><div class="tdot dot-todo"></div></div>
    <div class="tcard">
      <div class="tcard-title" contenteditable>推广给全组使用 <span class="mtag tag-todo">待做</span></div>
      <div class="tcard-body" contenteditable>整理使用说明，团队成员可直接使用案例库查询历史决策，无需技术背景</div>
    </div>
  </div>
</div>

<hr class="divider">

<p class="section-label">进阶路线</p>
<div class="roadmap">
  <div class="roadmap-row">
    <div class="roadmap-badge" contenteditable>第二阶段</div>
    <div class="roadmap-chips">
      <div class="roadmap-chip chip-teal"><span contenteditable>案例库扩充</span><span class="chip-sub" contenteditable>每个新需求完成后补充，目标 10+ 个</span></div>
      <div class="roadmap-chip chip-teal"><span contenteditable>质量评估</span><span class="chip-sub" contenteditable>记录每次建议的缺失，驱动优化</span></div>
    </div>
  </div>
  <div class="flow-arrow" style="margin-left:70px">↓</div>
  <div class="roadmap-row">
    <div class="roadmap-badge" contenteditable>第三阶段</div>
    <div class="roadmap-chips">
      <div class="roadmap-chip chip-purple"><span contenteditable>语义检索</span><span class="chip-sub" contenteditable>案例多了之后，支持更智能的搜索</span></div>
      <div class="roadmap-chip chip-purple"><span contenteditable>跨团队协作</span><span class="chip-sub" contenteditable>设计 / 研发 / 产品共用同一知识库</span></div>
    </div>
  </div>
</div>

<button class="export-btn" onclick="window.print()">导出 PDF</button>

</div>
</body>
</html>
```

---

### Step 4：在浏览器中打开

```bash
open reports/leader-report-[YYYY-MM-DD].html
```

输出提示：
```
✅ 汇报页已生成并打开

文件：reports/leader-report-[日期].html
数据：自动读取（案例数 {{案例总数}} / 本阶段新增 {{本阶段新增}} / 待完善 {{待完善项数}} 项）
操作：所有文字可在浏览器中直接点击修改，右下角可导出 PDF
```

---

## progress-notes.md 格式建议

在 `public/design-kb/knowledge/progress-notes.md` 记录阶段亮点，每次运行自动读取最新一条：

```markdown
# 进度备注

## 2026-05-22
- 系统首次完整跑通「设计稿读取→案例整理→AI 检索」全链路
- 所有维护文件均由 AI 自动更新，设计师零手动操作

## 上一阶段
- ...
```

---

## 关键约束

1. **严禁出现技术术语。** 报告中不出现任何代码、文件名、技术工具名称。
2. **数据必须来自知识库。** 案例数量、进展条数必须从文件中读取，不能编造。
3. **数字宁少勿多。** 核心统计卡片只展示 4 个数字。
4. **每条进展不超过 2 句话。** 领导看的是结论，不是过程。
5. **reports/ 目录加入 .gitignore。** 生成的汇报文件不需要纳入版本管理。

---

## 版本历史

- **v1.0** (2026-05-21) 初版
- **v1.1** (2026-05-22) 更新 HTML 模板样式，与设计知识库系统进度汇报视觉风格统一
