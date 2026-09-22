# Goal handoff mode

`handoff-mode` chooses the ownership rule used by existing Todo/lease operations:
`legacy` retains the claim/lease compatibility model, `soft_claim` uses the Todo
claim, and `hard_lease` requires the existing lease fences. It is not an Agent
capability grant, provider selector, or Goal promotion command.

## Read and change

```bash
loopx handoff-mode show --goal-id example-goal --format json
loopx handoff-mode set --goal-id example-goal --mode soft_claim --dry-run --format json
loopx handoff-mode set --goal-id example-goal --mode soft_claim --format json
```

Before promotion, these commands use the existing frontmatter writer and its
state/lease locks. After promotion, they use the selected canonical provider;
`show` returns `source=canonical_provider` and its `provider_revision`, even if
Markdown is stale or missing. `--runtime-root` applies to both show and set.
Provider errors fail closed. A leftover local lease file cannot override an
empty canonical lease collection.

A mode change requires no unfinished claimed active Todo and no time-active
lease. The canonical transaction checks the complete Todo/lease snapshot,
including records outside display limits. An expiry equal to the observation
time is expired; an invalid active lease timestamp or unknown lease schema
cannot prove quiescence. Concurrent mutations invalidate the CAS snapshot and
return a conflict without switching the mode. Todos, lease records and their
read-model digests are preserved by the mode change.

The unpromoted scan retains its older materialized-state scope: it does not
claim to include event-only Todos. Its quiescence decision and the canonical
transaction now share one typed policy. No default mode changes.

## Preserve claims during authority promotion

The reviewed whole-Goal authority cutover has a narrower migration option for
an active Goal that cannot satisfy the ordinary quiescence rule:

```bash
# Keep legacy or soft_claim while changing only the storage authority.
loopx coordination-shadow promote --goal-id example-goal \
  --minimum-operations 3 --require-event-kind todo_claim \
  --handoff-mode-migration preserve

# Move legacy/soft_claim directly to hard_lease in the same reviewed cutover.
loopx coordination-shadow promote --goal-id example-goal \
  --minimum-operations 3 --require-event-kind todo_claim \
  --handoff-mode-migration hard_lease

# Apply only the exact plan returned by preview.
loopx coordination-shadow promote --goal-id example-goal \
  --minimum-operations 3 --require-event-kind todo_claim \
  --handoff-mode-migration hard_lease --execute
```

This is not a general mode-change bypass. The only explicit choices are
`preserve` and `hard_lease`; omitting the option retains the older requirement
that the qualified source already be `hard_lease`. The TypeScript promotion
transaction preserves every Todo, claim, lease record, receipt and validation
field. It validates live claim owners against the Goal agent registry and
retains an active lease only when its owner, Todo scopes, expiry, version and
epoch are safe. It never invents a lease for a preserved claim. After a direct
move to `hard_lease`, the same claim owner must acquire a fresh lease through
the ordinary atomic claim-and-lease path before protected work; another owner
remains rejected.

Preview reports the source revision/digest, target digest, preserved claims,
lease dispositions and conflicts. The target digest, selected migration and
registered-agent set enter the promotion-plan identity. Therefore an
interrupted cutover can recover only the same reviewed intent. The durable
legacy-writer fence blocks late old-session writes after cutover; a zero active
lease count alone is never treated as proof that no old Turn exists.

The CLI is the only mutation surface for this reviewed administrative action.
Managed Turns invoke that same CLI contract. Dashboard delegation preflight and
Lark/Chat remain read-only here: they already project `promotion_required` or
the promoted canonical authority and direct an operator to the reviewed
preview. The migration choice is one-shot operation intent, not Goal
configuration, so adding it to the capability editor would create a second
source of truth. After apply, all ordinary Todo/lease actions and receipts on
those surfaces read the same promoted projection.

## Recover a canonical request

Choose an operation ID before a canonical set if a lost response must be retried:

```bash
loopx handoff-mode set --goal-id example-goal --mode soft_claim --operation-id mode-change-1 --format json
# Repeat this exact intent to recover its original receipt.
loopx handoff-mode set --goal-id example-goal --mode soft_claim --operation-id mode-change-1 --format json
loopx handoff-mode show --goal-id example-goal --format json
```

The ID binds the goal and requested mode. Reuse with a different mode is rejected.
A retry's clock may advance; it still recovers the original result. Even an
accepted unchanged canonical set seals a receipt and advances provider revision,
while returning `changed=false`. If another mode was selected afterward, replay
returns the original decision without restoring it. Use `show` for current mode.
Preview writes neither a mode nor an operation receipt. `--operation-id` requires
canonical authority; the legacy writer does not promise durable operation replay.

Select a previous mode with a **new** operation ID to change it back, subject to
the same quiescence check. Do not disable the writer fence or restore old Markdown
to roll back a canonical change. The existing Todo-section renderer does not
project frontmatter: canonical mode is read through `handoff-mode show`, not a
possibly old frontmatter value. This command does not qualify a provider profile,
complete D1–D3, deploy PostgreSQL, or authorize active-Goal migration.

## 中文

`handoff-mode` 选择 Todo 的 claim／lease 所有权规则，不授予 capability、不选择
provider，也不执行 Goal 晋升。上面的命令分别用于读取、预览和切换。

晋升前保留 frontmatter 与本地锁兼容路径；晋升后从 canonical provider 读取，
Markdown 缺失／陈旧和遗留本地 lease 不再影响判断。`show` 返回来源及 revision；
provider 失败明确报错，不回退旧文件。现有 Todo-section 投影不包含 frontmatter，
因此当前 mode 应通过 `show` 查询。

切换要求完整快照内不存在未完成的已认领活动 Todo、不存在有效 lease。过期时间
恰好等于观察时间视为已过期；非法有效期或未知 lease schema 不能作为空闲证据。
并发修改使 CAS 冲突，不能在旧检查结果上继续切换。原 Todo、lease 和摘要不变。
未晋升路径仍仅扫描物化状态，不宣称覆盖 event-only Todo；两条路径共用 TS 切换规则。

对于无法清空活跃 claim 的 Goal，整 Goal authority 晋升提供一个更窄的显式迁移入口：
`--handoff-mode-migration preserve` 只切换存储权威并保留 `legacy`／`soft_claim`；
`--handoff-mode-migration hard_lease` 在同一受评审事务中直接迁到 `hard_lease`。
未传该参数时，继续沿用“源端已经是 `hard_lease`”的旧门禁。它不是通用 mode 绕过，
也不开放降级。

TypeScript 事务会原样保存 Todo、claim、lease record、receipt 与验证字段；校验活跃
claim owner 是否仍在 Goal agent registry 中，并且只有 owner、Todo scope、expiry、
version 与 epoch 都安全时才保留活跃 lease。迁到 `hard_lease` 不会为 claim 伪造
lease：原 owner 下一次受保护写入前，必须走正常的原子 claim+lease 路径取得新 lease，
异主仍被拒绝。preview 会给出源 revision/digest、目标 digest、保留 claim、lease
处置与冲突；这些内容进入 promotion-plan identity，所以中断后只能恢复完全相同的
评审意图。持久 legacy-writer fence 负责拦截旧 Turn 的迟到写入，不能用“当前 0 条
active lease”推断没有在途 Turn。

该受评审管理动作只有 CLI 一个写入口，managed Turn 也调用同一 CLI contract。
Dashboard 的 delegation preflight 与 Lark／Chat 在这里保持只读：它们已经投影
`promotion_required` 或晋升后的 canonical authority，并把 operator 引导到受评审
preview。migration choice 是单次 operation intent，不是 Goal 配置；把它再放进
capability editor 会制造第二个 truth source。apply 之后，各入口的普通 Todo／lease
动作与回执统一读取同一份 promoted projection。

需支持丢响应恢复时，在首次 canonical set 前指定 `--operation-id`，重试沿用同一
目标 mode 和 ID。不同 mode 复用 ID 会被拒绝；即使最初 mode 未变，也记录耐久回执。
若后来已切到其他 mode，旧请求重放只返回原回执，不把 mode 改回去；用 `show` 读当前值。
预览不写入；旧 writer 不支持该幂等 ID。需要切回时，用新 ID 请求原 mode，仍须满足
空闲门禁，不能通过关闭 fence 或恢复旧 Markdown 回滚。本功能不解除 provider
默认值、长程资格化、PostgreSQL 部署或 D1–D3 的剩余条件。
