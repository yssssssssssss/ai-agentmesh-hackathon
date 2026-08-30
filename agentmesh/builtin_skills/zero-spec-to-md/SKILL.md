---
name: zero-spec-to-md
harness-version: 0
description: Convert Zero/Relay design specification boards into complete Markdown spec bundles by extracting structure trees,
  all tracked dev nodes (any node whose `devStatus.type` is in {READY_FOR_DEV, COMPLETED, CANCELED, NONE}), semantic classifications,
  screenshots, component-level Markdown descriptions, resource routing, and validation reports. Use when a user gives a Zero/Relay
  design link and wants a fully restored design-spec md package that can later accelerate frontend code generation.
allowed-tools:
- mcp__zero-design__get_design_metadata
- mcp__zero-design__get_design_context
- mcp__zero-design__get_screenshot
- mcp__zero-design__export_image
- mcp__zero-design__use_design_script
- Bash
- Read
- Write
- Edit
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/.agents/skills/zero-spec-to-md-skill-zero/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: Convert Zero/Relay design specification boards into complete Markdown spec bundles by extracting st…
disable-model-invocation: true
---

# zero-spec-to-md

Use this skill to turn a Zero/Relay spec board into a Markdown bundle with traceable source nodes, development-ready containers, screenshots, component-level Markdown descriptions, and validation. The long-term target is fast frontend code generation, but the current deliverable is Markdown descriptions, not frontend code.

Default to lightweight scope scan. Do not return the full Relay node tree unless the user explicitly requests full extraction or a debug audit requires it.

The bundle has three equal content tracks:

1. Full specification text restoration from the whole board.
2. Tracked dev container screenshots referenced from the restored specification (any node with `devStatus.type` in {READY_FOR_DEV, COMPLETED, CANCELED, NONE}).
3. Component Markdown translations for component-like development containers.

Do not treat tracked dev nodes as the only source of truth. They are visual/development anchors inside a broader specification narrative. The bundle preserves the specific `devStatus` of each tracked node so reviewers can distinguish between 待开发 / 已完成 / 已取消 / 无标记 markers.

## Output Contract

Create one output folder per source board:

```text
{slug}/
├── README.md
├── design.md
├── source-text.md
├── rules.md
├── examples.md
├── traceability.md
├── spec.md
├── spec-narrative.md
├── variants.md
├── behaviors.md
├── CHANGELOG.md
├── _structure.md
├── _dev-nodes.md
├── _assets.md
├── naming-review.md
├── visual-naming-review.md
├── _run.json
├── raw/
│   ├── extraction.json
│   ├── scope-audit.json
│   ├── dev-candidates.json
│   ├── dev-context.json
│   ├── text-extraction.json
│   ├── spec-text.json
│   ├── section-map.json
│   ├── spec-page.json
│   ├── rule-map.json
│   ├── example-map.json
│   ├── dev-nodes.json
│   ├── classification.json
│   ├── rename-map.json
│   ├── workflow-state.json
│   ├── review-assets.json
│   ├── final-rename-map.json
│   ├── assets.json
│   ├── asset-url-map.json
│   └── component-md.json
├── components-md/
│   └── {safeNodeId}.md
├── review-assets/
│   └── screenshots/
└── assets/
    └── screenshots/
```

The default authoritative source for the bundle is the lightweight set: `raw/scope-audit.json`, `raw/dev-candidates.json`, `raw/dev-context.json`, and `raw/text-extraction.json`. `raw/extraction.json` is optional and reserved for full extraction / debug audit. `raw/spec-text.json`, `raw/section-map.json`, `raw/rule-map.json`, and `raw/example-map.json` are derived restoration views.

## Stage Gate Policy

This workflow has a mandatory human confirmation gate. The default output is a `draft` bundle. For real naming review, advance to `visual-review`: this allows review screenshots, but still blocks final assets, Relay writes, and final bundle generation.

Allowed stages:

```text
extract
classify
naming_review
visual_review
rename_confirmed
local_sync
assets_export
component_md
final_bundle
validated
```

Hard rules:

- `scripts/build_bundle.py` defaults to `--stage draft`.
- Draft bundles must generate `naming-review.md` and `raw/workflow-state.json`.
- Draft bundles must not write names back to Relay.
- Draft bundles must not export final screenshots unless the user explicitly overrides the gate.
- Visual-review bundles may contain review screenshots under `review-assets/screenshots/`.
- Visual-review bundles must generate `visual-naming-review.md`.
- Draft bundles must not be described as final.
- Final bundles require `naming-review.approved.json` with `{ "approved": true }`.
- Relay name writes require explicit user approval and must be run as a separate step.

## Workflow

1. Parse the Relay URL and decode `node_id`.
2. Run a lightweight scope scan with `use_design_script`: return `scopeAudit`, `devNodes`, and `textExtraction` only. For naming v2, include `semanticAnchors`, `recognitionConfidence`, and `recognitionSource` on every dev node.
   New scans must also include each dev node's root-to-parent `ancestorNodeIds`
   and minimal `ancestorNodes` records. Include semantic `contentBlocks` in
   `textExtraction` when the board exposes reliable paragraph/list/table groups.
3. Save that scan result, then run `scripts/scan_dev_nodes.py --input {scan-json} --bundle {slug}` to create `raw/scope-audit.json`, `raw/dev-candidates.json`, `raw/dev-context.json`, and `raw/text-extraction.json`. Use `--recognition-version v2` only when the scan result includes spatial semantic anchors or should initialize empty v2 anchor fields.
4. Run `scripts/build_bundle.py --stage draft --output {slug}` to generate structure, text restoration, section mapping, classification, `naming-review.md`, and draft Markdown. Use `--naming-version v2` only when you want spatial-anchor naming.
5. Run `scripts/export_review_assets.py {slug}` to create a review screenshot plan. Use `mcp__zero-design__export_image` for each planned node, download the images under `review-assets/screenshots/`, and merge the results into `raw/review-assets.json`. If a file cannot be downloaded locally, keep the exported URL in `externalUrl`, mark the local file as `pending`, and continue with URL mapping.
6. Load `references/visual-naming-policy.md`. Review each screenshot plus `raw/dev-nodes.json`, `raw/review-assets.json`, and `raw/text-extraction.json`; write one item per dev node to `raw/visual-name-suggestions.json`.
7. Run `scripts/apply_visual_name_suggestions.py {slug}` to merge visual suggestions into `raw/rename-map.json`, `raw/classification.json`, and `raw/dev-nodes.json`.
8. If the user uploads correction images, run `scripts/scaffold_uploads.py {slug}` first, have the user place images under `user-uploads/{safeNodeId}/title.png`, write `raw/recognition-overrides.json`, then run `scripts/apply_recognition_overrides.py {slug}`.
9. Run `scripts/build_bundle.py --stage visual-review --output {slug}` to generate `visual-naming-review.md`. Preserve the same `--naming-version` used in draft.
10. Run `scripts/validate_bundle.py --stage visual-review {slug}` and fix naming / suggestion failures before showing the file. Add `--naming-version v2` for v2 bundles.
11. Stop. Show `visual-naming-review.md` to the user and wait for confirmation.
12. If the user approves names, run `scripts/approve_names.py {slug}` or create `naming-review.approved.json` manually. If names are revised, include the approved revisions in that file before continuing.
13. Run `scripts/sync_approved_names.py {slug}` to copy review screenshots to final screenshot names and update `raw/assets.json` / `raw/final-rename-map.json`.
14. If the user explicitly asks to write names back to Relay, use the approved rename map and `use_design_script` as a separate write step. Do not write names during draft or visual-review generation.
15. Re-run `scripts/build_bundle.py --stage final --output {slug}` after local sync so final docs include approved names and final resource routes. Preserve `--naming-version v2` for v2 bundles.
16. Run `scripts/validate_bundle.py --stage final {slug}` and fix failures before handing off.

## Specification Restoration

The restored specification must be more than a resource index:

- `source-text.md` preserves extracted board text in inferred reading order.
- `design.md` is the main restored specification narrative and must include source text, rule candidates, screenshot references, and component-MD links.
- `spec-narrative.md` is the pure-text readable specification. It must not contain image syntax or screenshot links; node ids are centralized in the glossary / appendix instead of interrupting prose.
- `rules.md` contains rule-like text extracted from labels, descriptions, annotations, and section copy.
- `examples.md` contains every tracked dev node (READY_FOR_DEV / COMPLETED / CANCELED / NONE) as a visual example or development container.
- `traceability.md` ties sections, source text, rules, examples, screenshot assets, component Markdown, and node ids together.

If evidence is incomplete, keep uncertainty visible. Do not silently drop text, sections, or development containers.

## MCP Extraction

Load `references/scope-scan-policy.md` first when writing the `use_design_script` scan script. Load `references/mcp-extraction.md` only when full extraction is explicitly needed. The extractor must return JSON only; do not rely on `console.log`.

Key fields:

- `node.devStatus?.type` in {`READY_FOR_DEV`, `COMPLETED`, `CANCELED`, `NONE`} qualifies a node as a tracked dev container. Nodes with no `devStatus` payload are NOT tracked.
- The bundle stores the specific status on each dev record so downstream consumers can prioritize `READY_FOR_DEV`, treat `COMPLETED` as shipped reference, surface `CANCELED` as historical/deferred, and surface `NONE` as explicit no-status.
- `devStatus.mark` is history. Do not treat historical statuses as current; always read `devStatus.type` directly.
- Preserve every node id exactly. Convert node ids to filename-safe form only for asset paths.
- Always return scope audit counts: root node count, root devStatus count, page node count, page devStatus count, and outside-root devStatus count. This prevents root-scope output from being mistaken for page-scope output.
- Default raw files are `raw/scope-audit.json`, `raw/dev-candidates.json`, `raw/dev-context.json`, and `raw/text-extraction.json`. `raw/extraction.json` is optional.
- Preserve `ancestorNodeIds` exactly. Downstream screenshot de-duplication must
  use IDs, never similarly named containers.

## Classification And Naming

Load `references/classification-rules.md` before classifying development nodes.

Default categories:

- `component`: complete reusable component.
- `component-state`: a named state/variant of a complete component.
- `component-part`: reusable part of a component.
- `spec-demo`: explanatory demo group, often with multiple examples.
- `annotation`: measurement labels, guide lines, A/B markers, callouts.
- `asset`: icon, tag, badge, image, or small material item.
- `unknown`: insufficient evidence.

Load `references/naming-rules.md` before writing names back to Relay. Names should be stable, human-readable, and prefixed with `准备开发/` for current development nodes.

Before showing `visual-naming-review.md`, load `references/visual-naming-policy.md` and generate `raw/visual-name-suggestions.json` from screenshots, rule context, and text. Do not show `准备开发/待确认-*` as a user-facing suggested name. If a node remains ambiguous, use `准备开发/未分类-{short label}` and mark `needsHumanReview: true` in the suggestion.

Naming v2 is opt-in. Use `--naming-version v2` when the scan has spatial semantic anchors. v2 name priority is: final approved name > `raw/recognition-overrides.json` user correction > `raw/visual-name-suggestions.json` visual suggestion > `semanticAnchors.primaryTitle + sectionPath` > meaningful Relay name > `textPreview` > node id fallback.

## Asset And Component Markdown Policy

Load `references/component-md-policy.md` before exporting or converting resources.

Screenshot export:

- **All slices must be exported at the expected dynamic scale based on the node's longest side:** `<600 => 3x`, `600-1199 => 2x`, `>=1200 => 1x` for the canonical-visible role. Trace-only / layout-context records default to `1x`. Copy the `mcpArgs.scale` emitted by `export_plan.py` / `export_review_assets.py` verbatim; override only when an upstream consumer explicitly requires a different ratio.
- Every dev node carries `assetRole` (`canonical-visible | trace-only | layout-context`) and `exportTier` (`visible | trace | layout`) populated by `build_bundle.py`. Downstream scripts use these to decide what gets a high-quality export and what may be deferred.
- `export_plan.py` / `export_review_assets.py` accept `--export-mode fast | balanced | full` (default `balanced`):
  - `fast` — only `canonical-visible` records are planned for export; `trace-only` records are written with `status="deferred"` and an `externalUrl` is preserved when available.
  - `balanced` (default) — `canonical-visible` exported at the size-based scale (capped at `--max-long-edge`, default 3600px), `trace-only` exported at 1x.
  - `full` — legacy behavior; every tracked dev node is exported by the size policy.
- All saved screenshot files must end with the matching dynamic suffix: `@3x.png`, `@2x.png`, or `@1x.png`. Files whose suffix or recorded `scale` does not match the dynamic policy are treated as legacy and must be re-exported.
- Export every tracked dev node (READY_FOR_DEV / COMPLETED / CANCELED / NONE) for visual review. In `fast` mode trace-only nodes stay deferred until the user re-runs export with `balanced` or `full`.
- Store review images at `review-assets/screenshots/{safeNodeId}_{slug}_review@{scale}x.png`.
- Store final images at `assets/screenshots/{safeNodeId}_{approvedSlug}@{scale}x.png` only after naming approval.
- Do not create final screenshot assets before `visual-naming-review.md` is confirmed, unless the user explicitly requests a forced export.
- Record export failures in `raw/assets.json`; do not silently omit failed nodes. Each successful asset record must carry the expected `scale` for that node.
- A `trace-only` record with `status="deferred"` is allowed in `final` and does not block the bundle. A `canonical-visible` record with `status="deferred"` is an error — re-run export with `balanced` or `full` to materialize it.
- If a screenshot cannot be downloaded as a local file but `export_image` returned a URL, record the URL as `externalUrl` and map it to the approved name in `raw/asset-url-map.json`. Markdown should reference the local path only when the local file exists/succeeds; otherwise it should reference `externalUrl` so the named asset remains viewable.
- Every Markdown screenshot block must include a visible resource status and a clickable image route. Besides the image syntax, include `图片状态`, Relay node id, local relative path when available, local absolute path when available, `点击打开：[查看图片](...)`, and `externalUrl` when local download failed. This applies to `design.md`, `examples.md`, `components-md/*.md`, `_assets.md`, `traceability.md`, and `visual-naming-review.md`.
- Asset manifests must expose `status`, `localPath`, `absolutePath`, `externalUrl`, `resolvedRoute`, `openLabel`, `scale`, `assetRole`, and `exportTier` so downstream HTML generation never has to guess where an image is or whether it is viewable.

Component Markdown:

- Generate component Markdown for **every** tracked dev node (READY_FOR_DEV / COMPLETED / CANCELED / NONE). There is no category-based skip list.
- Category routes the node to a flavor (`component` / `annotation` / `spec-demo` / `asset` / `review`); flavor selects template and required sections — see `references/md-templates/README.md`.
- Every md file MUST start with a YAML frontmatter declaring `flavor`, `nodeId`, `devStatus`, `category`, `screenshot`, plus `proposedName` / `approvedName` / `sectionId` / `sectionTitle` / `stage`.
- `component` flavor's `Props` / `States` / `Slots` may use `_(待补充)_` placeholders in draft / visual-review stages, but MUST be filled in `final`.
- Each dev node must have component Markdown status: `success`, `failed`, or `pending`. The legacy `skipped` status is removed.
- The component Markdown is an intermediate source for future frontend code generation. Do not claim code has been generated unless a separate code-generation step actually runs.

## Validation

Load `references/quality-gates.md` when debugging validation failures.

Minimum passing state:

- Every tracked dev node (READY_FOR_DEV / COMPLETED / CANCELED / NONE) appears in `_dev-nodes.md` with its specific `devStatus` recorded.
- `raw/scope-audit.json`, `raw/dev-candidates.json`, `raw/dev-context.json`, and `raw/text-extraction.json` exist in lightweight mode.
- `source-text.md` and `raw/spec-text.json` exist and contain extracted board text.
- `raw/section-map.json` exists and every development node has a `sectionId` or explicit `unmapped` state.
- `raw/spec-page.json` exists for final/modern bundles as the downstream page contract. It preserves section order, narrative blocks, canonical image slots, and trace-only covered child nodes so HTML generation does not need to re-infer the visible layout from screenshots.
- When a successful parent dev node only acts as a horizontal container for multiple similar child dev nodes, `raw/spec-page.json` must render the child nodes as grouped `image-slot` blocks and keep the parent as group trace. Use the parent screenshot only for true composite scene boards.
- Non-uniform horizontal section groups follow the same rule: when large child dev nodes are horizontally aligned with similar heights but different widths, render the child nodes as `horizontal-section-slots` and keep the parent as trace-only context. This includes narrow style columns paired with wider scene/example columns.
- Scene overview grids should recurse one level deeper: when a visible slot still contains multiple medium scene/card dev nodes arranged as a grid, render those children as `scene-grid-slots` and keep the overview parent as trace-only context.
- Vertical example lists follow the same rule: when a visible slot is only a column container for multiple medium example dev nodes, render those children as `vertical-example-list-slots` and keep the parent as trace-only context.
- When a horizontal section contains nested split groups, preserve the outer horizontal relationship with `layoutGroupId`, `layoutGroupRole`, and `layoutColumnId` so downstream pages can render left/right columns while still splitting each column internally.
- Grouped `image-slot` blocks should bind nearby external captions when titles live outside the screenshot node. Store `caption`, `captionNodeId`, `captionConfidence`, `captionSource`, and compact `captionCandidates` for traceability instead of silently dropping these labels.
- `design.md` contains a restored specification narrative, not only a route table.
- `spec-narrative.md` exists as a pure-text readable spec. Draft / visual-review bundles warn if it is missing; final bundles fail. It must include `## 总览`, at least one additional section, and no image syntax / screenshot markdown links.
- `rules.md`, `examples.md`, and `traceability.md` exist.
- Draft bundles stop at `naming_review` and include `naming-review.md`.
- Visual-review bundles stop at `visual_naming_review` and include `visual-naming-review.md` plus review screenshot records.
- Final bundles require confirmed names before screenshot export and component Markdown generation.
- Every dev node has either a local screenshot path, an external screenshot URL mapped to the approved name, or an explicit export failure reason. `trace-only` records may carry `status="deferred"` (no local file, no external URL) when export was run in `--export-mode fast`; this is acceptable in `final` and does not block the bundle. `canonical-visible` records must not be deferred.
- `raw/asset-url-map.json` exists in final bundles and maps every dev node to `{ nodeId, approvedName, localPath, externalUrl, resolvedRoute, scale }`.
- Every successful screenshot record has the expected dynamic `scale` and its path ends with the matching `@{scale}x.png`. Mismatched scales fail validation unless `--allow-legacy-scale` is set.
- Every dev node has component Markdown status, file routed to a flavor, and an md skeleton (frontmatter + required `## ` sections) at `components-md/{safeNodeId}.md`. `component` flavor in `final` stage requires non-empty Props / States / Slots. Use `--allow-md-skeleton-warnings` only for legacy bundles.
- Every Markdown resource path points to an existing file unless explicitly marked external.
- Final Markdown outputs must expose clickable image links (`查看图片` or `查看外部图片`) for every tracked dev node so reviewers can open screenshots even when the Markdown renderer cannot inline local images.
- `_run.json` records source URL, root id, page id, counts, warnings, and validation status.

## Recommended Commands

```bash
python3 scripts/scan_dev_nodes.py --input {output}/raw/scope-scan.json --bundle {output}
python3 scripts/build_bundle.py --stage draft --output {output}
python3 scripts/validate_bundle.py --stage draft {output}

python3 scripts/export_review_assets.py {output}        # plan 自动按节点尺寸 + assetRole 写入 scale + @{scale}x 路径
# 加 --export-mode fast  -> 只导出 canonical-visible,trace-only 标 deferred(快、便宜)
# 加 --export-mode full  -> 全部按尺寸导出(回到旧行为)
python3 scripts/apply_visual_name_suggestions.py {output}
python3 scripts/build_bundle.py --stage visual-review --output {output}
python3 scripts/validate_bundle.py --stage visual-review {output}

# naming v2
python3 scripts/scan_dev_nodes.py --recognition-version v2 --input {output}/raw/scope-scan.json --bundle {output}
python3 scripts/build_bundle.py --naming-version v2 --stage draft --output {output}
python3 scripts/scaffold_uploads.py {output}
python3 scripts/apply_recognition_overrides.py {output}
python3 scripts/build_bundle.py --naming-version v2 --stage visual-review --output {output}
python3 scripts/validate_bundle.py --naming-version v2 --stage visual-review {output}

# full extraction fallback
python3 scripts/build_bundle.py --stage draft --input {output}/raw/extraction.json --output {output}
python3 scripts/validate_bundle.py --stage draft {output}

# after user confirmation and asset/component generation
python3 scripts/approve_names.py {output}
python3 scripts/sync_approved_names.py {output}
python3 scripts/build_bundle.py --stage final --output {output}
python3 scripts/validate_bundle.py --stage final {output}
```

Use the workspace Python if available. The scripts depend only on the Python standard library.
