---
name: relay-demo-from-md
description: 从 channel-demo.yaml 与各组件 ai-schema.md 生成并同步 Relay 演示页。 当用户要求按 MD 规范生成/更新演示页、规范总览、串联预览，或提到 sync-relay-demo / channel-demo.yaml
  时使用。
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/local-life/Home Service 家政频道/.cursor/skills/relay-demo-from-md/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: during_design
  agentmesh-activation: explicit_only
  short-description: 从 channel-demo.yaml 与各组件 ai-schema.md 生成并同步 Relay 演示页。 当用户要求按 MD 规范生成/更新演示页、规范总览、串联预览，或提到 sync-rela…
disable-model-invocation: true
---

# MD → Relay 演示页同步

## 工作流

1. **校验配置**
   ```bash
   node scripts/sync-relay-demo.mjs --validate
   ```

2. **生成 Relay 脚本**（读取 `channel-demo.yaml` + `*/ai-schema.md`）
   ```bash
   node scripts/sync-relay-demo.mjs
   # 或只生成某一页：
   node scripts/sync-relay-demo.mjs --page channel-demo
   ```

3. **写入 Relay** — 用 MCP `user-zero-design` / `use_design_script`：
   - 读取 `scripts/generated/relay-demo.sync.js`（或 `relay-demo.{pageId}.js`）
   - 将文件全文作为 `code` 参数执行
   - **不要**手改 generated 文件；改 `channel-demo.yaml` 或各组件 `ai-schema.md` 后重新生成

4. **截图验收** — 对返回的 `nodeId` 调用 `get_screenshot` 检查布局与居中

## 源文件职责

| 文件 | 作用 |
|---|---|
| `channel-demo.yaml` | 演示页结构、模块顺序、布局、Relay 目标页、`preview_policies` |
| `*/ai-schema.md` | 组件 Relay 节点 ID、变体映射 |
| `.cursor/rules/relay-spec-page-align.mdc` | 375 居中、HUG 链规则（生成脚本已内置 offset） |

## 修改演示页的规范方式

- **增删模块** → 编辑 `channel-demo.yaml` 的 `pages[].sections` 或 `modules`
- **换组件变体** → 改 `components.*.default_variant_id` 或 ai-schema 中 `variants`
- **MD 输出页 Tab 展示** → `preview_safe: true` + `preview_policies.channel_page_head`（仅替换页面实例内 Tab，不改组件源）
- **换 Relay 节点** → 改对应组件 `ai-schema.md`，再 `--validate`

## StoredPackageCard（囤次卡）MD 演示

**唯一正确做法**：克隆参考画板 **`MD输出·囤次卡1`**，不要手搭 Frame/Text 模拟组件。

| 项 | 值 |
|---|---|
| 模板帧 | `MD输出·囤次卡1`（`[p]MD测试`，含 `套餐=未选中` / `套餐=选中` 两个 **COMPONENT** 克隆体） |
| 输出帧 | `MD输出·囤次卡` |
| 脚本 | `scripts/relay-storedpackage-md-demo.compact.js` |
| 锚点 | 紧贴 `MD输出·TabFeeds` 右侧，gap **40pt** |

经 MCP `use_design_script` 执行 compact 全文。模板内须为真实实例：

- 标题 `属性1=默认`（INSTANCE）
- 时长 Tab `个数=3`（INSTANCE，Tab 宽 **101pt**）
- 规格卡 `卡片=未选中` / `卡片=选中`（INSTANCE，166×97 / 166×116）
- 右侧 `查看更多`（GROUP + 矢量底，高 **111pt**）
- 选中态含先享后付等支付 INSTANCE（`12:15442` 语义）

### 禁止（相对囤次卡1）

- ❌ 用 `relay.createText` / 手画圆角框代替标题、Tab、次卡、支付区
- ❌ Tab 三等分手算宽度（应为组件库 **101×32** 三项）
- ❌ 「查看更多」纯竖排文字（缺灰底与播放 icon）
- ❌ 省30元/保洁师用纯文字 ✓/✕（应为图标 INSTANCE）
- ❌ 删除或改模板帧 `MD输出·囤次卡1`（仅作参照，可保留在页右侧）

## TabFeeds 专用脚本（结构+内容演示）

当仅需 TabFeeds 且当前稿无 `6:xxxx` 实例时：

```bash
# 可读维护: scripts/relay-tabfeeds-md-demo.js
# MCP 同步: scripts/relay-tabfeeds-md-demo.compact.js
node scripts/sync-tabfeeds-demo.mjs
```

经 MCP `use_design_script` 执行 **compact** 文件全文。必须遵守 `TabFeeds/visual.md` §6：

| 规则 | 实现要点 |
|---|---|
| Tab 文案居中 | `textAlignHorizontal: CENTER`，项宽 124/125/126 |
| 选中态与指示线 | 文案 `y = 34 - 6 - 2 - fontSize`，指示线 `y = 34 - 6 - 2` |
| 价格同行 | 到手价 + ¥149 + 划线 ¥189 同一 `priceRow` 帧 |
| 卡片 HUG | `总高 = 图高 + infoH`，单行标题用较小 infoH，禁止固定 296/260 留白 |

## 禁止

- ❌ 直接在 Relay 手搭演示页而不同步 YAML（会被下次 sync 覆盖）
- ❌ 修改 `scripts/generated/*.js` 而不改 YAML 源
- ❌ 跳过 `--validate` 就 sync（节点 ID 缺失会在 Relay 运行时报错）
- ❌ TabFeeds MD 演示里把划线价换行、Tab 文案贴底条、商卡固定超高留白

## 页面 ID

| id | 输出帧名 | 目标页 |
|---|---|---|
| `spec-overview` | 家政频道-规范总览 | Tile Area |
| `channel-demo` | MD输出·父子嵌套Tab预览 | Nested Structure |
| `tab-feeds-demo` | MD输出·TabFeeds预览 | Tab/Feeds |
| `channel-serial-md` | MD输出·家政频道串联页 | Channel Page / 当前页 |
| `serial-preview` | 页面串联预览 · 375 | 嵌在 spec-overview |

## 示例对话

> 「按 channel-demo.yaml 同步 Relay 演示页」

执行：validate → generate → use_design_script → get_screenshot
