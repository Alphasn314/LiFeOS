# LiFeOS V2 自更迭与多端闭环设计报告

> 日期：2026-08-30  
> 状态：**设计冻结前审阅稿，不是 V2 已实现声明**  
> 当前执行安全模式：`dry_run=true`、`real_enforcement_enabled=false`

## 1. 先说明“现在有什么”和“这次完成了什么”

### 1.1 当前已经存在并有证据的部分

LiFeOS V1 已有以下实现：

- FastAPI Core 与 PostgreSQL 持久化；
- Alembic migration；
- Task、FixedEvent、PlanVersion、ExecutionSession；
- 确定性 Planner/Replanner；
- RuntimeState、PolicyDecision、Command、ACK、EventLedger、Outbox；
- Web/PWA；
- Windows Agent 的 Session 同步、heartbeat、observation、SQLite 队列、Command 校验和 ACK；
- Emergency/`RELEASE_ALL` 的 fail-open 安全语义；
- SongNAS 上 PostgreSQL、API、Web 三容器启动和 `/ready` smoke 证据。

本机 Self Discipline Controller V4.2 已具备网站/程序限制、托盘、60 秒手打、安装/卸载、自动启动、Recovery 等能力，其测试结果为 **115 passed in 2.88s**。

### 1.2 本轮实际完成的部分

本轮完成的是 V2 架构、边界、选择、验收门和详细报告，不是完整 V2 代码：

- 新增 ADR-0006；
- 修订 NAS/Windows/iOS 拓扑、规划、状态、介入、安全、数据模型和验收门；
- 明确 Self-Evolution 的数据与算法边界；
- 明确 LifeOS Windows 与现有 Controller 的合并边界；
- 明确 iOS Xcode 免费签名、受限 SSH、本地通知、前台摄像头方案；
- 将 GitHub-first 复用原则写入项目规则；
- 将用户本轮选择写入 ADR 和验收门；
- 生成并检查中文 PDF 指南。

### 1.3 仍然没有实现的部分

以下仍属于“已设计、未实现”：

- Self-Evolution migration、schema、service 和学习任务；
- V2 合同、ADR 对应的 contract tests；
- `HUMAN_INTENT` 用户在场签名链；
- V1 自动 PlanVersion 生产入口的 V2 切断；
- LifeOS Windows 合并版源码与最终安装器；
- 启用真实 F3 限制所需的完整守卫测试；
- SwiftUI/Xcode iOS 工程；
- `lifeos-bridge` 受限 SSH 子系统；
- 手机 → NAS → Windows 的真实端到端链；
- VPN 生产 hostname 配置；
- V2 NAS production profile、维护、容量和备份任务。

因此，不能把本报告或 ADR 的存在解释为“功能已经安装”。

---

## 2. 系统总原则

### 2.1 唯一事实源

SongNAS 上的 Core/PostgreSQL 是唯一事实源。Windows、iOS、Web 缓存、AI proposal、学习结果和离线 fallback 都不能成为第二个业务权威。

### 2.2 自更迭不是运行时改源码

“自更迭”只允许更新：

- 版本化任务画像；
- 时长后验分布；
- 主观压力画像；
- 固定 schema 内的特征权重；
- ScheduleAdvice；
- 可审计的实验参数。

它不允许：

- 运行时重写 Python、Swift 或 Windows 生产源码；
- 下载和安装任意插件；
- 生成 shell、注册表、防火墙或任意 SSH 命令；
- 修改 Emergency、租约、blocklist、保留策略或用户 Replan 权限。

代码演进仍然走：Git 分支 → review → tests → signed release → rollback artifact。

### 2.3 AI 只产出数据提案

AI 可以提议受限标签、解释、提醒文案和候选估计。确定性服务负责：

- schema 校验；
- 范围和枚举校验；
- 版本控制；
- 样本量和漂移限制；
- 回滚；
- 审计；
- 最终是否接受 proposal。

AI 无法直接执行 hard action，也不能代表用户提交 Replan。

---

## 3. Self-Evolution 模块

### 3.1 为什么不做成 OMP extension

OMP extension 是在 harness 内运行的非沙箱 TypeScript/JavaScript 扩展；skill 和 memory 是代理指导信息，不是生产状态。LiFeOS 的学习模块必须：

- 静态导入 Core；
- 使用明确 Python 接口；
- 通过 migration 持久化；
- 使用版本化 manifest；
- 可审计、可回滚；
- 不依赖 OMP 进程存在。

建议模块位置：

```text
backend/lifeos/modules/self_evolution/
  service.py
  duration.py
  pressure.py
  advice.py
  features.py
  manifest.py
```

### 3.2 数据实体

#### TaskExecutionFeedback

追加式记录：

- Task、Session、PlanVersion/Block 身份；
- 用户原计划分钟数；
- active time、wall time、等待和中断；
- 完成/部分完成；
- 进度量和有意义尝试；
- 专注、疲劳、当前情绪；
- 主观压力 0–4；
- provenance、confidence、validity；
- 幂等键和用户修正。

#### TaskLearningProfile

按 `global → domain → action subtype → task` 层级保存：

- 时长分布的充分统计量；
- P50/P80；
- uncertainty/confidence；
- 主观压力分布；
- 样本数、有效权重；
- cold-start 来源；
- 当前选定 model revision；
- 用户 freeze/reset/override。

#### EstimateRevision

不可变保存每次学习更新的：

- prior profile version；
- evidence IDs；
- 固定 feature vector；
- algorithm/version；
- 新参数和预测；
- pre-update error；
- validation 和 reason codes。

#### ScheduleAdvice

不可变保存：

- 用户原计划；
- 学习 revision；
- 每块 P50/P80 和压力；
- 最小修改建议；
- feasibility/conflicts；
- 解释；
- `PENDING/ACCEPTED/REJECTED/EXPIRED`。

ScheduleAdvice 本身不是 PlanVersion。

#### LearningRun

记录输入 cursor、profile versions、AI provider/model、验证结果、输出 revision、错误、耗时和审计因果。

### 3.3 时长学习

主要标签是完成任务所需的 active time，不是简单 wall-clock time。等待、离开和中断单独记录。未完成 Session 是 censored observation，不能冒充完整总时长。

模型采用小维度、层级化、在线 Bayesian/log-duration 设计：

1. cold start 回退到 global/domain/subtype 先验；
2. 每个有效完成样本在线更新；
3. 对非有限值和不合理 outlier 拒绝或截断；
4. 更新前先记录预测误差；
5. 输出 P50、P80、置信度、样本数和 reason codes；
6. 可冻结、重置或回滚污染画像。

用户已选择：

- 高不确定科研任务使用 **P80**；
- 可拆分低压力任务使用 **P50**；
- UI 始终同时显示选中值和替代分位数；
- 用户原估时始终保留，不被模型静默覆盖。

### 3.4 主观压力学习

压力表示“做这项具体任务的主观认知/情绪成本”，不是客观 deadline pressure：

- 0：几乎无压力；
- 1：轻；
- 2：中；
- 3：高；
- 4：极高；
- `UNKNOWN`：证据不足。

英语=1、课程=2、科研=3 只能作为冷启动先验。画像必须按具体 subtype/task 学习。压力只影响排序、恢复间距和建议，不改变任务的道德优先级。

### 3.5 首批科研进度适配器

用户选择首批同时覆盖四类：

1. 实验运行：启动、完成、检查结果、失败原因；
2. 代码开发：实现、运行、调试、测试和有意义尝试；
3. 论文阅读：论文、章节、逻辑块和笔记进度；
4. 科研写作：段落、图表、章节和修订进度。

这些适配器记录 typed progress/attempt metadata，不采集源码内容、论文正文、屏幕或按键。

---

## 4. 下一日计划建议和 Replan

### 4.1 下一日 ScheduleAdvice

用户提交完整的时间—任务计划。系统：

1. 固定当前 profile/model revision；
2. 预测每块 P50/P80 和压力；
3. 检查固定事件、依赖、地点、设备、转场、休息和总时间；
4. 检测明显过短/过长、压力聚集和疲劳不匹配；
5. 在保留用户任务与硬事实的前提下模拟小改动；
6. 返回最小可解释建议；
7. 等待用户接受或拒绝。

不存在英语、科研或课程的固定每日最低配额。任何领域都可以因为用户选择而在某一天为零。

### 4.2 初始计划和替换计划必须分开

- `CREATE_DAILY_PLAN` 或 `ACCEPT_SCHEDULE_ADVICE` 只能在当天尚无权威计划时创建初始版本；
- 已有权威 PlanVersion 时，只有 `REQUEST_REPLAN` 可以替换它；
- 所有动作都需要用户在场认证。

### 4.3 严重偏离流程

Core 可以持续做 projection，但不能自动 Replan：

1. 对比 elapsed/progress 与学习分布；
2. 先尝试安全压缩和整块延期/删除柔性任务；
3. 若剩余计划仍可行，只显示状态；
4. 只有固定/必需工作仍冲突或超过严重阈值，才生成去重的 `REPLAN_RECOMMENDED`；
5. Windows、iOS 和 Web 显示短缺、恢复尝试和取舍；
6. 用户明确 `REQUEST_REPLAN` 后 Planner 才生成新 revision。

### 4.4 必须切断的 V1 自动 PlanVersion 入口

V2 实现时必须修改：

- `EventOrchestrator.ingest`：非用户 `PlanTrigger` 只能生成状态/建议；
- `POST /api/v1/sessions/{session_id}/break`：只记录 break 并解除控制，不再调用 `PlanService.insert_break` 创建 PlanVersion；
- `/api/v1/plans/generate`：不能覆盖已有计划，拒绝 AI/service/sensor/device-only trigger。

### 4.5 HUMAN_INTENT

SSH device key 只能证明“这台设备”，不能证明“用户刚刚按了 Replan”。计划创建/替换需要单独的 `HUMAN_INTENT`：

- 专用交互 UI；
- Windows Hello、iOS LocalAuthentication/Secure Enclave 或 Web 等价用户在场确认；
- 一次性 `intent_id`、nonce、issued/expiry；
- user/device、action、plan ID/revision；
- 签名和一次性消费；
- 拒绝 replay、过期、错误 revision；
- AI、service、sensor、普通 device principal 无此能力。

---

## 5. 三个核心当前状态

### 5.1 专注 0–4 + UNKNOWN

专注表示持续任务导向推进或有意义尝试，不等同于“摄像头看见人”，也不要求每分钟都有产物。认真调试或实验失败仍可能是高专注。

### 5.2 疲劳 0–4 + UNKNOWN

表示继续学习的功能性成本。用户自报为权威；性能下降只能触发询问，不能直接把用户判定为疲劳。

### 5.3 当前情绪 -2..+2 + UNKNOWN

只表示当前时点：

- -2：非常生气/伤心/不想做；
- -1：负面/抗拒；
- 0：中性；
- +1：正面；
- +2：非常有 passion。

不建立长期学科信心或人格模型。

### 5.4 辅助因素

睡眠、身体和环境只有在用户明确说明“它现在影响学习”时才进入模型，并带有效期。摄像头不能推断疲劳或情绪。

---

## 6. LifeOS Windows

### 6.1 合并方式

现有链路继续作为宿主：

```text
LifeOSWindowsAgent
  → CommandProcessor
  → capability adapter
  → durable ACK
```

从 Controller 适配有界 backend、UI 和安装生命周期，不把原 Controller 的自治主循环复制成第二权威。

最终目标：一个进程、一个托盘图标、一个 mutex、一个 ProgramData root、一个凭据存储、一个策略 manifest、一个安装/更新/卸载身份。

### 6.2 权威顺序

```text
本机 Emergency Release
  > NAS 休息/解除/终态
  > 完整守卫通过的 NAS 限制命令
  > 本地提醒/WOULD_BLOCK fallback
  > 普通通知
```

任何 NAS 消息都不能仅凭“来自 NAS”执行 hard action。真实限制需要：

- 正确目标设备；
- 当前非终态 Session；
- Session 预授权；
- `dry_run=false`；
- fresh state version；
- TTL/not-before；
- 幂等；
- exact blocklist 和 bounded duration；
- Core/device 在线；
- fresh `PRIMARY_ENFORCEMENT` lease；
- 本地 capability；
- rollback readiness；
- audit。

### 6.3 离线 fallback

没有新鲜 NAS 权威时，本地 fallback 只能运行：

- timer；
- focus UI；
- reminder；
- `WOULD_BLOCK` dry-run。

它不能修改 hosts、浏览器策略、进程或应用。原因不是能力不足，而是在线 Core、Session、lease 和预授权守卫无法成立。允许离线真实限制会产生第二执行权威，违反安全合同。

### 6.4 用户已选择 F3

首版摩擦为：

- 60 秒随机手打句子；
- 配置内网站/程序限制；
- 真实限制仍只有完整 hard-action guards 通过后才可达；
- 手打文字本身不能改变 Core 状态；
- 永远不能延迟 Emergency。

### 6.5 用户已选择 R1

R1 的关键语义是 fail-open：

1. 无条件、同步解除全部限制；
2. 即使 Core、Session 或 lease 不新鲜，也先解除；
3. Core 可达时，best-effort 提交并安排 10 分钟恢复休息；
4. 之后显示返回、Replan 或结束；
5. Replan 仍需 `HUMAN_INTENT`。

R1 不是 hard-action authorization，不能被 F3 的守卫阻止。

### 6.6 休息自动解除

`BREAK`、`PAUSED`、`MEAL`、`TRAVEL`、`RECOVERY`、`EMERGENCY`、终态/无 Session、过期命令/lease、stale Core 和用户 override 都必须同步移除 NAS-owned restriction。工作程序仍开着不能触发重锁。

### 6.7 Controller 私用授权

用户确认 V4.2 是其原创项目，并授权：

- 在其私有 LifeOS 项目内复制、修改和构建；
- 不授予公众再分发权；
- 第三方 MIT/BSD/HPND/LGPL/PyInstaller notices 必须保留。

该授权允许后续私有集成，但不等于允许公开发布原 Controller 源码。

---

## 7. iOS

### 7.1 安装路线

选择原生 SwiftUI + Xcode 免费 Personal Team 直装到 iPhone 17：

- 不加入付费 Apple Developer Program；
- 不依赖 TestFlight/App Store；
- 需要周期性重新签名/安装；
- 首版不把 APNs 当作必需或保证渠道；
- 接受计划后用 `UserNotifications` 安排本地准时提醒；
- App 被挂起时不能保证立即收到 NAS 临时改动。

### 7.2 网络

使用 Apple `swift-nio-ssh`，但只能通过 typed `NASAuthorityClient`：

- VPN 是默认远程边界；
- pin SongNAS host key；
- 每设备独立 key；
- forced `lifeos-bridge` subsystem；
- 无 shell、PTY、SFTP、forwarding 和任意 command；
- 有严格 input/output/time limits。

### 7.3 摄像头专注 evidence

摄像头仅在用户明确开启、前台运行的 focus Session 使用：

- AVFoundation 提供 preview 和限速 sample buffer；
- Vision/Core ML 全部在手机本地处理；
- frame 用后立即丢弃；
- 不存、不传 frame/video/embedding；
- 不做人脸身份、情绪、疲劳、医疗或人格推断；
- 只上传受限 presence/orientation/focus evidence、confidence、coverage 和有效期；
- 权限拒绝、遮挡、挂起、离开或错误均输出 `UNKNOWN`。

手机 evidence 先到 NAS，NAS 决策后 Windows 独立校验和显示。手机不在时，Windows evidence 和 reminder 继续工作。

---

## 8. NAS、VPN、维护、数据和备份

### 8.1 VPN

Windows/iOS 离家时默认先连接可信 VPN。Core/SSH 不做公网端口直通。实现仍需要一个从 iPhone 和 Windows 均可解析/访问的稳定 SongNAS hostname 或 MagicDNS 名称。

### 8.2 维护窗口

维护只能在本地时间 03:00–07:00 运行，并且不能在没有显式 maintenance transition 时中断 active Session。

### 8.3 决策上下文

普通决策默认读取最近 72 小时详细状态；需要长期模式时再读取摘要和 profile。永久保存不等于每次把全部历史塞入 prompt。

### 8.4 用户选择永久 raw evidence

以下永久保存：

- personal-history summaries；
- daily summaries；
- task profiles；
- model/estimate revisions；
- plan/session/audit history；
- 高频 raw evidence。

永久 raw 必须同时具备：

- 加密；
- 日期分区；
- 容量增长监控和告警；
- 用户导出和删除能力；
- 普通 AI prompt 排除；
- 明确 schema 和 provenance；
- camera frame/video/embedding、按键、剪贴板、截图、麦克风和内容监控永不进入 raw evidence。

正式版本冻结后删除测试/fixture 数据。

### 8.5 同 NAS 备份的限制

用户要求当前备份只放 NAS 本地。它可以防止部分误删和回滚问题，但主库和备份仍处于同一故障域，不能抵御 NAS 丢失、火灾、总盘损坏或整机文件系统故障。产品必须标记“灾难恢复不完整”，不能宣称已有 off-NAS backup。

---

## 9. GitHub-first 复用决定

实现能力前先查官方 API 和 GitHub，不凭空重写成熟能力。每项依赖需验证 license、tag/commit、活跃度、依赖、失败模式和安全边界。

当前决定：

| 候选 | 决定 |
|---|---|
| River BayesianLinearRegression 0.26.1 `64285b9` / BSD-3 | `ADAPT` 小型在线预测行为，不引入整套重依赖 |
| River adaptive tree | `STUDY_ONLY`，首版压力学习保持简单 |
| 本地 Controller V4.2 | `ADAPT`，仅私有 LifeOS 使用，保留 notices |
| H.NotifyIcon `61a5132` / MIT | 仅未来转 WPF/WinUI 时采用 |
| Velopack 1.2.0 / MIT | 未来 signed update；回滚测试前不自动 apply |
| Microsoft WFPSampler / MS-PL | `STUDY_ONLY`；不引入自定义内核 blocker |
| Apple swift-nio-ssh 0.15.0 `3ec2814` / Apache-2 | `ADOPT`，放在 typed client 后，不提供 shell |
| AVFoundation、Vision、UserNotifications | 直接采用平台 API |
| HandPoseDetection `cc8357c` / MIT | 只参考 camera queue/Vision pattern |
| NnReminderKit `f55a8d9` / MIT | 只研究 adapter/test；首版直接包原生 API |
| Shout | `REJECT`，陈旧且偏 macOS |

---

## 10. 实施顺序

1. 用户审阅并确认本报告和 ADR-0006；
2. 确认 VPN hostname 与严重偏离阈值；
3. 冻结 V2 合同；
4. 为冻结边界增加 ADR、migration、contract tests；
5. 实现 feedback/profile/revision/advice/learning-run 数据层；
6. 实现确定性时长/压力学习和回滚；
7. 实现四类科研 progress adapters；
8. 实现 ScheduleAdvice；
9. 实现 `HUMAN_INTENT` 和用户专属计划创建/Replan；
10. 切断 EventOrchestrator、break、generic generate 的自动 revision；
11. 合并一个非破坏性的 LifeOS Windows 托盘/传感/队列/传输应用；
12. 适配 Controller backend，但保持真实 enforcement feature-flagged off；
13. 完成完整 hard-action denial/expiry/replay/rollback/fail-open tests；
14. 实现选择的 F3 和 R1；
15. 创建 SwiftUI/Xcode iOS 工程；
16. 实现受限 SSH、本地通知和前台摄像头 evidence；
17. 完成手机 → NAS → Windows 真机 smoke；
18. 完成 VPN production profile、03:00–07:00 维护、永久 raw 容量治理和同 NAS backup；
19. 只有全部守卫和验收门通过后，才单独讨论是否把 real enforcement 从 disabled 切换为可达。

---

## 11. 仍需用户决定的两项

### 11.1 SongNAS VPN 地址

需要提供从 iPhone 和 Windows 均可访问的稳定 hostname/MagicDNS 名称。不要提供 NAS 密码、SSH 私钥或 VPN 密钥。

### 11.2 严重偏离建议阈值

建议起点：

- 发生固定事件冲突；或
- 剩余缺口超过 `max(30 分钟, 可支配时间的 20%)`。

这只是触发“建议 Replan”，不会自动改计划。阈值可以在审阅后微调。

---

## 12. 安全歧义的最终解释

1. **“NAS 最高权威”不等于收到任意 NAS 消息就执行。** 必须是当前、定向、完整守卫通过的 typed command。
2. **离线 Controller fallback 不执行真实 block。** 离线 hard action 会绕过在线 Core/lease/preauthorization，产生第二权威。
3. **F3 守卫只约束施加限制。** R1/Emergency/`RELEASE_ALL` 必须 fail-open，不可被同一守卫阻断。
4. **永久 raw 不包括画面和内容监控。** 它只表示允许 schema 内的高频元数据永久保存。
5. **摄像头专注不等于人脸识别或情绪识别。** frame 从不离开 Vision 边界。
6. **设备认证不等于用户意图。** Replan 需要独立、一次性、用户在场的 `HUMAN_INTENT`。
7. **Self-Evolution 不会改源码。** 它学习参数和画像；生产代码仍经 Git/review/test/release。
8. **同 NAS backup 不是完整灾难恢复。** 必须显式标注单故障域。
9. **Xcode 免费签名能直装，不保证 APNs。** 首版依赖本地通知和前台/系统给予的同步机会。
10. **V2 设计完成不等于 V2 实现完成。** 本报告明确列出的未实现项必须逐项交付和验证。

---

## 13. 验证证据

- Controller 测试：`115 passed in 2.88s`；
- ADR/安全一致性 review：最终 PASS；
- 文档 patch：`git diff --check` 无错误；
- PDF：XeLaTeX 编译成功，14 页 A4；
- 关键修改页完成视觉检查；
- Git 工作区在提交后 clean；
- PR：<https://github.com/Alphasn314/LiFeOS/pull/1>。

## 14. 关键源文件

- `docs/adr/0006-self-evolution-and-integrated-clients.md`
- `docs/adr/0005-nas-windows-ios-topology.md`
- `docs/architecture.md`
- `docs/data-model.md`
- `docs/planning.md`
- `docs/state-machine.md`
- `docs/intervention-policy.md`
- `docs/security.md`
- `docs/invariants.md`
- `docs/v2-acceptance.md`
- `LiFeOS_V1_REPORT.md`
