---
name: instance-manage
description: '执行实例标签管理命令：解析 UI 生成的操作清单 JSON， 逐条对 instances.json / scene.json 执行 add/update/delete/merge， 从 pending-instances.json
  移除已处理项并归档。 /instance-manage <粘贴 JSON 命令>

  '
user-invocable: true
triggers:
- 实例管理
- 标签管理
- 执行标签命令
allowed-tools:
- Bash
- Read
- Edit
- Write
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/huangliu-design/product-details/JD-ProductDetails-web/brain-frontend/public/design-kb/skills/instance-manage/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 执行实例标签管理命令：解析 UI 生成的操作清单 JSON， 逐条对 instances.json / scene.json 执行 add/update/delete/merge， 从 pendin…
disable-model-invocation: true
---

# /instance-manage · 实例标签管理

## 工作目录

执行本 skill 前，请先定位到仓库中的 `JD-ProductDetails-web/brain-frontend/` 目录，
所有路径均以此为根目录。

## 这个 Skill 做什么

接收 UI 弹窗（instance-tag-form.html）生成的 JSON 命令，逐条执行实例标签操作：

- **add**：追加新实例到 instances.json 对应 area
- **update**：修改已有实例的字段
- **delete**：从 instances.json 移除实例
- **merge**：删除源实例 + 新增目标实例

执行完成后：
- 从 pending-instances.json 移除已处理的条目
- 归档到 pending-instances-history.json
- 如果涉及 scene 字段，同步写入 scene.json

## 调用方式

```
/instance-manage
{
  "command": "instance-manage",
  "version": "1.0",
  "generated_at": "2026-07-17T10:30:00+0800",
  "note": "审核通过 3 条待审核实例",
  "operations": [...]
}
```

---

## 执行流程

### Step 1：解析并校验命令

1. 解析 JSON（JSON.parse 是允许的，只读）
2. 校验 `command === "instance-manage"` 和 `version === "1.0"`
3. 校验 `operations` 是数组且非空

校验失败 → 报错停止，输出具体错误原因。

---

### Step 2：逐条执行操作

**严格要求：所有文件写入用 Edit 工具的文本级替换，禁止 JSON.parse + JSON.stringify 后整体写回。**

#### 2a. add 操作

```json
{ "action": "add", "id": "beltCountdown", "name": "腰带倒计时", "depth": "universalFloors", "area": "card1Area", "ytype": "general", "xtype": 0, "scene": "nationalSubsidy", "pending_id": "pending_1721200000000" }
```

**执行步骤：**

1. 用 Read 读取 `public/design-schema/instances.json`
2. 找到 `depth.area.items` 数组的最后一个 `}` 位置
3. 用 Edit 在最后一个 item 后追加新条目：

```
找到: { "id": "lastExisting", ... }
     ]
替换: { "id": "lastExisting", ... },
        { "id": "beltCountdown", "name": "腰带倒计时", "ytype": "general", "xtype": 0 }
      ]
```

4. 如果 `scene` 字段非空，用 Edit 在 scene.json 对应条目的 `"instances": [...]` 里追加新 id

5. **回改来源需求档案**（若 pending 项含 `source_requirement.slug`，即该标签是从某条档案评审提出的）：
   - 查 `pending-instances.json`（或从命令的 pending 快照中）拿到 `source_requirement.slug`
   - 拼装完整标签名 `"{区域中文标签}·{name}"`（如 `已选弹层·多履约选项`）
     - 区域中文标签取自 instances.json 里对应 `area.label`（例如 `productSpec.label = "已选弹层"`）
   - 追加到该档案 3 处（**严格限定字段范围，不改正文**）：
     - `public/design-kb/knowledge/preview/index.js`：对应 slug 条目的 `keywords_component` 数组末尾追加，同时追加到 `keywords` 数组
     - `public/design-kb/knowledge/preview/cases/{slug}.js`:`keywords` 数组末尾追加
     - `public/design-kb/knowledge/**/{slug}/reasoning.md` 或 `pdp/**/{slug}-reasoning.md` 的 frontmatter：
       - `tags_instance: [..., 新标签]`
       - `keywords_component: [..., 新标签]`
       - `keywords: [..., 新标签]`
   - **去重**：如果对应字段中已包含此标签（大小写敏感精确匹配），跳过该字段的追加
   - **不存在**：如果找不到对应档案（slug 在 index.js 里找不到）→ 报告中标注 ⚠️ 但不阻断其它操作

**冲突检查：** 执行前 grep 确认 `"id": "beltCountdown"` 不存在于 instances.json。冲突则报错停止。

#### 2b. update 操作

```json
{ "action": "update", "id": "existingOne", "fields": { "name": "修改后的名字", "ytype": "health" } }
```

**执行步骤：**

1. 用 grep 定位 `"id": "existingOne"` 所在行
2. 读取该行及周围行，确认完整的 item 对象
3. 用 Edit 精确替换需要改的字段

**不存在则跳过，在报告中标注 ⚠️。**

#### 2c. delete 操作

```json
{ "action": "delete", "id": "obsoleteOne" }
```

**执行步骤：**

1. 用 grep 定位 `"id": "obsoleteOne"` 所在行
2. 确定该 item 的完整文本范围（从 `{` 到 `}`，含末尾逗号）
3. 用 Edit 删除整行

**注意：** 如果是数组最后一项，需同时去掉前一项的末尾逗号。

**不存在则跳过，在报告中标注 ⚠️。**

#### 2d. merge 操作

```json
{ "action": "merge", "source_ids": ["instanceA", "instanceB"], "target": { "id": "merged", "name": "合并后", "area": "card2Area", "ytype": "general", "xtype": 0 } }
```

**执行步骤：**

1. 对每个 source_id 执行 delete 逻辑
2. 对 target 执行 add 逻辑

---

### Step 3：清理 pending-instances.json

对每个成功执行的 add 操作（有 `pending_id` 字段的）：

1. 从 pending-instances.json 移除对应条目
2. 追加到 pending-instances-history.json（新增归档文件，格式和 pending 相同但多一个 `processed_at` 字段）

用 Edit 工具精确删除已处理条目。

---

### Step 4：回改引用了被删除/重命名/新增实例的档案

**两种回改场景：**

- **add + 有 source_requirement.slug**：给来源档案的 `keywords_component` / `keywords` / `tags_instance` 追加新标签 —— 详见 Step 2a 第 5 步（在 add 内联执行）
- **delete + redirect_to**：把旧实例引用替换为新实例 —— 见下方（本 Step 处理）

对每个 delete（含 redirect_to）操作，扫描并替换档案中的实例引用。

**替换范围限定（严格遵守）：** 只替换以下字段中的精确匹配值，**不替换 sections 正文**：
- index.js 的 `keywords_component` 数组元素
- cases/{slug}.js 的 `keywords` 数组元素
- reasoning.md frontmatter 的 `tags_instance` / `keywords_component`

**不替换**：sections.background / goal / constraints / states / patterns 等正文中的自然语言描述（即使包含相同文字）。

**匹配格式：** 使用完整的 `"区块·模块名"` 格式匹配（如 `"首卡区·以旧换新公式"`），不搜裸名称。

**扫描命令：**

```bash
# delete + redirect_to 场景：把旧实例引用替换为新实例
grep -rl "区块·旧实例名" public/design-kb/knowledge/preview/cases/
grep -l "区块·旧实例名" public/design-kb/knowledge/preview/index.js
grep -rl "旧实例名" public/design-kb/knowledge/pdp/ public/design-kb/knowledge/scene/ --include="*.md" | xargs grep -l "tags_instance.*旧实例名"
```

如果有命中：
1. 列出要改的文件清单和具体替换内容
2. **展示给用户 review**（明确标注"只改标签字段，不改正文"）
3. 用户确认后用 Edit 执行替换

---

### Step 5：输出执行报告

```markdown
## 执行报告

### 成功操作
- ✓ add: beltCountdown（腰带倒计时）→ universalFloors.card1Area
- ✓ add: newSheet（新弹层）→ secondaryLayers.secondarySheet
- ✓ delete: obsoleteOne

### 跳过
- ⚠️ update: nonExistentId — 未找到，已跳过

### 回改档案
- cases/app-xxx.js: keywords_component "首卡区·腰带倒计时（待审核）" → "首卡区·腰带倒计时"

### 待用户操作
请 review 以上改动后 commit + push。
```

---

## 约束

1. **禁止 JSON.parse + stringify 整体写回**。所有改动用 Edit 工具文本级操作。
2. **不自动 commit**。执行完报告后等用户确认。
3. **冲突即停**：add 时 id 已存在 → 报错停止，不继续后续操作。
4. **不存在跳过**：update/delete 时 id 不存在 → 跳过，继续后续操作。
5. **pending-instances-history.json 不存在时自动创建**，格式 `{"history": [...]}`。
6. **add 必回改来源档案**：所有待评审的实例标签都是从某条需求录入衍生出来的（`source_requirement.slug` 指向该档案）。审核通过（add）后，**必须**把新标签同步写回该档案的 keywords_component / keywords / tags_instance；否则会出现"实例存在但档案未挂载"的数据断层。历史遗留场景（无 source_requirement）才可以跳过回改。

---

## 版本历史

- **v1.1** (2026-07-29) add 操作强制回改来源档案（keywords_component / keywords / tags_instance）
- **v1.0** (2026-07-17) 初版
