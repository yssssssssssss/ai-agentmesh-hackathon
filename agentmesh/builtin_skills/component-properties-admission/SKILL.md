---
name: component-properties-admission
harness-version: 0
description: Admit and validate 商详大脑组件库 Properties 属性数据 for `component-properties.json`. Use when the user mentions 属性数据准入,
  Properties 准入, 组件属性录入, 为商详大脑组件补属性, 针对此模块数据准入, or asks to add/update/review component Properties content for the Product
  Detail Brain component library.
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/.agents/skills/component-properties-admission/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: Admit and validate 商详大脑组件库 Properties 属性数据 for `component-properties.json`. Use when the user menti…
disable-model-invocation: true
---

# Component Properties Admission

Use this skill to admit component Properties data into 商详大脑组件库. The target data file is:

`jd-design-system-md-v16/product-architecture/huangliu-design/product-details/JD-ProductDetails-web/brain-frontend/public/design-schema/component-properties.json`

The page reads entries by component `instanceId`. Existing examples include `bottomBar` and `mindCap`.

## Workflow

1. Identify the component `instanceId`.
   - Prefer the exact `instanceId` from the component library, such as `bottomBar` or `mindCap`.
   - If the user only gives a Chinese component name, search `public/design-schema/instances.json` for the matching `standardName` and confirm ambiguous matches before editing.

2. Gather the required admission content.
   - Component display name.
   - Component English `name` / `moduleName` for generated JSX.
   - `importPath`.
   - Top-level `description`.
   - Properties list grouped by `required: true` and `required: false`.
   - For each property: `name`, `label`, `type`, `description`, `required`, and `control`.

3. Write or update only the matching top-level object in `component-properties.json`.
   - Do not rewrite unrelated component entries.
   - Preserve existing entries unless the user explicitly asks to change them.
   - Use Chinese for user-facing strings: `displayName`, `description`, `label`, option labels, and property descriptions.
   - Keep field names and enum values stable in English for code generation.

4. Validate the JSON and schema shape.
   - Run `node .agents/skills/component-properties-admission/scripts/validate-component-properties.mjs` from the repository root.
   - Fix all reported errors before responding.

5. Validate the app.
   - Run `npm run build` inside `jd-design-system-md-v16/product-architecture/huangliu-design/product-details/JD-ProductDetails-web/brain-frontend`.
   - If the user asks for visual verification, open local 商详大脑 and inspect the target component’s `属性` tab.

## Required Entry Shape

```json
{
  "instanceId": {
    "name": "ComponentName",
    "displayName": "中文组件名",
    "moduleName": "ComponentName",
    "importPath": "@jd/product-detail/ComponentName",
    "category": "Action",
    "description": "中文说明",
    "pkg": "JD Product Detail Brain",
    "pkgVersion": "draft",
    "props": []
  }
}
```

`instanceId` is illustrative; the real top-level key must be the component instance id.

## Property Shape

```json
{
  "name": "fieldName",
  "label": "中文字段名",
  "type": "string",
  "description": "中文字段说明",
  "required": true,
  "default": "'default'",
  "control": {
    "type": "text",
    "default": "默认值",
    "placeholder": "value"
  }
}
```

Supported controls:

```json
{ "type": "text", "default": "默认文案", "placeholder": "value" }
```

```json
{
  "type": "select",
  "default": "default",
  "options": ["default", "active"],
  "optionLabels": {
    "default": "默认",
    "active": "高亮"
  }
}
```

```json
{ "type": "boolean", "default": true }
```

## Admission Checklist

Before final response, confirm:

- The top-level key matches a real `instanceId`.
- All user-facing strings are Chinese where practical.
- Every prop has `name`, `label`, `type`, `description`, `required`, and `control`.
- Select controls include `options` and Chinese `optionLabels` for every option.
- Boolean controls use boolean defaults, not string defaults.
- `component-properties.json` remains valid JSON.
- The validator script passes.
- The frontend build passes.
