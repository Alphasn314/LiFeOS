# LiFeOS V1 交付、验收与微调报告

- 报告日期：2026-08-28
- 仓库：`C:\Users\Alpha.sn\Documents\ChatGPT\LiFeOs`
- 契约版本：V1 / schema `1.0`
- 默认展示时区：`Asia/Shanghai`
- 当前安全模式：`dry_run=true`、`real_enforcement_enabled=false`

## 0. 结论先行

LifeOS V1 的冻结验收集已经实现并通过。交付物包括：FastAPI Core、PostgreSQL
迁移、确定性 Planner/Replanner、多轴 RuntimeState、干预策略与安全 Command
Guard、事件账本/outbox、AI Provider 故障隔离、React PWA、Python Windows
Agent、契约/单元/集成/场景/安全测试，以及本报告。

“通过”具体指：53 个 Backend 测试、24 个 Windows Agent 测试、9 个 Web
测试全部通过；Python Ruff/MyPy、Web Prettier/TypeScript/生产构建通过；npm
官方审计端点报告 0 个已知漏洞；真实 PostgreSQL 在线迁移和重启恢复通过；真实
Core/Web/Windows Agent 的本地集成 smoke 通过。真实 Agent smoke 覆盖注册、assignment、
heartbeat 和 observation；命令升级/ACK 由自动化端到端场景与 Agent 单元测试覆盖。

需要精确理解两个边界：

1. Docker CLI 可用，但本机 Docker Desktop daemon 未运行且当前进程无权启动，
   因此只验证了 `docker compose config`，没有声称 PostgreSQL 16、API、Web 的
   Compose 镜像已在 Docker 中构建或启动。数据库在线验收使用隔离的用户态 WSL
   PostgreSQL 18.3 完成。
2. V1 验收证明了冻结命名场景和安全不变量，不代表所有产品语义已经替用户决定。
   例如 session 完成后如何扣减任务工时、直接修改固定事件是否立即自动重排、重复
   日程如何表达，仍是明确列出的微调项，而不是隐藏的“自动猜测”。

任何情况下，本 V1 都不会真实关闭程序、修改注册表/防火墙、设置自启动、永久锁机，
也不会采集按键、剪贴板、截图、麦克风或摄像头。`WOULD_BLOCK` 只记录如果启用
真实执行时“本来会做什么”。

## 1. 本次范围如何解释

LifeOS 被实现为个人闭环执行系统，而非聊天机器人。闭环是：

```text
Task / FixedEvent / 可用时间
            ↓
确定性 PlanVersion（不可变、可追溯）
            ↓
ExecutionSession（启动时冻结 commitment mode）
            ↓
Observation → FeatureSnapshot → RuntimeState
            ↓
PolicyDecision → 有界 Command → CommandAck
            ↓
EventLedger / Outbox / 新 PlanVersion
```

Core 的 PostgreSQL 提交状态是唯一事实源。Web 的浏览器存储、Agent 的 SQLite
队列和最后一次 session assignment 都只是缓存或待发送事实，不能覆盖 Core。

### 1.1 已实现的 V1

- Task 与一次性 FixedEvent CRUD、乐观并发控制。
- 确定性日计划、不可行冲突、旧计划保留、滚动重排安全门。
- 计划、Session、Observation、Feature、State、Decision、Command 的分层。
- Windows 前台进程、截断窗口标题、idle、lock、session、heartbeat 采集。
- 60/300 秒窗口、UNKNOWN 优先、OFF_TASK 迟滞。
- ADVISORY/STANDARD/STRICT 纯策略；所有限制动作保持 dry-run。
- Command 的设备/时间/state/version/idempotency/lease 安全边界。
- Emergency Release、Ordinary Override、10 分钟 break + replan。
- 外部事件到 PlanVersion 的同事务编排与重复事件结果恢复。
- Agent 自动注册、active-session 同步、SQLite 断网队列。
- PWA 今日计划、任务、状态、Session、安全解除、审计视图。
- AI Mock/Offline Provider、结构校验、同步 AIJob、失败不影响确定性 Planner。
- Alembic、Docker Compose 定义、测试和真实进程重启恢复。

### 1.2 明确未实现或未启用

- 摄像头、音频、完整截图、按键内容、剪贴板。
- 原生 iOS、真实电话、移动推送、NAS 实机 profile。
- Codex runtime、向量数据库、外部消息总线、Kafka、Kubernetes。
- 真实 blocklist、process termination、注册表/防火墙/计划任务、自启动。
- 真正可点击的 Windows 四选一确认结果回传、托盘/热键式本地 Emergency UI。
- 多设备 lease 选举/handoff、Recovery 自动生命周期、AI worker queue。
- 自动 daily summary、backup/restore、摄像头 presence prototype。

这些属于 V2 或产品微调，不应从现有表名、枚举或 UI 文案反推为已经完成。

## 2. 环境检查、技术选型与实施组织

### 2.1 环境检查结果

| 项目 | 结果 | 影响 |
|---|---|---|
| OS / Shell | Windows / PowerShell | Windows Agent 可在真实宿主采样 |
| Python | 3.12.7 | 满足 Core/Agent `>=3.12` |
| Node/npm | Node 24、npm 11 | Web 构建和测试通过 |
| Git | 2.55，仓库初始无提交 | 本次按 Phase 形成独立提交 |
| Docker CLI | 29.x | Compose 配置可验证 |
| Docker daemon | 不可用，服务停止且无启动权限 | 不能声称镜像构建/容器启动 |
| PostgreSQL 在线验证 | WSL 用户态 PostgreSQL 18.3，127.0.0.1:54330 | Alembic、真实事务、重启恢复通过 |
| 初始工作树 | 除用户的 `research_data.db` 外为空 | 该数据库未读取、未修改、已加入忽略规则 |

### 2.2 最终技术选型

| 层 | 选择 | 原因 |
|---|---|---|
| Core | Python 3.12 + FastAPI + Pydantic v2 | 显式契约、类型化 API、易测 |
| Persistence | SQLAlchemy 2 + Alembic + psycopg 3 | 成熟迁移、PostgreSQL、事务/OCC |
| Database | 部署目标 PostgreSQL 16 | 与冻结基线一致；测试另有 SQLite 快速后端 |
| Web | React 18 + TypeScript 5 + Vite PWA | 小型、可安装、无服务端 UI 状态 |
| Windows Agent | Python + `ctypes` + `psutil` + `httpx` | 能限定 Windows capability 边界 |
| Agent queue | 本地 SQLite | 离线 store-and-forward，不引入消息总线 |
| Core queue | PostgreSQL Outbox/Command 表 | 单体事务边界，避免 V1 外部 broker |
| Tests | pytest、jsonschema、Vitest、Ruff、MyPy | 契约/逻辑/集成/安全多层证据 |

选择 SQLAlchemy/Alembic 的收益、成本和迁移风险记录在 ADR-0001；V1 安全执行
边界在 ADR-0002；契约/事件边界在 ADR-0003；事件编排与 replay 在 ADR-0004。

### 2.3 仓库结构

```text
LiFeOs/
├─ contracts/              # 10 类冻结 JSON Schema + common scalars
├─ docs/                   # 架构、不变量、状态机、规划、安全、验收、ADR
├─ backend/
│  ├─ lifeos/              # FastAPI、领域 schema、planner/runtime/policy/services
│  ├─ migrations/          # Alembic 0001 Core schema
│  └─ tests/               # 53 个测试
├─ windows-agent/
│  ├─ src/lifeos_windows_agent/
│  └─ tests/               # 24 个测试
├─ web/
│  ├─ src/                 # React PWA
│  └─ public/              # manifest、静态 service worker、SVG icon
├─ compose.yaml            # postgres/api/web
├─ README.md               # 启动与验证入口
└─ LiFeOS_V1_REPORT.md     # 本报告
```

### 2.4 子 Agent 分工与集成责任

| 工作流 | 责任 | 总协调处理 |
|---|---|---|
| Architecture/Contracts | 契约、迁移、实体、不变量 | 冻结字段、补充 ADR、纠正文档过度声明 |
| Core/Persistence | SQLAlchemy/Alembic/PostgreSQL | 在线 PG 验证、事件编排、并发/时序修复 |
| Planner/Runtime/Policy | 确定性算法、状态和安全策略 | 命名场景集成、阈值边界复核 |
| Windows Agent | 采集、capability、HTTP/SQLite | 补自动注册、active-session 和重启队列测试 |
| Web UI | React/PWA 四视图和安全操作 | 真实 Core/PG 浏览器端到端试跑 |
| AI/Memory | Provider、AIJob、Context Builder | offline/invalid fail-closed 验证 |
| QA/Security | 门禁矩阵、V1/V2 越界审计 | 修复 ACK Core 时间、乱序 heartbeat、负例矩阵 |

共享契约先冻结，后续模块依次依赖：

```text
contracts → persistence/migration → Core services → planner/runtime/policy
          → HTTP API → Windows Agent/Web → scenario/failure/real-process checks
```

### 2.5 主要风险现状

| 风险 | 当前控制 | 剩余风险 |
|---|---|---|
| 错误强制/锁机 | V1 没有真实执行能力、全局 dry-run | V2 前必须加入本地 Emergency UI 与故障注入 |
| 断网重放旧命令 | TTL、state binding、Core receipt time、状态持久化 | 设备时钟同步/签名命令仍是 V2 |
| 传感器误判 | 45 秒覆盖、0.65 confidence、UNKNOWN 优先、迟滞 | app profile 仍需个人化标定 |
| 计划抖动 | freeze horizon、debounce、每小时上限、确定性重排 | horizon 外尚无旧时段稳定性代价；触发语义和冻结例外需实际使用调整 |
| 隐私 | 字段白名单、标题 256 字、无敏感传感器 | 标题仍可能敏感；队列未加密；保留清理未自动化 |
| 数据丢失 | PostgreSQL、迁移、append-only history、Agent SQLite | backup/restore 和 outbox dispatcher 属于 V2 |
| AI 不可用/幻觉 | AI 非权威、结构校验、失败隔离 | 当前 AIJob 同步且只有 Mock/Offline |
| 本地认证 | bearer token、CORS | 单 token、无 TLS/多用户；默认 token 不会自动拒绝 |
| 部署可移植性 | Compose 配置、真实 PostgreSQL 验证 | 本机未实际构建 PG16 Docker 镜像 |

## 3. 架构与权威边界

### 3.1 模块化单体

FastAPI 进程内包含 API、application services、planner、runtime reducer、policy、
command guard、AI provider port。模块之间通过类型化 Python 对象和数据库事务
协作，而非网络微服务。PostgreSQL 同时保存权威业务状态、EventLedger、Outbox
和命令队列。

事务由每个 HTTP 请求的数据库 session 管理：成功时整体提交，异常时回滚。典型
外部 replan event 会在同一事务中写 EventLedger/Outbox、生成 PlanVersion、写
ScheduleBlock、移动 PlanHead，并写 `PLAN.VERSION_CREATED` 因果审计。

### 3.2 唯一事实源

- Core/PostgreSQL：Task、当前 plan head、历史 plan、session、runtime head、命令状态。
- Web：只保存连接设置和当前 tab 的 session UUID，不是业务事实源。
- Agent：SQLite 保存未发送 envelope/ack、已处理 command ACK 和最新 state version，只为
  可靠传输；active assignment 只在进程内存中，重启后重新向 Core 获取。
- AI：只返回建议；失败、离线或 schema 无效都不改变确定性基本能力。

### 3.3 事件语义

外部 `POST /api/v1/events` 只在 `event_type` 精确等于冻结 PlanTrigger 时自动
replan。此时 `payload` 必须可校验为 PlanRequest，Core 强制使用 envelope 的
`event_type` 作为 trigger、`occurred_at` 作为 `now`。

顺序重放相同 idempotency key 且语义内容一致时，Core 不再运行 planner，而是沿
`causation_id` 找回原 PlanVersion ID 并返回。调用方新给的 `event_id` 和 Core 接收时钟
`received_at` 不参与重放语义；其余 envelope 语义字段不同则是 409。并发同 key 由数据库唯一约束
阻止第二份副作用，但竞争请求可能收到 409，并不保证拿到原 outcome。
非触发事件只进入账本/Outbox，无隐式计划副作用。

直接 Task/FixedEvent CRUD 与所有 Session transition 并不自动等价为外部触发
事件；这个边界是当前最重要的产品微调项之一。

## 4. 冻结契约、API 与错误模型

### 4.1 十类契约

`contracts/` 提供 Draft 2020-12 JSON Schema：Event Envelope、Observation、
RuntimeState、Command、PlanVersion、Task、Device Heartbeat、Role Lease、AI
Planning Request/Response、Error Response。`common.schema.json` 保存 UUID、UTC
时间、reason code 等共享定义。

安全契约采用 extra-forbid/封闭枚举思想。Command 不接受任意 shell 字段，必须有
UUID、target、issued/not-before/expires、required state version、idempotency key、
typed payload、dry-run、reason codes。契约负例逐项验证缺失或非法安全字段。

### 4.2 时间、ID、并发和幂等

- 重要实体 UUID；计划 revision 是本地日期 + 时区范围内单调递增。
- 数据库存 UTC aware datetime；请求可带任意合法时区偏移，进入领域后归一到 UTC。
- 日历边界用 IANA 时区解释，默认 `Asia/Shanghai`。
- 可修改 aggregate 使用 `expected_version`；不匹配返回 409。
- Observation、Event、Ack、Command、AIJob 等外部/副作用路径有唯一 idempotency key。
- append-only 对象不提供 update API；EventLedger 的不可变性是服务约定，不是 DB trigger。

### 4.3 HTTP surface

| 范围 | 端点 |
|---|---|
| 健康 | `GET /health`、`GET /ready` |
| Task | `POST/GET /api/v1/tasks`、`GET/PATCH/DELETE /api/v1/tasks/{id}` |
| FixedEvent | `POST/GET /api/v1/fixed-events`、`GET/PATCH/DELETE .../{id}` |
| Plan | `POST /api/v1/plans/generate`、`GET .../current`、`GET .../history` |
| Device | 注册/list/get、幂等 `PUT .../{id}` enrollment、heartbeat |
| Assignment | `GET /api/v1/devices/{id}/active-session`，无 assignment 返回 204 |
| Observation/State | `POST /api/v1/observations`、`GET .../runtime-state` |
| Session | start/get、break、emergency-release、ordinary-override、pause/resume/complete/abort |
| Command | device poll、ACK |
| Event | append/orchestrate、list |
| AI | 同步提交/执行 AI job |

正常配置下，受保护的 `/api/v1/*` 端点使用一个开发 bearer token；若显式把
`LIFEOS_DEV_AUTH_TOKEN=''` 设为空，鉴权会完全关闭。源码 Settings 还有固定开发 fallback，
只有 Compose 强制要求非空 secret；`/health` 和 `/ready` 始终不要求 token。错误响应采用
`application/problem+json`，包含 `error_code`、
`reason_codes`、correlation UUID 和字段 errors。当前不是生产认证：无用户身份、
token rotation、TLS 或 signed device identity。

## 5. 数据模型和生命周期

迁移建立 19 张领域表，另有 Alembic 自身的 `alembic_version`：

| 表/实体 | 作用 | 更新方式 |
|---|---|---|
| `tasks` | 任务约束、app profile、剩余时间 | OCC；DELETE 是状态改为 CANCELLED |
| `fixed_events` | 一次性硬固定事件与显式 travel | OCC；DELETE 为物理删除并先审计 |
| `plan_versions` | 不可变计划版本/冲突/参数 | 只插入 |
| `plan_heads` | 某日期+时区当前 non-INFEASIBLE 计划（FEASIBLE/PARTIAL） | 事务内移动 |
| `schedule_blocks` | 计划内固定/任务/meal/travel/break/buffer | 随版本只插入 |
| `execution_sessions` | block 的执行、authority、状态/override | OCC；终态不可复活 |
| `devices` | 设备身份、能力、heartbeat、在线头状态 | OCC/heartbeat 更新 |
| `observations` | 原始白名单 evidence | 只插入、幂等 |
| `feature_snapshots` | 60/300 秒派生特征 | 只插入；不保证精确历史重建 |
| `runtime_states` | 多轴状态估计 | 只插入、state_version |
| `runtime_state_heads` | 每设备最新状态 | 原子移动 |
| `device_role_leases` | role/TTL/state 授权结构 | V1 表/契约，选举属 V2 |
| `policy_decisions` | 精确输入 state 和策略结果 | 只插入、幂等 |
| `commands` | typed command 与交付状态 | 有限状态更新 |
| `command_acks` | Agent 结果 | 只插入、幂等 |
| `event_ledger` | 审计、correlation、causation | 应用层 append-only |
| `outbox` | 与事件同事务的待发布记录 | V1 无通用常驻 dispatcher |
| `ai_jobs` | provider 请求/响应/失败 | OCC；V1 同步执行 |
| `daily_summaries` | 日总结结构 | V1 scaffold，无自动调度 |

不可行 PlanVersion 仍被持久化以保留证据，但不会替换当前 PlanHead。早期
PlanVersion 和其 blocks 永不覆盖。一个设备同时最多一个 non-terminal session，
Session start 对设备行加锁以避免并发双启动。

## 6. 确定性 Planner/Replanner

### 6.1 输入默认

| 参数 | 当前默认 | 允许范围 |
|---|---:|---:|
| focus | 50 min | 10–90 |
| break | 10 min | 5–30 |
| max focus | 90 min | 10–120，且不小于 focus |
| buffer | 10% | 0–50% |
| freeze horizon | 15 min | 0–120 |
| automatic debounce | 120 s | 0–3600 |
| automatic replans/hour | 3 | 0–20 |
| day horizon | 07:00–23:00 local | request 字符串可改 |
| lunch | 30 min，11:30–13:30 | 目前代码常量 |
| dinner | 30 min，17:30–19:30 | 目前代码常量 |

### 6.2 算法顺序

1. 把本地日期/时区转换成 UTC 日界，检查 HARD fixed event 重叠。
2. 放置 fixed event 及显式 `travel_before/after`；不调用地图推断。
3. 在窗口内选择最早可行的午餐、晚餐 30 分钟；不能放置即冲突。
4. 计算剩余 free intervals。
5. 对 flexible time 计算 10% buffer，向下取 5 分钟，放在区间末端。
6. Task 排序：deadline 已过/有 deadline → mandatory → deadline pressure →
   priority 数字较大 → deadline 较早 → UUID 稳定 tie-break。
7. 只在 location/capability 匹配的 interval 装填，chunk 不小于 task minimum，
   通常 50 分钟，绝不超过 max focus。
8. focus 后插 break；已有 fixed/meal/buffer 足够长时可充当间隔。
9. 校验 HARD、mandatory、所有带 deadline 的剩余工作、meal/travel/minimum chunk、
   horizon 和 non-overlap。
10. 返回 FEASIBLE、PARTIAL 或带结构化 conflicts 的 INFEASIBLE。

`deadline_pressure = remaining_minutes / max(deadline 前可用分钟, 1)`。当前实现把
“有 deadline”都保守地当作必须在 deadline 前排完，没有 hard/soft deadline 字段。
可选任务排不完可 PARTIAL；mandatory 或有 deadline 任务排不完会 INFEASIBLE。

### 6.3 Replan

唯一允许 trigger：`DAY_STARTED`、`USER_REQUESTED_REPLAN`、
`TASK_COMPLETED_EARLY`、`TASK_OVERRUN`、`BLOCK_MISSED`、
`FIXED_EVENT_CHANGED`、`USER_REPORTED_FATIGUE`、`USER_REPORTED_EMERGENCY`、
`SESSION_ABORTED`、`AVAILABLE_TIME_CHANGED`。

`USER_REQUESTED_REPLAN` 和 `USER_REPORTED_EMERGENCY` 免 debounce/每小时上限；
其他触发视为 automatic。过去一小时内同日期/时区的 accepted automatic plan
持久化计数，间隔小于 120 秒拒绝；滚动一小时已有 3 个 accepted automatic plan 时
拒绝本次。非紧急 replan 会冻结
`[now, now+15min)` 内的 TASK/BREAK/BUFFER；紧急不冻结。V1 尚不会自动剔除与新
fixed event 冲突或已不可能的 frozen block，也没有 horizon 外的旧时段 jitter cost；
其余工作由确定性排序重新安置。

每个 accepted attempt 都创建新 PlanVersion；INFEASIBLE 不替换 plan head。break
端点在同一请求事务内尝试暂停 session、发 `RELEASE_ALL`，并用
`USER_REPORTED_FATIGUE` 重排。该 trigger 受 automatic debounce/每小时上限：被拒绝时
返回 429 且整笔事务回滚；被接受时仍可能得到不会移动 plan head 的 INFEASIBLE 版本。

## 7. RuntimeState：观察、特征、状态

### 7.1 独立轴

- context：FOCUS/CLASS/BREAK/MEAL/TRAVEL/FREE/SLEEP/RECOVERY/EMERGENCY/UNPLANNED。
- presence：PRESENT/ABSENT/UNKNOWN。
- engagement：ON_TASK/OFF_TASK/IDLE/UNKNOWN。
- session_state：PLANNED/DUE/STARTING/RUNNING/PAUSED/INTERRUPTED/RECOVERY/COMPLETED/ABORTED/MISSED。
- device_role：PRIMARY_INTERACTION/PRIMARY_ENFORCEMENT/SENSOR/NOTIFICATION_ONLY/AI_WORKER/STANDBY。

每一状态都含 confidence、reason_codes、valid_until、递增 state_version 和 FeatureRead。
Observation reduction 的 state 关联持久 FeatureSnapshot；start/break/override/emergency
等 Session workflow 生成的是零覆盖 synthetic features，不关联 FeatureSnapshot row。
V1 observation reduction 时设备角色写 SENSOR；真正 role election 属 V2。

### 7.2 Agent 自动采集、传输与契约字段

Windows collector 自动采集的 evidence 只有：

- foreground process basename；路径只用于提取名称。
- window title，最多 256 个字符。
- idle seconds。
- PC lock/unlock evidence。

Agent 另外在 Observation 顶层传输 Core 分配的 LifeOS session UUID，并发送 heartbeat
和 sensor status；这些是调度/健康元数据，不是 collector 从桌面内容中采集的字段。
契约允许 `client_session_state` 和 `manual_presence`，但当前 Windows Agent 不设置前者，
也没有自动采集或 UI 来产生后者。

禁止按键内容、clipboard、截图、音频、视频。Windows collector 失败产生
`sensor_ok=false`，不会伪造活动。

### 7.3 窗口和阈值

- short window 60 秒，medium window 300 秒。
- 每个 activity sample 默认最多代表 15 秒，且不会越过下一 sample 或 `now`。
- short-window coverage 少于 45 秒时（未 lock）视为 insufficient。
- confidence 默认为 `coverage60/60`；lock evidence 为 1，sensor conflict/failure 为 0。
- confidence <0.65、冲突、故障、覆盖不足优先 UNKNOWN。
- allowed ratio >=0.75 是 ON_TASK candidate。
- blocked 连续 >=30 秒或 blocked ratio >=0.60 是 OFF_TASK candidate。
- 连续两个 candidate estimate（间隔 0–90 秒）或 blocked 连续 90 秒才进入 OFF_TASK。
- OFF_TASK 后，allowed 连续 30 秒退出；否则维持迟滞。
- idle seconds 严格大于 task tolerance 才为 IDLE；Task 默认 300 秒。
- 在 coverage/confidence 足够且无 conflict/failure 的前置门通过后，manual ABSENT 连续
  90 秒令 RuntimeState 的 session_state 为 INTERRUPTED。
- lock 令 presence/engagement UNKNOWN，并令派生 RuntimeState 的非终态 session_state
  为 INTERRUPTED；不推断物理 ABSENT。

优先级是 uncertainty/safety → interruption → idle → engagement hysteresis。重复
observation key 返回当前状态，不产生新 feature/state/decision/command。
当 observation 关联到非终态 session 时，这两种中断会在同一 ingest 事务中同步把权威
`ExecutionSessionRow.session_state` 改为 INTERRUPTED；终态不会被复活或覆盖。

### 7.4 App profile 语义

每个 Task 可提供 allowed/blocked apps，统一转小写 basename。两集合必须不相交。
Runtime 对所有 session 额外加入全局默认 `cs2.exe` blocked。allowed 集为空不会
把任意应用当作 allowed，因此可能长期 UNKNOWN/OTHER；这需要按实际任务配置。

## 8. 干预、解除与 Command 安全

### 8.1 Commitment mode

- ADVISORY：通知和建议；180 秒后仍只给选择建议。
- STANDARD：显示置顶信息提示；V1 仅记录 10 分钟 WOULD_BLOCK。
- STRICT：纯策略还能产生 15 分钟 Recovery dry-run；真实执行关闭。

mode 在 session start 时冻结，之后不能升级权限。Session 实际 `dry_run` 来自 Core
安全配置，V1 必须为 true。

### 8.2 精确级别边界

| Level | 代码边界 | V1 结果 | Command TTL |
|---|---|---|---:|
| 0 | 非有效 RUNNING OFF_TASK，或 `<30s` | NONE | 无 |
| 1 | `30s <= t < 90s` | SHOW_NOTIFICATION | 60s |
| 2 | `90s <= t <= 180s` | confirmation；ADVISORY 为 notification | 120s / 60s |
| 3 | `t >180s`、mode>=STANDARD | WOULD_BLOCK 10min | 60s |
| 4 | STRICT、ignored>=2 | Recovery WOULD_BLOCK 15min | 60s |
| 5 | ignored>=3 | interrupt/replan notification | 60s |

策略要求 state 有 session、RUNNING、OFF_TASK、confidence>=0.65 且 `now < valid_until`。
这里的 `t` 是连续“已确认 OFF_TASK”的 RuntimeState 历史时长；第一条 OFF_TASK state
的 `t=0`，不是从更早的原始 blocked foreground evidence 起算。
表中 TTL 是命令类型的名义上限；policy 取它与 RuntimeState `valid_until` 的较早者，
当前状态通常只有效 30 秒。
同一 session/state/level/mode 使用确定性 UUID/idempotency。RuntimeService 当前把
`ignored_prompts=0`，因此 Level 4/5 只在纯 policy 单元测试中可达，尚未形成业务闭环。

Windows Level-2 目前使用只有 OK 的置顶 MessageBox 列出四段文字；它不会随 Command
TTL 自动关闭。Agent 回传的 ACK 状态是 `EXECUTED`，`details.outcome` 才是
`CONFIRMATION_SHOWN`。它不是四个真正可区分并回传 Core 的按钮。Web 提供 break、
replan、结束等独立控制，但不能替代未来 Agent 本地确认闭环。

### 8.3 Command guard

Command 包含 target、session/decision、authority、risk、issued/not-before/expires、
required state version、idempotency、typed payload、dry-run、reason codes。普通
command polling 会检查：

- `now >= expires_at` 立即过期；expiry 边界不执行。
- current state version 必须完全相同。
- target device 必须相同。
- hard command 还需 Core 全局 dry-run 关闭、real-enforcement feature flag 开、持久化的
  device 状态为 online/core reachable、有效 PRIMARY_ENFORCEMENT lease 且 lease 未
  撤销/未过期。
- schema 把单个 duration 限制为最多 1800 秒（30 分钟）。

这是当前 partial hard-row branch，不是完整 V2 guard：它不检查 Command row 自身的
`dry_run`，poll 时不按 heartbeat age 刷新设备状态，也尚未重新验证 active session、
session preauthorization、blocklist membership、payload duration 与 lease state version。
因此真实 enforcement 不能启用。

Agent 也在本地检查 device、not-before、TTL、state、lease，并拒绝 V1 不支持的
`START_BLOCK`/`ENTER_RECOVERY`。ACK 的 ACCEPTED/EXECUTED 同时按 Agent
`acknowledged_at` 和 Core 实际接收时间检查 TTL，防止设备回填旧时间绕过过期；这个
双时钟拒绝不适用于 fail-open 的 `RELEASE_ALL` ACK，Core 对后者跳过 state/TTL 检查。

`RELEASE_ALL` 是故意的安全例外：仍要求正确 target 和 TTL，但可绕过 state mismatch，
以免状态变化阻止解除。Core restart 后只 poll PENDING/DELIVERED 且仍有效的 command；
已过期或已 ACK 不重放。

### 8.4 三种用户动作

- Break：需要 expected version，5–30 分钟，默认 10；仅 RUNNING/INTERRUPTED 且其 plan
  仍为 current head 时可尝试暂停、释放、重排，并仍受 automatic throttle/feasibility。
- Ordinary Override：需要 expected version 和非空 reason；审计后解除，不等于完成。
- Emergency Release：不要求 expected version，要求稳定 idempotency key。Core/数据库
  可达时，其事务在响应前取消该 Session 的 pending/delivered enforcement、排队一个
  五分钟 TTL 的 RELEASE_ALL，并在所选 Session 非终态时将它置 INTERRUPTED；终态保持不变。
  设备实际解除依赖 Agent 异步 poll/执行。

相同 Emergency key + 相同请求不重复副作用，但返回查询时的当前 Session row，并非
持久化的第一次响应快照；相同 key + 不同 reason 返回冲突。Agent
内部有离线 `release_all()`，但 V1 没有托盘/热键/本地 UI 入口。由于 V1 根本没有
真实限制，不存在被锁风险；启用任何真实限制前这必须变成阻断门禁。

## 9. Windows Agent

### 9.1 默认配置

| 配置 | 默认 |
|---|---|
| Core | `http://127.0.0.1:8000` |
| device ID | hostname + `uuid.getnode()` 派生的稳定 UUIDv5 |
| device name | Windows hostname |
| queue | `%LOCALAPPDATA%\LifeOS\agent-queue.db` |
| heartbeat | 15 秒，禁止配置得更短 |
| activity sample | 5 秒 |
| command poll | 5 秒 |
| HTTP timeout | 5 秒 |
| clock skew allowance | 0 秒 |
| Agent version | 0.1.0 |

环境变量为 `LIFEOS_CORE_URL`、`LIFEOS_DEVICE_ID`、`LIFEOS_DEVICE_NAME`、
`LIFEOS_DEV_TOKEN`、`LIFEOS_AGENT_DB`、`LIFEOS_HEARTBEAT_SECONDS`、
`LIFEOS_SAMPLE_SECONDS`、`LIFEOS_COMMAND_POLL_SECONDS`、
`LIFEOS_REQUEST_TIMEOUT_SECONDS`、`LIFEOS_CLOCK_SKEW_SECONDS`。

### 9.2 注册、assignment 和断网

sample 与 heartbeat 先共享 single-flight enrollment。Core 的幂等 PUT 接受稳定
UUID；同 UUID/同 device type 返回已有设备，同 UUID/不同 type 冲突。已有记录的 name
不会因 enrollment 自动改名；capabilities 会由后续 heartbeat 刷新。

每次 activity sample 前查询 active session：200 更新、204 权威清空、断网/5xx 在当前
进程内保留最后已知 assignment。Observation 因此携带采样时的 session context；Agent
重启后 assignment 从空开始并重新查询 Core，不由 SQLite 恢复。失败的 enrollment 不会
丢采样，envelope 仍进入 SQLite，下一周期重试。

SQLite outbox 对当前到期项目按最老优先、保留原 key；同 key 的 row 仍在 outbox 时，
不同 payload 冲突。发送成功会删除 row，因此 V1 本地库不永久保留已发送 envelope key，
之后复用同 key 可以重新入队，但 Core 仍会按其持久幂等记录处理。
失败项目退避期间，较新的到期项目可以先发送，而某失败项重新到期后会停止该轮批次。
关闭再打开数据库后 queue 和 state 均保留。不同 key 的旧 heartbeat 可进入事件证据，但不会把 Core 的
`last_heartbeat_at` 倒退。Agent 不安装 service/autostart。

## 10. Web/PWA

Web 有四个主要视图：今日计划时间线、Task CRUD、设备/Runtime/Session、安全状态、
append-only 审计。可生成当天计划、手动 replan、启动 session、pause/resume/complete/
abort、break、Ordinary Override、Emergency Release。

没有 seeded/fallback 业务假数据；Core 离线、无计划、UNKNOWN、过期状态都会显式显示。
健康状态每 15 秒刷新。Emergency 确认框打开时生成一个 key，失败重试沿用同 key。

- API base 与展示时区：`localStorage`。
- bearer token 与 active session UUID：`sessionStorage`，关闭 tab/session 后消失。
- 静态 service worker 只缓存 app shell，不缓存 `/api/*`、`/health`、`/ready`。
- 默认 Core URL `http://localhost:8000`，默认展示时区 Asia/Shanghai。
- 当前无 Session list API；Web 从刚启动的 session、RuntimeState 或手填 UUID 恢复。
- Core 已有 per-device active-session API，Web 尚未自动采用它。
- PWA icon 是 `sizes:any` SVG；老平台可能更偏好 PNG 尺寸集合。

## 11. AI、Context Builder 与总结

V1 默认 `MockAIProvider`；测试提供 `OfflineAIProvider` 和无效响应。AIJob 当前在 HTTP
请求内同步执行，不是后台 worker。Provider 输出必须匹配 AI Planning Response；异常、
离线或 invalid schema 会把 job 标 FAILED、`fallback_used=true`，确定性 planner 和
当前计划不受影响。

Context Builder 默认边界包含：current time、RuntimeState、current plan/current block、
未来最多 3 blocks、today progress、unfinished tasks（schema 上限 256）、active incident、
policy constraints。接口没有完整 Archive 输入，测试断言不会默认读取全历史。

`DailySummary` 表和 Context Builder 是 V1 scaffold。自动日/周总结、检索同任务历史、
过去七天同一时段、embedding、AI job queue/Codex Adapter 属 V2。

## 12. 部署与恢复

Compose 定义：

| 服务 | 镜像/构建 | 端口 | 恢复行为 |
|---|---|---:|---|
| postgres | `postgres:16-alpine` | `127.0.0.1:54329→5432` | named volume `lifeos-postgres` |
| api | `python:3.12-slim` 构建 | `127.0.0.1:8000→8000` | 启动前 `alembic upgrade head` |
| web | Node 24 build + nginx 1.27 | `127.0.0.1:5173→80` | 静态 PWA；依赖 API healthy |

Core 源码 Settings 的开发默认 URL 指向本机 54329，并含固定开发凭据；Compose 覆盖为
`postgres:5432` 并从必填环境变量取密码。这里“SQLite 只在测试显式传入”仅指 Core；
Windows Agent 的正常离线 queue 本来就是 SQLite。配置还包括 display timezone、dry-run、
real-enforcement flag、dev token、CORS origins。`docker compose config` 的 PASS 是在验证时
提供临时非空密码/token 变量所得；裸跑缺少这些必填变量会故意失败。

Core 重启从 plan head/runtime head/session/command/event 表恢复。不会覆盖旧 plan，也不会
重新执行 expired/ACK command。Outbox 能保证业务事实与待发布记录同事务，但 V1 没有
常驻通用 dispatcher；当前 command 使用 polling，事件副作用在请求事务内完成。

## 13. 最终验证证据

### 13.1 自动门禁

| 门禁 | 结果 |
|---|---|
| Backend pytest（含在线 PostgreSQL） | 53 passed（最终全量复核） |
| Backend Ruff | All checks passed |
| Backend strict MyPy | 25 source files，0 issues |
| Windows Agent pytest | 24 passed，0.88s |
| Agent Ruff | All checks passed |
| Agent strict MyPy | 11 source files，0 issues |
| Web Prettier | 全部匹配 |
| Web TypeScript | 通过 |
| Web Vitest | 2 files / 9 tests passed |
| Web production build | 通过；JS gzip 59.66 kB |
| npm audit（官方 registry） | 0 vulnerabilities |
| Compose config | 通过；services=postgres/api/web |

唯一测试 warning 是当前 Starlette TestClient 对 `httpx` 兼容层的弃用提醒；不影响测试
结果，但后续依赖升级时应迁移到新 test client 组合。第一次 `npm audit` 使用用户配置的
`npmmirror.com` 返回“endpoint not implemented”，随后用 npm 官方 registry 成功复核，
因此 0 漏洞结论来自可用审计服务，而不是忽略错误。

### 13.2 真实 PostgreSQL 与进程恢复

- 在隔离用户态 PostgreSQL 18.3 执行 Alembic `upgrade head`，revision 为
  `0001_core_schema`。
- 检查到 19 张要求的领域表 + `alembic_version`，关键 unique/check/index 存在。
- `LIFEOS_TEST_POSTGRES_URL` 在线测试通过。
- 真实 uvicorn 进程写入 plan revision 2、RUNNING session、RuntimeState；停止进程后
  启动独立新进程，ID/revision/session/state 均恢复，已消费命令不重放。
- Compose 目标是 PostgreSQL 16；PG18 验证证明在线 PostgreSQL 语义，但不能替代“已在
  本机运行 PG16 容器”的声明。待 Docker daemon 可用后应补一次 `compose up --build`。

### 13.3 真实 Web/Agent 集成 smoke

- Web 使用真实 bearer token 连接真实 Core/PG，创建 Task，生成 revision 1，手动 replan
  到 revision 2，查看审计。
- 浏览器桌面和 390×844 移动视口均可操作，控制台无 warning/error。
- 实际 Windows Agent 一次运行自动注册稳定 UUID、采集前台/idle、发送 heartbeat 和
  observation，outbox 归零。
- Web 显示设备 ONLINE；初期 evidence 不足时 RuntimeState 正确为 UNKNOWN。
- 启动真实 STANDARD dry-run session 后，Agent 自动取得 active assignment，下一条
  observation 携带该 session ID。
- 这次人工真实进程 smoke 未驱动 Agent 的 command escalation/ACK；该链路由 13.4 的
  自动化端到端场景和 Agent command/queue 测试覆盖。

### 13.4 冻结命名场景

一个端到端场景测试函数完成：三段固定课程 + English/Research → 初始计划 → 模拟迟到的
`AVAILABLE_TIME_CHANGED` → revision 2 且保留 revision 1 → 启动 STANDARD session →
allowed samples → 21 个间隔 15 秒的 `cs2.exe` samples → OFF_TASK → NOTIFY/CONFIRM/
WOULD_BLOCK → 重复 observation 无副作用 → 插入 10 分钟 break/revision 3 → release ACK →
Emergency Release/replay/conflict → restart → plan/session/event 恢复且 command 不重放 →
重复迟到 event 返回原 plan ID → AI offline job 失败但当前计划继续可用。

详细 Gate 到测试映射见 `docs/v1-acceptance.md`。

## 14. 验收矩阵

### 14.1 V1

| Gate | 状态 | 关键证据/限定 |
|---|---|---|
| V1-01 PostgreSQL migration | PASS | 在线 Alembic + 19 张领域表/约束检查 |
| V1-02 CRUD/UTC/OCC | PASS | Task/FixedEvent API、UTC runtime normalization、409 stale write |
| V1-03 契约安全负例 | PASS | JSON Schema + Pydantic runtime 对 UTC/reason codes 对齐 |
| V1-04 三课程两任务计划 | PASS | planner golden + named scenario |
| V1-05 迟到新 revision | PASS | event side effect，旧 plan 完整保留 |
| V1-06 不可行冲突 | PASS | structured conflict；不可行不移动 head |
| V1-07 commitment/dry-run | PASS | snapshot 仅含 mode/dry_run/allowed_actions；mode immutable |
| V1-08 cs2→OFF_TASK | PASS | 60/300 window、45s coverage、hysteresis |
| V1-09 提醒/确认/WOULD_BLOCK | PASS | typed SAFE commands；无 OS block |
| V1-10 休息重排 | PASS | 10 分钟 break、PAUSED、release、revision 3 |
| V1-11 heartbeat | PASS | 15/45、replay、乱序不倒退、>5min future 拒绝 |
| V1-12 command safety | PASS | expiry/state/target/idempotency/ACK Core-time |
| V1-13 Emergency | PASS | Core 事务取消/排队 RELEASE_ALL；设备异步；terminal 不复活 |
| V1-14 restart | PASS | 自动场景 + 真实 PG/独立 uvicorn 进程恢复 |
| V1-15 AI isolation | PASS | offline/invalid job FAILED；deterministic Core 独立 |
| V1-16 event replay | PASS | 顺序 replay 仅一份 ledger/outbox/plan side effect、stable ID |
| V1-17 Windows Agent | PASS | 字段白名单、自动注册/session、SQLite reopen、真实试跑 |
| V1-18 Web | PASS | 9 tests、build、desktop/mobile + real Core/PG smoke |
| V1-19 V1 安全边界 | PASS | Python 源码有限 token/import assertion + adapter test + 全树人工审计 |

这里的 PASS 是对冻结 gate 的结论。后续章节列出的 UX/产品闭环缺口并不把测试
结果改成失败，但它们会决定该系统是否适合进入你日常长期使用。

### 14.2 V2 边界

| V2 能力 | 当前状态 | V1 中已有的准备 |
|---|---|---|
| NAS Compose profile | NOT STARTED | 普通 local Compose |
| Role Lease 选举/handoff | SCAFFOLD ONLY | table/schema/poll response/guard 部分检查 |
| 移动推送/Notification Provider | NOT STARTED | typed notification Command |
| 真实 blocklist | FEATURE OFF / ADAPTER ABSENT | WOULD_BLOCK 和应用列表 |
| Recovery lifecycle | PURE POLICY ONLY | Level 4 输出，未接 ignored prompt/runtime |
| AI queue/worker/Codex | NOT STARTED | AIJob、Provider、Mock/Offline、Context Builder |
| Camera presence | NOT STARTED | V1 没有 camera code，符合边界 |
| Daily summary | SCAFFOLD ONLY | table，无 scheduler |
| Backup/restore | NOT STARTED | PostgreSQL persistence/migration |
| 故障注入 | PARTIAL | AI/network/TTL/restart/replay；无 VPN/camera/lease 故障 |

不要因为 `DeviceRoleLease`、`DailySummary`、`ENTER_RECOVERY` 枚举已经存在，就把
对应 V2 工作视为可用。

## 15. 最终审计中已修复的隐蔽问题

这些问题不是“报告备注”，而是在收尾审计后已经进入代码和回归测试的修复：

1. **不可行 revision 卡死**：PlanHead 不移动时，下一次曾会重复使用 revision。现在
   从该日期/时区历史最大 revision + 1 分配；已测试 FEASIBLE v1 → INFEASIBLE v2 →
   FEASIBLE v3。
2. **Session scope 切换 422**：Runtime head 是 per-device，旧 session-bound state 曾会
   与后续 `session_id=null` evidence 冲突。现在 scope 变化时重置 hysteresis previous，
   state_version 仍保持设备级单调。
3. **45 秒覆盖阈值不一致**：feature 虽标 insufficient，reducer 曾只看 0.65 confidence。
   现在 `<45s` 明确 UNKNOWN，44/45 秒边界有测试。
4. **break 参数失效**：判断“现有休息是否足够”曾硬编码 10 分钟；现在使用请求的
   `break_minutes`。
5. **终态被解除操作复活**：Emergency 现在仍始终 release，但保持 COMPLETED/ABORTED/
   MISSED 终态；Ordinary Override 拒绝终态。
6. **未来 heartbeat 维持假在线**：比 Core 超前超过 5 分钟的 heartbeat 现在 422，
   不移动 liveness head；乱序旧 heartbeat 也不倒退 head。
7. **契约 runtime 偏差**：Pydantic 现在把所有 aware timestamp 归一 UTC，并执行与
   common schema 一致的 reason-code regex、unique、1–32 条限制；AI/event payload
   边界也更接近冻结 JSON Schema。
8. **Compose 暴露与默认密码**：三个 published port 现在只绑定 127.0.0.1；数据库
   密码和 API token 必须由 `.env` 显式提供，Compose 不再公开仓库固定数据库密码。
9. **Web 规划约束丢失**：今日计划页现在发送 available location 和所选设备
   capabilities；带地点/能力要求的 Task 不再必然 mismatch。
10. **配置时区未生效**：未显式传 timezone 时，plan API、event orchestrator、
    FixedEvent storage 和 current/history 默认都从 Settings 注入；非法 IANA 时区拒绝。
11. **幂等比较过窄**：Observation、Event、ACK replay 现在比较更多规范化语义字段，
    避免同 key 改 session/time/reason/details 被误判成同一请求。
    Event 的 `event_id` 被视为一次投递的元数据：同 key 的重试即使重生 event UUID，
    仍返回第一次的权威事件 ID；改变业务语义字段才冲突。
12. **未来命令饥饿**：poll SQL 先过滤 `not_before<=now`，前 20 个未来 command 不会
    挡住后面的 ready command。
13. **Agent 健康采样 reason**：稳定 sample 现在是 `SENSOR_SAMPLE`，不再永久写
    `SENSOR_WARMING_UP`。
14. **Web Emergency 文案**：成功提示改为“Core 已接受并排队 RELEASE_ALL”，不再
    在 Agent ACK 前声称设备侧已经解除。

## 16. 可微调与歧义目录

下表是本报告最适合你逐项批注的部分。优先级含义：P0 是进入长期使用或 V2 真实
执行前必须决定；P1 会明显改变日常体验；P2 可在积累数据后调整。

### 16.1 计划与任务语义

| ID | 优先级 | 当前实现 | 可能歧义/后果 | 建议选项 |
|---|---|---|---|---|
| PLAN-01 | P0 | session complete 不修改 Task | “完成一个 block”不一定等于“任务全部完成” | 选 A 按实际分钟扣减；B 用户确认完成量；C block 完成即 task 完成。推荐 B |
| PLAN-02 | P0 | Task/FixedEvent CRUD 不自动 replan | 编辑后 current plan 可陈旧，需 Web 手动重排或发 trigger event | 选 A 每次自动；B 弹窗确认；C 保持显式。推荐 B，并把 cause 写 envelope |
| PLAN-03 | P0 | session abort/complete 不自动发 SESSION_ABORTED/TASK_COMPLETED_EARLY/TASK_OVERRUN | trigger 枚举存在但业务动作未全闭环 | 定义实际结束时间/剩余量后自动分类触发；同事务写 event + plan |
| PLAN-04 | P0 | FixedEvent 是一次性 UTC interval | 每周课程要逐条创建，无 recurrence exception/skip | V1.1 增 RRULE + occurrence snapshot；计划仍引用 occurrence UUID |
| PLAN-05 | P1 | 所有 deadline 都是硬约束 | “希望周五前”会导致 INFEASIBLE，而非柔性延期 | 增 `deadline_hardness=HARD/SOFT`；推荐默认 SOFT，mandatory 可独立 |
| PLAN-06 | P1 | BACKLOG 也参与 planner | 尚未整理的任务可能进入今天 | 只排 READY/IN_PROGRESS；推荐 BACKLOG 默认不排 |
| PLAN-07 | P1 | 数字 5 优先级最高 | 用户可能习惯 P1 最高 | UI 已显示 P1–P5，但算法是 5 高；建议改 UI 文案为“1低—5高”而非改算法 |
| PLAN-08 | P1 | 07:00–23:00，同一自然日 | 不能表示跨午夜/夜班；睡眠只是窗口外隐含 | 保持个人日计划或允许 end 属于次日；若作息晚，推荐支持次日 02:00 |
| PLAN-09 | P1 | 午/晚餐各 30 分钟，最早 11:30/17:30 | 计划会倾向窗口一打开就吃饭；无早餐 | 把餐窗、时长、可跳过性移到 profile；推荐提供 preferred time + tolerance |
| PLAN-10 | P1 | travel 只取 FixedEvent 显式分钟 | 不推地图，地点切换的 Task 无 travel | V1 保持显式最安全；未来 travel provider 只能建议，Core 持久确认值 |
| PLAN-11 | P1 | location 大小写精确；capability 集合精确 | `Home` 与 `home` 不同，别名不匹配 | 存规范化 ID + display label；capability 使用冻结枚举 |
| PLAN-12 | P1 | Web 用所选 device capabilities 生成 plan | 计划设备和真正启动 session 的设备可后来改变 | 把 planning device/location 写入 PlanVersion context，并在 start 再校验 |
| PLAN-13 | P1 | break replan 丢失原 availability location/capabilities/window，只保留 parameters | 自定义窗口或约束任务在休息后可能变 mismatch | 将完整 PlanningContext 持久到 PlanVersion；break 必须继承 |
| PLAN-14 | P1 | freeze 只保留 horizon 内 TASK/BREAK/BUFFER | 新 fixed event 与 frozen block 冲突时可直接 INFEASIBLE | 冻结前剔除已冲突/不可能块；记录 `FROZEN_BLOCK_RELEASED` reason |
| PLAN-15 | P1 | horizon 外无显式 jitter cost | 确定性但可能大幅移动后续任务 | 加 old-time distance penalty；不要破坏 hard constraints |
| PLAN-16 | P1 | automatic throttle 按日期/时区统计；break/fatigue 也受限 | 短时间多次休息可能 429 | 显式用户 break 是否免限流需决定；推荐免 debounce、仍保留审计 |
| PLAN-17 | P1 | buffer 10%，向下取 5 分钟，区间末端 | 短区间无 buffer，且缓冲都在末尾 | 可改前后各半/最低 5 分钟；先用 10% 收集一周数据再调 |
| PLAN-18 | P1 | focus 50、break 10、max 90、minimum task chunk 25 | 50/10 可能不适合阅读、写作、编码 | 建 activity-profile presets；Task override > profile > global |
| PLAN-19 | P2 | pressure=`remaining/available_before_deadline` | 未计切换成本、认知能量、deadline 风险分布 | 保持可解释 V1；未来只加显式权重，不让 AI 直接排序 |
| PLAN-20 | P2 | fixed event 横跨 day horizon 或正在进行时可能冲突/跳过 | 起晚后正在上的课不会自动截断成 remaining interval | 决定：保留整块占用、从 now 截断，或标 MISSED；推荐从 now 截断并审计 |
| PLAN-21 | P2 | optional task 剩余小于 minimum 是 WARNING/PARTIAL | 文档若理解为全部 minimum failure 都 INFEASIBLE 会有分歧 | 推荐维持：mandatory/deadline ERROR，optional WARNING |
| PLAN-22 | P2 | FEASIBLE/INFEASIBLE revision 都占序号，只有可行版移动 head | revision 可跳过，current revision 不等于历史条数中的最后可行序号 | 这是合理审计语义；UI 应同时显示 current 与 latest attempt |
| PLAN-23 | P1 | Break 仅接受 RUNNING/INTERRUPTED，且 session plan 必须仍是 current head | 旧计划/PAUSED session 发起 break 会 409；throttle 也可 429，整事务回滚 | Web 在提交前刷新 session/head；把错误原因直接展示，不要先乐观显示“已休息” |

### 16.2 Runtime、采样与隐私

| ID | 优先级 | 当前实现 | 可能歧义/后果 | 建议选项 |
|---|---|---|---|---|
| RUN-01 | P0 | Agent 自动上传窗口标题（≤256） | 标题可能含文档名、消息、客户信息 | 增 per-profile `collect_window_title=false/hash/redact`；推荐默认 hash 或关闭 |
| RUN-02 | P1 | `cs2.exe` 是 Core 全局硬编码 blocked | 这是项目验收样例，也变成所有任务的产品偏好 | 移到用户全局 blocklist；命名场景用 fixture 注入 |
| RUN-03 | P1 | sample 5s，feature hold 15s，窗口 60/300s | 单样本最多贡献 15s；短断采仍可能补齐 | profile 化或保持 algorithm constant；改变即升级算法版本 |
| RUN-04 | P1 | coverage `<45s` UNKNOWN；confidence=coverage/60 | 45s 时 confidence=.75，可判断 | 这是当前保守平衡；若误判多，提高到 50–55s |
| RUN-05 | P1 | 无 absent evidence 且数据充分时默认 PRESENT | “电脑有活动”被当人在场 | 可将 presence 保持 UNKNOWN，仅 engagement 判定；无 camera 的 V1 更保守 |
| RUN-06 | P1 | idle 必须严格 `>` tolerance，默认 300s | 恰好 300s 仍非 IDLE | 决定 `>` 或 `>=`；实际差 1 秒，推荐保留并写边界测试 |
| RUN-07 | P1 | OFF_TASK 先需 candidate 两窗或 blocked 90s | 进入慢但误判少；退出 allowed 30s | 一周后基于误报调 30/60/75/90，不要跳过迟滞 |
| RUN-08 | P1 | allowed 为空时没有应用能成为 ON_TASK | PHYSICAL/READING 等可能长期 OTHER/UNKNOWN | activity profile 应支持“不依赖 app”或 manual check-in 模式 |
| RUN-09 | P1 | manual check-in 只有 schema/ingest 能力，无 UI | 用户无法方便纠正 UNKNOWN/ABSENT | Web/Agent 加 PRESENT/ABSENT + validity duration 控件 |
| RUN-10 | P1 | observation 最多允许比 Core 快 5min，旧 observation 无最大迟到 | 很旧 envelope 会被审计并产生一个新 UNKNOWN state | 设 late threshold；超时只 ledger，不运行 reducer/policy |
| RUN-11 | P1 | terminal session 的离线旧 assignment observation 仍可接收 | 历史 session 后继续产生 state/Level0 decision | 标 `STALE_SESSION_OBSERVATION`，只保存 evidence 不改变 runtime head |
| RUN-12 | P1 | RuntimeStateHead per-device、state_version 设备级 | session 切换仍继续 version，利于 command binding | 推荐保持；切换时 hysteresis 已清空，报告/UI应解释 version 不从1重置 |
| RUN-13 | P2 | device_role 在 reducer 恒 SENSOR | 表里有 lease 但状态轴不反映 | V2 从当前有效 lease 派生，多个 role 需定义优先级 |
| RUN-14 | P2 | Agent UUID 来自 hostname + `uuid.getnode()` | 改名/网卡可能变新设备，也泄露稳定硬件派生关系 | 首次安装生成随机 UUID 存本地；环境变量继续支持迁移 |
| RUN-15 | P2 | Agent SQLite 未加密、无自动 retention | 标题/进程历史可长期存在 | 即使 V1 无真实限制，也应先加 max age/size；加密属 V2 |
| RUN-16 | P1 | Agent 只限制 heartbeat `>=15s`，可配置到 `>=45s`；clock skew 无上限 | 心跳间设备会被标 offline；过大 skew 会放宽本地 TTL 判断 | heartbeat 上限设 `<45s`（推荐15）；clock skew 上限推荐 30–120s |
| RUN-17 | P1 | SQLite `latest_state_version` 直接覆盖，不取 max | observation flush 与 command poll 竞争时旧响应可能让本地版本回退 | 同一 Core epoch 内只允许单调增加；真正 reset 需显式 epoch |

### 16.3 Policy、Session 与解除

| ID | 优先级 | 当前实现 | 可能歧义/后果 | 建议选项 |
|---|---|---|---|---|
| POL-01 | P0 | Windows confirmation 不是四个真实按钮 | 无 choice ACK，无法触发 return/break/replan/end，ignored count 永远0 | 做 native/tray UI，ACK 必须含 choice；这是 V2 real block 前置门 |
| POL-02 | P0 | Agent 本地 Emergency 只有内部方法 | 断网用户没有托盘/热键入口 | 提供不可被限制阻挡的 tray + keyboard shortcut + CLI，离线先解除后补审计 |
| POL-03 | P0 | hard guard 尚未重验 active session/preauth/blocklist/duration/lease state version | V1 不生成 hard，因此当前安全；V2 不能直接开 flag | 将所有条件集中为 fail-closed guard，并逐项 failure test |
| POL-04 | P1 | Session 可提前/过期/offline 启动并直接 RUNNING | 这是“手动立即开始”还是“按计划执行”未定义 | 增 start tolerance（如提前5/迟到15min）及 explicit `start_anyway_reason` |
| POL-05 | P1 | 同 block 可在不同 device 同时启动 | 可能重复 session；也可能是有意 handoff | V1 推荐 block 全局一个 active；V2 handoff 用 lease/同一 session 多设备 |
| POL-06 | P1 | API/pure state graph 不完全同一张表 | DUE/STARTING/MISSED/RECOVERY 主要是 scaffold | V1.1 建单一 transition table，scheduler 再启用 DUE/MISSED |
| POL-07 | P1 | Ordinary Override 总是 PAUSED | “解除后继续任务”需要另点 resume | 可在请求加 `follow_up=PAUSE/RESUME/ABORT/REPLAN`；默认 PAUSE 最安全 |
| POL-08 | P1 | Emergency 非终态变 INTERRUPTED，终态保持；release TTL 5min | 设备离线超过 5min 时 Core command 过期 | 真限制场景依赖本地 release；Core 可在重连下发新 RELEASE snapshot |
| POL-09 | P1 | nominal command TTL 60/120s，但被 state valid_until 30s 截断 | 表面 120 秒确认实际上通常最多 30 秒 | 决定 state validity 还是 command 与 evidence 解耦；推荐 confirmation 90s 且重新验证后执行选择 |
| POL-10 | P1 | 每个 5s 新 state 可产生同 level 新 command | 可能通知/MessageBox 风暴 | 加 session+level cooldown 和只在 level transition 发 prompt |
| POL-11 | P1 | L4/L5 纯策略可达，runtime 不可达 | 文案可能误以为 Recovery 已工作 | 继续标 scaffold，直到 choice/ignored state 持久化 |
| POL-12 | P1 | RELEASE_ALL 允许 stale/expired ACK | fail-open 解除的有意例外 | 推荐保持；audit reason 显式写 `RELEASE_ACK_LATE_ACCEPTED` |
| POL-13 | P2 | safe notification 也严格 state-bound | 显示后新 sample 推进 state，ACK 可能被 Core 记 REJECTED | hard action严格绑定；notification 可记录 delivered-at-state 而不否定已显示事实 |
| POL-14 | P2 | override/emergency 不取消未送达 notification/confirmation | 解除后旧提示仍可能出现 | 取消所有非 RELEASE pending commands，或 Agent 看到 release epoch 后抛弃更老 command |
| POL-15 | P0 | start snapshot 仅含 mode/dry_run/allowed_actions；Runtime 对 Task block 优先读取当前 Task app rules | Session 中途修改 Task 会改变 ON/OFF_TASK 分类和 WOULD_BLOCK 列表；这不是完整 preauthorization | start 时冻结允许/阻止 app 与时长边界；真实 hard guard 只读不可变授权快照 |

### 16.4 API、数据、Web、AI 与运维

| ID | 优先级 | 当前实现 | 可能歧义/后果 | 建议选项 |
|---|---|---|---|---|
| SYS-01 | P0 | 单共享 bearer，无用户/device identity | 仅适合 loopback 本地个人使用 | 继续 loopback；V2 加 per-device credential + user session，不要暴露公网 |
| SYS-02 | P0 | 默认 Settings token 仍有已知 fallback，Compose 则强制 `.env` | 直接源码启动若忘记设置仍可用默认 | 增 `environment=production` 时拒绝默认/空 token；本地 test 保留注入 |
| SYS-03 | P0 | EventLedger append-only 是服务约定 | DB 管理员/直接 SQL 可更新/delete | 生产加独立 DB role/权限或 immutable trigger；backup 也要含 ledger |
| SYS-04 | P1 | FixedEvent DELETE 物理删除；被历史 block FK 引用时会 409/回滚审计 | 用户以为删除成功但历史引用阻止 | 改软删除 `CANCELLED`/`deleted_at`，历史 snapshot 永远保留 |
| SYS-05 | P1 | Task DELETE 是 CANCELLED | 与 FixedEvent DELETE 语义不同 | UI 使用“取消任务”；FixedEvent 也统一软删除 |
| SYS-06 | P1 | 无通用 outbox dispatcher | PENDING 不代表故障，也不会自动清空 | V1 监控不要报警；V2 加 publisher、lock、retry、dead letter |
| SYS-07 | P1 | 30/365 天 retention 只是建议，无 job | 数据会无限增长 | 先决定隐私期限，再写可审计 batch deletion；ledger/plan 可能不同期限 |
| SYS-08 | P1 | Agent queue oldest-first，但失败项退避期间后项可先发；poison item 到期会再阻塞批次 | “严格顺序”并非所有时间成立，4xx 可反复 | 4xx dead-letter、5xx backoff、queue size/age cap |
| SYS-09 | P1 | Core env token 名 `DEV_AUTH_TOKEN`，Agent 名 `DEV_TOKEN` | 容易配置错 | 统一为 `LIFEOS_AUTH_TOKEN` 或 README 明确映射；当前 README 已示范 |
| SYS-10 | P1 | Web `/health` 不查 DB/不验 token | 可能显示 Core 在线但业务 401/DB down | connection test 同时调用 `/ready` + protected lightweight endpoint |
| SYS-11 | P1 | Web fetch 无 timeout/abort | 网络半开时按钮可长期 pending | 加 8–15s AbortController；轮询请求应取消前一轮 |
| SYS-12 | P1 | Web deadline 的 `datetime-local` 用浏览器时区，不一定是 LifeOS display timezone | 两时区不同会写错 deadline | 用所选 IANA 时区解析/展示，并在提交前显示最终 UTC |
| SYS-13 | P1 | Web 没有 FixedEvent CRUD、Planner advanced settings、AI、lease UI | API 能力不等于普通用户可用 | 优先 FixedEvent UI 和 planner profile；AI/lease 留 V2 |
| SYS-14 | P1 | Web active session 主要依靠 tab sessionStorage/手填 UUID | 新 tab 恢复体验差 | 调用现有 per-device active-session endpoint，terminal 自动清理 UUID |
| SYS-15 | P1 | PWA 不缓存计划数据 | 离线只能看到 app shell，不能读最后计划 | 若需要，缓存只读 redacted Plan snapshot并显示 timestamp；绝不作为权威 |
| SYS-16 | P1 | DB/API/Web Compose 都 loopback | LAN 手机无法访问，正是安全默认 | 若开放 LAN，必须 TLS、强 secret、DB 仍不发布、CORS/防火墙明确配置 |
| SYS-17 | P1 | Core/PostgreSQL 未有 backup/restore | 当前 volume 是单点 | V2 前做 `pg_dump` + restore test；不要只备份 derived feature |
| SYS-18 | P1 | AIJob “fallback_used”只表示 AI 失败不影响 Core | 该 job 不会自动调用 planner 产一个替代响应 | UI/文档改称 fail-closed/planner-independent，避免理解成 job 内 fallback |
| SYS-19 | P2 | Context future blocks 取调用顺序前3，unfinished 前256 | 调用方排序决定 AI 看到什么 | Builder 内按时间/urgency 规范化排序 |
| SYS-20 | P2 | AI 默认永远是 Mock；无 provider env factory | “AI 可用”也只返回使用确定性计划 | V1 保持 Mock 标识；接真实 provider 时先新增契约/超时/预算/审计 |
| SYS-21 | P2 | PWA 只有 SVG `sizes:any` icon | 部分旧平台安装图标兼容弱 | 生成 192/512 PNG + maskable icon |
| SYS-22 | P2 | Starlette/httpx TestClient 有弃用 warning | 未来升级可能破测试 | 锁兼容版本或迁移到新 test client；当前不影响运行 |
| SYS-23 | P1 | 外部 PlanTrigger event 直接把 `occurred_at` 当 planner `now`，无 future/late 边界 | 错误设备时钟可把规划推进到未来或用很旧时刻重排 | 增允许 skew/late window；越界事件只入 ledger 或要求人工确认 |

## 17. 建议你优先回复的十个决定

为了微调时不被几十个细节淹没，建议先只回答下面十项；可以直接回复 ID 和选择：

1. `PLAN-01`：session complete 后，工时由用户确认、按时钟扣减，还是 block 全额扣减？
2. `PLAN-02`：Task/FixedEvent 编辑后自动 replan、弹窗确认，还是保持手动？
3. `PLAN-05`：是否增加 HARD/SOFT deadline？默认是哪一个？
4. `PLAN-08/09`：你的真实可用日界、午晚餐窗口和时长是什么？
5. `PLAN-18`：READING/WRITING/CODING 是否需要不同 focus/break preset？
6. `RUN-01`：窗口标题默认上传、hash、仅白名单应用上传，还是完全关闭？
7. `RUN-02`：`cs2.exe` 是否应继续作为全局默认 blocked，还是仅测试/特定 Task？
8. `POL-04`：允许比计划提前/迟到多少分钟启动 session？offline 可否启动？
9. `POL-07`：Ordinary Override 默认 PAUSE，还是允许同时选择 RESUME/ABORT/REPLAN？
10. `SYS-15`：离线 PWA 是否需要显示最后一份只读计划？

若暂时不回答，系统继续使用本报告写明的保守默认，不会偷偷推断新的权限或真实
enforcement。

## 18. 推荐的后续顺序

### V1.1：先让日常使用闭环完整

1. Task progress/complete 语义和自动 trigger 编排。
2. FixedEvent Web CRUD + recurrence occurrence 模型。
3. Web 采用 active-session API、deadline 时区修复、Core readiness/auth 状态。
4. PlannerContext 持久化，保证 break/replan 继承 location/device/window。
5. manual check-in UI、global/user app profile，而非硬编码 cs2。

### V1.2：体验和隐私

1. Window-title off/hash/redaction 与数据 retention。
2. notification cooldown、真实四选一 confirmation（仍不启用 hard block）。
3. stale observation/terminal assignment 处理、Agent dead letter/queue cap。
4. 只读离线计划 snapshot（若你选择需要）。

### V2 前置阻断门

1. 不可阻断的本地 Emergency Release UI + 离线测试。
2. 完整 hard guard：active session、commitment/preauth、blocklist、duration、lease
   state/version、heartbeat freshness、command signature。
3. Role Lease issuance/revoke/election/handoff 全生命周期。
4. 真实限制 feature flag 仍默认 off，并做 timeout/restart/network/VPN 故障注入。
5. Backup/restore、per-device auth、TLS、数据库不对网络发布。

## 19. 不应从 V1 推导的结论

- “STANDARD/STRICT 已能锁应用”：错误；只会 WOULD_BLOCK。
- “Recovery Mode 已工作”：错误；只有 pure policy 输出和枚举。
- “Role Lease 已能选主”：错误；仅 schema/table/部分 guard scaffold。
- “Outbox 正在向 broker 发布”：错误；没有 publisher/broker。
- “AI offline job 自动运行另一个 planner”：错误；planner 独立可用，job 自身只标失败。
- “PWA 离线仍能看计划”：错误；service worker 只缓存静态 shell。
- “Agent 可由用户离线按 Emergency 按钮”：错误；目前只有内部 release 方法。
- “display timezone 改变存储时区”：错误；存储永远 UTC，只改变日界和展示。
- “Docker Compose 已在本机完整运行”：错误；配置通过，daemon 不可用。
- “PG18 验证等于精确运行 PG16 容器”：错误；是强在线 SQL 证据，不是相同镜像证据。

## 20. 微调时的变更规则

为了避免个人化调整破坏安全边界，建议按以下分类：

- 只改数值（focus、break、窗口、阈值）：更新配置/profile、边界测试和算法版本说明。
- 改 transport 字段/枚举：先 ADR + JSON Schema version 决策 + Pydantic/Agent/Web
  同步 + contract fixtures。
- 改 persistence：Alembic migration，不修改已应用的 0001 内容来“伪装历史”。
- 改 planner 排序/feasibility：升级 `algorithm_version`，保留旧 PlanVersion 可解释性。
- 改 hard action：必须先完成 V2 阻断门；不能仅把 feature flag 从 false 改 true。
- 改隐私采集：默认更少可直接收紧；扩大采集必须显式授权、用途和 retention。

本报告中的“推荐”不是不可变规范。真正不可变的是：Core 权威、证据/状态/决策/命令
分层、旧计划不覆盖、不可行不伪造、命令有限期与幂等、Emergency 优先、AI 不直接
执行系统命令，以及真实强制默认关闭。
