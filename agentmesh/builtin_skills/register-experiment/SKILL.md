---
name: register-experiment
description: 录入频道 AB 实验结论到 `$BASE/_knowledge/experiments/` 分类子目录。接收 PDF / 粘贴文本 / 截图任一形式的实验数据,先展示结构化预览让设计师审核,通过后再落盘 md、示意图、更新
  INDEX.json,最后重建对应分类的预览 html 和总目录 index.html。触发词包括:录入实验、新增实验、experiment、AB 实验录入、实验数据入库、这个实验录一下。
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/plus-and-new-channel/_skills/register-experiment/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 录入频道 AB 实验结论到 `$BASE/_knowledge/experiments/` 分类子目录。接收 PDF / 粘贴文本 / 截图任一形式的实验数据,先展示结构化预览让设计师审核,通过后再…
disable-model-invocation: true
---

# register-experiment · 实验录入 Skill

用于把 PLUS 与新品频道设计部做过的 AB 实验结论,按标准格式录入 `$BASE/_knowledge/experiments/`。

**核心设计**:
- **一个实验一个 md,按分类放在子目录**(商卡 / 腰部楼层 / 父子嵌套)
- **一个分类一个 preview html**(商卡.html / 腰部楼层.html / 父子嵌套.html)
- **一个总目录 index.html**(所有分类的导航)
- **两段确认流程**:结构化预览 → 落盘 + 重建对应分类预览

## 路径基准 · 必读

**skill 内所有路径都以 `$BASE` 为基准**,`$BASE` 是部门根目录:
```
$BASE = {仓库根}/jd-design-system-md-v16/product-architecture/plus-and-new-channel
```

**执行前必须先定位 $BASE**,详见 `references/路径规范.md`。核心逻辑:
1. 假设 skill 目录不变,`$BASE = $SKILL_DIR/../..`(优先)
2. 如果方式 1 失败,从当前 pwd 往上搜到含 `$BASE/_knowledge/experiments/INDEX.json` 的目录

**关键路径清单**(所有引用都用 `$BASE/` 前缀):
| 用途 | 路径 |
|---|---|
| 实验索引 | `$BASE/_knowledge/experiments/INDEX.json` |
| 实验 md 落盘 | `$BASE/_knowledge/experiments/{分类}/{缩写}.md` |
| 图片落盘 | `$BASE/_knowledge/experiments/assets/{缩写}-mock.png` |
| 分类预览页 | `$BASE/_knowledge/experiments/previews/{分类}.html` |
| 总目录页 | `$BASE/_knowledge/experiments/index.html` |
| 组件权威清单 | `$BASE/_foundation/components/COMPONENT_NODE_MAP.json` |
| 组件规范 | `$BASE/_foundation/components/{组件 slug}/spec.md` |

## 任务边界

**只做**:
- 录入**已完成、有数据结果**的 AB 实验
- 每次调用只录入 **1 个**实验
- 落盘到 `$BASE/_knowledge/experiments/{分类}/`

**不做**:
- ❌ 录入还没跑数据的方案想法
- ❌ 修改已录入的实验(除非用户明确要求重录)
- ❌ 跨部门录入(只服务本部门)
- ❌ 生成新的实验方案
- ❌ 一次录多个实验(用户说"批量"时,提示"我一次只录一个,先录哪个?")

## 目录结构

```
$BASE/_knowledge/experiments/
├── README.md                       (目录说明)
├── EXPERIMENT-TEMPLATE.md          (空白模板)
├── INDEX.json                      (按分类组织的索引)
├── index.html                      (总目录页,自动生成)
│
├── 商卡/                           (商卡类实验)
│   ├── {缩写}.md
│   └── ...
├── 腰部楼层/                       (腰部楼层类实验)
│   └── {缩写}.md
├── 父子嵌套/                       (父子嵌套类实验)
│   └── {缩写}.md
│
├── previews/                       (分类预览页)
│   ├── 商卡.html
│   ├── 腰部楼层.html
│   └── 父子嵌套.html
│
└── assets/                         (所有实验共用图片目录)
    ├── 送礼逛品商卡-mock.png
    ├── 楼层氛围-mock.png
    └── ...
```

## 输入约定

用户提供的实验数据可能是以下**任一形式**:

| 输入形式 | 处理方式 |
|---|---|
| **PDF 文件** | 用 Read 工具读 PDF 文字;用 Bash + pdfimages 提取图片 |
| **粘贴的文本**(表格 / 一段话) | 直接解析文本抽字段 |
| **截图**(PNG/JPG) | Read 工具读图理解内容;图片本身直接作为示意图 |
| **在线文档链接**(腾讯 / 飞书 / 京me) | ⚠️ 拿不到内容,必须提示用户改用上述三种之一 |

**在线文档处理话术**(严格照抄):

```
在线文档我拿不到内容(需要企业登录鉴权)。请把这个实验用以下任一方式给我:

1. 复制文本:选中实验内容 → Ctrl+A + Ctrl+C → 粘贴到对话框
2. 导出 PDF:文档 → 导出为 PDF → 拖进对话框(推荐,会自动提图)
3. 截图 + 简述:截图上传 + 补充关键数据
```

## 必读引用

执行录入前,必须按需读取以下 reference:

- `references/路径规范.md` — **首先读**,含 $BASE 定位逻辑和所有路径清单
- `references/字段抽取规则.md` — 从自由文本里抽取 20 个字段的规则(用户模板 18 项 + skill 反查 2 项),包含**自动分类判断表**
- `references/命名规则.md` — 中文缩写生成规则、重名处理、分类判断兜底
- `references/预览展示格式.md` — Stage A 结构化预览的输出模板
- `references/md-template.md` — md 输出模板
- `references/preview-card-template.html` — 分类预览页里单个实验卡片的 HTML 模板
- `references/preview-shell-template.html` — 分类预览页外壳模板
- `references/index-template.html` — 总目录 index.html 模板

## 两段流程

```
┌─────────────────────────────────────────────────┐
│  Stage A · 结构化预览(纯对话,不落盘)              │
│  1. 判断输入类型                                    │
│  2. 提取原始素材(PDF 图 / 截图)                    │
│  3. 抽取字段                                       │
│  4. 判断分类(不在初始 3 类时先单独确认)             │
│  5. 生成文件名                                     │
│  6. 展示结构化预览 → 用户 Y/n                       │
└─────────────────────────────────────────────────┘
              ↓ Y
┌─────────────────────────────────────────────────┐
│  Stage B · 落盘 + 重建对应分类预览                  │
│  7. 保存示意图到 assets/                           │
│  8. 生成 md 到 {分类}/                            │
│  9. 更新 INDEX.json                                │
│  10. 询问是否重建分类预览页 + index.html            │
│  11. (如用户选 Y)重建对应分类预览 + index.html      │
└─────────────────────────────────────────────────┘
```

**重要**:重建预览时**只重建被影响的那个分类的 html + index.html**,其他分类的 html 完全不动。

## Stage A · 详细步骤

### 第 1 步 · 判断输入类型

- 检查用户消息里是否有:PDF 附件 / 粘贴文本(超过 30 字) / 图片附件 / 在线文档链接
- **只有在线文档链接**:输出上面的话术,停止流程
- 输入类型不明:直接问用户"数据在哪里给我"

### 第 2 步 · 提取原始素材

- **PDF**: 用 `Read` 工具读取文字内容
- **PDF 图片提取**: Bash 执行:
  ```bash
  cd $BASE/_knowledge/experiments/assets && \
  mkdir -p .tmp && \
  pdfimages -all -p "<pdf-path>" .tmp/extract && \
  ls .tmp/extract-*
  ```
  然后让用户确认哪张是本次实验的示意图。如 PDF 里只有一张图,直接用。
- **粘贴文本**: 直接分析
- **截图**: `Read` 工具查看图片理解内容;把截图**本身**当作示意图

### 第 3 步 · 抽取字段

按 `references/字段抽取规则.md` 抽取 20 个字段。

**拿不准就问,不要猜**。典型需要问的场景:
- 业务线不明确 → 问"这是新品 / 排行榜 / PLUS 哪条业务线?"
- 复用条件描述模糊 → 问"这个方案在什么条件下可以抄?给我 3-5 条关键条件"
- 落地建议不清晰 → 问"这个实验最终决定:全量上线 / 迭代优化 / 废弃方案?"

### 第 4 步 · 判断分类 🔑

按 `references/字段抽取规则.md` 里的关键词表判断分类:

**分类枚举**:`商卡` / `腰部楼层` / `父子嵌套`

**判断结果**:

- **命中初始 3 类**:直接进入第 5 步
- **不属于初始 3 类**(如"标签栏"、"入口"):**先单独确认一次**,不要直接放到"其他":

  ```
  ⚠️ 分类判断:根据实验描述,这个实验涉及"标签栏"改动,不属于初始 3 类
     (商卡 / 腰部楼层 / 父子嵌套)。

  请确认分类:
    [1] 归到"标签栏"(自动创建新分类目录)
    [2] 归到已有分类的其中一个:_______
    [3] 我来告诉你分类名

  回复后我再展示完整预览。
  ```

  用户确认后,skill:
  - 如选 [1]:后续 Bash 会自动 `mkdir -p $BASE/_knowledge/experiments/{新分类}/` 和 `previews/{新分类}.html`
  - 如选 [2]:用用户指定的现有分类
  - 如选 [3]:用用户告诉的名字

### 第 5 步 · 生成文件名(中文缩写)

按 `references/命名规则.md`:

1. 从实验标题里提炼 3-6 字的中文缩写
2. Bash 检查 `$BASE/_knowledge/experiments/{分类}/{缩写}.md` 是否存在
3. 已存在 → 自动加 `-2` 后缀,同时**主动问用户**:"文件名 `X-2.md` 已生成,建议改个更清楚的名字?"

### 第 6 步 · 展示结构化预览

按 `references/预览展示格式.md` 输出摘要格式(不是 md 格式),让用户 5 秒扫完。

处理用户反馈:
- **Y / 通过 / OK / 对** → 进入 Stage B
- **指出具体问题**(如"业务线错了") → 修改对应字段,重新展示预览(回第 6 步)
- **q / 取消** → 清理 `.tmp/`,退出流程

## Stage B · 详细步骤

**顺序不能乱**:

### 第 7 步 · 保存示意图

- PDF 场景:从 `.tmp/extract-*` 里把用户确认的那张 → 改名为 `{缩写}-mock.png` → 移动到 `assets/`
- 截图场景:从用户上传路径复制到 `assets/{缩写}-mock.png`
- 清理 `.tmp/` 里剩下的其他图片

### 第 8 步 · 生成 md

按 `references/md-template.md` 填充,写到 `$BASE/_knowledge/experiments/{分类}/{缩写}.md`。

**注意 md 里图片引用路径**:因为 md 在子目录里,要用 `../assets/{缩写}-mock.png`。

### 第 9 步 · 更新 INDEX.json

- Read `$BASE/_knowledge/experiments/INDEX.json`
- 找到 `categories.{分类}` 数组(不存在则新建)
- 追加新条目 → 分类的 count+1 → total count+1 → updated_at 更新为今天
- Write 回去

### 第 10 步 · 输出落盘结果 + 询问重建预览

```
✅ 已录入 {title}

📄 md:      $BASE/_knowledge/experiments/{分类}/{缩写}.md
🖼 图片:    $BASE/_knowledge/experiments/assets/{缩写}-mock.png
📋 索引:    已同步 INDEX.json({分类} 分类现共 {N} 条 / 总计 {M} 条)

是否现在重建预览页?(默认 Y)
  [Y] 重建 {分类}.html + index.html(只影响这一个分类的预览)
  [n] 跳过,后续说"重建预览"可以手动触发
```

### 第 11 步 · 重建预览(可选)

用户 Y → 重建**两个** html:

**A. 重建 `previews/{分类}.html`**:

1. 读 INDEX.json,获取 `categories.{分类}` 下所有实验
2. 逐个读 `$BASE/_knowledge/experiments/{分类}/{缩写}.md` 的 frontmatter + 正文
3. 用 `references/preview-card-template.html` 生成每个实验的卡片
4. 用 `references/preview-shell-template.html` 包裹
5. Write 到 `$BASE/_knowledge/experiments/previews/{分类}.html`

**B. 重建 `index.html`**:

1. 读 INDEX.json 的 categories 结构
2. 用 `references/index-template.html` 生成总目录页
3. 每个分类展示:分类名 + 实验数 + 到分类 html 的链接
4. Write 到 `$BASE/_knowledge/experiments/index.html`

**其他分类的 html 完全不动**。这是方案 B 隔离性的核心。

输出:
```
🌐 预览已更新:
   分类页: $BASE/_knowledge/experiments/previews/{分类}.html
   总目录: $BASE/_knowledge/experiments/index.html
```

用户 n → 输出:"已跳过预览更新",结束。

## 独立子命令:重建预览

如果用户说"重建预览" / "刷新 experiments" / "重新生成 index":

- 用户指定分类("重建商卡预览"):只重建那一个分类的 html + index.html
- 用户没指定("重建所有预览"):**逐个**重建每个分类的 html + index.html
- 只说"重建 index":只重建 index.html

## 硬性要求

- ✅ Stage A 必须让用户确认后才落盘,不允许"看起来对就直接生成"
- ✅ 中文缩写不超过 6 字,不含空格 / 标点 / emoji
- ✅ 示意图必须落到 `assets/{缩写}-mock.png`,不允许多图
- ✅ INDEX.json 里的 `file` 字段和实际文件名必须一致
- ✅ 分类判断不确定时,**必须先问用户**,不能强行归到某类
- ✅ 更新预览时只碰**被影响的分类**的 html,不动其他分类
- ✅ 落盘失败(如权限不足)要回滚:删掉已经创建的 md 和图片
- ✅ **总目录 index.html 里的分类卡只保留:分类名 + icon + 实验数 + 最近录入**
  - ❌ 不要生成"✅ 正向 N / 🌟 可沉淀 N / ❌ 负向 N"等 stat-chip 标签
  - ❌ 不要在 category-recent 上方放分隔虚线
  - 新增分类或新增实验时也一样,不要以任何形式回退

## 禁止

- ❌ 编造用户没提供的数据(如流量分配没说就写 90/10)
- ❌ 跳过 Stage A 直接落盘
- ❌ 修改 EXPERIMENT-TEMPLATE.md(那是给人拷贝用的静态模板)
- ❌ 修改其他部门的 experiments/
- ❌ 修改已存在的历史 md 文件(除非用户明确要求"重录 XXX")
- ❌ 把 PDF 里所有图都当示意图存(用户没确认前只暂存 .tmp/)
- ❌ 处理超过 1 个实验
- ❌ 一次重建所有分类的 html(除非用户明确要求)—— 只重建被影响的分类
- ❌ 分类判断不确定时强行归类(必须问用户)

## 完成标准

- Stage A 展示的字段和用户输入一致(无编造)
- Stage B 落盘后:md 打开能看到图 + INDEX.json 能查到 + `{分类}.html` 里有对应卡片 + index.html 里能看到分类总数(如果用户选择更新预览)
- 每一个字段都有依据(用户提供 / 用户确认 / 规则明确的默认值)
- 其他分类的 html 完全不受影响
