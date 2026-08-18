# PRD 可行性分析(prd-feasibility)

> 设计**前**的 PM 视角评估工具 · 独立 skill
> 维护:leixiaoming3 · 最近更新:2026-07-16
> 沉淀来源:[JoySpace · 设计分析类 Skill 使用教程](https://joyspace.jd.com/pages/27qhyKA2mO0i5XI1LTMO)

## 一句话

拿到 PRD → 从产品视角评估"业务逻辑是否合理""方案是否 OK""上线后哪些数据会涨/跌",输出可分享 HTML 报告。

## 什么时候用

- 评审一份新 PRD,想判断要不要做、怎么做
- 拿到方案想找业务硬伤 / 优化空间
- 需要给决策层一份"上线后数据涨跌预估"

## 什么时候不用

- 想找测试用例 / 边界 case → 用 `req-review`
- 已经上线在跑 AB → 用 `design-abtest-analysis`

## 常用触发语

`PRD 评审` `可行性分析` `方案评估` `prd-feasibility` `业务硬伤` `双方案对比`

## 主要产出

- 业务逻辑硬伤识别
- 方案逐步评估(高保真流程图)
- 双方案对比(保守 A / 积极 B)
- 上线后数据涨跌预估
- 专题探讨 + 整体结论
- 可分享单文件 HTML 报告

## 文件说明

- `SKILL.md` —— skill 主入口,给 AI agent 用的定义与工作流
- `examples/` —— 案例(如 `case-1-redbag.md`)
- `templates/` —— HTML 报告模板 + 截图裁剪脚本

## 本地安装

```bash
cp -R prd-feasibility/ ~/.claude/skills/prd-feasibility/
```

---

_首次入库:2026-07-16 · leixiaoming3_
