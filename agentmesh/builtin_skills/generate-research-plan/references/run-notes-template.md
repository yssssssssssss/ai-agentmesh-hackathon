# 《本次运行说明》· 模板（两阶段产出末尾都要附）

> 让使用者知道这份 brief / 方案建立在什么之上、哪里可能不牢。**逐项填实，没有的写「无」。**
> 阶段一就停下（仅出 brief + 待确认清单）时也要附——只是②③④按阶段一实际读到的填。

```
---
## 本次运行说明

**① 调用的正典**（路径 + status）
- methods/standards/requirement-elicitation.md（status: [draft/reviewed/…]）
- methods/standards/research-project-workflow.md（status: […]）   ← 出方案时
- methods/toolbox/collection/[…].md（status: […]）
- methods/toolbox/analysis/[…].md（status: […]）
- methods/scenarios/[…].md（status: […]）                        ← 若用了场景打法
- models/[…].md（status: […]）                                   ← 若用了理论透镜
- [其余按实际读到的列全]

**② 应调用但未找到的内容**（缺的正典 / 空目录）—— 按本次实际遇到的填
- [如：无业务术语库 → 术语对齐降级跳过]
- [如：未找到贴合「XX 主题」的场景打法 → 编排为通用兜底]
- [如：methods/standards/sampling.md 读不到 → 「样本与配额」为通用建议、未背书。⚠️ 仅在确实读不到时才写；若能读到，不要谎报为缺口]
- 无则写「无」

**③ 走空的链接**（related 指向但不存在的文件）
- [如：某正典 related/正文指向 models/kano.md、models/fogg-behavior-model.md、methods/toolbox/analysis/ipa-matrix.md，这些文件不存在]
- [如：撞见指向 sampling.md 的 ⚠️待补充 旧标记，但该文件其实已存在 → 属过时悬挂标记，建议清理]
- 无则写「无」

**④ 基于 draft（未评审）内容的部分**
- [列出哪些段落来自 status: draft 的正典；当前本库依赖多为 draft，方案整体基于未评审规范]

**⑤ 反馈入口**
- 方案/brief 有问题，或正典需补充，请在此反馈：http://xingyun.jd.com/codingRoot/JD_Research_Wiki/Research_Wiki/settings/issues
---
```

填写提醒：

- **①** 只列**真正打开读过**的正典，别把没读的也列上凑数；每条带 `status`。
- **②** 列本次**真正想读却没有**的：空目录、缺失的正典、无贴合场景。**不要预设某个文件一定缺**——以本次实际读取结果为准（例如 sampling.md 现已存在，就不该把它当缺口）。
- **③** 与②的区别：②是"我想读但没有"，③是"某篇正典的 `related:` 指过去、但目标文件不存在"。读正典时留意其 frontmatter 的 `related:`，指向空文件就记这里。
- **④** 当前 wiki 正典基本都是 `status: draft`，所以这条几乎总要写——明确告诉使用者"方案基于未评审规范，结论性规则待规范定稿后复核"。
- 五个部分**一个都不能少**，哪怕内容是「无」。
