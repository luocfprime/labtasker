# Labtasker v1 → v2 功能与重构对照

本文件只用于快速查看迁移取舍；完整且权威的用户语义在
`LABTASKER_V2_SPEC.md`。任何实现者或新会话都应能只读 spec 理解已决定的
contract；本表与 spec 冲突时以 spec 为准并同步修正本表。

状态说明：

- **2.0.0 initial release**：首个可用版本必须完成。
- **后续**：保留设计空间，但只有出现实际需求才实现。
- **删除**：明确不迁移。
- **保留**：用户语义基本不变，内部实现重写。

## 1. 安装、包与部署

| 项目 | v1 | v2 2.0.0 | 后续计划 | 取舍 |
|---|---|---|---|---|
| Python 包 | client、server、共享模型混在 `labtasker` | monorepo 发布 `labtasker` client 与 `labtasker-server` 两个包 | 有真实公共复用需求时再评估 `core` 包 | client 不安装 FastAPI、SQLAlchemy 等 server 依赖 |
| 首发版本 | v1 `1.0.1` | 两个 distribution 同步发布 `2.0.0`，但运行时不要求 exact package match | 后续按 SemVer/API compatibility 发布 | breaking product/API generation 与 package major 对齐，不再把首发称作 0.1.0 |
| 版本管理 | 单包版本，import 时检查 PyPI | 两包初期同步版本；HTTP 使用 `/api/v2` 协议版本 | 独立发布节奏出现后再解耦版本 | 删除 import 联网检查 |
| 默认部署 | MongoDB 服务或 mongomock embedded | 单进程 server + SQLite 文件 | PostgreSQL、多进程仅在规模需要时增加 | 优先个人和单机实验 |
| Docker | Compose 同时启动 API 与 Mongo replica set | 非必需；`labtasker-server serve` 可直接启动 | 可提供可选容器镜像 | 不让本地使用依赖 Docker |
| Server CLI | 多项部署/Worker相关配置分散 | 仅 `serve --host --port --database PATH`；默认 `127.0.0.1:8000` + `.labtasker/server.db`；token 仅 `LABTASKER_SERVER_TOKEN` | 多进程/PostgreSQL 真有需求后另行设计 | SQLite path 而非假想通用 URL；无 reload/workers/daemon/log-level/token flag，监督交给外部 |
| Python 版本 | `>=3.10`，文档存在漂移 | `>=3.11`，CI 与文档统一 | 随受支持 Python 生命周期升级 | 减少兼容矩阵 |

## 2. 核心对象与数据模型

| 项目 | v1 | v2 2.0.0 | 后续计划 | 取舍 |
|---|---|---|---|---|
| Queue | 持久实体；名称、密码、metadata | 保留为唯一 Task namespace 与统一调度池，但 public model 只有 `name`；fresh DB 创建 `default` | 按需增加配额或归档 | 不增加 Project；submit 不隐式创建 Queue，也不预付 description/count/timestamp 等字段 |
| Queue API | create/get/list/delete 及较重响应模型 | 仅 create/list/delete；分别返回 Queue、非分页 JSON array、None/204；无 item get | 有真实 Queue metadata 后再考虑 get | name-only 资源没有额外内容可 get；删除冗余端点和方法 |
| Task | 大型 Pydantic 模型，混合存储与 API 字段 | 明确区分数据库模型、HTTP schema、client model | 仅按实际需求增加字段 | server/client 不共享 Python model |
| Worker | 持久实体 + Worker FSM + retries | 删除 Worker 实体、worker ID/name/status/resources/process heartbeat/restart counter | 真有 worker 运维需求时重新设计 registry | Task 内的 active `run_id`/heartbeat 足以保障当前执行归属，但不假装表示进程在线状态 |
| Worker process lifecycle | loop/process 与 server Worker FSM 混合 | 一次 decorated-function invocation 或 `labtasker loop` 是一个专用本地 Worker；一次只执行一个 Task，固定模型/参数跨 Task 复用 | 无 | server 不保存进程生命周期；单个 run 失效只撤销当前执行 |
| Single-node torchrun/Accelerate | launcher 在外层时每个 rank 都可能启动 loop 并领取不同 Task；heartbeat/context 边界不清 | Labtasker command Worker 在外层，一次 claim 启动一次 launcher；仅父进程 heartbeat，launcher process group 是一个 command child；pre-claim 拒绝 nested loop 和已识别的多-rank 环境 | persistent multi-Task distributed Python Worker 仅在真实需求出现后重设 | 用进程树自然表达一个 distributed experiment，不增加 rank/Worker/resource Server 实体或隐式协调协议 |
| Launcher fork/exec | heartbeat thread、HTTP state 与 launcher 子进程继承边界未形成契约 | fork child 只有 calling thread，随后 exec 替换为 launcher；关闭无关 FD、只传 stdio/PTY，不使用 Python `preexec_fn`；ranks 从 post-exec launcher 产生 | 无 | 地址空间可以短暂复制，但运行中的 heartbeat thread 不会被复制，更不会随 exec 保留 |
| Distributed result | 多 rank 可能共同继承 client 能力，缺少单一 reporter 契约 | 用户通过 `torch.distributed.get_rank()==0` 或 `accelerator.is_main_process` 显式选择唯一 `finish()` caller；Labtasker不自动猜 rank | 通用 reduction API 不计划 | launcher 的 rank API 才是权威；多 rank 同时报结果是明确 user error，而非 first-wins feature |
| Stale heartbeat local action | heartbeat 失败主要记录日志，无法可靠撤销本地执行 | 明确 stale 才 revoke；command/Python 默认等待自然结束，显式 finite `force_stop_timeout` 才强制终止；Python 通过 `cancellation_requested()` cooperative return，并可用 `set_force_stop_timeout()` 改写当前 run | 按真实需要优化 cooperative API | 不把网络不确定性当 stale，不使用跨线程异常注入或每 Task 子进程 |
| 执行实例 | 主要依赖 `worker_id` | 每次 claim 生成 `r_` + 12-char/72-bit random `run_id`；首版不建 run/attempt 历史表 | 只有真实诊断需求超过 `last_error` 时再评估历史表 | 防止超时后的旧进程误报，同时避免先建审计子系统 |
| 状态 | pending/running/success/failed/cancelled | pending/running/succeeded/failed/cancelled | 不预留更多状态 | cancelled 独立且不重试 |
| 重试 | `retries` 与 `max_retries` 容易产生计数歧义 | `attempt` 从 0 开始，claim 后为 1；`max_attempts=3` 表示最多三次 charged execution；transient 撤销本次计数 | backoff 仅在真实需求出现后考虑 | 总执行次数比“重试次数”直观；不增加第二个预算计数器 |
| Retry ownership | Task retry、HTTP retry、Worker restart 容易混在 FSM 中 | Server 只管 Task attempt；Client 管 request transport；外部 Agent/supervisor 管进程 restart | 真实运维需求再增加 registry | Task 达到 max attempts 只失败该 Task，Worker继续；claim transport耗尽才退出本地 Worker |
| 输入 | `args` JSON dict | `args`/`metadata` 均为严格 JSON object，默认 `{}`；无参数 Task 可直接提交 | 可选 schema 校验 | Python/HTTP/CLI 共用 JSON 类型，不做 CLI 推断 |
| metadata | JSON dict，可过滤 | 保留轻量 JSON metadata | tags 专用索引按使用情况增加 | 不预设复杂标签系统 |
| Route | 无独立概念；主要依赖 worker filter 和参数形状隐式匹配 | 下一项主要重构功能：worker claim 声明单个 `route`，Task 保存非空 `routes` 集合，精确 membership 才可领取 | 只根据真实工作流扩展可观测性 | route 是 opaque string，不创建 Route/Provider/Worker 实体 |
| Queue/route identifier | 多处字符串约束不统一 | 共用 `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`；保留大小写并精确匹配 | 有真实 Unicode identifier 需求后再评估 | 128 chars 足够 Agent 描述性命名；URL/log/path 无空白、slash 与 normalization 歧义 |
| 输出 | `summary` 同时混入实验输出与异常信息 | 改为始终是 JSON object 的 `result`，默认 `{}`；completion 原子写入，非 running 时可显式完整替换 | 大结果引用外部 artifact | 不提供 incremental merge；failure diagnostics 使用独立 server-owned `last_error` |
| 最近运行摘要 | 时间与 worker/run 信息分散，语义不稳定 | Task 暴露 `last_route`、`started_at`、`finished_at`；每次 claim 覆盖，run 结束时补齐，保留到下一次 claim | 真有跨 attempt 诊断需求再建 history | 只提供粗略 server-observed duration；不把 Run 升为公开资源 |
| cmd | 提交和 fetch 过程中语义混杂 | command template 属于 client runner，不作为 task 状态核心字段 | 若需 server-defined job 再增加 execution spec | 任务保存参数，runner 决定如何执行 |

## 3. 任务生命周期与可靠性

| 功能 | v1 | v2 2.0.0 | 后续计划 | 取舍 |
|---|---|---|---|---|
| Submit | Python/CLI 提交 | 保留；Client 生成 Task ID并通过 create-by-ID PUT 幂等创建 | batch submit 优化 | 网络重试不能重复创建任务；不增加 Idempotency-Key 子系统 |
| Pull worker | worker 主动 fetch；首次无任务即退出 | 保留 pull；首次空 claim 后默认等待 300 秒，`idle_timeout=0` 可立即退出；仅接受 finite non-negative non-bool number，不接受 null | 等真实负载证明需要时再优化 transport | 不支持无限等待；poll cadence 为内部常量，不增加 idle Worker 或 server wait protocol |
| Worker startup | 部分配置/签名问题可能到 fetch 后才暴露 | config/auth/Queue/route/timeout 与静态 Python binding 在首次 claim 前验证；失败不触碰 Task | 无 | startup failure 和 Task failure 分离，Agent 可直接诊断 |
| Explicit routing | worker 通过启动时 filter 单方面筛选 Task | 统一 Queue 内使用 `claim.route IN task.routes`；默认双方均为 `default` | 不增加隐式 routing policy | 新 Worker 上线不会自动改变旧 Task 去向 |
| Route migration | 依赖修改 metadata/filter 或重启 worker | 普通 Task update 对非 running Task 的 `routes` 做完整替换；支持按 ID 和服务端 filter 批量更新 | 可增加 dry-run/影响预览 | 禁止隐式 add/remove/merge 和 client list-then-update；请求直接表达最终 routing contract |
| Worker claim filter | `extra_filter` 参与领取 | 从 routing contract 删除 | 不计划恢复为隐藏运行时策略 | 查询 filter 仅用于 list 与显式 batch action |
| 调度顺序 | priority、last_modified、created_at | `priority DESC, pending_at ASC, task_id ASC`；charged failure 和 TransientError 都回到同优先级末尾 | 公平性问题出现后再调整 | 一个 private Task 时间即可稳定排序；普通 update 不暗中改队列位置，也不增加 Queue counter |
| Claim | aggregate 后按 `_id` 更新，存在竞态窗口 | 单条条件 `UPDATE ... RETURNING` | PostgreSQL adapter 使用等价原子语义 | 必须证明不会重复领取 |
| Claim response loss | retry 可能遗留 running Task 或再次领取 | Client 预生成 `run_id`，同一 `queue + route + run_id` logical claim 最多三次复用；active token 的 Queue/route 不同则冲突 | 无额外 idempotency table | 直接复用 fencing token，不再增加 claim ID；幂等重试不能改变原请求 |
| 执行归属 | `worker_id`，部分接口允许绕过 | heartbeat/complete/fail/unclaim 使用 Queue/Task path，body 携带并匹配 active `run_id`；只保留最近一次 terminal `(run_id, action)` 去重 | 更长幂等窗口仅在真实需要时增加记录表 | stale report 必须被拒绝；不建 `/runs` API、Run 实体或 payload hash |
| Heartbeat | task ID + optional worker ID，且可携带多种执行配置 | 每个 claimed run 强制 heartbeat；只有 claimant 得到的 active run lease 可刷新，不上报 progress/ETA/Worker status | jitter 和自适应间隔按需增加 | active run handle 不在普通 Task API 暴露；不依赖 Worker identity 或 lock file |
| Heartbeat timing | interval/timeout 可随 Task/Worker 配置漂移 | 全局 timeout 300 秒，Client 固定 60 秒 interval；claim/heartbeat 返回 server `lease_expires_at`；只有明确 stale 才在本地 revoke | 按实测网络环境调整全局默认 | 降低 SQLite 写入压力并容忍短暂故障；删除 per-scope override，接受最长约五分钟失联回收延迟 |
| Terminal report transport | 状态上报与 heartbeat 停止存在竞态，重试边界不统一 | terminal action 发起后继续 heartbeat并重试同一 action；成功/dedupe/stale/不可重试协议错误才结束；显式 finish 可先结束 Server run 但仍不并行 claim | 真实故障数据证明需要时再加 deadline | 不因短暂 outage 丢弃昂贵 completion，也不在 cleanup 尚未返回时领取下一项 |
| Task 更新时间 | heartbeat 与各类状态写入可能共同扰动修改时间 | claim、run outcome、heartbeat-expiry recovery、cancel、requeue 与有效普通 update 刷新 `updated_at`；普通 heartbeat 不刷新 | 无 | 避免 lease 流量污染 change inspection 与排序 |
| Heartbeat loss | server 周期扫描 heartbeat/task timeout | startup/background 每 60 秒扫描；deadline 是硬边界，迟到 action 可原子触发 `heartbeat_expired`，claim 不夹带清理 | 外部 scheduler 仅在多进程部署时考虑 | 用户概念是 heartbeat recovery，不引入 `reaper` 术语；最长约六分钟回收且不让扫描时机决定 lease 有效性 |
| 成功 | 正常 return 自动 `finish(success)`，返回值忽略；command child 可由环境上下文直接 finish | 正常 return 或未 finish 的 command exit 0 自动 succeeded 并覆盖 result 为 `{}`，不继承旧值；返回值无协议含义；`finish(result)` 立即可靠完成，缺省 `{}`，第二次调用报错；command child 继承 URL/token/Queue/Task/run/route/run-dir 并复用同一 API | 无 | 每次成功都有本次执行的明确完整 result；结果取得后仍可先 durable succeed 再等待资源释放 |
| 失败 | exception、两阶段交互 prompt、retry | Client 通过公开 `TransientError`/`TaskError`/`FatalWorkerError` 自主分类；分类只在 active run 上选择 Task action；finish 后普通异常只记录，fatal 只退出 Python Worker，不改 succeeded | 无额外 policy system | `running + matching run_id` 是稳定 FSM guard；不保留特殊 command exit code或增加 Server error level |
| Oversized failure diagnostic | 无统一边界 | official Client 在 fail payload 超过 1 MiB 时发送保留原异常类型、指向本地 run.log、traceback=null 的固定小型 fallback | 无截断配置 | 确保真实 failure 不因诊断过大最终伪装成 heartbeat timeout；完整 traceback 留在本地日志 |
| Run outcome API | status report 混合 success/failed/cancelled | `complete`、`fail`、`unclaim` 三个显式 action；transient→unclaim，fail/abort→fail | 无 | unclaim 撤销 claim 与 attempt；cancel 是外部 Task lifecycle action |
| Terminal wire body | outcome payload 与 Task/worker 字段混合 | complete=`run_id+result`，fail=`run_id+error(type/message/traceback)`，unclaim=`run_id`；首次和同 action 重试均 204 | payload hash 只在真实客户端 bug 需要时考虑 | Server 补权威 time/attempt/run；第一份 body 生效，不返回冗余 Task snapshot |
| 进程终止 | KeyboardInterrupt/SystemExit/signal 存在多条捕获与等待分支 | KeyboardInterrupt best-effort unclaim 后重抛；SystemExit/SIGTERM 自然传播，由 heartbeat loss recovery 接管 | 无 | 保持 Python/OS 直觉，不用隐藏 handler 改写退出原因 |
| Worker exit status | task child、CLI usage、Worker failure 容易混合 | 0=idle 正常结束、1=Worker failure、2=CLI usage、130=KeyboardInterrupt，其他 signal 保持 OS 状态 | 无 | command child 非零只形成 TaskError，父 Worker默认继续 |
| Worker stop/restart controls | Worker FSM 可承载 suspend/restart 等状态 | 不提供 `max_tasks`、`once`、`stop_after_current`、`daemon` 或 automatic restart | 出现明确 bounded-worker 工作流后重评 | 不为远程 stop 引入 control plane；process supervision 留给 Agent/systemd/Slurm |
| Cancel | FSM 可从过多状态转 cancelled | pending/running 可 cancel，cancelled 幂等成功；running cancel 原子失效 `run_id`；attempt/diagnostic/result 保留 | 本地执行中止行为随 Worker lifecycle 定稿 | server 先保证逻辑 fencing，不把取消混成 failure |
| Requeue | success/failed/cancelled 等均可 reset，且多层默认不一致 | pending/failed/cancelled 可 `requeue(task_id)`；清零 `attempt`/`last_error`、刷新 `pending_at`，保留用户数据与最近运行摘要 | batch requeue 仅按真实需求 | pending 可显式免除已耗预算；running 禁止，succeeded 重跑使用新 Task |
| Task delete | 可通过多种批量/交互路径删除 | 任意非 running Task 可按 ID 幂等删除；running 必须先 cancel；HTTP 204/Python None/CLI 静默成功 | batch delete 按需 | destructive intent 明确，同时不让活跃 run 在未 fencing 时失去资源 |
| Failure diagnostics | exception 写入 `summary.labtasker_exception` | `last_error={type,message,traceback,occurred_at,attempt,run_id}`；不建 attempt history | 历史表仅按真实诊断需求 | transient/cancel 不覆盖，成功重试后保留，人工 requeue 清空 |
| Queue delete | 支持 cascade hard delete | 空 Queue 直接删；非空必须显式 cascade；存在 running Task 时拒绝；事务内 hard delete | 备份/归档仅按需求 | CLI 用 `--cascade` 明确授权，不增加 prompt/soft-delete 状态 |
| Task execution timeout | `task_timeout`、`eta_max` 与可选 heartbeat 并存 | 删除 task execution timeout、`eta_max`、`start_heartbeat=False` 及相关分支 | 不预留；wall-clock deadline 由任务程序或外部 supervisor 负责 | 健康但耗时长不是 Labtasker failure；只检测 client 消失 |

## 4. Python API 与运行体验

| 功能 | v1 | v2 2.0.0 | 后续计划 | 取舍 |
|---|---|---|---|---|
| `@loop()` | 保留实验函数式入口 | 保留并重写；首版仅支持同步函数 | async function 支持按需增加 | 核心 UX，不为假设需求增加第二套执行分支 |
| Loop signature | extra_filter、required_fields、heartbeat/timeout 等参数混合 | 仅 `route`、`queue`、`idle_timeout`、`force_stop_timeout`，且只支持 `@loop(...)`；timeouts 拒绝 bool/NaN/Infinity/negative，仅 force-stop 可 null | 无 | routing、binding 与 heartbeat 已各自收敛，不保留旧控制面 |
| Worker route | 无；用 `extra_filter` 和 required fields 间接表达 | `@loop(route="...")`，每个 loop 恰好一个 route，默认 `default` | route 展示/诊断按需增加 | route 在进程生命周期内固定，不是 Worker entity |
| Task 参数注入 | `Required()` 同时表达注入与必需，默认值语义不完整 | 只支持 `parameter: T = TaskArg(...)`；每个 annotation 启动时编译 Pydantic TypeAdapter，逐值 `strict=True` 校验并遵循 annotation 自己的 Pydantic schema；resolver 负责应用特定转换；generic overload 暴露最终类型；无 annotation 跳过；`path` 复用 object-only dot path | 无 | 不维护 `Annotated` 双语法或自研/coercive validator；保留固定运行时对象与逐 Task 参数的区分 |
| `task_info()` | 全局/context 状态 | 返回 flat frozen local `TaskInfo`：public Task fields + `run_id`/`run_dir`；使用 contextvars；finish 后到本地 executor 退出前仍可读 | 无 | claimant可定位当前执行和 cleanup，但普通 Task API 不泄漏 active run |
| finish 后 cancellation helpers | 无明确语义 | `cancellation_requested()` 固定 false；`set_force_stop_timeout()` 因无 cancellable run 而 RuntimeError | 无 | succeeded 后不再伪装存在 revocation deadline |
| Context misuse | `finish(..., skip_if_no_labtasker=True)` 默认 outside-loop 静默跳过 | 保留 v1 参数名但默认改为 false；`task_info`/cancellation helpers 在 active execution 外 RuntimeError；显式 true 仅跳过缺失 context | 无 | 支持低侵入 standalone 代码，同时不吞 validation/network/server 错误 |
| `finish()` | 写本地文件并上报，文件存在即跳过 | best-effort 原子备份 `reporting + complete` payload 后立即做 run-fenced Server action；备份失败只 warning、不阻塞或改变完成；代码继续，重复调用显式报错 | checkpoint API 按需增加 | Server 幂等/fencing 是 correctness；journal 仅提高本地可见性和恢复能力 |
| command finish race | 父 heartbeat 与子 finish 的关系隐式 | reporting 时继续 heartbeat；complete 先赢后 heartbeat 由 Server terminal slot 返回 `run_finalized(action=complete)`；有本地 payload 时 child-exit 可由父进程重试 | 无 | 即使磁盘不可写也不误杀已完成后的 cleanup；不引入 socket/pipe |
| Python client 形态 | 多数 API 依赖不可见的全局 config/client | 顶层函数是主要 API；同步 `Client(url=None, token=None, queue=None)` 逐字段 fallback，并在显式构造或首次顶层调用时解析一次形成快照；支持 context manager/`close()` | async client 按真实需求 | `url` 与 TOML/env/config show 同名，不增加 `base_url` alias；运行中配置变化不暗中切换 Server |
| Client close | 生命周期依赖全局/隐式清理 | explicit close 幂等，context exit 调用；close 后操作固定 `RuntimeError("Client is closed.")`，不重开；lazy default 无 reset/close | 无 | 显式 Client 可确定释放，默认函数式入口不增加生命周期控制面 |
| Python 返回值 | `found/content/message` 等 response wrapper | 单资源直接 `Task`，list 返回 `TaskPage(items,next_cursor)`，count 返回 `int`，delete 返回 `None` | 无 | 不泄漏 HTTP 包装到领域 API |
| Python 异常 | httpx 与 Labtasker exception 混合、类型较散 | `LabtaskerError` 下仅 `ConfigError`、固定 `transport_error` 的 `TransportError`、结构化 `APIError`；malformed/nonconforming response 也归 transport；Worker outcome signals 独立 | 按真实处理分支再拆分 | agent 判断稳定 code，不为协议异常增加低收益 `ProtocolError` |
| Python 命名 | `submit_task`、`ls_tasks` 等历史命名混合 | 顶层与 Client 统一使用 `submit_task/get_task/list_tasks/count_tasks/update_task/update_tasks/cancel_task/requeue_task/delete_task` 及 Queue 对应命名 | 无 short alias | 函数式顶层需要资源名保证 discoverability，避免两套词汇 |
| Python public boundary | 普通资源调用和 Worker transport helper 混在 client API | package root 明确导出普通资源函数、Client、文档化 model/type、loop/runtime helper 与异常；claim/heartbeat/terminal transport 不提供公共 Python wrapper | 独立 executor 直接实现已公开 HTTP contract | `submit_task` 等主 API 必须稳定可 import，但不复制一套容易误用的底层 Worker API |
| Python Task update | `TaskUpdateRequest` model + merge/replace switch | 普通 dict 按 `TaskUpdate` TypedDict 静态描述；单项传 changes，批量传 `filter + changes` | 无 request model/sentinel | 省略字段与 `name=None` 明确区分，同时保持 JSON/Python 同形 |
| Python submit | 多层默认与旧字段名 | `submit_task(args=None, *, name=None, metadata=None, priority=0, max_attempts=3, routes=None, task_id=None, queue=None)` | batch submit 按需 | 无参数 Task 零配置；显式 ID仍保持 opaque 格式 |
| Client models | 共享 server Pydantic response wrapper，ID 命名漂移 | client-owned frozen Pydantic `Task`/`TaskPage`/`LastError`；统一 `task.id`，Task 2.0.0 字段精确列举，nested JSON 保持普通 dict | 后续 `/api/v2` 只加 optional response field | `LastError` 不与 Worker `TaskError` 异常重名；明确本地 snapshot，不制造共享 runtime package |
| Python list | `ls_tasks` 参数与 CLI 能力漂移 | keyword-only `list_tasks(status,name,filter,order_by,descending,limit,cursor,queue)`；快捷筛选相互 AND；ID 使用 get | 聚合/streaming 按需 | 一次只取一个显式页面，不隐藏网络请求 |
| Client transport | 所有网络错误最多重试 10 次/100 秒 | 普通请求 10 秒；仅 read 和 exact client-ID PUT 对 `TransportError`/`database_busy` 最多 3 次；其他 APIError 与所有 lifecycle/update/delete/Queue mutation 不自动重试；Worker report 独立 | 真实网络数据出现后调常量 | 避免 retry 跨越 requeue 或 ID reuse；不为低概率并发加 operation ID/revision/tombstone |
| Import 行为 | 版本联网检查、安装 traceback hook | 无网络、无全局 hook、无配置写入 | 无 | import 必须无副作用 |
| 失败交互 | 默认两轮面向人的 timed prompt | 删除运行时交互；错误类型/预设规则确定 outcome，结构化日志供 Agent 监督 | 仅完善分类与可观测性 | Agent 不在 Worker 执行环内，系统脱离 Agent 仍能正确运行 |
| Resolver | 支持 Annotated、自定义 resolver、alias、full-dict mode | 保留 `resolver` 名称，但严格限定为同步单值转换；Task value/default 走同一 resolver；输出按 annotation 严格校验；静态定义错误在 claim 前失败，value 错误为 `TaskError`；`path` 替代 alias；删除 `pass_args_dict`/`required_fields` | 复杂依赖注入不计划 | 一条显式转换路径；动态代码可读 `task_info().args` |

## 5. CLI 与命令模板

| 功能 | v1 | v2 2.0.0 | 后续计划 | 取舍 |
|---|---|---|---|---|
| CLI 框架 | Typer | 保留 Typer | 无 | 已满足需求 |
| CLI 交互对象 | 人工终端操作与脚本混合，包含 rich pager、表格和交互编辑 | agent-first、非交互、稳定结构化输出与退出码 | TUI/UI 作为独立 API client 后续设计 | CLI 不承担半套 TUI，不为临时展示体验增加状态和依赖 |
| CLI 数据输出 | table、quiet IDs、pager 等多套 schema | 两空格缩进的 UTF-8 JSON、无 ANSI、固定 schema；list 始终输出 `TaskPage` | 独立 TUI/UI | 保持人可读的同时可直接交给 agent/`jq`；不按 TTY 改行为 |
| Pager/终端展示层 | 内置 rich/custom pager、syntax highlight 等 | 删除 | 不恢复到核心 CLI | stdout 输出数据，stderr 输出诊断；组合与展示交给 agent/shell/独立 UI |
| 命令层次 | queue/task/worker/event/config/loop | `task submit/get/list/count/update/cancel/requeue/delete`、`queue create/list/delete`、`loop`、只读 `config show`；Server 仅为独立 `labtasker-server serve` | TUI/UI 另行设计 | 删除 worker/event/admin、缩写 alias、client 内 server 与半套展示命令 |
| CLI connection scope | config/global 参数与各命令行为不够统一 | `--queue` 仅放相关 Task leaf 和 `loop`；无 global placement、`--url`、`--token`；一次性连接覆盖用环境变量 | 无 | Queue 是常用资源范围，URL/token 是连接配置；避免同一选项两种位置 |
| Config CLI | interactive init 与多层配置行为 | 只读、network-free `config show`，输出 URL/Queue/token-present boolean；Agent 直接写三字段 TOML；无 init/set/write | 真实 onboarding 需求再评估 | 不维护配置 mutation DSL，也绝不把 token 打到 stdout/history |
| Submit | `task submit -- --k=v` 通过 `literal_eval` 猜类型，或传 dict 字符串 | 保留 CLI submit，但 `--args` 只接受严格 JSON object；删除 trailing shorthand 和类型猜测 | JSON file/stdin 仅按真实需求增加 | Python/CLI/HTTP 使用同一 JSON 类型模型；agent 生成 JSON 不构成负担 |
| Task routes | 无 | submit 可重复传 `--route`；省略为 `default`；拒绝空值/重复并按字典序返回 | 无 wildcard/priority/fallback | Task 显式穷举兼容执行类别，数组只是无序 set 的 canonical wire 表示 |
| Route update | 通过通用 update/filter 间接实现 | `update_task`/`update_tasks` 对非 running Task 的 `routes` 做完整替换 | dry-run 按真实需求 | 它是普通 Task update，不增加 route action；claim 与 update 原子竞争 |
| Task update CLI | `-u field=value`、dot-path patch、merge/replace 混合 | positional ID 或 `--filter` 二选一，并且只接受严格 `--changes` JSON object | 无 per-field flag | 与 Python/HTTP 同一 changes model，不保留第二套 parser 与隐式 merge |
| 模板语法 | `%(foo.bar)`，会被 zsh 抢先解释 | `%{foo.bar}` | 不兼容旧 `%()` | 新语法在常见 POSIX shell 中按字面传递 |
| 模板 escape | 无清晰规则 | `%{{` 输出字面 `%{`；`%%{a}` 是字面 `%` 加插值 | 无 | 不全局改写 `%%`，且能表达紧邻占位符的字面 `%` |
| 模板 path | 支持 parser 定义的嵌套字段 | 仅对象路径，segment 为 `[A-Za-z_][A-Za-z0-9_]*`；禁止数字 segment、数组、连字符、Unicode key、escape | 只有真实需求出现后才扩展 | `%{items.0}` 第一眼像数组索引，禁止比赋予反直觉含义更明确；任意 key 可由 Python 读取完整 args |
| 命令 parser | ANTLR grammar + vendored runtime | 删除 ANTLR/generated/runtime，改为按 EBNF 与状态表实现的 compiled deterministic scanner；不保留 shadow `.g4` | 仅在加入 nesting/quoted key/operator/recovery 后重新评估 parser generator | 语言是 regular、nonrecursive、fail-fast；scanner 更小、更易审计，完备性由明确 contract 与测试保证 |
| Command 输入 | positional argv、`--command/-c`、`--script-path`、stdin 多入口 | 仅 `loop [OPTIONS] -- COMMAND [ARG...]`，必须显式 `--` | 无 | 一条执行路径，Agent 可直接生成 argv |
| Shell/quoting | shell、shlex/mslex、executable 等分支 | 直接 exec argv，不内置 shell/quote；需要时显式执行 `bash -lc` 或脚本 | PowerShell 专门支持按真实需求增加 | shell 能力仍可组合，但不成为 Labtasker 隐式语义或注入面 |
| JSON→argv | 多依赖 parser/Python 字符串化 | string 原样；其余值为 deterministic compact JSON；每个模板始终一个 argv，不二次切词 | 无 | object/array 有标准可逆表示，空格和特殊字符不破坏参数边界 |
| Child environment | 继承环境并注入若干 `LABTASKER_*` | 继承 Worker 环境，再覆盖 reserved context；auth disabled 时移除 token；无 `--env`，动态值用 platform launcher/wrapper | 无 | 不创造第二套 env 模板语言；POSIX 可直接组合 `env 'LR=%{lr}' ...` |
| Child stdin | PTY/subprocess 分支隐含继承行为 | 只在 interactive PTY 中 relay；非交互 pipe 使用 null stdin | 真实 workload 证明需要后再设计输入协议 | 并行实验不应让第一项 Task 隐式消耗共享 stdin |
| PTY/output relay | POSIX 默认 PTY，可切换 subprocess；动机和差异暴露为用户选项 | 不暴露开关；仅当 Labtasker 自己处于 POSIX interactive TTY 时内部 PTY，否则并发 pipe；两者 raw-byte live relay + `run.log`，不承诺 UTF-8 | ConPTY 仅按真实 Windows 需求 | 保持直接 wrapper 的第一眼行为，不因解码任意程序输出而崩溃，也不增加公开执行模式 |

## 6. 查询、分页与结果

| 功能 | v1 | v2 2.0.0 | 后续计划 | 取舍 |
|---|---|---|---|---|
| 基础查询 | ID/name/status/filter | 保留 ID、queue、status、name 和 filter | 增加常用索引按数据验证 | 不暴露 SQL |
| Query 语法 | Python AST → MongoDB query | 统一命名为 `filter`；Python AST allowlist → `FilterExpr` → SQLAlchemy，仅支持比较、`and/or`、`in/not in` 与 `exists(path)`/`missing(path)`；不支持一元 `not` | 仅按真实案例增加操作符 | 不再作为 worker claim 时的隐藏 routing policy；不提供 `where`/`query` 别名 |
| Filter 边界 | 无统一表达式大小约束 | 所有 surface 的 UTF-8 filter 最多 8192 bytes，超出 `filter_too_large` | 无公开 AST depth/node knobs | 一个边界同时限制 URL 和 parser 增长，不制造配置矩阵 |
| Mongo dict filter | client 可直接发送 Mongo 操作符 | 删除 | 不恢复 | 防止存储泄漏和 NoSQL 注入 |
| 嵌套 JSON | 深层 dict/list 查询 | 保留对象 dot path；普通 predicate 只有在路径存在且类型兼容时才匹配 | SQLite JSON 能力不足的部分明确报错 | 路径拼错时尤其是负向查询会 fail closed，而不是意外选中大量 Task |
| Missing/null | 语义随 Mongo 操作符而异 | absent 不满足任何普通比较，显式 null 是可比较的 JSON 值；`exists` 包含 null，`missing` 仅匹配 absent | 无三值逻辑或隐式 missing value | `x != None` 明确表示 present and non-null；agent 可显式写 `missing(x) or ...` |
| 否定操作 | `!=`、`not` 等缺失 | 支持 guarded `!=` 和 `not in`；删除一元 `not` | 只有真实需求证明必要时再讨论通用 complement | 避免 `not (result.acc >= 0.9)` 把没有 `result.acc` 的 Task 一并选中 |
| 类型比较 | MongoDB coercion/ordering 细节泄漏到行为 | 严格 JSON 类型；bool 与 number 分离，string 不转 number，int/float 同属 number | 仅按真实案例增加显式转换 | Python/CLI/HTTP 共用 JSON 模型，查询结果可预测 |
| JSON numeric domain | Python/Mongo/JSON 对 NaN、超大整数行为可能不同 | 所有递归 JSON 与 filter literal 仅允许 signed int64 或 finite binary64；拒绝 NaN/Infinity/overflow，bool 不作 number | 无 | 与 SQLite/跨语言语义一致，不让同一值随入口或查询路径改变类型 |
| JSON nesting | 后端/解析器递归边界隐式 | args/metadata/result 最大 container depth 64，scalar=0、container=1+children；超出 `json_too_deep` | 无 per-field knob | 1 MiB 内仍可能构造递归炸弹；统一一个确定边界而不扩张数据模型 |
| JSON text domain | Python/JSON/backend 对孤立 surrogate 的处理可能不一致 | 所有 JSON string/key 只接受 Unicode scalar values，拒绝 `U+D800`–`U+DFFF` | 无 repair/replacement mode | canonical UTF-8、日志与数据库保持同一文本域 |
| Comparison shape | 支持较宽的 AST 组合 | 每项恰好一个 path 和一个 scalar literal；拒绝 path-to-path、chained 与 structured equality | 按真实案例扩展 | 避免 SQL translator 和跨后端语义膨胀 |
| Membership shape | 语义跟随 MongoDB 翻译 | 只允许 `path in [scalar literals]` 与 `scalar literal in array_path`（及 `not in`）；其他 operand shape 报错 | 按真实案例扩展 | syntax 明确声明预期容器方向，不猜测歧义写法 |
| Object key presence | 可借助后端或容器语义间接表达 | 只用 `exists(path)`/`missing(path)`；`in` 不表示 dict key lookup | 非 dot-path key 确有需求时再设计显式操作 | 同一个 `literal in path` 不随 row 的 array/object 类型改变含义 |
| Ordering domain | 行为跟随 MongoDB | 动态 JSON 仅 number ordering；内建 timestamp 使用严格 RFC 3339 literal | 不增加任意 string collation | 避免 backend collation 漂移 |
| Nullable run fields | start/worker 等字段语义分散 | `last_route`、`started_at`、`finished_at` 可过滤；内建字段始终存在，以 `!= None` 判断已有值 | 无 | `exists/missing` 留给可能真正缺失的动态 JSON path |
| Filter mutation scope | 通用 update/delete 可携带 filter | 首版仅非 running Task update 使用 filter且强制显式提供；cancel/requeue/delete 均按 ID | 真实批量需求出现后单独设计 | guarded query 不成为扩张 batch lifecycle API 的理由 |
| Regex/date | 自定义函数 | 删除 | 有反复出现且不能组合表达的案例再讨论 | 避免复杂度、性能边界和时间解析歧义 |
| 排序 | CLI 支持，Python/文档曾漂移 | 单个公开内建标量白名单 `order_by` + `descending`；默认 `created_at` 降序，null 始终在末尾，`id` 同方向稳定打破平局 | 多字段或 JSON 排序按需 | cursor 顺序确定且不依赖 backend 的 null 默认顺序；拒绝自由 sort 表达式 |
| Duration query | 可由调用方自行估算 | 不增加 stored/virtual duration、duration filter 或 sort | 只有明确服务端分析需求再评估 | 心跳检测延迟使 server duration 容易产生虚假精确性 |
| 分页 | offset/limit，默认 100 易静默截断 | `limit` 1–1000、默认 100；无状态 opaque cursor 绑定 Queue/filter/order，返回明确 next cursor；每页独立一致但无跨页 snapshot；无 auto iterator/all；server-side batch 独立遍历完整 match set | streaming 仅按真实需求 | 网络请求可见；不增加 snapshot/session，concurrent mutation 的跨页变化按普通 keyset 处理 |
| Task count | 需要列出后在 Client 统计 | `count_tasks` / `task count` / `GET .../tasks/count` 复用 status/name/filter，返回单个总数；TaskPage 不附带 total | 分组统计仅按真实需求 | backlog 数量是实用诊断，但不让每次分页承担额外 COUNT，也不扩张成聚合系统 |
| Result 更新 | summary merge 与 status 混合 | completion 原子写 result；普通 update 仅在非 running 时完整替换 | 中间 metrics/checkpoint 后续 | 用户可显式修正数据，但没有 incremental merge 或隐式状态变化 |
| 导出/聚合 | 功能有限 | 非首版核心 | CSV/JSONL export、结果排名按使用需求增加 | 不把 server 做成分析平台 |

## 7. HTTP API 与协议

| 项目 | v1 | v2 2.0.0 | 后续计划 | 取舍 |
|---|---|---|---|---|
| API 结构 | `/api/v1/queues/me/...`，Queue 从 Basic Auth 身份隐式推导 | 明确版本化 `/api/v2` resource/action endpoints | 破坏变更增加新 API version | HTTP 协议版本独立于 Python 包版本 |
| Schema | client/server import 同一 Pydantic 模型 | server 与 client 各自维护边界模型 | 可从 OpenAPI 生成静态检查产物 | 两包不形成运行时依赖 |
| Contract test | 主要依靠共享实现和 e2e | 真实 client 对真实 server 的契约测试 | 兼容矩阵按版本需求增加 | 防止独立包漂移 |
| 错误模型 | HTTPException 深入 FSM/DB，响应形状随路径漂移 | 领域异常 → `{error:{code,message,details}}` → client exception | 错误文档自动生成 | code 是稳定机器 contract，message 给人读 |
| Request validation | FastAPI/Pydantic 默认 shape 可能泄漏 | 专用 code 优先，其余统一 `422 invalid_request` + located readable errors | 无 per-endpoint validation code | Client/Agent 只处理一个 fallback，框架输出不成为协议 |
| Update API | 通用 TaskUpdateRequest merge/replace | 单项 `PATCH /tasks/{id}` 直接接 changes；collection `PATCH /tasks` 接 `filter + changes`；batch 先全量校验再原子写入 | 无 revision/ETag；last-write-wins | running 竞态项排除，其他不变量冲突整批回滚；无隐式 update-all |
| Routing API | 无独立 contract | submit 保存非空 `routes`；claim 提交单个 `route`；非 running route 变更复用 Task update | 影响预览按需 | 不增加 Provider CRUD、route registry、route mutation DSL 或在线校验 |
| Idempotency | server-generated Task ID，submit 超时后重试可能重复创建 | `t_` + 12-char/72-bit client-generated Task ID + create-by-ID `PUT`；canonical submit JSON 的内部 SHA-256 hash 识别原请求；hard delete 后同 ID 可重用 | 批量请求按真实需求 | 不增加独立 Idempotency-Key/table 或永久 tombstone；自动 ID 碰撞概率可忽略，显式 reuse 由用户负责 |
| Empty claim | `found` 布尔包装 nullable Task | `204 No Content` | 无 | 正常空结果，不伪装错误或 nullable success body |
| Request/body data limit | 未形成统一 contract | 所有 HTTP request body 统一上限 1 MiB；create/update/complete 后的完整用户 Task 数据同样最多 1 MiB，分别用 `413 request_too_large` / `422 task_data_too_large` | 仅按真实 payload 调整一个常量 | 多次 PATCH 不能绕过限制；Task/result 是小型 JSON 与摘要，不承载 artifact，不增加逐字段配置 |
| Protocol discovery | server notification/version warning | unauthenticated `/health` 返回固定 status/API-version/database shape 并实际查 DB；`/openapi.json` 公开；无 capabilities、Swagger/ReDoc | 真有 optional protocol feature 后再协商 | 2.0.0 initial release 是一个完整 mandatory contract；Agent 获得机器 schema，不在 import 时联网或维护半套网页 UI |

## 8. 数据库与一致性

| 项目 | v1 | v2 2.0.0 | 后续计划 | 取舍 |
|---|---|---|---|---|
| 主数据库 | MongoDB replica set | SQLite | PostgreSQL 只有实际并发/部署需求后才做 | ORM 不等于自动获得跨后端语义 |
| Embedded DB | mongomock + jsonpickle + 模拟事务 | 删除 | 不恢复 | SQLite 本身就是可靠本地存储 |
| ORM/access | PyMongo 与手写文档 | 同步 SQLAlchemy 2.x：private ORM 做 CRUD，Core/explicit SQL 做 claim/filter；每 command 一事务 | 不预设 repository adapter/async DB | 一套直接可审计的 persistence path；不叠 SQLModel、UnitOfWork、aiosqlite |
| Migration | 无正式 schema migration | Alembic 从首版启用；启动前自动 init/forward upgrade，拒绝 newer/unknown/failed revision；无 migrate CLI/backup | v1 importer 按真实迁移需求增加 | 本地升级零额外步骤，同时不把 Mongo importer 或 rollback 子系统塞进启动路径 |
| SQLite 配置 | 无 | 固定并验证 WAL、foreign_keys、5000 ms busy_timeout、synchronous FULL | 参数仅按实测负载重新设计 | 优先 acknowledged Task durability；不暴露无证据的 tuning surface |
| Server restart | running/heartbeat recovery 与服务进程生命周期耦合不清 | shutdown 不改 Task；启动监听前按普通 heartbeat loss 回收已过期 lease，保留未过期 lease；无 restart grace | 多进程协调进入范围后重设 | 短重启可透明、长停机服从同一 lease contract，不增加恢复状态 |
| Claim SQL | 多步骤 aggregate/update | 显式原子 SQL | 每个后端必须通过同一并发测试 | 不强行 ORM 化 |
| 事务边界 | 散落在 DBService | 每个 TaskService command 一个明确事务 | 无通用 UnitOfWork | 具体而可审计 |
| 索引 | queue/status/priority/created_at 分散索引 | 只建 claim、expiry、default/status list、active/terminal run 与 route 热路径索引 | 用真实 query plan 调整 | 不预建 name、JSON path 或所有排序组合索引 |
| Task identity | Mongo `_id` 与 Queue 关系混杂 | composite `(queue_name, task_id)` primary key；non-null active run ID 全局 partial unique | 无 | Queue 真正是 Task namespace；同 ID 可存在不同 Queue，但一个 active run 只能拥有一项 Task |
| JSON | Mongo 原生嵌套文档 | args/metadata/result 为 sorted compact canonical JSON text + valid-object CHECK，查询用 JSON1 | 大规模分析再考虑其他存储 | 文件可检查且不绑定 SQLite JSONB 版本；API 不承诺 key order |
| 时间存储 | datetime/string 语义分散 | SQLite `INTEGER` UTC Unix microseconds，由可注入的 Server clock 生成；HTTP/Python 边界转换 | 无 per-field 格式开关 | 精度、比较与测试统一，client 不提供权威生命周期时间 |
| Task 主行 | 文档字段同时承担存储与 API 模型 | 单一 private row 保存 identity/FSM/JSON/attempt/timestamps/latest-run/error/lease/dedupe/order；routes 仅存 association table | 真有 run history 再独立建模 | 数据库、HTTP 与 client model 明确分层，同时避免 route 双写 |
| FSM 数据约束 | 主要依赖应用代码维护文档状态 | SQLite CHECK 强制 attempt、pending time、active run 与 lease 对五种状态的一致性 | 无额外状态 | 不增加公开概念，但阻止 partial write 形成不可能状态 |
| SQLite 写事务 | 写锁取得时机随调用路径变化 | 所有 mutation 使用 `BEGIN IMMEDIATE`；五秒仍繁忙则 `503 database_busy` | 只有实测 contention 再调整 | WAL reader 继续，writer 在验证前串行化；不隐藏无限重试 |
| Route storage | filter/args shape 中隐式表达，缺少专门索引路径 | private `task_routes(queue, task, route)` association + composite FK/index；完整集合事务替换，批量装载 | 只有真实 Route metadata/lifecycle 需求才考虑实体 | 这是可索引的多值字段，不是 Route registry；claim 不逐行展开 JSON array |
| 多 server 进程 | 可部署但后台任务/事件存在协调问题 | 明确只支持一个 server process | PostgreSQL + leader/reaper 协调后再开放 | 不提供未经验证的部署模式 |

## 9. Event system

| 功能 | v1 | v2 2.0.0 | 后续计划 | 取舍 |
|---|---|---|---|---|
| FSM event handle | 状态机返回可 commit 的发布 handle | 删除 | 不恢复 | 状态机不负责 I/O |
| EventManager | 进程内 per-queue buffer | 删除 | 不恢复为事实来源 | 当前实现会丢事件且不可重放 |
| SSE | 实时推送，依赖内存状态 | 不实现；使用 task polling | 有真实自动化消费者后恢复 | 不阻塞核心发布 |
| 持久事件 | 无 | 无 | 增加 append-only `task_events` 表 | 状态与事件同一 SQLite 事务 |
| 重放 | 无可靠恢复 | 无 | `Last-Event-ID` + event cursor | at-least-once，按 event_id 去重 |
| 外部 broker | 无 | 无 | 只有明确规模需求才考虑 | 不预先引入 Redis/Kafka |
| 插件回调 | CLI entry-point 与事件脚本 | 删除 | 有真实第三方插件后重新设计 | 不建立通用 EventBus |

## 10. 配置、日志与可观测性

| 功能 | v1 | v2 2.0.0 | 后续计划 | 取舍 |
|---|---|---|---|---|
| Client config | `.labtasker/client.toml` + 全局读取 | `queue=None` 按 per-call > Client > `LABTASKER_*` env > CWD `.labtasker/config.toml` > built-in 解析；文件为 strict flat TOML，仅 optional string `url/queue/token`；配置错误仅 `invalid_config`/`legacy_config_found`；token 缺省即不发送认证头 | 无 profile/父目录/用户配置 merge，也不解析/迁移旧文件 | message + source/field details 说明具体错误，避免 code/class 膨胀并防止旧项目静默落到 localhost/default |
| Server config | env/settings，多模式 | data dir、host、port、token、全局 heartbeat timeout 最小集合 | 部署配置按需求增加 | interval 由 Client 派生；删除 task execution timeout、per-scope heartbeat knob 与无 heartbeat 开关 |
| 本地 run journal | 每任务目录、run.log、summary | `.labtasker/runs/{queue}/{slug}__{task_id}/{time}__attempt-{n}__{run_id}`；Task name 最多 256 Unicode code points 且拒绝 `Cc` control，slug 按 Unicode alnum 规则生成并截断至 80 UTF-8 bytes；初始目录/snapshot 失败则 unclaim+Worker exit；terminal 写 best-effort | 未来可基于 journal 做显式恢复；v2 不自动 replay | 完整 name 留在 Task/task.json，ID保证目录身份；路径/日志 label 有界且本地备份不成为 Server correctness 前置条件 |
| 本地 journal 清理 | 行为不够明确 | 不自动 retention、压缩、清理，也不随远程 Task 删除级联 | 有真实磁盘管理需求后增加显式工具 | 避免隐式删除实验现场 |
| 服务/loop 日志 | standard logging | 普通 Python logging 的人类可读 stderr；finite data commands 仍输出格式化 JSON；无 JSONL/format switch | OpenTelemetry/metrics 按需求 | 持续执行日志与机器数据响应分开，不引入日志模式矩阵 |
| CLI 错误 | 输出形态易随调用路径变化 | finite command 的已处理错误向 stderr 输出一个可读 JSON envelope 并 exit 1；Typer usage exit 2、loop 保持自然语言日志 | 无格式切换 | Agent 可稳定读取，人的第一眼也能理解；agent-first 不等于 machine-only |
| 日志级别 | verbose/debug 配置与多种展示路径 | CLI/Server 固定 INFO；Transient/Task/Fatal 分别 WARNING/ERROR/CRITICAL，后两者含 traceback；command failure 不重复 child output | 有真实排障需求再加统一入口 | 保持常规严重度直觉，不增加 verbosity 参数面 |
| Python tee | import 时永久 patch stdout/stderr、重置 Loguru，并用 ContextVar 支持嵌套 destination | 仅 Worker invocation 内安装一个进程级 active-run tee；共用锁、退出恢复、fork child 禁用；不捕获 native fd | 出现真实底层捕获需求再评估 | 保留 print 同时显示/落盘的价值，删除 import 副作用及不存在的并发 Task 抽象 |
| Library logging | import 时配置 Loguru/Rich | 尊重已有 `labtasker` logger；Worker 无有效 handler 时只加 named INFO stderr fallback，不碰 root | 无 | loop 有默认可见消息，同时不接管训练程序日志系统 |
| Traceback filter | import 时安装全局 hook | 删除 | 可提供显式 formatter/helper | 不修改宿主程序全局行为 |
| 健康检查 | connection/full health | `/health` 真实查 DB；200/503 都用固定 redacted JSON，不认证 | readiness/liveness 拆分按部署需求 | 不泄露异常、SQL、凭据或路径 |

## 11. 安全

| 项目 | v1 | v2 2.0.0 | 后续计划 | 取舍 |
|---|---|---|---|---|
| 默认绑定 | server 可绑定 `0.0.0.0` | 默认 `127.0.0.1`；tokenless 仅允许 `ipaddress.is_loopback` literal 或大小写不敏感的 exact `localhost` | 远程部署文档明确 TLS/reverse proxy | 保留常见 localhost UX；wildcard/其他 hostname 不因偶然 DNS 被视为安全 |
| 认证 | queue name/password Basic Auth | 单个 server-wide Bearer token；loopback 可省略且忽略多余 Authorization；启用时 missing/malformed/wrong 均统一 `401 unauthorized`；非 loopback 无 token 拒绝启动 | 多租户需求出现时重新评估 | 一台 server 是一个 trust domain；fallback token 不破坏 tokenless Server，也不泄露失败细节 |
| Token 管理 | 每 Queue 密码可更新 | server config/env 设置，修改后重启轮换 | 无 live rotation API | 删除 users/roles/token CRUD 等控制面 |
| Queue 创建 | 可无鉴权创建 | 必须显式创建并受同一 server token 保护 | 无 | submit 到未知 Queue 报错，不因拼写错误产生新 Queue |
| Filter 输入 | 可发送 Mongo dict/operator | 只接受受限 query string，server 解析 | 增加资源限制 | 不信任 client transpile 结果 |
| Secrets | password 可写 client.toml | token 可选且支持配置文件/环境变量，不做跨平台文件权限检查；Authorization/token 永不进入日志，其他诊断字段允许按需记录 | secret manager 集成按部署需求 | 权限位不能防止误提交版本库；远程凭据推荐环境变量，不增加不一致的权限策略 |

## 12. 测试与质量保障

| 项目 | v1 | v2 2.0.0 | 后续计划 | 取舍 |
|---|---|---|---|---|
| 测试分层 | 同一测试多 marker，语义混乱 | unit、SQLite integration、API、e2e 目录明确 | stress/nightly 按需求 | 一测一层 |
| DB unit fake | mongomock 模拟生产 Mongo | 删除；临时 SQLite 文件即真实后端 | PostgreSQL adapter 自带 contract suite | 不模拟事务 |
| 并发测试 | 随机 sleep，大型测试在 CI 跳过 | 两个独立连接/进程的确定性 claim 测试进入 PR CI | 大规模 stress 独立运行 | 核心不变量必须持续验证 |
| 时间测试 | freezegun + 真实 sleep + lock hack | 注入/显式传递 clock，避免真实等待 | 无 | timeout 测试确定性 |
| Client/server 漂移 | 依赖共享模型 | request extra forbid、response additive extra ignore；真实当前 Client contract test，并用上一已发布 v2 Client 跑核心 release flow | 更大多版本矩阵按需 | 两包独立安装但不引入协商层；已知字段仍严格校验 |
| API 演进 | package/API 变化边界不清 | `/api/v2` 仅允许 additive endpoint/optional response/error code；字段或 Task state 的破坏变化进入新 API prefix | 无 capabilities negotiation | package version 与 protocol version 解耦，普通调用不增加 health preflight |
| Parser tests | corner-case 覆盖较丰富 | v1 用例作为迁移 checklist；覆盖 `%{{`/percent overlap、空/非法/未闭合 path、相邻占位符、精确位置、valid-template property 与 Unicode fuzz；验证每步前进和 O(n) | 小字母表 exhaustive test 按收益增加 | v2 语义有意变化，不能把旧测试或 parser generator 当作完备性本身 |
| Migration tests | 缺失 | fresh install + upgrade fixture | legacy importer 测试 | 从首版防止 schema 债务 |
| Distributed launcher tests | 无明确所有权测试 | PR CI 用 fake multi-rank launcher；scheduled/release suite 跑真实单机 torchrun/Accelerate，覆盖唯一 claim/heartbeat、rank result、exit/cancel 与误用 guard | 多机仅在进入支持范围后增加 | 每次验证核心进程边界，但不让 PyTorch 成为普通 client/test 依赖 |
| 平台范围 | 多平台行为由依赖和偶然测试决定 | Linux 为完整 release-gated；macOS/Windows 普通 Client/Server/pipe Worker best effort | 有真实使用后增加对应 launcher/process-tree matrix | 不让 ConPTY 和非目标 GPU 平台阻塞精简首发 |
| Release gate | 测试入口与发布条件分散 | unit、真实 SQLite、API/OpenAPI、e2e、并发、migration、fake+real launcher、prior-client contract | stress/nightly 按证据增加 | 不设 coverage 数字或全平台矩阵来替代关键行为验证 |

## 13. 明确删除或暂不计划

| 功能/设计 | v2 决策 | 重新考虑条件 |
|---|---|---|
| Worker FSM、suspended/crashed/retries | 删除 | 出现真实 worker 运维控制需求 |
| 通用 `query_collection/update_collection` | 删除 | 不恢复；始终使用领域命令 |
| Client 直接发送 Mongo/SQL 查询结构 | 删除 | 不恢复 |
| mongomock/jsonpickle embedded DB | 删除 | 不恢复 |
| Import 时版本检查 | 删除 | 不恢复；需要时显式读取 `/health` 的 API version 或 `/openapi.json` |
| 全局 traceback hook | 删除 | 不恢复；只提供显式工具 |
| 默认交互式失败 prompt | 删除 | 可在 CLI 外层显式启用 |
| Task execution timeout、`eta_max` | 删除 | 不恢复；wall-clock deadline 属于任务程序或外部 supervisor |
| 无 heartbeat 执行模式 | 删除 | 不恢复；每个 claimed run 都必须 heartbeat |
| pytest 跨文件依赖 | 删除 | 不恢复 |
| 多 marker 复用测试 | 删除 | 不恢复 |
| 独立 `labtasker-core` distribution | 暂不创建 | 出现第三个真实消费者且能形成稳定公共 API |
| 多数据库 repository abstraction | 暂不创建 | PostgreSQL 实现已经存在并显示出稳定共同接口 |
| Web UI | 暂不计划 | CLI/Python 用户出现明确可视化需求 |
| DAG/workflow engine | 暂不计划 | 实验任务出现真实依赖编排需求 |
| Route/Provider/Worker registry | 不创建 | 只有 route 字符串不足以解决已出现的运维问题时重新评估 |
| Worker-side claim filter | 删除 | 不恢复；使用 Task routes 显式物化执行兼容关系 |
| CPU/GPU requirements/offers | 暂不计划 | Labtasker 真正开始负责资源分配、预留与容量调度时重新评估 |
| Redis/Kafka/Celery | 暂不计划 | SQLite/单 server 被实际负载证明不足 |
| 通用插件系统 | 暂不计划 | 至少两个独立插件需求且核心不能合理承载 |
| 结果分析平台 | 暂不计划 | 简单 export 无法覆盖真实分析工作流 |

## 14. 建议的发布阶段

| 阶段 | 交付内容 | 退出条件 |
|---|---|---|
| 2.0.0-alpha | SQLite schema/migration、submit、atomic claim、run_id、heartbeat、success/fail/retry、list/cancel/requeue | 并发领取、stale report、heartbeat loss recovery 测试全部稳定 |
| Explicit routing（下一主要 feature） | worker 单 route、Task routes 集合、route-aware atomic claim、非 running route batch update、Task `last_route` 记录实际 claimed route | 新旧 codebase rolling coexistence 与 pending backlog 显式迁移的并发测试稳定 |
| 2.0.0-beta | 独立 client/server 包、Python `@loop()`、CLI、`%{}` parser、基础查询/batch-selection filter transpiler | 两个真实实验脚本和两个 worker 端到端运行 |
| 2.0.0 initial release | 文档、安装流程、升级测试、shared token、安全默认、发布流水线 | 新环境可在十分钟内安装并完成实验闭环 |
| v0.2 候选 | 根据真实反馈选择 batch submit/export、完整 filter 子集或持久事件 | 只实现已有用户案例支持的功能 |
| Future | PostgreSQL、多进程 server、SSE event replay、artifact backend | 当前架构被可测量负载或明确用户工作流证明不足 |
