---
name: platform-transaction-shared-foundation
description: 平台交易设计部共享底座索引，按业务线、场域和阶段路由设计任务。
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/platform-transaction/_共享底座/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: during_design
  agentmesh-activation: explicit_only
  short-description: 平台交易设计部共享底座索引，按业务线、场域和阶段路由设计任务。
disable-model-invocation: true
---
# SKILL —— 平台交易设计部 · 共享底座索引 + 路由

> **可执行入口在 `../SKILL.md`（field-design-build）**：PRD/需求 → 四步 → ZERO 设计稿的完整跑法。本文件是共享底座的清单与三跳路由。
> 任何请求三跳定位:**认业务线 → 认场域 → 认阶段**。
> 结构原则:**共享底座定规矩(方法论一份 + 零件读 coding),场域自包含四步(各写各的差异)**。

## 一、先过输入门(必做)

读 `./输入SOP.md`:判输入类型(A 新场域从零 / B 整页生成 / C 局部改动·PRD)、备五项通用输入、过完整性校验门。**任一项缺 → 先追问,不假设默认值。**

## 二、三跳路由

1. **认业务线** —— 本次需求属于哪条线:
   - `../交易链路/`(购物车 / 结算 / 收银台 / 成功页 / 地址)
   - `../店铺/`、`../权益中心/`(占位,待建)
2. **认场域** —— 进该业务线下的具体场域目录,先读该场域 `场域元信息.md` 认边界;新场域则整份复制一个已建空骨架场域(如 `../交易链路/成功页/`)。
3. **认阶段** —— 进入该场域的 `SKILL.md`,按输入类型决定四步起点(A 从①起 / B 从③起 / C 先走改动工作流分类)。

## 三、共享底座清单(全场域引用,勿复制)

**本地维护(方法论):**
- `0-判断标准/judgment-criteria.md` —— 务实/自然/包容/焕新,可勾选自检项(贯穿所有场域所有阶段)
- `输入SOP.md` —— 输入门(判类型/备五项/过校验门)
- `搭建配方.md` —— 克隆 / 实例化 / 从零 三条降级路径
- `AI闭环工作流/` —— 输入校验(任务成立性)→ 改动工作流(结构有效性)→ 交付模板(设计质量+人工校准)→ 规则回流 → 场域标准
- `错误案例总库/` —— 跨场域行为/判断类坑,**执行前先扫命中项**

**读 coding foundation(零件,不在本地维护,见 `coding-foundation读取指南.md`):**
- 设计系统 —— coding `foundations/tokens|设计语言基础|视觉规范/`(material/color/typography/corner-radius/layout/tokens)
- 组件库 —— coding `foundations/基础组件库|业务组件库/` + `场域特性规范/购物链路/<场域>/<组件>/bundle/`
- 资源assets —— coding `foundations/assets/`;场域私有未收录的临时登记在本地 `资源assets/assets.md`
- 交互规范 —— coding `foundations/交互规范/`

## 四、场域内四步(每个场域一致的骨架)

① 确定场域任务(为何而来,不谈视觉)→ ② 建立认知模型(六要素显式化)→ ③ 转译为结构(稳定组织规则)→ ④ 落实设计(调底座 + 写差异)。四步之上贯穿判断标准,之下接 AI 闭环。

## 五、新增场域

整份复制一个已建空骨架场域(如 `../交易链路/成功页/`)到目标业务线下,重命名为场域名,按场域 SKILL 逐步填。通用规范一律引用共享底座 / 读 coding,不复制。
