---
name: instance-suggest
description: '为 pending-instances.json 中的待审核实例生成命名建议。 读取现有 instances.json 学习命名风格，结合来源需求上下文推断 Ytype/Scene。 建议写回 pending-instances.json
  的 suggestion 字段。 /instance-suggest

  '
user-invocable: true
triggers:
- 生成标签建议
- 建议实例命名
allowed-tools:
- Bash
- Read
- Edit
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/huangliu-design/product-details/JD-ProductDetails-web/brain-frontend/public/design-kb/skills/instance-suggest/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 为 pending-instances.json 中的待审核实例生成命名建议。 读取现有 instances.json 学习命名风格，结合来源需求上下文推断 Ytype/Scene。 建议写回 pe…
disable-model-invocation: true
---

# /instance-suggest · 实例命名建议生成

## 工作目录

执行本 skill 前，请先定位到仓库中的 `JD-ProductDetails-web/brain-frontend/` 目录。

## 这个 Skill 做什么

为 `public/design-schema/pending-instances.json` 中尚无 `suggestion` 字段的待审核实例，生成英文 ID、Ytype、Xtype、Scene 建议。

**白名单用户在打开"标签维护"弹窗前手动运行此命令。**

---

## 命名规则（学习自现有 instances.json）

### 格式

- **严格 camelCase**（首字母小写，后续单词首字母大写）
- 无连字符、无下划线、无前缀（不加 app-/pdp-）
- 意译（不是拼音）

### 后缀惯例

| 组件类型 | 后缀 | 示例 |
|---|---|---|
| 弹层 | Sheet | `nationalSubsidySheet`, `couponSheet` |
| 弹窗 | Dialog | `genericDialog` |
| 多Tab | Tabs | `purchaseTabs`, `heroAnchorTabs` |
| 公式/计算模式 | Formula | `tradeInFormula`, `medicineFormula` |
| 挂件/浮层 | Widget | `floatWidget`, `chatWidget` |
| 独立楼层（无明显类型） | 不加后缀 | `store`, `tradeIn`, `installService` |

### 命名示例

| 中文名 | 英文 ID | 规则说明 |
|---|---|---|
| 顶部导航 | `topNav` | 位置+组件 |
| 底Bar | `bottomBar` | 位置+组件 |
| 主图锚点Tab | `heroAnchorTabs` | 功能+复数 |
| 以旧换新公式 | `tradeInFormula` | 业务+组件类型 |
| 国补弹层 | `nationalSubsidySheet` | 业务+组件类型 |
| 小图选款 | `skuPicker` | 功能动词+对象 |
| 心智加盖 | `mindCap` | 功能名意译 |
| 宠物档案（新） | `petProfileNew` | 对象+后缀 |
| 上门安装 | `installService` | 动作+对象 |
| 线下门店 | `store` | 极简单词 |

### 重名处理

如果建议的 ID 已存在于 instances.json，加业务前缀区分：
- 已有 `sheet` → 新的叫 `nationalSubsidySheet`
- 已有 `countdown` → 新的叫 `beltCountdown`

---

## Ytype 推断规则

通过 `source_requirement` 字段获取来源需求信息：

1. 如果 pending 有 `source_requirement.slug`：
   - 在 `preview/index.js` 里找到该 slug 的 entry
   - 读取 `keywords_business` 和 `area` 字段

2. 推断映射：

| keywords_business / area 特征 | 建议 Ytype |
|---|---|
| 含"国补" / 含"补贴" | `general`（国补是通用能力） |
| 含"健康" / area 含 "health" | `health` |
| 含"以旧换新" / 含"二手" | `secondHand` |
| 含"家电" / 含"家居" / area 含 "home" | `home` |
| 含"3C" / 含"数码" / 含"手机" | `3C` |
| 含"超市" / 含"生鲜" | `supermarket` |
| 含"时尚" / 含"服饰" | `fashion` |
| 含"汽车" / 含"轮胎" | `auto` |
| 无特殊标识 | `general`（默认） |

3. 如果没有 slug（来源需求尚未录入完成）：
   - 从 `context` 补充说明推断
   - 推断不出则默认 `general`

---

## Scene 推断规则

在 `public/design-schema/scene.json` 中匹配：

| 来源需求特征 | 建议 Scene |
|---|---|
| keywords 含"国补"/"国家补贴" | `nationalSubsidy` |
| keywords 含"预约"/"预售" | `reserve` 或 `preSale` |
| keywords 含"拼团"/"拼购" | `groupBuy` |
| keywords 含"以旧换新" | `tradeInTab` |
| keywords 含"定期购" | `regularBuyTab` |
| 无法确定 | 留空 |

---

## 执行流程

### Step 1：读取 pending-instances.json

```bash
cat public/design-schema/pending-instances.json
```

筛选出 `suggestion` 字段为空或不存在的条目。

如果全部已有 suggestion → 输出"所有待审核实例已有建议，无需处理"并结束。

---

### Step 2：读取现有 instances.json

```bash
cat public/design-schema/instances.json
```

收集所有已存在的 id，用于冲突检测。

---

### Step 3：逐条生成建议

对每个缺少 suggestion 的 pending 条目：

1. 根据 `name`（中文名）意译为 camelCase 英文 ID
2. 根据 `source_requirement` 推断 Ytype
3. 根据 `source_requirement` 推断 Scene
4. Xtype 默认 0
5. 检查 ID 是否和现有冲突，冲突则加前缀

---

### Step 4：写回 pending-instances.json

对每条 pending 用 Edit 工具追加 `"suggestion": {...}` 字段。

**文本级操作示例：**

```
找到: "submitted_at": "2026-07-17T10:30:00+0800"
    }
替换: "submitted_at": "2026-07-17T10:30:00+0800",
      "suggestion": {
        "id": "beltCountdown",
        "area": "card1Area",
        "ytype": "general",
        "xtype": 0,
        "scene": "nationalSubsidy",
        "confidence": "high",
        "reasoning": "现有腰带相关实例命名为 belt，倒计时功能用 Countdown 后缀"
      }
    }
```

---

### Step 5：输出报告

```markdown
## 建议生成完成

| 中文名 | 建议 ID | Ytype | Scene | 置信度 |
|---|---|---|---|---|
| 腰带倒计时 | beltCountdown | general | nationalSubsidy | high |
| ... | ... | ... | ... | ... |

已写入 pending-instances.json。请打开"标签维护"弹窗查看。
```

---

## 约束

1. 只修改 pending-instances.json，不改 instances.json
2. 用 Edit 文本级操作，不整体重写
3. 不自动 commit

---

## 版本历史

- **v1.0** (2026-07-17) 初版
