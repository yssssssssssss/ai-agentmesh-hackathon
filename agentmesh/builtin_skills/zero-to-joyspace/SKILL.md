---
name: zero-to-joyspace
harness-version: 0
description: 把 Zero(原 Relay)设计稿一键转写到 JoySpace 文档。设计稿白底正文按结构转为 Markdown 文字(标题/段落/列表),灰底示例区(如规范展示面板、SKU 卡片样例)精确导出为图片穿插嵌入。一二级标题用
  `#`/`##` 真标题块(进左侧导航)并叠加 20/16 号字号。既能新建文档(upload),也能把内容更新进已有文档(edit)。当用户给出 relay.jd.com 链接、要求"把设计稿转到 JoySpace / 转成文档 / 沉淀到
  JoySpace / 更新到某 JoySpace 文档"时使用。
allowed-tools:
- mcp__zero-design__get_design_metadata
- mcp__zero-design__get_design_context
- mcp__zero-design__get_screenshot
- mcp__zero-design__export_image
- Bash(webcli *)
- Bash(curl *)
- Bash(python3 *)
- Read
- Write
- TodoWrite
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/.agents/skills/zero-to-joyspace/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 把 Zero(原 Relay)设计稿一键转写到 JoySpace 文档。设计稿白底正文按结构转为 Markdown 文字(标题/段落/列表),灰底示例区(如规范展示面板、SKU 卡片样例)精确导出为…
disable-model-invocation: true
---

# zero-to-joyspace

把京东内部 **Zero(原 Relay)设计稿** 一键转写到 **JoySpace 文档**,保留 1:1 内容结构。

## 它能干什么

- 设计稿里的 **白底正文**(规范说明、定义、应用场景等纯文字段落)→ 转为 markdown **标题/段落/列表/加粗**
- 设计稿里的 **灰底示例区**(产品规范常见的 #f2f4f7 / #ededed 灰底面板,内含 SKU 卡片、手机模拟器、视觉示例等)→ 精确导出为 PNG **嵌入文档**(走 JD CDN,JoySpace 原生渲染)
- 最终产物:**JoySpace 文档**,默认落到当前登录用户的"我的文档/草稿箱"

## 何时调用

- 用户给出形如 `https://relay.jd.com/file/design?id=...&page_id=...&node_id=...` 的链接,并要求转到 JoySpace
- 用户希望把设计规范、设计系统说明、UI 组件文档等沉淀为可分享的 JoySpace 文档
- 用户希望部门同事不用打开 Zero 也能阅读设计稿内容

> **不适用**:跨企业/外部 Zero 文件、需要保留交互动画、需要工程级 design token 同步(那是 design-to-code 流程,直接用 `get_design_context` 转代码即可,无需走 JoySpace)。

## 前置依赖(用户首次使用前需完成)

```bash
# 1. zero-design MCP 已注册到 Claude Code(检查 ~/.claude.json 里有没有 mcpServers.zero-design)
#    若没有,需在京东 Zero 桌面端开启 MCP 后,本地 http://127.0.0.1:27618/mcp 自动可用
#    然后重启 Claude Code 会话以加载工具列表

# 2. o2 CLI 已装(参考 https://o2.jd.com/install.md;非管理员 Mac 用 uv venv 兜底安装)
o2 --version

# 3. webcli 已装,且 Browser Bridge Chrome 扩展已加载
o2 install webcli
webcli extension install
# Chrome 里手动加载 ~/.webcli/extension 一次,之后永久生效
webcli --json doctor   # extensionConnected 应为 true

# 4. 浏览器里已登录 JoySpace(`joyspace.jd.com`),登录态由 webcli 借用
```

## 执行步骤(按顺序)

### Step 1 · 解析链接 & 起手骨架

从用户给的 URL 中提取 `fileKey` 和 `nodeId`:
- `https://relay.jd.com/file/design?id=:fileKey&page_id=:pageId&node_id=:nodeId`
- nodeId 形如 `3411:1`;若是 `3411-1` 这种 `-` 形式,替换为 `:`

用 `TodoWrite` 建立工作清单(5 步):
1. 解析画板节点结构
2. 提取所有正文(从 design_context)
3. 导出灰底示例面板为图片
4. 组装 markdown
5. 上传到 JoySpace

### Step 2 · 摸清画板结构

调用 `get_design_metadata` 取目标 nodeId 的结构(返回 XML-like 节点树),理解层级。
**输出可能很大(>100KB),会被持久化为文件**;用 Python 脚本按缩进解析层级,只输出顶层章节即可:

```python
# 找出 root 下的直接子帧(章节)
import json, re
with open(METADATA_FILE) as f:
    data = json.load(f)
xml = data[0]["text"]
# 按缩进数 // 2 = depth,depth==2 通常是章节
for line in xml.split("\n"):
    m = re.match(r'^(\s*)<(frame|instance) id="([^"]+)" name="([^"]*)"[^>]*?y="([^"]*)"[^>]*?height="([^"]*)"', line)
    if m and len(m.group(1)) == 4:
        print(m.group(3), m.group(4), float(m.group(5)), float(m.group(6)))
```

同时调一次 `get_screenshot(nodeId, maxDimension=1600)` 拿张全图,**对照视觉确认章节边界**(metadata 里看不到颜色,要靠截图判断哪些区域是灰底)。

### Step 3 · 提取每个章节的真实正文

⚠️ **关键陷阱**:metadata 里的 `name` 属性 **可能是旧模板**(比如设计师从其他规范模板复制过来)。看到 `name="JD APP 15.0 GUIDELINE"` 不一定准 —— 实际渲染可能是 16.0。

**必须** 用 `get_design_context(nodeId=章节nodeId)` 取真实 React 代码,从 `<p>...</p>` / `<div>...</div>` 里抓文字。

提取要点:
- 多行文本可能用嵌套 `<p>` 表示段落分隔(`定义：...` 一段,`应用场景：...` 另一段)
- 用 grep 搜关键词(如 "应用场景"、"定义")配合上下文 250 字截取最稳
- 输出 >100KB 会持久化为文件,用 Python `re.finditer` 处理
- ⚠️ **有些序号/文字是 `{"b. "}` 这种 JSX 字符串字面量**(不在 `>...<` 之间)。**提取时必须一并抓 `{"..."}`**,否则会漏字、误判"这条没有序号"(实测真踩过:`b.` 是 `{"b. "}` 没抓到,导致误删序号、连锁改错正文)。

```python
# 抓正文段落 —— 同时覆盖 >文本< 和 {"JSX字面量"}
import re
for kw in ["定义", "应用场景", "适用品类"]:
    for m in re.finditer(kw, react_code):
        ctx = react_code[max(0,m.start()-20):m.end()+250].replace("\n"," ")
        print(f"[{kw}] {ctx}")
# 逐字提取某段时,把两类节点都收进来(保留原始顺序与空格):
# re.finditer(r'>([^<>{}]*[一-鿿][^<>{}]*)<|\{"([^"]*)"\}', react_code)
```

### Step 4 · 锁定灰底面板的 nodeId

> ⚠️⚠️⚠️ **本步骤是 skill 最容易出错的地方**,务必严格执行。

#### 4.1 灰底面板的特征
- React 里有这类**灰色背景**的 div:
  - **显式 hex**:`bg-[#f7f8fc]` / `bg-[#f5f5f7]` / `bg-[#f2f4f7]` / `bg-[#f2f3f5]`
  - **CSS 变量**(实测很多新板子用这种,别只搜 hex):`bg-[var(--color-background-color-background,#f2f3f7)]` / `bg-[var(--background-color-background-component,#f0f2f7)]` / `bg-[var(--backgroundgray-2,#f5f6fa)]` / `bg-[var(--gray-3,...)]`
- 容器 frame 名常为 `.`(占位)或 `Frame 19xxx`,宽度 ≈ 1426(主区宽)
- 通常每个子小节对应 **一个** 灰底面板
- ⚠️ 注意排除**干扰色**:`bg-[rgba(255,15,35,0.1)]`(红底标签)、`bg-[var(--color-primary...,#ff0f23)]`(主色)、`...background-overlay,#ffffff)`(白底卡片)都不是灰底示例面板

#### 4.2 禁止:不要直接 export 子小节容器

设计稿的典型嵌套结构是这样的:

```
[子小节容器 1829:303]              ← 整个 c.独立热区 区块
├─ <text> "c. 独立热区"             (白底正文,标题)
├─ <text> "由独立控件较短边..."      (白底正文,定义 + 应用场景)
├─ [灰底面板 1829:308]              ← ✅ 这个才是要 export 的
│   └─ 视觉示例(开关示意图)
└─ <text> "示意:54*32 开关..."     (白底脚注,继续是 markdown 文字)
```

**直接 export `1829:303` 会把白底正文+灰底+白底脚注全部截进去**,违反"白底归文字、灰底归图片"的硬规则。

#### 4.3 正确做法:drill down 到内层灰底节点

```python
# 1. 在子小节容器的 React 里 grep 灰色 hex 模式
import re
gray_re = re.compile(r'bg-\[#(?:[fF][7-9aA-fF][fF][8aA-fF][fcF]\w|[fF]2[fF]4[fF]7|[eE][dD][eE][dD][eE][dD])\][^>]*data-node-id="([^"]+)"|data-node-id="([^"]+)"[^>]*bg-\[#(?:[fF][7-9aA-fF][fF][8aA-fF][fcF]\w|[fF]2[fF]4[fF]7|[eE][dD][eE][dD][eE][dD])\]')
matches = [m.group(1) or m.group(2) for m in gray_re.finditer(subsection_react)]

# 2. 灰底节点是这堆里**最外层、宽度最大、name 不在子标题/脚注名单**的那个
#    — 通常 width ≈ 1426 / height 400-700 的就是
```

#### 4.4 必做:导出后**肉眼验证**
```bash
curl -s -o /tmp/check.png "<exported-url>"
# 用 Read 工具打开看,确认:
# - 上下边缘是连续的灰色,**不是白底文字**
# - 不包含「示意:xxx」「注:xxx」「定义:xxx」这种白底脚注
# 不对就继续往里挖一层
```

#### 4.5 容易漏掉的白底脚注 / 边注

子小节里**灰底外的所有文字都要进 markdown**,常见模式:
- 灰底**前**:子小节标题(`a.边缘热区`)、定义、应用场景、适用品类
- 灰底**后**:`示意:xxx`、`注:xxx`、`手机/折叠屏/平板 各 X dp`、参数标注
- 灰底**右上角红色提示注释**:`注:实际设计中...`(作为普通段落单独成段,**不要用引用块**)

把这些用 markdown 单独成段,**不要漏**。

> 💡 **遇到白底标题与示意图混在同一块灰底、无法干净拆分的章节**(实测案例:"位置关系布局"把 `a.内容模块外部`/`b.内容模块内部`/`c.…` 标题和示意铺在一块大灰底上,export 整块会把白底标题截进图):**问用户怎么处理**,不要自作主张。常见取舍是「a/b/c 规则文字转 markdown 正文 + 整块灰底图放文字下方」。
>
> ⚠️ **不要用 markdown 引用块 `>` 包正文**(早期模板写过,已废弃)。所有正文一律普通段落 / 加粗段,引用块会被 JoySpace 渲染成特殊样式。

### Step 5 · 导出灰底面板为图片

对每个灰底 nodeId 调用 `export_image(nodeId, format="png")`,**用 png 不要 jpg**(规范图通常有透明背景或线条,jpg 会糊)。

返回的 `image_url` 是 JD CDN 链接(`img10-30.360buyimg.com`)。

> ⚠️⚠️⚠️ **关键(实测踩坑):md 里图片必须用「本地路径」,不能直接用 CDN 链接!**
> 原因:`webcli upload` 对图片有两条不同路径(见 `clis/joyspace/upload.js`):
> - 图片是 **http(s)/data 链接** → upload.js **跳过处理**,只靠把整篇 HTML **粘贴**进 Slate 编辑器带图。而 Slate **批量粘贴多张图极不稳定**——实测 7 张图重传 7 次得到 0/3/5/6/6/5/0 张,从没满过,纯靠重传撞不齐。
> - 图片是 **本地相对路径** → upload.js 会**逐张调 JoySpace `uploadImage` API 服务端上传**、替换成 JoySpace 图床 URL,再粘贴。**稳定可靠,一次到位。**
>
> 所以正确做法:
> 1. 把 `export_image` 得到的每个 CDN 图**下载到本地**(放在 md 同目录的子文件夹,如 `imgs/`):
>    ```bash
>    # CDN 有防盗链,curl 必须带浏览器 UA,否则 403
>    curl -s -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" -o imgs/img1.png "<cdn_url>"
>    ```
> 2. md 里图片引用写**相对本地路径**:`![描述](imgs/img1.png)`,**不要**写 `![描述](https://img*.360buyimg.com/...)`。
> 3. 上传时 md 和 `imgs/` 在同一目录(都放 `/tmp` 下即可),upload.js 会按相对路径找到图、服务端上传。

可以并行调用 `export_image`,7 张图秒级出来;下载到本地也可并行 curl。

### Step 6 · 装配 markdown

> ⚠️⚠️ **排版规范(硬要求,作用于生成的 JoySpace 文档)**:
>
> **先理解写入机制(决定了下面为什么这么写)**:不管走 `upload`(新建)还是 `edit --mode write`(写入已有文档),底层都先用 `marked`(gfm,breaks:false)把 md 转 **HTML**,再粘贴/插入进 JoySpace 的 Slate 编辑器。三个后果务必记牢:
> 1. **左侧导航(大纲目录)只认"真标题块"**。普通段落即使设成 20 号大字,也**不会**进左侧导航。要进导航,一二级标题**必须用 markdown `#` / `##`**(marked 转 `<h1>`/`<h2>` 标题块)。⚠️**这是本版与旧版最大的区别**——旧版为控字号弃用 `#`、改用"段落大字",代价是没导航;实测发现标题块能再叠字号,于是改回 `#`/`##`。
> 2. **标题块能再叠加自定义字号**。`#`/`##` 写出标题块后,JoySpace"是不是标题"和"字多大"是两个独立属性——可在写入后用 `edit --style "size:20"` 给标题块叠 20 号、`size:16` 叠 16 号,**既进导航又满足字号要求**(实测两全)。
> 3. **空行用空段落,绝不写 `&nbsp;` 字面**。⚠️ 关键坑:`edit --mode write` 的 markdown 解析器**不认 `&nbsp;` 这个 HTML 实体**,会把 "&nbsp;" 当**字面文字**插进去(满屏 `&nbsp;` 很难看)。所以**空行一律用真正的空行**(md 里多空一行,marked 保留段落间距),**任何路径都不要写 `&nbsp;` 字面**。
>
> 具体规则:
> - **🆕 一二级标题用 `#` / `##` 真标题块(进左侧导航),写入后叠字号**:
>   - **一级标题**:写 `# 1. 标题`(marked → `<h1>` 标题块,进导航),写入后用 `edit --find "1. 标题" --style "size:20"` 叠 **20 号加粗**。
>   - **二级标题**:写 `## 1.1 子标题`(→ `<h2>` 标题块,进导航),写入后 `--style "size:16"` 叠 **16 号加粗**。
>   - **三级及更深 / 字段锚点**:如"默认/反白""定义/应用场景/适用品类""a./b. 参数",**不用 `#`,保持普通加粗段** `**默认**`(不进导航、不编号,避免大纲过深)。
>   - ❌ **不要写开头的 `- `**:旧版用 `- <span>` 会渲染成无序列表圆点 `•`,已废弃。一律用 `#`/`##`。
> - **🆕 标题层级识别与编号**:**自动识别**设计稿的一级/二级标题层级并**加点分编号**(一级 `1. 2. 3.`,二级 `1.1 1.2` / `2.1 2.2`,在所属一级下从 `.1` 递增)。编号是写在 `#`/`##` 后面的**手写文字**(`# 1. 组件定义`),不是 markdown 有序列表。
>   - **一级标题** = 设计稿顶层章节(对应 metadata 里 depth==2 的 frame、常带 `01`/`02` 章节角标或 `Component-title`,如"组件定义""锚点指示器""典型场景")。
>   - **二级标题** = 一级章节内部的第一层子标题(如锚点指示器下的"常规型/等分型"、滑动指示器下的分型名)。
>   - 识别依据:design_context 的视觉层级(字号大小、加粗程度)+ metadata 结构嵌套深度;**拿不准是一级还是二级时,保守归并或问用户**,绝不为了凑编号而臆断层级。
> - **模块间距(拉开章节)**:一级标题**上方留两个空行**、二级标题**上方留一个空行**。**绝不写 `&nbsp;` 字面**(见上方机制 3)。
> - **正文文字**:普通段落(JoySpace 默认 16 号,无需额外设字号)。
> - **序号(⚠️ 重要规则,区分两类)**:
>   - **① 标题层级编号 = 自动生成**(本次新增):一级/二级**标题**按上面规则自动加 `1.` / `1.1` 点分编号,这是对标题的层级标注,不算改动正文内容。
>   - **② 正文内容里的序号字段 = 原样照搬,不自动增删改**:设计稿**正文**里已有的序号(如 `a. b. c.`、字段自带的 `1. 2.`)原样保留,写的是 `a. b. c.` 就转 `a. b. c.`,没有序号的字段(如"材质参数:""阴影参数:")**不要硬加**序号。
>   - 两者对象不同、互不冲突:**标题**自动编号,**正文**序号照搬。
>   - ⚠️ **正文序号千万别用 markdown 有序列表语法**(行首 `1.` `2.`):JoySpace 粘贴时会把全文所有有序列表**连续编号**(第一段 1/2/3,下一段不重新从 1 而接 4/5……,`<ol start>` 也压不住)。
>   - 所以即使源文是阿拉伯数字序号,也要写成**不会被 marked 解析成 `<ol>` 的形式**:行首用 `a.`(源文本来就是字母序号时)或全角 `1）`(源文是数字且必须保留时),让它停留在普通段落里。标题的 `1./1.1` 编号因为跟在 `#`/`##` 后(不是行首裸 `1. `),不会被解析成 `<ol>`,安全。
> - **❌ 正文必须逐字照搬源文,不增、不删、不改、不加空格**。这是硬底线:
>   - **不要杜撰**任何说明性文字。某章节(如"应用场景")源文若只有示意图、没有正文,就**只放标题+图**,不要自己写一句"XX 在 XX 场景下的应用示意"。
>   - **不要合并/拆分/改写**源文的句子和字段。源文是两个文本节点就分两行,源文用 `：` 连接就用 `：`,源文有 `a. b.` 序号就保留(注意 `b.` 可能是 `{"b. "}` 这种 JSX 字面量,**提取时要一并抓 `{"..."}`,否则会误判"没有序号"**)。
>   - **空格一字不动**。源文 `右侧边距8DP`(无空格)、`距底导 60DP`(有空格)即使不规则也照搬,**不要自作主张加/删空格做"美化"**。
>   - **唯一允许的字符替换**:尺寸里的 `*`→全角 `×`(因为 `*` 是 markdown 斜体标记,`40*40DP` 同段两个 `*` 配对会把中间文字变 `<em>` 斜体;`×` 既消除误斜体又是设计规范标准写法)。其它会触发 markdown 的裸字符(行首 `#`、`>`、`-` 等)若出现在正文也要转义。
>   - **完成后务必逐行比对**:把每行正文(去掉 `#`/`##`、去掉 `**`、去掉标题前的 `N.`/`N.N` 编号、还原 `×`→`*`)在 `design_context` 文本里做子串匹配,确认逐字(含空格)命中,再交付。
>   - **澄清「逐字照搬」管什么**:它约束的是**正文文字内容本身**——字、标点、空格不能动。但以下**排版包装**不算改正文、可以照规范施加:① 给标题用 `#`/`##` 块 + 写入后叠字号(20/16 号);② 给字段名套 `**加粗**`;③ "定义/应用场景/适用品类"前缀加粗做锚点;④ 尺寸 `*`→`×`;⑤ **给一级/二级标题加 `1.`/`1.1` 点分编号**(标题层级标注,非正文内容)。判断准则:**还原掉这些包装后(去 `#`/`##`、去 `**`、去标题编号、还原 `×→*`),逐字比对必须命中源文**。
> - **表格**:表头 正文 16 号 / 加粗 / 浅灰底;内容 正文 16 号。
> - **❌ 不读取设计稿头部的"表头/文档头信息"**(名称、部门署名、`JD APP XX.X GUIDELINE` 版本号这类页眉字段)。**正文一个字都不要写表头**;设计稿名称只用作 JoySpace **页面标题**(见 Step 7 的 `--title`),不进正文。
> - **❌ 不要自己加分割线 `---`**。设计稿里本来没有分割线,章节之间**只用空行**分隔,**任何位置都不要输出 `---`**。
> - **底部超链接**:全文最后空一行,再另起一行写 `以上规范内容可跳转 [Zero链接](本次输入的 relay.jd.com URL) 查看`,把「Zero链接」字段做成超链接,地址就是用户这次调用 skill 时输入的那条 Zero 链接。

模板结构(可按实际章节增删):**注意正文不含设计稿名称/表头**,名称只进 Step 7 的 `--title`。

```markdown
# 1. {章节1标题}

{章节1正文}


# 2. {章节2标题}

## 2.1 {子节标题}

**{子小节1标题}**

**定义**:...

**应用场景**:...

**适用品类**:...

![{描述}](imgs/imgN.png)

## 2.2 {子小节2标题}
...

a. {正文里源文已有的序号,原样转写;源文是 `a.` 就 `a.`,没有序号就不要加}
b. ...

以上规范内容可跳转 [Zero链接](https://relay.jd.com/file/design?id={fileKey}&page_id={pageId}&node_id={nodeId}) 查看
```

> 注意上面模板:**第一行就是正文第一个章节**(没有设计稿名称/署名/版本号行),**没有任何 `---`**,**没有任何 `&nbsp;` 字面**。一级标题用 `# `、二级用 `## `(写入后再叠 20/16 号字号);一级标题上方留两个空行、二级上方留一个空行拉间距(全文第一个一级标题上方无需空行)。

排版要点:
- **🆕 一二级标题用 `#`/`##` 真标题块** —— 这样才能进 JoySpace **左侧导航(大纲目录)**;普通段落大字不进导航。一级 `# `、二级 `## `,写入后再用 `edit --style "size:20"`/`size:16` 叠字号(标题块与字号是两个独立属性,可叠加)
- **🆕 自动识别标题层级并编号**:一级标题 `# 1. XXX`、二级 `## 1.1 XXX`(在所属一级下递增);更深层级(默认/反白、定义/应用场景、a./b. 参数)用普通加粗段、不编号、不用 `#`。拿不准层级时保守归并或问用户,不臆断
- **❌ 标题不写 `- ` 前缀、不用 `<span>`**:旧版 `- <span>` 写法会渲染成圆点 `•`,已废弃,一律用 `#`/`##`
- **❌ 绝不写 `&nbsp;` 字面**:`edit --mode write` 不认 `&nbsp;` 实体,会原样显示成文字。空行/模块间距一律用**真正的空行**(一级上方两个空行、二级上方一个空行)
- **正文序号:原样保留源文,不自动增删改**(与标题编号是两回事——标题自动编号,正文序号照搬)。源文有 `a. b. c.` 就照写,没序号的字段别硬加。**正文禁止用 markdown 有序列表 `1.`**(JoySpace 会全文连续编号);源文是数字序号且必须保留时,用 `a.` 或全角 `1）` 等不会被解析成 `<ol>` 的写法
- "定义/应用场景/适用品类" 用 `**...**:` 加粗前缀做视觉锚点
- 表格表头加粗 + 浅灰底,表头与内容均 16 号
- **正文不读设计稿名称/表头**(名称只进 `--title`,署名/`JD APP XX.X GUIDELINE` 一律丢弃)
- **绝不输出分割线 `---`**,章节之间只用空行
- 图片紧跟在该子小节正文之后
- **全文最后一行**永远是 Zero 源链接跳转(上方空一行),链接地址 = 本次输入的 Zero URL
- 验证:写入后用 `webcli joyspace export <doc-id> --output <文件>` 导出复查,确认①一级标题导出为 `# `、二级为 `## `(= 真标题块,进导航);②点分编号正确(`1.`/`1.1` 层级连贯);③**无 `&nbsp;` 字面残留**(`grep -c nbsp`=0);④正文逐行比对源文逐字命中

### Step 7 · 写入 JoySpace(两种场景)

先判断用户要**新建文档**还是**更新进某个已有文档**:
- "转到草稿箱 / 生成到 XX 文件夹 / 转成文档" → **场景 A:新建**(`upload`)
- 给了 **JoySpace 文档链接**(`joyspace.jd.com/pages/XXXX`)说"更新到这个文档" → **场景 B:写入已有**(`edit`)

> ⚠️ 图片对两种场景都必须用**本地路径**(`upload` 相对、`edit` 绝对),两者都会逐张服务端上传 `uploadImage`,稳定带图;绝不用 CDN http 链接(Slate 批量粘贴丢图)。

#### 场景 A · 新建文档(upload)

```bash
# 文件路径含中文 → 偶发 paste verification failed:先 cp 到 /tmp/{ascii-name}.md
cp "/path/with/中文.md" /tmp/zero-export.md
# --title 必填 = JoySpace 页面标题(设计稿真实名)
webcli joyspace upload /tmp/zero-export.md --title "{设计稿名称}" -f json
```

成功返回:`{"status":"✅ 上传完成","title":"...","url":"https://joyspace.jd.com/pages/XXXX"}`
新建后归档文件夹:`webcli joyspace move <doc-id> --to <folder-id>`。标题块要叠 20/16 号字号见场景 B 第 3 步。

#### 场景 B · 写入已有文档(edit)

写进**已有**文档要用 `webcli joyspace edit`。完整四步(准备 md → 清空旧内容 → `edit --mode=write` 写入 → 叠字号+导出复查)详见 **[references/edit-existing-doc.md](references/edit-existing-doc.md)**。三个最易踩的坑:1)`--content` 必须等号绑定 `--content="$(cat file.md)"`,否则 md 里以 `-` 开头的行被 commander 误当选项报错;2)清空已有文档要从 React fiber 取 `editor` 实例用 `remove_node` 删块(Slate 不认合成 Cmd+A);3)写入后用 `edit --find="标题" --style="size:20"` 叠字号(一级 20、二级 16,标题块与字号可叠加)。

**失败排查**(两场景通用,`paste verification failed` / 插入无效):
1. **⭐ 最常见根因:Chrome 不在前台聚焦**。写入靠合成粘贴,**目标窗口必须是前台、可见、聚焦的普通标签页**。Chrome 最小化/后台/被盖住 → 粘贴失效 → **请用户把 Chrome 切到前台**再重试。(跑过一串 `browser` 自动化后焦点易乱。)
2. 焦点不在 `chrome://extensions` 这类特殊页 → 切普通 tab
3. `sleep 5` 重试(Chrome 防抖)
4. 文件名含中文偶发失败 → 用 ASCII 文件名
> ⚠️ **注意**:每次失败,API 仍会**先建一个空文档再粘贴**,所以反复失败会在草稿箱残留多个空页。`webcli joyspace list` 不一定能拿到可靠的 id/标题来区分,**不要盲删**(可能误删用户文档);成功后让用户自行清理,或确认安全范围后再删。

> 💡 **MCP 工具没加载怎么办**:若本会话 `mcp__zero-design__*` 工具不在列表里(常见于刚开会话没刷新),但 Zero 桌面端 MCP 仍在跑(`~/.claude.json` 有 `mcpServers.zero-design`,默认 `http://127.0.0.1:27618/mcp`),可以直接用 `curl` 走 HTTP 调 MCP:先 `initialize` 拿 `Mcp-Session-Id`,再发 `notifications/initialized`,最后 `tools/call`;响应是 SSE,取 `data:` 行的 JSON。无需重启会话。

## 完整范式 Prompt(给同事用)

把 Zero 链接和这段话发给 Claude Code 即可:

> 用 zero-to-joyspace skill,把这个设计稿 1:1 转到我的 JoySpace 草稿箱:
> https://relay.jd.com/file/design?id={fileKey}&page_id={pageId}&node_id={nodeId}
> 要求:白底文字转 markdown 文字,灰底示例区转截图穿插。
> (可选)目标标题:"{自定标题}"

## 常见踩坑速查

| 现象 | 原因 | 解决 |
|---|---|---|
| MCP 工具列表里没有 `mcp__zero-design__*` | Zero MCP 没注册或会话没刷 | 检查 `~/.claude.json` 有 `mcpServers.zero-design` → 重启 Claude Code |
| metadata `name` 字段是旧模板文字 | 设计师沿用模板没清字段 | **永远走 design_context 取真文字**,不要信 metadata 的 name |
| design_context 输出 >100KB 看不全 | 章节体量大 | 输出会持久化到文件,用 Python re 解析,不要 cat |
| 文字段落 grep 不到 | React 多行嵌套 `<p>` 把内容拆了 | 按关键词("定义"、"应用场景")+ 上下文窗口提取 |
| 灰底/白底分不清 | metadata 没颜色信息 | 必看截图,或问用户标注红框 |
| **图片包含了白底文字(标题/示意/注释/脚注)** | **export 了子小节容器,而非内层灰底节点** | **drill down:在子小节 React 里搜 `bg-\[#[fF]\d[fF]\d[fF]\w+\]` 模式,找到 width≈1426 的灰底 div,export 它的 nodeId。导出后 `curl + Read` 肉眼验证边缘是纯灰色,不是有白底文字** |
| 上传 paste verification failed | **Chrome 未前台聚焦**(最常见)/ 焦点在 chrome:// 页 / 路径有中文 | **让用户把 Chrome 切到前台**(合成粘贴需要窗口聚焦)+ 切普通 tab + ASCII 文件名 + sleep 重试 |
| **左侧没有导航(大纲目录)** | **一二级标题用了普通段落大字,不是真标题块** | **一二级标题用 `#`/`##`(真标题块才进导航),写入后再 `--style size:20/16` 叠字号,见 Step 6** |
| **一二级标题字号不对(默认标题预设大小)** | **`#`/`##` 标题块用的是 JoySpace 标题预设字号** | **写入后用 `webcli joyspace edit <doc-id> --find="标题" --style="size:20"` 叠字号(一级 20、二级 16),标题块与字号是独立属性可叠加** |
| **一级标题前面多了个圆点 `•`** | **写法带了开头的 `- `(旧版无序列表写法)** | **去掉 `- `,改用 `# 1. XXX` 标题块** |
| **满屏 `&nbsp;` 字面文字** | **`edit --mode write` 不认 `&nbsp;` 实体,当字面插入** | **绝不写 `&nbsp;`,空行用真正的空行**;历史残留用 fiber→editor 的 `remove_text` 清(见 references/edit-existing-doc.md) |
| **upload 页面标题异常** | **没传 `--title` 被正文首行自动提取** | **upload 必须带 `--title "设计稿名称"`** |
| **序号跨段落连续编号**(行为准则 1/2/3,下一节不从 1 开始而接 4/5……) | **用了 markdown 有序列表 `1.`,被 JoySpace 全文合并连续编号,`<ol start>` 也无效** | **别用 markdown 有序列表**。原样保留源文序号字段,用 `a.` 或全角 `1）` 写进普通段落(marked 不解析成 `<ol>`),每段独立计数 |
| 序号被自动增删改 / 与设计稿不一致 | 自动套用了序号样式 | **不自动设序号**,源文有什么序号就原样转写,没序号的字段不硬加 |
| **尺寸标注变成斜体**(如 `40*40DP` 中间一段文字斜体) | **`*` 是 markdown 斜体标记,同段两个 `*` 配对把中间文字变 `<em>`** | **尺寸里的 `*` 换成全角乘号 `×`**(`40×40DP`),消除误斜体 |
| **图片部分/全部丢失**(7 张只进了几张,数量随机) | **md 用了 CDN http 链接 → upload.js 靠 Slate 粘贴带图,批量粘贴多图极不稳定** | **md 改用本地相对路径**:先把 CDN 图 `curl`(带浏览器 UA 绕 403)下载到本地 `imgs/`,引用 `![](imgs/imgN.png)`,upload.js 会逐张服务端上传,稳定到位(见 Step 5) |
| 图片在 JoySpace 里加载不出来 | 用了 base64 内嵌或本地 file:// 绝对路径 | 用 `export_image` 取图后下载到本地,md 引用相对路径(见 Step 5) |
| `mcp__zero-design__*` 工具不在工具列表 | 会话没刷新加载 MCP | Zero 桌面端 MCP 仍在跑时,直接 `curl` 走 HTTP 调(见 Step 7 末尾说明),无需重启 |

## 限制 & 边界

- **不能跨页面**:一次只处理一个 nodeId 子树,跨 page 切换需要 `use_design_script`(超出本 skill 范围)
- **不能保留动画/交互**:Zero 的 prototype/transition 信息无法转 markdown
- **图片清晰度依赖 Zero 源图**:如果设计师上传的是低清素材,导出也低清
- **不可逆**:转 JoySpace 后再回 Zero 没有官方通路;源头单向
- **私密文档**:确保 Zero 文件你有权限读,以及上传到 JoySpace 的目标空间符合数据合规要求(默认是当前用户私人草稿,公开/团队空间需另行 `webcli joyspace move`)

## 历史案例

部门内部第一个跑通的真实案例:**JD APP 16.0 GUIDELINE - 资源库-主图**
- 源:Zero `node_id=3411:1`(7322px 高的设计系统页)
- 提取:1 个文档头 + 4 章正文 + 7 张灰底示例图(白底图/规格图/场景图/方图1:1/长图3:4/容错说明/典型场景)
- 耗时:约 8 分钟(大头在排错 metadata vs design_context 的差异)
- 产物:JoySpace 文档,正文+图片完整,部门内可直接传阅

**价格规范(2026-06-23)**:确立“`#`/`##` 真标题块进左侧导航 + 写入后叠 20/16 号字号”的两全方案,并跑通“写入已有文档”(场景 B)全流程。关键收获已固化进 Step 6 / Step 7 / [references/edit-existing-doc.md](references/edit-existing-doc.md):标题块能叠字号、`edit --content` 必须等号绑定、Slate 清空要走 fiber→editor、`edit` 不认 `&nbsp;` 字面。
