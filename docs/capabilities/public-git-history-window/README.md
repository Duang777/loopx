# Public Git history window

`public_git_history_window` is an opt-in LoopX capability for callers that
publish public Git history. It evaluates a typed effect before commit, push,
merge, tag, or release execution and returns an `allow`, `defer`, or `reject`
receipt. Deferred work remains local until the configured window ends.

The capability does not cover ordinary PR collaboration. Comments, reviews,
labels, reviewer requests, and metadata remain available. PR creation is also
outside the history window when the head is already remote and the caller does
not perform an implicit push.

## Enable it for a goal

Keep the real timezone and window values in an ignored, untracked file below
the goal repository's `.loopx/config/` directory:

```json
{
  "schema_version": "public_git_history_window_config_v0",
  "timezone": "Region/City",
  "blocked_windows": [
    {
      "window_id": "working-window",
      "start": "09:00",
      "end": "17:00"
    }
  ],
  "public_repositories_only": true,
  "collaboration_writes_allowed": true
}
```

Preview and then apply the goal pointer:

```bash
loopx configure-goal \
  --goal-id <goal-id> \
  --public-git-history-window-config .loopx/config/public-history-window.json

loopx configure-goal \
  --goal-id <goal-id> \
  --public-git-history-window-config .loopx/config/public-history-window.json \
  --execute
```

The registry stores only the ignored file pointer. Quota and status projections
report that the capability is active without returning its private window
values.

## Evaluate an effect

Every public history caller supplies a stable effect id, the action, repository
visibility and identity, and the execution timestamp:

```bash
loopx --format json public-git-history-window evaluate \
  --goal-id <goal-id> \
  --effect-id <stable-effect-id> \
  --action push \
  --repository-visibility public \
  --repository-identity <provider/repository>
```

For push, merge, tag, and release, callers must also provide a verified JSON
list of newly outgoing commits. An empty list is accepted only after a real
comparison against the target remote ref proves that the effect publishes no
new commit:

```json
[
  {
    "sha": "<commit-sha>",
    "author_at": "2026-01-01T08:30:00+00:00",
    "committer_at": "2026-01-01T08:30:00+00:00"
  }
]
```

This prevents a commit created during a blocked window from being silently
published later. LoopX rejects that effect and asks the caller to recreate the
unpublished commit outside the window; it never falsifies author or committer
timestamps.

## Decision rules

- Window start is inclusive and window end is exclusive.
- Windows may cross midnight.
- Unknown repository visibility fails closed for history writes.
- Private repositories are outside a public-only policy.
- Auto-merge enablement is rejected because execution time would not be
  rechecked; the host must evaluate `pr_merge` when the merge actually runs.
- A repeated request with the same effect identity and inputs produces the same
  receipt identity.
- `pr_create` receipts require `head_already_remote` and `no_implicit_push`.

## Disable it

Preview and apply removal of the goal pointer:

```bash
loopx configure-goal --goal-id <goal-id> \
  --clear-public-git-history-window-config

loopx configure-goal --goal-id <goal-id> \
  --clear-public-git-history-window-config --execute
```

## Enforcement boundary

This version defines the provider-neutral decision and receipt contract plus a
real CLI entrypoint. A host or capability that can write public Git history
must call the evaluator before execution and obey non-allow receipts. Raw Git
commands that bypass the evaluator are not intercepted by this version.

中文摘要：该能力只约束公开仓库的历史写入，不约束 PR 评论、review、标签和
reviewer 等协作操作；真实时区和禁运时段只保存在项目本地的 ignored 配置中，
不会进入公开仓库或 quota 投影。
