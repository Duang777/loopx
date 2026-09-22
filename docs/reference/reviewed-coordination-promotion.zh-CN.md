# 审核后的协调状态晋升与恢复

晋升会把 Goal 的 Todo／lease 权威来源从旧路径切换到选定的 canonical provider。
预览、封住旧写者、提交新存储、收到成功响应是不同的步骤。预览成功并不代表已经切换。

现在可以保存完整预览，执行这份计划，再用同一份计划恢复原事务。计划校验、准入、
fence 与 receipt 证明由 TypeScript 协调边界负责；Python 只读文件、传输请求。

## 操作

先显式启用并 bootstrap runtime shadow，让它捕获真实变更并通过资格校验。
现有 v0 晋升仍要求 Goal 已处于 `hard_lease`；保存 JSON 不会降低这个条件。

```bash
loopx --format json coordination-shadow promote \
  --goal-id example-goal --minimum-operations 3 \
  --require-event-kind todo_update > reviewed-promotion.json

loopx --format json coordination-shadow promote \
  --goal-id example-goal --reviewed-plan reviewed-promotion.json

loopx --format json coordination-shadow promote \
  --goal-id example-goal --reviewed-plan reviewed-promotion.json --execute
```

执行前审核 `ok`、`promotion.status`、目标 provider、源 revision、projection digest
和资格策略。文件可以是完整 CLI 成功预览，也可以是其中的
`promotion.plan.reviewed_plan`。它包含 runtime 路径与 Goal 身份，应保存在本地，
不要贴到公开 PR。

保存的计划决定 operation id 和资格策略，不能再叠加 `--minimum-operations` 或
`--require-event-kind`。不传计划文件的旧命令继续沿用原默认值。

执行会在现有锁内重新捕获、校验源状态。计划变了，就在 fencing 前返回
`local_authority_reviewed_plan_changed`。此时重新预览并审核；不要修改旧 digest
来强行通过。digest 说明“执行的是哪份意图”，持久 fence 和 provider 状态说明
“这份意图现在能否执行”。

## 断点恢复

```bash
loopx --format json coordination-shadow recover-promotion \
  --goal-id example-goal --reviewed-plan reviewed-promotion.json

loopx --format json coordination-shadow recover-promotion \
  --goal-id example-goal --reviewed-plan reviewed-promotion.json --execute
```

恢复仍要找到注册的 Goal 与 runtime，但不读取旧 Markdown，也不依赖临时 shadow
开关。它必须看到完全相同的持久 writer fence，不能创建缺失的 fence、换 provider，
也不能回退到旧来源。

| 状态 | 仅预览 | 加 `--execute` |
| --- | --- | --- |
| 没有匹配的 fence | 拒绝 | 拒绝 |
| 有 fence、尚未提交、保留的 shadow 仍完全合格 | `recovery_ready` | 提交并读回 |
| 原晋升已提交，甚至 canonical 已继续变更 | `replayed` | `replayed`，不重写 |
| 已被其他事务初始化，或 receipt 与事务链矛盾 | 拒绝 | 拒绝 |
| provider 不可用 | 报告 provider 错误 | 报告 provider 错误 |

尚未提交的恢复仍核对原 shadow revision、projection、capture binding、完整事务链、
outbox 是否结清、操作次数和事件覆盖；校验与提交共用 canonical writer 的维护锁。
它不会把已经失去权威地位的旧文件当作必须重新观察的来源。

提交调用抛错，也可能是“数据已落盘，但响应丢了”。两条晋升路径现在共用一次提交、
持久读回的实现，不盲目重做业务事务。receipt 与第一笔事务的 operation id、cursor、
provider revision、receipt 内容和初始 projection 必须全部一致。

返回的 revision 与 cursor 指向原晋升事务，不一定是当前最新 head。重放返回
`executed=false`，表示本次没有业务写入。失败时还要看 `legacy_writer_fenced` 和
恢复提示；失败不等于旧写者一定还能继续工作。

## 大 Goal 的捕获证明

序号恢复以前会返回完整 head 和历史事务的完整 projection，大 Goal 可能因此超过
现有 2 MiB RPC 响应上限，甚至不能产生晋升所需的 shadow 变更。
现在 `outbox_read` 的 proof read model 在 TS 内完整校验事务链，只传回进度、receipt、
projection digest 和 partition marker；分配序号不返回事务行，drain 使用紧凑行。
原有完整诊断读取保持默认合同，不提高传输上限、不减少持久数据，也不省略链校验。
若 outbox 尚未结清，晋升仍会拒绝。先执行并检查既有的有界 drain：
`authority-shadow drain --goal-id example-goal --budget-seconds 60`。

## 交付边界

这是运维 CLI 的显式管理操作，没有新增 Dashboard／飞书自动迁移按钮、设置项或
capability grant。它们在获授权的切换后继续使用既有 canonical 路由和展示合同。
PostgreSQL 仍需要服务持有的 factory 与租户权限，不能仅靠本地 selector 接通数据库。

PR #4870 提供保留 claim 的 `preserve`／`hard_lease` 转换，属于互补前置工作；
两者涉及同一个晋升编排，需要组合验证。本功能单独合入不会让 v0 checkout 自动获得
这些模式转换。默认切换、SQLite 长时资格、晋升后导出／回退、剩余 Python 删除，仍
遵守 RFC 的独立门槛。

恢复用于向前补齐或确认原切换，不是 rollback。不要删除活跃 fence、重置 canonical
存储或替换源文件来绕过拒绝。执行前放弃一份预览，只需停止使用该文件。

验证包括真实 File／SQLite CLI、完整合成状态的多 provider conformance、receipt
索引与事务链分别被破坏的负例，以及提交前中断、提交后丢响应的故障注入。故障注入
不等于任意进程崩溃或长时 soak 已验证。真实项目演练只在只读快照的可丢弃副本上执行。
