# Canonical 终结操作的审核与验证

在已显式晋升的本地 Goal 上，Agent 完成与 Monitor 停止现在复用 Todo 编辑、User
完成已有的审核恢复路径：预览绑定完整 provider revision 和注册摘要，保留同一个
operation identity，只有永久投影 outbox 确认当前显示后，Chat 才生成成功显示回执。

## 操作与恢复

CLI 完成后若响应丢失，重试时保留原完成标识：

```bash
loopx todo complete --goal-id example-goal --todo-id todo_work \
  --agent-id agent-a --completion-identity-key reviewed-result --no-follow-up
loopx todo list --goal-id example-goal --todo-id todo_work
loopx todo project-markdown --goal-id example-goal --execute
```

确实没有后继时才使用 `--no-follow-up`。有租约的工作还需要当前
`--task-lease-idempotency-key` 和 `--task-lease-expected-version`；用户确认不提供
租约或 lifecycle grant。Chat 重试同一个失败 proposal；stale proposal 需要重新预览，
不能换一个 operation id 绕过审核。

| 边界 | 可观察结果 |
| --- | --- |
| 新审核操作执行前 provider 或注册发生变化 | 私有验证执行前拒绝，Chat 标为 stale |
| 验证期间 provider 发生变化 | 拒绝旧验证结果，Todo 保持未完成 |
| 验证期间租约过期 | 以新的运行时时间重新检查执行证明并拒绝 |
| Canonical 提交成功，但显示失败 | 业务保持提交，Chat 返回可恢复失败，不生成成功显示回执 |
| 提交后的响应或 Chat 回执丢失 | 先恢复原业务回执，再处理当前显示，不用新状态否定历史提交 |
| 相同 operation 改了已审核的 note/evidence/reason/basis | 拒绝 identity 复用，不假装已接受新意图 |
| 完成后私有声明丢失 | 公开摘要足以恢复业务回执；无损显示恢复仍需找回原声明 |

TS terminal owner 统一决定准入、来源新鲜度、验证计划、租约退休、关联效果、CAS 与
回执恢复。Python 传事实，收到请求后解析私有 argv，执行已声明验证并交付投影，
不再决定旧验证是否可以完成当前工作。预览不执行 validator。User 的组合编辑/完成
语义以及已有 Chat proposal 协议保持兼容。

## 协议与迁移边界

当前 Python adapter 使用 `loopx_local_coordination_todo_terminal_lifecycle_request_v2`，
复用已有 terminal method，新增字段限定为：

- `review_basis`：若提供，精确包含 `provider_revision` 和 `registry_sha256`，绑定
  已审核意图并进入回执 identity。
- `validation_source_provider_revision`：发出 effect 前为 null，继续执行时传回发出的
  revision。它约束新鲜度，不创建新 operation identity；v2 的普通验证和 Goal acceptance
  验证都要求它。
- `validation_declaration_sha256`：canonical 的公开声明摘要。先查历史回执，再获取私有
  声明；新执行仍须验证原声明和当前授权。

同一 method 可先返回 `resolve_validation`，再返回 `execute_validation`。两者均绑定
来源 revision，均不提交业务。有验证的新完成从原先两次跨 runtime 请求变为三次
（解析声明、规划 effect、提交）；无验证完成和历史回放仍是一次 terminal 请求。
这次额外调用让恢复不依赖本机 argv，未来原生 host 同时拥有声明解析与 effect 执行后可删除。

v0/v1 保留原 fingerprint 和验证合同，拒绝新字段，不能静默丢弃约束。不带 review 的
v2 保留原 CLI terminal fingerprint，不改写旧回执。带审核 basis 的请求若遇到已回退
的 legacy authority，公共 facade 拒绝落入旧写路径。

本次不改变 provider 默认值、晋升、权限、保留策略或存储格式。回滚保留 provider
数据、回执和 writer fence，恢复兼容代码；旧代码不能执行 v2，应重新生成兼容预览，
不能剥掉审核字段。Markdown 仍是永久显示。此批闭合终结审核/恢复调用族，不等于
全部 leased metadata、executor-held effect fence、D1–D3 或整 Goal 切换完成。

共享 provider conformance 使用完整复杂 fixture、native/imported 两种记录，覆盖审核/
验证过期、租约过期、提交响应丢失和非目标记录不变。真实 File/SQLite Chat HTTP 测试
检查打包入口与重试反馈。前端运行时 decoder 与共享 action-review plan 现在为 Agent 完成和 Monitor
停止识别 terminal basis，打包 Chat 同步包含原操作重试路径，并区分显示待交付与
已验证完成；无需新增配置项或视觉控件。本次未新增 Lark 命令或传输。
