# ADR 0046：文档解析进程、资源限制与取消

状态：接受（本地 POSIX 生产解析进程与原子导入；文件/网络安全沙箱、旧部分导入修复和外部连接器另行实施）。

原生产解析在有界线程池内直接调用原生 PDF、OOXML 或 OCR 解析器。持久 claim 可以阻止撤权或旧执行者写入，但无法停止已经开始的线程，也无法将原生崩溃与应用进程分开。服务停止可能长时间等待；解析中间分配的资源也早于最终 1 MiB 正文检查。

保留两名线程池协调者、八个排队位置、DocumentParseJob 与现有持久输入/claim，不新增调度系统。生产上传入口使用 `IsolatedDocumentParser`，每个已验证输入创建一个独立 Python 进程与 POSIX session。该进程只运行固定 parser module；不用 shell 或线程环境下不安全的 preexec hook。执行使用当前安装的 Python 和 `-I`，关闭继承的文件描述符，环境仅包含 locale/PATH、明确 OCR 配置、独立 TMPDIR 和禁止 dotenv 加载的标记；API/OAuth/Provider 配置不进入子进程。

解析临时目录为 0700，输入及元数据文件为 0600，名称由服务端固定。持久 `.inputs` 继续先做当前 Job identity/size/hash 校验；子进程拿到校验后的私有临时副本，不接收客户端任意路径。stdin/stdout/stderr 均不回传解析器日志或异常正文。JSON 结果最多 2 MiB，读取拒绝 symlink、非常规文件、超限、非法格式/错误码和 owner 不一致；正文/标题/元数据的现有限制在进程内与父进程再次检查。Source/Document/Memory 身份仍由原子导入服务生成，解析结果中的 Source 不能替换它们。

默认墙钟期限 90 秒。子进程设置 CPU 90 秒、单文件 32 MiB、最多 128 个描述符和禁止 core dump；Linux 额外设置 1 GiB address-space 上限。32 MiB 文件上限允许既有最多 20 MiB 输入的 OOXML/OCR 临时复制，不能将它误写成 2 MiB 结果上限。原生输出的 1 MiB 文本与 JSON 上限继续单独约束。

父进程每最多 100ms 检查取消、期限与解析器/后代 RSS 之和，超过 512 MiB 或发现超过八个后代则停止；监控不可用也停止，不降级为无监控解析。新增 `psutil>=7.2,<8`，当前 lock 固定 7.2.2，提供 macOS/Linux 的当前进程树读取。macOS 不能在本机设置上述 RLIMIT_AS ceiling，所以不能以设置成功宣称它的内存硬上限。RSS 是采样后的主动终止条件，可能在采样间短暂超额，也不是 cgroup 的内存硬上限。

到期、取消、异常、非法结果和正常结束都清理该 session 的进程组，包括可能存活的 OCR 子进程，并等待主 worker 退出；回收等待上限五秒，异常明确失败。临时副本随请求结束移除。该进程分离与资源限制不是文件/网络权限沙箱，原生漏洞的全面权限隔离仍需实际部署的 OS/container policy，不能用临时目录白名单替代。

服务停止立即设置解析取消信号，然后停止队列并等待清理。持久 claim 的每 30 秒续期失败也设置信号；父进程下一次检查中断解析，不再等旧线程自行完成。原子提交仍独立复查当前权限/claim/输入，替换 worker 已完成的导入不能被旧失败覆盖。停止或超限保留既有 failed 与静态原因，持久原始输入在原七天保留期内仍可由本人按现有版本化命令重试；已提交导入继续保持 completed，不从失败分支回滚。

OOXML 在解压前限制最多 4,096 个 ZIP entry、1,000 个正文 XML part、总正文 XML 4 MiB，通过 XML parser 的 `TreeBuilder.doctype` 回调拒绝 DTD/entity 定义。真实子进程测试复现了 UTF-16 绕过字节匹配的缺陷；回调在 XML 解码后检查，UTF-8/UTF-16 均明确失败。PDF 最多 1,000 页，提取时累加正文预算并在关闭文件后退出。超限均明确失败，不悄悄截断为可检索资料。这些检查减少输入膨胀，但不代表所有恶意原生文档漏洞已被消除。

验证记录见 `docs/verification/2026-10-07-bounded-document-parser-processes.json`：真实独立进程解析文本/PDF/Word/Slides；受控 OCR 可执行程序验证图片适配、配置传递与凭据剔除，不冒称真实 OCR 识别质量。另有真实进程超时/取消/内存分配、后代终止、撤权续期中断、失去 claim 后晚返回、非法/超限/异主/symlink/崩溃结果及真实上传 HTTP 原子提交。未验证 Linux 容器运行：本机 Docker CLI 存在，但 daemon 不可连接；不为验收启动用户 Docker 或宣称远程 CI 已通过。API 模型和前端控件不变。

新增 26 项行为场景。最终 Python 3.12/3.13 的 14 组关联回归各 261 passed，耗时 50.73/50.97 秒，均有五个既有 PyMuPDF 警告。Ruff、diff 与 lock 一致性检查通过；没有重跑整个后端、前端或调用真实外部 Provider。

依据：[Python subprocess 文档](https://docs.python.org/3/library/subprocess.html)、[Python resource 文档](https://docs.python.org/3/library/resource.html)、[ElementTree DTD 回调](https://docs.python.org/3/library/xml.etree.elementtree.html#xml.etree.ElementTree.TreeBuilder.doctype)、[Apple getrlimit 文档](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/getrlimit.2.html)、[psutil 官方 API](https://psutil.io/)。

完整上下文/累计成本、通用 Source 生命周期、旧输入证明和部分导入的人工修复、Session/Runner 交付、连接器、过程复用及真实模型/企业试点继续按主方案推进，阶段 3–5 不据此整体完成。
