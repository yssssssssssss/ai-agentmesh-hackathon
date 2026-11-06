# ADR 0036：当前项目市场读取范围

状态：接受（市场读取；发布来源和模型等待期间的授权另行开发）。

旧市场 status、board、me 和 activity 遍历整个数据库的用户、信号和匹配审计；当前登录并不限定项目。四个真实 API 均复现其他 workspace/项目的主题、姓名或数量泄漏。新 MarketReadSnapshot 在一次只读事务中读取当前持久 User 的 default Project，检查 active 身份、项目、workspace 和成员关系，再在 SQL 中筛选可见记录。

信号必须具有明确 metadata workspace/project、project scope、project_visible permission 和 published 状态，且 signal owner 当前仍是 active 项目成员。旧缺少项目证明的信号不跟随 owner 的当前默认项目移动。匹配审计要求明确 workspace/project、双方当前 active 同项目成员及不同身份。Scout 的信号分页与 fingerprint 使用同样的显式范围要求，新增匹配审计保存信号项目，不推断为请求方当前默认项目。

同次读取最多解码 200 位成员、200 条信号和 200 条匹配；参与者 ID 也只装载该 roster。SQL 聚合给出完整授权范围内的信号/匹配/参与者数量及本人 received/given 总计，授权数量仅为本人当前项目的有效 grant。个人 Memory 数量仅统计本人当前 workspace、当前项目或无项目、private、active 且未归档记录。图的 ties/边来自最近匹配窗口，不称为完整历史图。board 最多返回 30 条匹配，activity 40 条，个人 timeline 200 条。

公开 worker 状态只保留运行状态、间隔和最近运行时间。队列数量/静态错误限定当前本人/workspace/project，不投影整个进程的 last_published/last_triggered 或他人错误。个人 timeline 不再读取共享 match 帖的正文或以旧 Inbox 猜出确认动作；实际答案/确认/采用沿 ADR 0034 的受限 Query。排序按真实时间，重复匹配使用 event ID 作为 activity 身份。

界面说明当前项目和最近窗口，将匹配记录与实际答案状态区分，并将 grant 数量标为“我的有效授权”。不引入图数据库、全局缓存或另一套任务事实。

最终市场/持久代答/隔离专项 Python 3.12、3.13 各 106 passed。前端 234 passed / 46 files，生产构建和 bundle 检查通过，最大 chunk 322,377 bytes。此前 2,356 项双版本全量快照先于本切片，不能声称覆盖本次修改。具体 RED、开发纠正和边界见 `docs/verification/2026-10-06-current-project-market-reads.json`。

本切片不证明自动发布的私有来源选取、原生来源撤回、模型等待期间 opt-in/项目变化或统一 SDK 预算已经修正；这部分继续开发。真实企业连接器、模型质量和完整阶段 3/4/5 保持未完成。
