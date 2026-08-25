---
name: platform-transaction-address
description: 平台交易设计部地址场域入口，按输入校验和四步方法路由地址设计任务。
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/platform-transaction/交易链路/地址/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: during_design
  agentmesh-activation: explicit_only
  short-description: 平台交易设计部地址场域入口，按输入校验和四步方法路由地址设计任务。
disable-model-invocation: true
---
# SKILL —— 地址 场域路由

> 本文件是「地址」场域的入口路由。上层总路由见 `../../_共享底座/SKILL.md`。
> 原则:**先读共享底座定规矩,再读本场域定差异**;执行前必扫错误案例。

## 固定执行顺序

1. **过输入门** → 读 `../../_共享底座/输入SOP.md`,判类型(A新场域/B整页/C局部)、备五项输入、过校验门。缺输入先追问,不假设。
2. **扫错误案例** → 先看 `../../_共享底座/错误案例总库/` + 本场域 `./错误案例/`,命中触发条件的先规避。
3. **认边界** → 读 `./场域元信息.md`,确认本次改动在本场域范围内、碰哪个内部单元。
4. **走四步**(按输入类型决定起点):
   - 类型 A → 从 `1-确定场域任务/` 起,依次 1→2→3→4。
   - 类型 B → 直接 `3-转译为结构/`(读结构六要素 + 整页试跑配置)→ `4-落实设计/`。
   - 类型 C → 先 `../../_共享底座/AI闭环工作流/改动工作流.md` 做拆分→定位→分类→置信度,命中 `3-转译为结构/主流程边界.md` 的不自动改,再落到 3/4 的局部补丁。
5. **落设计** → `4-落实设计/` 调用 coding foundation(设计系统 `foundations/tokens|设计语言基础|视觉规范/`、组件 `foundations/基础组件库|业务组件库/` 与 `foundations/场域特性规范/购物链路/<本场域>/<组件>/bundle/`、资源 `foundations/assets/`;读法见 `../../_共享底座/coding-foundation读取指南.md`);本场域专属组件在 `4-落实设计/组件/`。
6. **交付 + 回流** → 按 `../../_共享底座/AI闭环工作流/交付模板.md` 五段交付;实测/校准结论按 `规则回流.md` 回写,记入 `./change-log/`,通用坑升级到共享底座错误总库。

## 本场域四步入口

- ① `1-确定场域任务/`  用户为何来到本场域(想清楚,不谈视觉)
- ② `2-建立认知模型/`  用户必须理解什么(六要素显式化)
- ③ `3-转译为结构/`    认知的显性表达(稳定可复用的组织规则)
- ④ `4-落实设计/`      视觉语言的加强引导(调用底座 + 写本场域差异)

验证私有件:`evals/` `ground-truth/` `错误案例/` `change-log/` `experiment/`。
