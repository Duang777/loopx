# Local CPA operator

The package now includes `loopx-cpa-operator`, a separately invoked local CLI.
The managed extension protocol remains read-only and permission-free. Installing
or running that protocol does not enable the operator, discover credentials,
start CPA, change an App, or write a task store.

## Routing preset

The operator's `abc-sol-astra` preset uses the existing `compile_catalog` ring
contract. Its credentials, App catalog, validation and observations share the
same selector definitions.

| Entry | Sol and Astra candidate order | Terminal fallback |
| --- | --- | --- |
| Auto / Prefer A | A → B → C | Ark, for eligible Standard text requests |
| Prefer B | B → C → A | Ark, for eligible Standard text requests |
| Prefer C | C → A → B | Ark, for eligible Standard text requests |
| Fast variants | Same account order | None |
| Luna | A → B → C | None |

Both Sol and Astra expose Auto, Prefer A/B/C and four Fast siblings. Together
with Luna and four existing Ark/compatibility rows, the App catalog has 21 rows.
Bare Sol/Astra identifiers are compatibility aliases and are not picker rows.
A preferred account is an entrypoint, not an exclusive pin. Ineligible, cooling
or exhausted accounts can be skipped. Auto affinity is a hint that CPA must
revalidate against account availability, input modality and service tier.

Standard routes keep the existing heterogeneous fallback, so their model labels
explicitly name Ark. Image history, effective priority tier and unsupported tool
transport must not be silently sent to a text/function-only provider. Code Mode
needs the CPA candidate's qualified `custom_tool_call` adaptation; the extension
compiler alone cannot enforce a wire capability. Fast/Luna routes have no Ark
alias at all. Transparent retry ends at the first visible output or tool call.

The pinned CPA runtime remains the only online router. The operator emits
configuration and metadata; it does not reimplement request retries. Existing
retry settings remain 10 CPA retries, up to a 65-second advised wait, and one
account-ring traversal per selection pass. Outer App retries are separate and
can start another request: one ring pass is **not** a bound on total turn time.
Account A no longer bypasses cooling. Fresh quota resets and recovery probes
remain CPA's responsibility; a cached quota observation is not permission to
permanently disable an account.

Fast rows set a picker default and the checksum-pinned request plugin forces
`service_tier=priority` before alias mapping. Verify the provider-bound request,
not just the App's thread default: a custom-provider App may report `default`.
The upstream response may also report `default`; a priority request is not a
promise that the upstream supplied an accelerated tier.

## Configuration and activation

Install in a dedicated Python 3.11+ environment:

```sh
python3 -m pip install packages/loopx-codex-provider-routing
loopx-cpa-operator --config /absolute/private/operator.json validate
loopx-cpa-operator --config /absolute/private/operator.json --execute validate
```

The first command produces a credential-free plan and performs no writes or
network/process operations. `--execute` authorizes only that invocation. Supply
a mode-0600 JSON file with `schema_version: "loopx_cpa_local_operator_v1"` and:

- `paths`: explicit absolute references for `runtime_root`, `temporary_root`,
  `binary`, `plugin_directory`, `codex_binary`, `gpt_cache`, `astra_cache`,
  `ark_catalog`, `ark_profile_catalog`, `ark_env_file`; optionally `login_source`;
- `binary_sha256`, `plugin_sha256`, `source_commit`: exact reviewed artifact pins;
- `port`: an unprivileged local TCP port; `launchd_label`: the owned service id;
- `ark_base_url`: a credential-free HTTPS endpoint;
- `ark_model`, `ark_pro_model`: upstream model identifiers.

Keep that file outside Git. Supply references, never inline keys or tokens.
Writable roots must be dedicated directories outside Git worktrees. Slot files
are basenames under the configured auth directory; traversal, duplicates and
symlink targets are rejected. Every receipt stays symbolic and credential-free.
The API key is read only by the local operator and placed in a private temporary
runtime config. Credentials, caches, binaries, plugin artifacts, logs, snapshots
and service-manager files are never package resources or LoopX state.

The App cache for each model is its metadata source; Astra does not inherit
Sol's prompt, context window or model capabilities. Auto retains the existing
low-through-max effort policy, while preferred routes preserve native levels.
CPA must refresh its model definitions: an old `-local-model` catalog can omit a
new model even when the App picker advertises it. The operator enables CPA's
model-definition refresh while keeping the executable/plugin hashes pinned.
Model-definition refresh and binary upgrade are separate operations.

## Commands

```sh
# Import the explicitly configured current login into a vacant symbolic slot.
loopx-cpa-operator --config /absolute/private/operator.json enroll --slot c
loopx-cpa-operator --config /absolute/private/operator.json --execute enroll --slot c

# Validate all three identities before updating any routing metadata.
loopx-cpa-operator --config /absolute/private/operator.json --execute reconcile
loopx-cpa-operator --config /absolute/private/operator.json --execute write-catalog

# Process supervision: configure the owned service manager to invoke this.
loopx-cpa-operator --config /absolute/private/operator.json --execute serve

# Content-free live and isolated App Server readback.
loopx-cpa-operator --config /absolute/private/operator.json --execute status
loopx-cpa-operator --config /absolute/private/operator.json --execute validate
loopx-cpa-operator --config /absolute/private/operator.json --execute probe
loopx-cpa-operator --config /absolute/private/operator.json --execute route-status
```

Enrollment checks account identity, token expiry, vacant slots and duplicate
accounts. It leaves the source login untouched. CPA owns subsequent refreshes.
Use a separately authorized OAuth login if another client concurrently rotates
that login and causes refresh conflicts. Never copy task databases or rollouts.

`serve` replaces its process with the pinned CPA executable; the service manager
owns restart supervision. `start`/`stop` are for an unmanaged process. `stop`
refuses to signal a launchd-managed or unrelated process. For launchd, unload the
specific configured service before changing its program, then load it again.
The operator does not modify LaunchAgents, App bundles or App processes itself.
Restart only the affected App after changing its model catalog, and verify the
21-row readback. Model registration is not proof of account entitlement or a
successful model call; perform a bounded live request separately.

## Rollback and disable

`reconcile`, `write-catalog` and `enroll` emit a `rollback_snapshot` identifier.
Snapshots stay in the configured private state directory. To restore one:

```sh
loopx-cpa-operator --config /absolute/private/operator.json rollback --snapshot-id SNAPSHOT_ID
loopx-cpa-operator --config /absolute/private/operator.json --execute rollback --snapshot-id SNAPSHOT_ID
```

Integrity and target checks precede writes. Restore routing metadata onto the
latest credential instead of restoring stale OAuth refresh tokens. Credentials
newly enrolled after the snapshot are retained but disabled during rollback.
Restart the owned service/App when restoring process configuration or a catalog.
The operator never deletes a credential or changes a task store.

To disable, unload the operator-owned service or stop its unmanaged process.
Restore the previous service program and private config from the installation
backup, or uninstall the dedicated environment. Keep auth/state for recovery.
Uninstalling the managed read-only extension does not stop an independently
installed operator service.

## Verification

```sh
python3 packages/loopx-codex-provider-routing/smoke/operator_smoke.py
python3 packages/loopx-codex-provider-routing/smoke/codex_provider_routing_smoke.py
```

Offline tests use only synthetic credentials and temporary directories. They
cover default-off isolation, slot/target boundaries, Sol/Astra parity, ring
order, rollback integrity and token rotation, and legacy A/B qualification.
`qualify_snapshot` accepts `routing_preset: "abc-sol-astra"`; omitting it keeps
the original A/B/Sol contract for existing consumers.
