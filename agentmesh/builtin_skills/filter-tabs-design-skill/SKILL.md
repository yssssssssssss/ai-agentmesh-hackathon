---
name: filter-tabs-design-skill
description: Generate or update the Zero Filter Tabs 筛选项 component family as pixel-accurate React, TypeScript, and Tailwind
  CSS v3 code. Use when the user runs /gen-component, requests 操作图标/按钮-28/筛选TAB, asks for FilterTabs or Button28, or pastes
  the linked Zero or Relay node URL. Always read the target through Zero MCP before generating code.
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/local-life/Channel 频道/Filter Tabs 筛选项/filter-tabs-design-skill/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: during_design
  agentmesh-activation: explicit_only
  short-description: Generate or update the Zero Filter Tabs 筛选项 component family as pixel-accurate React, TypeScript, a…
disable-model-invocation: true
---

# Filter Tabs 筛选项 GenerationSkill

Zero is the only visual source of truth. This Skill is scoped to the `Filter Tabs 筛选项` specification root, not to every component in the full design-system file.

## 触发

- Command: `/gen-component <组件名、需求或 Zero 节点链接>`
- Implicit trigger: paste `https://3.cn/11m-3EWFc` or a `relay.jd.com` node URL.
- Empty command input: use Zero root node `122:8486`.
- Supported Zero component names: `操作图标`, `按钮-28`, `筛选TAB`.
- Supported React names: `OperationIcon`, `Button28`, `FilterTabs`.

## Zero 来源

| Field | Value |
| --- | --- |
| Provider | Zero MCP |
| Short URL | `https://3.cn/11m-3EWFc` |
| File key | `2057090330888527873` |
| Page | `[p]Tag Button 标签按钮` / `74:3` |
| Spec root | `Filter Tabs 筛选项` / `122:8486` |
| Component frame | `操作图标` / `122:8521` |
| Component frame | `按钮-28` / `122:8528` |
| Component frame | `筛选TAB` / `345:1527` |
| Extracted | `2026-06-15` |

The older nodes `6:1`, `6:2`, `6:3`, and `6:14` belong to a derived example file and are not the component-library source. Do not use them unless the user explicitly targets that file.

## 约束

1. Before generating code, call Zero `get_design_metadata`, `get_design_context`, `get_variables`, and `get_screenshot` for the requested node. Never implement from metadata or screenshots alone.
2. Match Zero at the 375 px reference viewport: width, height, inset, gap, alignment, radius, font metrics, overflow, sibling order, vector geometry, colors, and state-specific surfaces.
3. Use React + TypeScript + Tailwind CSS v3.
4. Generate only into:

   ```text
   src/components/atoms/
   src/components/composites/
   src/layouts/
   src/pages/
   ```

5. Put `OperationIcon` and `Button28` in `atoms/`; put `FilterTabs` in `composites/`. `layouts/` and `pages/` are only for user-requested compositions.
6. Every visual value must resolve from [TOKENS.json](TOKENS.json) through named CSS custom properties or Tailwind `theme.extend` entries. Raw hex, `rgb()`, `rgba()`, numeric spacing, numeric radius, numeric typography, raw shadow, and raw z-index are forbidden in TSX/CSS.
7. Numeric SVG `viewBox`, path data, transforms, and coordinates exported from Zero are permitted because they are asset geometry, not handwritten style values.
8. Do not use arbitrary Tailwind values such as `w-[375px]`, `top-[5px]`, or `text-[#3d414d]`. Create semantic utilities such as `w-ft-tabs-upscroll`, `inset-x-ft-tabs`, and `bg-ft-control-muted`.
9. Preserve Zero SVGs. Do not replace them with icon libraries, emoji, CSS triangles, text glyphs, or approximate paths.
10. MCP `localhost` asset URLs are temporary. Download/re-export the asset and commit a stable local SVG; never ship the temporary URL.
11. Preserve fixed single-line labels, `overflow: hidden/clip`, and non-wrapping horizontal layout. The Zero component clips; it does not expose a native scrollbar.
12. Preserve DOM paint order: button track first, `MoreOverlay` second. The overlay must remain above the track.
13. Do not add borders, focus rings inside measured bounds, gradients, blur, or shadows. Zero contains none for these components.
14. Add accessible names and keyboard behavior without changing measured visual dimensions. Put enlarged hit areas outside the 12 px icon viewport if needed.
15. The Zero annotation says `radius-6`, while the actual component frames returned by `get_design_context` measure `4 px`. Pixel output must use the measured `radius.control = 4`.
16. Do not invent Button, Card, Input, Modal, Navbar, SearchBar, or other component docs. They are absent from the `122:8486` subtree.

## Tokens

Read [TOKENS.json](TOKENS.json) before writing any component.

### Colors

| Semantic token | Zero variable | Value | Usage |
| --- | --- | --- | --- |
| `color.surfaceOverlay` | `color-background-overlay` | `#FFFFFF` | Default controls, upscroll root, category control |
| `color.surfaceCanvas` | `color-background` / `BackgroundGray-3` | `#F2F2F4` | Default more overlay |
| `color.surfaceMuted` | `BackgroundGray-2` | `#F7F8FC` | Upscroll controls |
| `color.textDefault` | `color_text` | `#3D414D` | Default and upscroll labels/icons |
| `color.primary` | `color_primary` / `color-primary` | `#FF0F23` | Click label/icon |
| `color.primaryLight` | `color_primary_light` | `#FFF0F4` | Click control background |
| `color.onPrimary` | `color_primary_text` | `#FFFFFF` | Reserved matching source variable |

### Typography

- Default/upscroll label: PingFang SC Regular, `12/12`, weight `400`, letter spacing `0`.
- Click label: PingFang-SC Medium, `12/12`, actual weight `500`, letter spacing `0`.
- All labels are centered and `white-space: nowrap`.

### Layout

- Operation icon viewport: `12 × 12`.
- Button height: `28`; horizontal and vertical padding: `8`; content gap: `4`; radius: `4`.
- Filter item gap: `8`.
- Default FilterTabs: root `359 × 28`; track `375 × 28` at `(0, 0)`; more overlay `34 × 28` at `(325, 0)`.
- Upscroll FilterTabs: root `375 × 38`; track `367 × 28` at `(8, 5)`; more overlay `34 × 28` at `(341, 5)`.
- More icon viewport inside overlay: `12 × 12` at `(11, 8)`.
- Shadows: `none`.
- Layers: track `0`, more overlay `1`.

Configure Tailwind with semantic names from `tailwindMapping` in [TOKENS.json](TOKENS.json). Do not copy token values into component source.

## 组件规范

### 操作图标 / OperationIcon

Full specification: [components/OperationIcon.md](components/OperationIcon.md)

| State | Node | Exact geometry |
| --- | --- | --- |
| `默认` | `122:8522` | viewport `12 × 12`; glyph `12.01 × 11` at `(0, 0.5)` |
| `展开` | `122:8524` | viewport `12 × 12`; glyph `8.718 × 4.5` at `(1.64, 3.75)` |
| `收起` | `122:8526` | same glyph bounds as 展开; preserve Zero asset/rotation |
| `商场` | `122:10055` | viewport `12 × 12`; glyph `12 × 10.625` at `(0, 0.38)` |
| `更多` | `345:1423` | three exact horizontal SVG strokes at y `1`, `6`, `11` |

The component root is always `position: relative; width: 12; height: 12`. Preserve each exported SVG separately.

### 按钮-28 / Button28

Full specification: [components/Button28.md](components/Button28.md)

Structure is `button > leading icon? + label + trailing icon?` with fixed order, centered alignment, intrinsic width, `28` height, `8` padding, and `4` gaps.

| State | Node | Surface | Text/icon | Font |
| --- | --- | --- | --- | --- |
| `默认` | `122:8529` | `surfaceOverlay` | `textDefault` | Regular `12/12` |
| `点击` | `122:8533` | `primaryLight` | `primary` | Medium `12/12`, weight `500` |
| `上划` | `360:108` | `surfaceMuted` | `textDefault` | Regular `12/12` |

Leading and trailing icon visibility are independent Boolean variants. The Zero reference with `Button` plus two icons is `86 × 28`. Do not hardcode widths for arbitrary labels; exact font metrics and intrinsic layout produce the width.

### 筛选TAB / FilterTabs

Full specification: [components/FilterTabs.md](components/FilterTabs.md)

```text
FilterTabs
├── Track
│   └── Button28[]
└── MoreOverlay
    └── OperationIcon(state="更多")
```

| State | Node | Root | Track | More overlay |
| --- | --- | --- | --- | --- |
| `默认` | `345:1523` | `359 × 28` | `(0,0) 375 × 28`, white buttons | `(325,0) 34 × 28`, canvas surface |
| `上划` | `345:1525` | `375 × 38`, white | `(8,5) 367 × 28`, muted buttons | `(341,5) 34 × 28`, white |

Default source fixture labels: `综合排序`, `超级月卡折上折`, `百补新客券`, `常购/关注`, `Button`.

Upscroll source fixture labels: `综合排序`, `超级月卡折上折`, `百补新客券`, `常购/关注`, `快餐简餐`.

The first item has the `展开` trailing icon. In the upscroll fixture, the category item remains white while the preceding controls use the muted surface. Keep `MoreOverlay` as a sibling of the track, never as a track item.

## Zero MCP 工作流

1. Resolve the supplied URL and confirm file key `2057090330888527873`, unless the user intentionally supplied another Zero node.
2. Call `get_design_metadata` on the target to enumerate child components and variants.
3. Call `get_design_context` on each requested component/state.
4. Call `get_variables` and map every returned binding to [TOKENS.json](TOKENS.json).
5. Call `get_screenshot` immediately after each context call and compare the rendered component.
6. Export referenced SVG assets with stable local paths.
7. Inspect the target repository and reuse its exports, class-merging helper, testing conventions, and Tailwind setup.
8. Add token mappings first, then atoms, then composites, then requested layout/page compositions.
9. Run typecheck, tests, build, token validation, and screenshot comparison.

For a full-file scan, first load the Zero `use-design-script` skill and API index, then use `use_design_script`. Limit generated docs to components inside the requested root.

## React API

Use typed named exports:

```ts
export type OperationIconState = "default" | "expand" | "collapse" | "mall" | "more";

export interface OperationIconProps {
  state: OperationIconState;
  className?: string;
  decorative?: boolean;
}

export type Button28State = "default" | "pressed" | "upscroll";

export interface Button28Props
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  label: string;
  state?: Button28State;
  leadingIcon?: OperationIconState;
  trailingIcon?: OperationIconState;
}

export interface FilterTabItem {
  id: string;
  label: string;
  state?: Button28State;
  leadingIcon?: OperationIconState;
  trailingIcon?: OperationIconState;
}

export interface FilterTabsProps {
  mode: "default" | "upscroll";
  items: readonly FilterTabItem[];
  onItemClick?: (id: string) => void;
  onMoreClick?: () => void;
  ariaLabel?: string;
  className?: string;
}
```

Use controlled interaction state unless the target repository already has an established pattern.

## 验收

- Geometry tolerance: at most `1 CSS px` at the 375 px reference viewport.
- Color, font family, font weight, line height, radius, order, clipping, and vector paths: exact.
- Every rendered state must be compared with its Zero screenshot.
- No unrelated component docs or source-file IDs remain.
- Run:

  ```bash
  node .claude/skills/filter-tabs-design-skill/scripts/check-token-usage.mjs .
  ```

- Fix every violation before completion.
