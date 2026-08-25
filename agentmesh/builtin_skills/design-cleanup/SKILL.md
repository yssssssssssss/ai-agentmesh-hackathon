---
name: design-cleanup
description: 清洗并验收准备交付或入库的 Zero/Relay 设计稿。当用户提供 Frame、含多个界面的 Section 或当前多选界面，需要清理隐藏图层、透明噪音、空节点、关闭的 Fill/Stroke/Effect，或排查清洗残留、completed
  误报、clone 视觉差异、失败副本核验时使用。只在本轮新副本上清洗，源 Frame 与存活实例分支不改，逐界面产出可点击的清洗副本或待核验副本。
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/search-recommend-foundation/skills&tools/design-cleanup/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: 清洗并验收准备交付或入库的 Zero/Relay 设计稿。当用户提供 Frame、含多个界面的 Section 或当前多选界面，需要清理隐藏图层、透明噪音、空节点、关闭的 Fill/Stroke/E…
disable-model-invocation: true
---

# Design Cleanup

用于设计完成后的交付稿和 AI 设计资产入库前清洗。用户可以提供一个 Zero/Relay **Frame**、一个包含多个界面的 **Section**，或选中多个 Frame；Skill 先解析出最外层界面 Frame，再为每个界面在同一页面原生创建独立副本，自动删除不影响当前视觉和结构的噪音，并输出中文结果。

## 第一原则

设计完成稿中，不生效且不影响当前视觉、布局、交互或图形结构的内容默认删除。只有存在明确作用时才保留。

## 输入与边界

- 接受 Relay URL；URL 中读取 `fileKey`、`page_id` 和 `node_id`。`node_id` 可以指向一个 `FRAME` 或 `SECTION`。裸节点 ID 只在当前文件与 Page 已由同轮 Zero 回执明确时接受，否则返回 `incomplete`，不猜文件或页面。
- 用户说“清洗当前选择”时，读取目标 Page 的 `selection`；选择中只接受 `FRAME` 与 `SECTION`，其他节点进入拒绝清单，不把 Group、Component 或 Instance 内部的 Frame 猜成界面。
- `SECTION` 按文档顺序向下识别最外层 `FRAME`：一旦遇到 Frame 就把它视为一个完整界面并停止向其内部继续找 Frame。因此界面里的布局 Frame 不会被拆成独立稿件；Section 中经普通 Group 包裹的最外层 Frame 仍能识别。
- 多选与 Section 展开结果按节点 ID 去重；若同时包含父 Frame 与其内部子 Frame，只保留父 Frame，并在 `excludedNestedFrameIds` 报告被折叠的子 Frame。
- 若没有解析出任何界面 Frame，返回 `incomplete` 且零写入。不会复制 Section 或 Page，不遍历重建节点，不修改源 Frame。
- 一轮批量请求为每个解析出的源 Frame 创建一个全新副本；每个 Frame 使用独立 `runId`、独立保真判定、独立清洗与独立最终状态，不修改历史清洗副本。
- 只把本轮返回的 `copyRootId` 视为本轮结果。不得把页面中已有的“清洗副本”当成本轮结果，也不得用旧节点 ID 证明新规则已生效。
- 若本轮在 clone 保真、候选一致性、写入或终验阶段停止，把本轮副本标记为待核验并保留，明确报告“本轮没有最终清洗副本”；不得删除证据或指向历史副本冒充成功结果。
- Skill 版本自动清洗，不要求用户逐项确认。确认流程留给后续 Zero 插件。
- 所有 Zero 读写通过 `zero-design/use_design_script` 完成。每次调用前加载当前内置 `use-design-script/SKILL.md`、Relay Plugin API index；涉及具体字段时继续核对 d.ts 与 gotchas。
- 实际传给 `use_design_script` 的代码必须由 `scripts/generate-zero-live-call.mjs` 生成并原样执行。禁止 agent 临场重写树遍历、证据派生、候选、分批、复读或失败清理逻辑。
- 生成器只开放 `runId/phase/targetMode/fileKey/pageId/sourceRootId/copyRootId` 和阶段必需回执字段；每次调用先核对当前 `relay.fileKey` 与实例子树读取开关，脚本超过 49,800 UTF-8 bytes 时停止，不自行压缩或删减验证。
- 读取设计稿前先确认当前 Codex 任务已暴露 `zero-design/use_design_script`。如果工具不存在，不尝试 clone，直接返回 `incomplete`，说明“Zero Design 通道未注入当前任务”。若通道是在当前任务创建后打开，新建 Codex 任务后再运行。
- clone 脚本只执行一次原生 `FrameNode.clone()`；不创建第二个诊断副本，不把失败副本修补成成功副本。

## 不适用场景

以下情况不要使用本 skill：

- 仍在编辑、尚未定稿的草稿——清洗面向"已完成、准备交付或入库"的稿件；
- 希望直接修改源 Frame 本身——本 skill 只在新副本上操作，从不改源稿；
- 非 Zero/Relay 文件，或当前任务未注入 `zero-design/use_design_script`；
- 期望视觉重设计、改版式/配色/内容——本 skill 只删不生效的隐藏、透明、空节点、关闭样式噪音，不改可见结果；
- 期望图层重命名、层级结构整理、组件/变量规范化、跨平台适配或交付检查——这些属于 Ready Rename / Ready Structure / Design System Compliance 等其它 skill，不在本 skill 范围。

## 原生 clone 与稳定性确认

字体、图片和实例本来就是设计文件的一部分。原生 clone 直接复用这些资源引用，不加载、不重载、不改写。

`relay.loadFontAsync()` 只在**编辑文本**（设置 `fontName`/`characters` 等）时才需要，且它只是把文件里已有的字体载入插件运行时，不做网络下载。本 Skill 只做 `FrameNode.clone()`、`appendChild`、`node.remove()` 和关闭样式数组过滤——没有任何一步编辑文本，因此全流程不调用 `loadFontAsync`，也不收集 `getRangeAllFontNames()` / `fontName` 做字体准备。这既是最短路径，也避免个别文本节点字体证据异常（例如 `getRangeAllFontNames` 返回空条目而 `fontName` 本身合法）阻断整帧复制。

标准流程同样不调用 `getImageByHash().getBytesAsync()` 预热图片，也不调用 `getMainComponentAsync()` 预热实例；不为字体、图片或实例做任何“重载/改写”修补。

clone 后先取得一次未清洗副本截图，并按用户可见结果而不是像素绝对相等分级：

- `matched`：文字、图片、图标、布局和整体视觉一致，直接进入清洗扫描。
- `non_material_variance`：只有局部抗锯齿、阴影边缘或极小栅格差异，没有文字、图片、图标、布局、节点数或根边界变化；记录差异后继续清洗，不得把像素绝对相等当作前置条件。
- 首次疑似出现实质差异：不写入、不修补、不重新 clone；只对同一个副本做一次只读复读和稳定性确认截图。
- 第二次确认存在文字、图片、图标缺失、布局变化或其他实质可见差异：停止清洗，把副本改名为 `保真失败待核验｜runId｜原名称`，输出 `blocked_clone_fidelity` 并提供副本链接。
- 第二次仍无法可靠判断差异是否实质：停止清洗，把副本改名为 `保真待确认｜runId｜原名称`，输出 `incomplete` 并提供副本链接；不得用“更稳妥”为由删除副本。

只读复读仅确认副本根仍存在、节点数与边界可读，不做全树路径映射。条件性第二次截图不是 clone 或写入重试；同一运行最多两张未清洗副本截图。生产 `scan/apply_next_batch` 必须携带 `cloneFidelity=matched|non_material_variance`；后者还必须携带简短差异说明，禁止继续使用无语义的 `cloneFidelityApproved=true`。

需要平台诊断时，只读汇总图片引用数、可解析图片数、实例数和效果数；这些数据用于定位，不作为修补副本的依据。失败副本默认保留；只有用户明确指定副本并要求清理时才调用 `discard`。

## 清理规则

| 对象 | 行为 |
| --- | --- |
| 普通 `visible=false` 图层 | 自动删除；只删除最外层隐藏根节点 |
| `opacity=0` | 无结构作用时自动删除 |
| 明确空节点或空容器 | 无视觉内容且无结构作用时自动删除 |
| Fill/Stroke/Effect `visible=false` | 从存活普通节点中移除；同一节点整体过滤并回写数组 |
| `INSTANCE` 及其全部后代 | 不直接删除、不修改、不打散；存活实例分支完全跳过 |
| 最外层普通 `visible=false` 根包含实例后代 | 清洗优先，连同整棵隐藏子树整体删除；不单独操作其中实例 |
| `opacity=0` 或空祖先包含实例后代 | 保留，避免在非 hidden 情况下间接删除实例 |
| 文件级本地样式 | 当前 Frame 清洗不检测、不删除；回执固定返回 `fileStyleCoverage.status=not_assessed`，不伪造“未使用”或“重复”结论 |

普通 hidden 不因 Auto Layout、组件属性引用、交互未知、引用未知或包含实例而保留。最外层普通 `visible=false` 根即使包含实例也整体删除；这是“存活实例分支不直接处理”的唯一例外。直接选中 `INSTANCE` 或位于实例内部的 hidden 仍完全跳过。

`opacity=0` 和空节点仅在以下情况保留：

- 位于 Auto Layout 流中且承担尺寸或占位；
- 已知是交互或点击热区；
- 是蒙版或布尔运算组成部分；
- 包含实例后代。

## 执行流程

真实 Zero 的原生字段、Adapter 派生字段、固定 JSON 回执、写预算和恢复流程见 [Zero 执行与证据映射](references/zero-execution.md)。缺少其中任一必需字段时按无法验证处理，不由 agent 临场猜测。

1. 检查 `zero-design/use_design_script` 已注入当前任务，为本轮生成批次 ID。先用生成器 `resolve_targets`：URL/节点入口使用 `targetMode=node`，当前多选入口使用 `targetMode=selection`；只接受回执中有序、去重后的 `sourceFrameIds`。
2. 为每个源 Frame 派生独立 `runId`，依次完成本节后续流程。批次中的每个 Frame 都必须产生自己的可点击正式副本或待核验副本；单个 Frame 失败不隐藏、回滚或冒充其他 Frame 的结果。
3. 对当前 Frame 用生成器 `preflight` 只读获取源 Frame、所在 Page、完整节点数和截图。
4. 用生成器 `clone` 阶段直接调用一次 `FrameNode.clone()`；不加载字体、不预读图片、不解析实例。副本放到同一 Page 现有内容右侧约 120px，执行期间命名为 `清洗处理中｜runId｜原名称`。
5. 保存未清洗副本截图并按 `matched / non_material_variance / material_mismatch / uncertain` 分类。前两类进入清洗；后两类用生成器 `mark_failure` 标记并保留副本，返回可点击链接，不得进入清洗。
6. clone 达到 `matched` 或 `non_material_variance` 后，把该值原样传入生成器 `scan`；`apply_next_batch` 必须沿用同一值和说明。不要复用历史扫描、旧副本节点 ID、调用方传入的候选子集或删除前缓存。
7. 统计实例根和实例分支节点。实例自身与实例内部节点不生成直接动作；收集全部最外层图层删除候选，其中普通 `visible=false` 根可连同实例子树整体删除。若一个可执行删除根包含其他可执行候选，只保留最外层原子删除根，后代不得再次进入批次。
8. 自动选择当前完整扫描中的全部可执行候选。每次 `apply_next_batch` 只携带上一回执完整、有序的候选 ID 集合；集合不完全一致时不执行部分清洗。子树和关闭样式内容不跨调用重复搬运，而是在当批当前真实树中重新派生并验证，避免证据载荷阻断生产脚本。
9. 删除批次按持久写成本最多使用 200 次正常写（放宽后的写预算，足以让单帧一次批次清完；安全性来自每写后的根级复读 + 子树抽样,与预算大小无关），并预留失败副本改名的写；先验证每个待删根的完整子树身份及双向父子关系，然后删除。每批后对每个删除根复读子树 `[首,中,末]` 三个节点 ID(子树 ≤3 时全查);任一仍存在即停止并保留待核验副本。
10. 删除候选清空后，从存活副本完整树重新扫描关闭样式；样式批次按 `fills/strokes/effects` 实际 setter 数计费，同样受 200 写预算约束，再复读对应数组。
11. 用生成器 `finalize` 重新读取源 Frame 和副本完整树，执行最终零残留扫描并获取清洗后截图。全部硬门通过后才把名称改为 `清洗副本｜runId｜原名称`；finalize 回执丢失时以该身份幂等复读，不重复写入。
12. 批次结束后按 `sourceFrameIds` 原顺序汇总每个 Frame 的状态与链接。批次可以是“部分完成”，但不得把部分完成写成全批 `completed`；只有每个 Frame 都为 `completed` 时，批次状态才是 `completed`。

不要为一次清洗新增本地 Writer、Hash、JCS、授权信封、百分比 Gate、状态机、自动重试或逐动作回滚。

## 高效模式：one-shot 单次注入与事后保真

per-phase 流程把每帧拆成 preflight→clone→scan→apply→finalize 多次 `use_design_script` 调用，每次都重新注入约 42KB 的 Core，成本高、易受 agent 上下文限制影响。生成器新增 `oneshot` phase，把整条链路收进**一次调用**：给定一个源 Frame，脚本内联 Core 一次，在 VM 内部完成 clone→scan→（多轮 apply，受 200 写预算约束）→finalize，返回该帧最终回执（`completed / incomplete`）。脚本体积恒定（约 46KB），与候选数量无关。

- **优先用 `oneshot` 做批量**：先 `resolve_targets` 得到有序 `sourceFrameIds`，再对**每个** Frame 各调用一次 `oneshot`（一帧一调用，原子、可靠）。不要把整段几百次写塞进一次调用——实测单次调用有规模/时间上限，整段一次会中断。
- **事后保真（必须执行，命名强制不误判）**：VM 内无法 `get_screenshot`，`oneshot` 只做结构清洗（源不动、只删不可见噪音，故安全），完成后把副本命名为 `清洗待核验｜runId｜原名` 并返回 `status=awaiting_fidelity` + `needsPostHocFidelity:true`——**在保真确认前它绝不叫「清洗副本」**，因此不可能被误当成品。调用方必须对该帧源与副本各截一次图比对，再调用生成器 `confirm_fidelity`（带 `fidelityVerdict`）定名：`matched`/`non_material_variance` → 改名 `清洗副本｜runId｜原名`、返回 `completed`；`material_mismatch` → 改名 `保真失败待核验`、返回 `blocked_clone_fidelity`；`uncertain` → 改名 `保真待确认`、返回 `incomplete`。源始终未变。
- **保真截图参数（关键、影响正确性）**:两次截图(源 + 副本)都必须传 `contentsOnly:true`,把画布上覆盖其上的 connector 等排除,避免假阳性;`maxDimension` 依副本 `original_width` 自适应,大帧(>1500px)传 ≥2048、超大帧(>4000px)传 ≥3072,避免默认 1024 把小差异降采样吞掉。这两张截图可**并发发起**(两个 `get_screenshot` 同 turn 内发)缩短墙钟。
- `oneshot` 的内部安全门与 per-phase 完全一致:unresolved 候选、写入/复读失败、最终仍有可执行残留或源节点数变化 → 返回 `incomplete` 并把副本标记为待核验,绝不冒充 `completed`。
- **删除后复读采用「根 null + 抽样 3」**(速度优化):`FrameNode.remove()` 对子树原子生效,复读只对子树 `[首,中,末]` 三个 ID 做 `getNodeByIdAsync===null` 验证,子树 ≤3 节点时全查。安全网仍由 finalize 完整重扫 + 源节点数守恒 + 事后截图门兜底;单次 oneshot 内的 async 调用可数量级下降。

## 最小写入检查

每批执行前只确认：

- 目标仍存在并位于本轮副本内部；
- 图层删除目标仍满足对应规则；
- 目标不是源 Frame、副本根、`INSTANCE` 或实例后代；
- 普通祖先包含实例后代时，仅当目标是最外层 `visible=false` 根才允许整体删除。
- 完整快照中的节点 ID 全局唯一；待删根的全部后代身份完整，`children` 与 `parentId` 双向一致；关闭样式所在节点身份不完整时生成无法验证候选，不能静默跳过。

原生 clone 出现实质差异或无法判断，候选选择不完整，任一写入批次失败，或最终扫描仍有可执行残留：立即停止，把本轮副本改名为对应的“待核验”副本并保留，不重试 clone 或任何写入，不继续后续批次。源 Frame 不需要恢复，因为它从未成为写入目标。

只读复读和截图不得借机修改副本内容。任何字体预加载、图片字节预读、Fill 重写修补、节点重建、实例打散/重解析或重复 clone 都不属于本 Skill。

## 完成标准

只有同时满足以下结果才输出 `completed`：

- 源 Frame 节点数和截图未变；
- 未清洗副本与源 Frame 没有文字、图片、图标、布局或其他实质可见差异；允许已记录的局部非实质渲染差异；
- 所有实际删除目标复读后不存在；
- 最终扫描来自写入后的完整存活副本树，不复用删除前候选或调用方候选子集；
- `remainingExecutableCandidates=[]` 且 `unresolvedCandidates=[]`；最终扫描仍有可执行残留或无法验证的候选时必须输出 `incomplete`。任何仍可删除的普通 hidden、无结构 `opacity=0`、明确空节点或关闭样式都属于可执行残留；
- 普通区域没有未解释的 hidden。最外层普通 `visible=false` 根即使包含实例也属于可执行残留，不得以“实例保护”排除后再报告残留为 0；
- 存活普通节点没有 `visible=false` 的 Fill、Stroke、Effect；
- 存活实例根、实例后代及实例内部样式未改变；随最外层 hidden 根删除的实例子树已明确计入删除结果；
- 清洗副本前后没有实质可见变化；局部非实质渲染差异必须明确记录；
- 文件级样式明确标注为 `not_assessed`，说明当前不检测、不删除。

## 中文结果格式

```text
批次结果：completed / partial / incomplete
- 输入方式：node / selection；解析源 Frame：{sourceFrameIds}
- 折叠的嵌套 Frame：{excludedNestedFrameIdsOrEmpty}
- 拒绝的选择：{rejectedSelectionOrEmpty}

界面 {index}/{total}
- 清洗结果：completed / blocked_clone_fidelity / incomplete
- 源 Frame：{sourceRootId}，未修改
- 本轮副本：{copyRootId} / {relayNodeUrl}；不得复用历史副本
- clone 保真：matched / non_material_variance / material_mismatch / uncertain；{differenceNote}
- 删除图层：{deletedRootCount} 个根候选；连同子树减少 {deletedNodeCount} 个节点
- 移除关闭样式：Fill {fillCount} / Stroke {strokeCount} / Effect {effectCount}
- 实例处理：存活跳过 {survivingInstanceRootCount} 个实例根、{survivingInstanceNodeCount} 个实例分支节点；随 hidden 根删除 {removedInstanceRootCount} 个实例根
- 规则保留：{keptItemsAndReasons}
- 可执行残留：{remainingExecutableCandidateIdsOrEmpty}
- 无法验证候选：{unresolvedCandidateIdsOrEmpty}
- 普通区域残留：{remainingNoise}；不得排除当前规则要求删除的 hidden 根
- 前后截图：{beforeScreenshot} / {afterScreenshot}
- 文件级样式：not_assessed；当前不检测、不删除
```

`blocked_clone_fidelity` 必须明确写出两次未清洗副本截图确认的实质可见差异、已保留的 `保真失败待核验` 副本 ID 和链接、源稿未变及“本轮没有最终清洗副本”。该状态不填写清洗删除或样式移除数量，因为清洗从未开始。

`incomplete` 必须列出无法判断的保真差异、候选不一致、批次失败或最终复扫残留的节点 ID，保留并链接本轮 `保真待确认` 或 `清洗失败待核验` 副本，并明确“本轮没有最终清洗副本”。不得把页面中的历史清洗副本当作本轮交付。

仓库内 `src/` 是生成到真实 `use_design_script` 的同源规则与 Adapter；`scripts/generate-zero-live-call.mjs` 是唯一生产入口；`fixtures/` 和 `tests/` 负责离线回归。真实完成仍必须以 Zero 新副本写入、复读和截图为准。上线前的端到端验收基线见 [黄金评估场景](references/eval-scenarios.md)。
