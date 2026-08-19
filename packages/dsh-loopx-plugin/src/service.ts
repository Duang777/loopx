import { createHash, randomUUID } from 'node:crypto'
import { Context, Service } from '@deepseek-ai/cordis'
import s from '@deepseek-ai/schemastery'
import type { KvTable } from '@deepseek-ai/dsh-storage-domain'
import {
  coldRestoreBinding,
  createBinding,
  fenceMatches,
  fenceOf,
  sameSessionIdentity,
  schedulerBinding,
  snapshotBinding,
  transitionBinding,
} from './binding.ts'
import { LoopXCliClient, LoopXCliError } from './cli-client.ts'
import { failure, rejected, success } from './errors.ts'
import {
  bootstrapCommandPackSchema,
  bootstrapResultSchema,
  heartbeatPromptSchema,
  loopxBindingDomainSpec,
  quotaShouldRunSchema,
  refreshStateResultSchema,
  registerAgentSchema,
  startGoalGuidedSchema,
  statusSchema,
  threadBindingCommandSchema,
  todoAddCommandSchema,
  todoCommandSchema,
} from './schemas.ts'
import type {
  BootstrapCommandPackPayload,
  BootstrapCommandPackSuccessPayload,
  BootstrapResultPayload,
  HeartbeatPromptPayload,
  QuotaShouldRunPayload,
  RefreshStateResultPayload,
  RefreshStateResultSuccessPayload,
  StartGoalGuidedPayload,
  StartGoalGuidedSuccessPayload,
  TodoAddCommandPayload,
  TodoCommandPayload,
} from './schemas.ts'
import type {
  LoopXAttachRequest,
  LoopXAttachValue,
  LoopXBindingFence,
  LoopXBindingReason,
  LoopXBindingRow,
  LoopXFailure,
  LoopXHostStatus,
  LoopXIdentitySelection,
  LoopXPlanningCheckpoint,
  LoopXQuotaDecision,
  LoopXResult,
  LoopXSchedulerHint,
  LoopXServiceApi,
  LoopXSessionRef,
  LoopXStartValue,
  LoopXStartOptions,
  LoopXSwitchRequired,
  LoopXStatusValue,
  LoopXTaskBody,
  LoopXTodoClaimRequest,
  LoopXTodoAddRequest,
  LoopXTodoAddValue,
  LoopXTodoCompleteRequest,
  LoopXTodoMutationValue,
  LoopXTodoUpdateRequest,
} from './types.ts'

const HOST_SURFACE = 'deepseek-harness-native'
const RUNTIME_PROFILE = 'generic_cli'
const AGENT_SCOPE = 'DeepSeek Harness same-session LoopX plugin gated by LoopX'
const PUBLIC_AGENT_ID = /^[a-z0-9][a-z0-9._-]{0,127}$/u
const SWITCH_CONFIRMATION_TTL_MS = 2 * 60 * 1000
const PLANNING_TODO_LIMIT_CAP = 5
const PUBLIC_ACTION_KIND = /^[a-z][a-z0-9._:-]{0,63}$/u
const PUBLIC_TARGET_KEY = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$/u
const PRIORITY_PREFIX = /^\[P[012]\](?:\s|$)/iu
const UNSAFE_TODO_TEXT = /[\u0000-\u001F\u007F]/u
const FORBIDDEN_ACTIVATION_ARGUMENTS = new Set([
  'sessionId',
  'registryPath',
  'taskBody',
  'argv',
])

export interface Config {
  /** Explicit locally installed LoopX executable. Falls back to LOOPX_BIN, then PATH. */
  readonly loopxBin?: string
  /** Project locator used when a Session header has no cwd. */
  readonly project?: string
  /** Optional LoopX global runtime locator. */
  readonly runtimeRoot?: string
  readonly readTimeoutMs?: number
  readonly writeTimeoutMs?: number
  readonly stdoutCapBytes?: number
  readonly stderrCapBytes?: number
  /** Explicit child-only variables. The ambient environment is not inherited. */
  readonly environment?: Readonly<Record<string, string>>
}

interface ResolvedConfig extends Config {
  readonly readTimeoutMs: number
  readonly writeTimeoutMs: number
  readonly stdoutCapBytes: number
  readonly stderrCapBytes: number
  readonly environment: Readonly<Record<string, string>>
}

interface TaskBodyCacheEntry {
  readonly generation: number
  readonly body: string
}

interface SwitchConfirmationRecord {
  readonly token: string
  readonly session: LoopXSessionRef['identity']
  readonly currentGoalId: string
  readonly currentAgentId: string
  readonly digest: string
  readonly operation: 'start' | 'attach'
  readonly requestedGoalId?: string | undefined
  readonly requestedAgentId?: string | undefined
  readonly newPeer: boolean
  readonly newIndependent: boolean
  readonly expiresAt: number
}

interface NormalizedStartOptions {
  readonly goalId?: string | undefined
  readonly agentId?: string | undefined
  readonly newPeer: boolean
  readonly newIndependent: boolean
  readonly switchConfirmation?: string | undefined
}

interface ConnectedStartPacket {
  readonly packet: StartGoalGuidedSuccessPayload
  readonly connectedNow: boolean
}

interface NormalizedTodoAddRequest {
  readonly text: string
  readonly priority: 'P0' | 'P1' | 'P2'
  readonly role: 'user' | 'agent'
  readonly actionKind: string
  readonly targetKey?: string | undefined
  readonly normalizedTodo: string
}

declare module '@deepseek-ai/cordis' {
  interface Context {
    loopx: LoopXService
  }
}

function present(value: string | null | undefined): string | undefined {
  const normalized = value?.trim()
  return normalized ? normalized : undefined
}

function normalizedGoalText(value: string): string | undefined {
  const normalized = value.trim().replace(/\s+/gu, ' ')
  return normalized.length === 0 ? undefined : normalized
}

function validGoalId(value: string | undefined): value is string {
  return value !== undefined && value.length <= 256 && !value.includes('\0')
}

function operationDigest(value: Readonly<Record<string, unknown>>): string {
  return createHash('sha256').update(JSON.stringify(value)).digest('hex')
}

function optional<T extends object>(condition: boolean, value: T): T | Record<never, never> {
  return condition ? value : {}
}

function argsWhen(condition: boolean, ...values: string[]): string[] {
  return condition ? values : []
}

function isRecord(value: unknown): value is Readonly<Record<string, unknown>> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function safeFailure(error: unknown, operation: string): LoopXFailure {
  if (error instanceof LoopXCliError) return error.failure
  return failure(
    'LOOPX_CLI_FAILED',
    'The LoopX operation could not be completed.',
    { operation },
  )
}

function readbackFailure(operation: string, message: string): LoopXFailure {
  return failure('LOOPX_READBACK_FAILED', message, { operation })
}

function sameAgentSet(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every(agentId => right.includes(agentId))
}

function deterministicRegistrationFailure(errorKind: string): LoopXFailure {
  if (errorKind === 'agent_identity_already_registered') {
    return failure(
      'LOOPX_IDENTITY_CONFLICT',
      'The generated fresh LoopX identity already exists; retry Goal start to generate another.',
      { operation: 'register-agent', retryable: true },
    )
  }
  if (errorKind === 'agent_registration_sync_preflight_failed') {
    return failure(
      'LOOPX_REGISTRY_INTEGRITY',
      'LoopX rejected fresh-agent registration during source/global registry preflight. Run sync-global for the Goal in dry-run mode and repair the reported integrity error before retrying.',
      { operation: 'register-agent' },
    )
  }
  if (errorKind === 'global_registry_write_denied') {
    return failure(
      'LOOPX_CLI_FAILED',
      'LoopX could not write its global registry; repair the configured registry permissions before retrying.',
      { operation: 'register-agent' },
    )
  }
  return failure(
    'LOOPX_CLI_FAILED',
    'LoopX rejected fresh-agent registration before confirming any source write.',
    { operation: 'register-agent' },
  )
}

function driverFenceFailure(operation: string): LoopXFailure {
  return failure(
    'LOOPX_DRIVER_NOT_ARMED',
    'The requested Host transition no longer matches the armed binding.',
    { operation },
  )
}

function fenceMatchesSession(
  sessionId: string,
  row: LoopXBindingRow | undefined,
  fence: LoopXBindingFence,
): boolean {
  return fence.sessionId === sessionId && fenceMatches(row, fence)
}

function validateSession(session: LoopXSessionRef): LoopXFailure | undefined {
  if (!present(session.id) || session.id.length > 512 || session.id.includes('\0')) {
    return failure('LOOPX_INVALID_REQUEST', 'The current DSH Session identity is invalid.')
  }
  if (!Number.isSafeInteger(session.identity.createdAt) || session.identity.createdAt < 0) {
    return failure('LOOPX_INVALID_REQUEST', 'The current DSH Session lifecycle is invalid.')
  }
  if (session.identity.cwd?.includes('\0')) {
    return failure('LOOPX_INVALID_REQUEST', 'The current DSH Session working directory is invalid.')
  }
  return undefined
}

function normalizeStartOptions(
  options: LoopXStartOptions | undefined,
): LoopXResult<NormalizedStartOptions> {
  const goalId = present(options?.goalId)
  const agentId = present(options?.agentId)
  const switchConfirmation = present(options?.switchConfirmation)
  const newPeer = options?.newPeer === true
  const newIndependent = options?.newIndependent === true
  if ((options?.goalId !== undefined && !validGoalId(goalId))
    || (agentId !== undefined && !PUBLIC_AGENT_ID.test(agentId))
    || (options?.agentId !== undefined && agentId === undefined)
    || (options?.switchConfirmation !== undefined && switchConfirmation === undefined)
    || (switchConfirmation !== undefined && switchConfirmation.length > 128)
    || (newPeer && agentId !== undefined)
    || (newIndependent && (goalId !== undefined || agentId !== undefined))) {
    return rejected(failure(
      'LOOPX_INVALID_REQUEST',
      'Goal start selections, peer intent, independent intent, or confirmation are incompatible.',
      { operation: 'start' },
    ))
  }
  return success(Object.freeze({
    ...optional(goalId !== undefined, { goalId: goalId as string }),
    ...optional(agentId !== undefined, { agentId: agentId as string }),
    newPeer,
    newIndependent,
    ...optional(switchConfirmation !== undefined, {
      switchConfirmation: switchConfirmation as string,
    }),
  }))
}

function identitySelection(gate: {
  readonly default_action: string
  readonly reason?: string | undefined
  readonly choices: readonly { readonly agent_id: string; readonly label?: string | undefined }[]
  readonly fresh_agent_registration?: {
    readonly agent_id?: string | undefined
  } | null | undefined
}): LoopXIdentitySelection {
  const suggested = present(gate.fresh_agent_registration?.agent_id)
  return Object.freeze({
    kind: 'agent',
    defaultAction: gate.default_action,
    ...optional(gate.reason !== undefined, { reason: gate.reason as string }),
    choices: Object.freeze(gate.choices.map(choice => Object.freeze({
      agentId: choice.agent_id,
      ...optional(choice.label !== undefined, { label: choice.label as string }),
    }))),
    ...optional(suggested !== undefined && PUBLIC_AGENT_ID.test(suggested), {
      freshAgentSuggestedId: suggested as string,
    }),
  })
}

function goalSelection(gate: {
  readonly reason: string
  readonly choices: readonly { readonly goal_id: string }[]
}): LoopXIdentitySelection {
  return Object.freeze({
    kind: 'goal',
    defaultAction: 'select_goal',
    reason: gate.reason,
    choices: Object.freeze(gate.choices.map(choice => Object.freeze({
      goalId: choice.goal_id,
    }))),
  })
}

function modelCheckpoint(payload: StartGoalGuidedSuccessPayload): string | undefined {
  const checkpoints = (payload.guided_transaction?.ordered_steps ?? [])
    .filter(step => step.kind === 'model_checkpoint' && present(step.prompt) !== undefined)
  return checkpoints.length === 1 ? present(checkpoints[0]?.prompt) : undefined
}

function planningCheckpoint(
  payload: StartGoalGuidedSuccessPayload,
  goalText: string,
  goalId: string,
  agentId: string,
): LoopXPlanningCheckpoint | undefined {
  if (modelCheckpoint(payload) === undefined) return undefined
  const contract = payload.command_pack?.goal_start_contract
  const planner = contract?.planner
  const profiles = planner?.profiles
  const openEnded = profiles?.open_ended_product_direction
  const bounded = profiles?.clear_bounded_problem
  const required = planner?.required_fields ?? []
  if (contract === undefined || planner === undefined
    || contract.goal_text !== goalText
    || openEnded === undefined || bounded === undefined
    || openEnded.suggested_items_min > openEnded.suggested_items_max
    || !['priority', 'text', 'task_class', 'action_kind']
      .every(field => required.includes(field))) return undefined
  const limit = Math.min(
    planner.maximum_runnable_todos_written_ahead ?? PLANNING_TODO_LIMIT_CAP,
    PLANNING_TODO_LIMIT_CAP,
  )
  return Object.freeze({
    schemaVersion: 'dsh_loopx_planning_checkpoint_v0' as const,
    goalId,
    agentId,
    goalText,
    planner: Object.freeze({
      defaultProfile: planner.default_profile,
      profileSelection: planner.profile_selection,
      openEndedProductDirection: Object.freeze({
        suggestedItemsMin: openEnded.suggested_items_min,
        suggestedItemsMax: openEnded.suggested_items_max,
        intent: openEnded.intent,
      }),
      clearBoundedProblem: Object.freeze({
        itemCountPolicy: bounded.item_count_policy,
        mayReuseCurrentTodoWhenItAlreadyRepresentsThePlan:
          bounded.may_reuse_current_todo_when_it_already_represents_the_plan,
        intent: bounded.intent,
      }),
      allowedPriorities: Object.freeze(['P0', 'P1', 'P2'] as const),
      defaultRole: 'agent' as const,
      defaultTaskClass: 'advancement_task' as const,
      requiredFields: Object.freeze([...required]),
      publicSafeOnly: true as const,
      budgetPolicy: planner.budget_policy,
      ...optional(planner.fine_grained_plan_horizon !== undefined, {
        fineGrainedPlanHorizon: planner.fine_grained_plan_horizon as string,
      }),
    }),
    writeback: Object.freeze({
      todoTool: 'loopx_todo_add' as const,
      minimumTodos: 1 as const,
      maximumTodos: limit,
      ordering: 'priority_then_tool_call_order' as const,
      activationTool: 'loopx_goal_activate' as const,
      activationArguments: Object.freeze({ goalId, agentId }),
    }),
    stopConditions: Object.freeze([...contract.stop_conditions]),
    forbidden: Object.freeze([
      'shell_or_bash',
      'raw_loopx_cli',
      'registry_edit',
      'ctx.goals',
    ] as const),
  })
}

function renderPlanningCheckpoint(checkpoint: LoopXPlanningCheckpoint): string {
  return [
    'Follow this DSH-native LoopX planning checkpoint. Use only the named typed tools; do not execute shell or returned CLI text.',
    JSON.stringify(checkpoint),
  ].join('\n')
}

function normalizeTodoAddRequest(
  request: LoopXTodoAddRequest,
): LoopXResult<NormalizedTodoAddRequest> {
  const keys = Object.keys(request)
  const allowed = new Set(['text', 'priority', 'role', 'actionKind', 'targetKey'])
  const text = present(request.text)
  const role = request.role ?? 'agent'
  const actionKind = present(request.actionKind)
    ?? (role === 'agent' ? 'advance' : 'owner_decision')
  const targetKey = present(request.targetKey)
  if (!keys.every(key => allowed.has(key))
    || text === undefined || text.length > 1000
    || UNSAFE_TODO_TEXT.test(text) || PRIORITY_PREFIX.test(text)
    || !['P0', 'P1', 'P2'].includes(request.priority)
    || !['user', 'agent'].includes(role)
    || (request.actionKind !== undefined && present(request.actionKind) === undefined)
    || !PUBLIC_ACTION_KIND.test(actionKind)
    || (request.targetKey !== undefined && targetKey === undefined)
    || (targetKey !== undefined && !PUBLIC_TARGET_KEY.test(targetKey))
    || (role === 'user' && targetKey !== undefined)) {
    return rejected(failure(
      'LOOPX_INVALID_REQUEST',
      'Todo add requires bounded public-safe text, one P0/P1/P2 priority, a supported role/action, and an Agent-only public target key.',
      { operation: 'todo-add' },
    ))
  }
  return success(Object.freeze({
    text,
    priority: request.priority,
    role,
    actionKind,
    ...optional(targetKey !== undefined, { targetKey: targetKey as string }),
    normalizedTodo: `[${request.priority}] ${text}`,
  }))
}

function activationReadbackMatches(
  payload: BootstrapCommandPackPayload,
  session: LoopXSessionRef,
  goalId: string,
  agentId: string,
): payload is BootstrapCommandPackSuccessPayload {
  if (!payload.ok) return false
  const activation = payload.host_loop_activation
  const input = activation.activation_input
  const forbidden = activation.host_mutation.forbidden_tool_arguments
  const inputKeys = Object.keys(input.arguments)
  return payload.goal_id === goalId
    && payload.agent_id === agentId
    && payload.thread_id === session.id
    && payload.thread_agent_binding?.status === 'bound'
    && payload.thread_agent_binding.agent_id === agentId
    && activation.activation_allowed
    && activation.agent_id === agentId
    && activation.goal_id === goalId
    && input.arguments.goalId === goalId
    && input.arguments.agentId === agentId
    && [...FORBIDDEN_ACTIVATION_ARGUMENTS].every(field => forbidden.includes(field))
    && inputKeys.every(field => !FORBIDDEN_ACTIVATION_ARGUMENTS.has(field))
}

function terminalClosureIsComplete(payload: QuotaShouldRunPayload): boolean {
  if (payload.should_run || payload.effective_action !== 'terminal_no_followup') return false
  const projection = payload.goal_frontier_projection
  if (projection === undefined) return false
  const normalized = isRecord(projection.normalized_progress)
    ? projection.normalized_progress
    : undefined
  const frontier = isRecord(projection.remaining_advancement_frontier)
    ? projection.remaining_advancement_frontier
    : undefined
  const monitors = isRecord(projection.monitor_only_lanes)
    ? projection.monitor_only_lanes
    : undefined
  const successors = isRecord(projection.deferred_successors)
    ? projection.deferred_successors
    : undefined
  if (normalized === undefined || frontier === undefined
    || monitors === undefined || successors === undefined) return false
  const zeroValues = [
    normalized.user_open_count,
    normalized.agent_open_count,
    normalized.agent_advancement_open_count,
    normalized.agent_monitor_open_count,
    normalized.agent_monitor_due_count,
    frontier.current_agent_claimed_advancement_count,
    frontier.unclaimed_advancement_count,
    frontier.other_agent_claimed_advancement_count,
    successors.ready_count,
    successors.blocked_count,
    successors.current_agent_ready_count,
  ]
  return projection.terminal_state?.kind === 'no_followup'
    && projection.terminal_state.derived === true
    && projection.terminal_state.source === 'validated_goal_closure'
    && projection.source_completeness?.user_todos === 'valid'
    && projection.source_completeness.agent_todos === 'valid'
    && Array.isArray(projection.acceptance_gaps)
    && projection.acceptance_gaps.length === 0
    && Array.isArray(projection.autonomy_blockers)
    && projection.autonomy_blockers.length === 0
    && projection.replan_required === false
    && zeroValues.every(value => value === 0)
    && monitors.present === false
    && monitors.quiet_until_material_transition === false
}

function schedulerHint(payload: QuotaShouldRunPayload): LoopXSchedulerHint {
  const source = payload.scheduler_hint
  const detail = source.cold_path_detail.local_scheduler
  const resetToken = source.reset_policy.reset_token
  return Object.freeze({
    action: source.action,
    cadenceClass: source.cadence_class,
    resetToken,
    recommendedIntervalMinutes: detail.recommended_interval_minutes,
    ...optional(detail.unchanged_poll_limit !== null, {
      unchangedPollLimit: detail.unchanged_poll_limit as number,
    }),
    afterLimit: detail.after_limit,
  })
}

function boundedStatusProjection(payload: Readonly<Record<string, unknown>>, goalId: string) {
  const queue = isRecord(payload.attention_queue) ? payload.attention_queue : undefined
  const rawItems = Array.isArray(queue?.items) ? queue.items : []
  const items = rawItems.flatMap((value) => {
    if (!isRecord(value) || String(value.goal_id ?? '') !== goalId) return []
    const projected: Record<string, unknown> = { goal_id: goalId }
    for (const key of [
      'status',
      'waiting_on',
      'severity',
      'lifecycle_phase',
      'recommended_action',
    ] as const) {
      if (typeof value[key] === 'string') projected[key] = value[key]
    }
    return [Object.freeze(projected)]
  })
  return Object.freeze({
    schema_version: payload.schema_version,
    ok: payload.ok,
    goal_filter: payload.goal_filter,
    attention_queue: Object.freeze({ items: Object.freeze(items) }),
  })
}

function boundedTodoProjection(payload: TodoCommandPayload): Readonly<Record<string, unknown>> {
  const projected: Record<string, unknown> = {
    schema_version: payload.schema_version,
    ok: payload.ok,
    goal_id: payload.goal_id,
  }
  for (const key of [
    'todo_id',
    'status',
    'changed',
    'dry_run',
    'claimed_by',
    'task_class',
    'settlement_result',
  ] as const) {
    if (payload[key] !== undefined) projected[key] = payload[key]
  }
  return Object.freeze(projected)
}

function todoAddReadbackMatches(
  payload: TodoAddCommandPayload,
  row: LoopXBindingRow,
  request: NormalizedTodoAddRequest,
): payload is TodoAddCommandPayload & { readonly todo_id: string; readonly status: 'open' } {
  const agentFieldsMatch = request.role === 'agent'
    ? payload.claimed_by === row.agentId
      && payload.bound_agent === null
      && payload.agent_id === null
      && payload.blocks_agent === null
    : payload.claimed_by === null
      && payload.bound_agent === row.agentId
      && payload.agent_id === row.agentId
      && payload.blocks_agent === row.agentId
  return payload.ok
    && payload.dry_run === false
    && (payload.added || payload.already_exists)
    && payload.goal_id === row.goalId
    && payload.role === request.role
    && payload.todo === request.normalizedTodo
    && typeof payload.todo_id === 'string'
    && payload.todo_id.length > 0
    && payload.status === 'open'
    && payload.task_class === (request.role === 'agent' ? 'advancement_task' : 'user_gate')
    && payload.action_kind === request.actionKind
    && payload.target_key === (request.targetKey ?? null)
    && agentFieldsMatch
}

function boundedTodoAddProjection(
  payload: TodoAddCommandPayload,
): Readonly<Record<string, unknown>> {
  return Object.freeze({
    schema_version: payload.schema_version,
    ok: payload.ok,
    dry_run: payload.dry_run,
    added: payload.added,
    already_exists: payload.already_exists,
    goal_id: payload.goal_id,
    role: payload.role,
    todo: payload.todo,
    todo_id: payload.todo_id,
    status: payload.status,
    task_class: payload.task_class,
    action_kind: payload.action_kind,
    claimed_by: payload.claimed_by,
    bound_agent: payload.bound_agent,
    blocks_agent: payload.blocks_agent,
    target_key: payload.target_key,
  })
}

function refreshStateReadbackMatches(
  payload: RefreshStateResultPayload,
  row: LoopXBindingRow,
): payload is RefreshStateResultSuccessPayload {
  if (!payload.ok) return false
  const registry = row.registryLocator
  if (registry === undefined) return false
  const sync = payload.global_sync
  const sourceIsGlobal = sync.skipped === true
    && sync.reason === 'source registry is already the global registry'
    && sync.registry === registry
    && sync.global_registry === registry
    && sync.synced_goal_ids.length === 0
  const syncedGoal = sync.skipped !== true
    && sync.registry === registry
    && sync.synced_goal_ids.includes(row.goalId)
  return payload.dry_run === false
    && (payload.appended || payload.idempotent_replay === true)
    && payload.partial_write !== true
    && payload.registry === registry
    && payload.project === row.projectLocator
    && payload.goal_id === row.goalId
    && payload.agent_id === row.agentId
    && payload.agent_lane === row.agentId
    && payload.progress_scope === 'agent_lane'
    && payload.external_sink_delivery_authorized === false
    && sync.ok
    && (sourceIsGlobal || syncedGoal)
}

function boundedQuotaProjection(payload: QuotaShouldRunPayload): Readonly<Record<string, unknown>> {
  const projected: Record<string, unknown> = {
    schema_version: payload.schema_version,
    ok: payload.ok,
    mode: payload.mode,
    goal_id: payload.goal_id,
    should_run: payload.should_run,
    effective_action: payload.effective_action,
  }
  for (const key of ['decision', 'state', 'reason'] as const) {
    if (typeof payload[key] === 'string') projected[key] = payload[key]
  }
  return Object.freeze(projected)
}

/** Host-only service. LoopX remains authoritative for all Goal and Todo state. */
export class LoopXService extends Service implements LoopXServiceApi {
  static inject = ['storageDomain']

  static Config: s<Config> = s.object({
    loopxBin: s.string(),
    project: s.string(),
    runtimeRoot: s.string(),
    readTimeoutMs: s.number().step(1).min(1).default(15_000),
    writeTimeoutMs: s.number().step(1).min(1).default(30_000),
    stdoutCapBytes: s.number().step(1).min(1).default(1_048_576),
    stderrCapBytes: s.number().step(1).min(1).default(262_144),
    environment: s.dict(s.string()).default({}),
  })

  private readonly config: ResolvedConfig
  private readonly cli: LoopXCliClient
  private table: KvTable<string, LoopXBindingRow> | undefined
  private readonly operationTails = new Map<string, Promise<void>>()
  private readonly taskBodies = new Map<string, TaskBodyCacheEntry>()
  private readonly switchConfirmations = new Map<string, SwitchConfirmationRecord>()
  private mutationAdmissionOpen = true

  constructor(ctx: Context, config: Config) {
    super(ctx, 'loopx')
    const resolved = config as ResolvedConfig
    this.config = resolved
    this.cli = new LoopXCliClient({
      ...optional(present(config.loopxBin) !== undefined, {
        loopxBin: present(config.loopxBin) as string,
      }),
      readTimeoutMs: resolved.readTimeoutMs,
      writeTimeoutMs: resolved.writeTimeoutMs,
      stdoutCapBytes: resolved.stdoutCapBytes,
      stderrCapBytes: resolved.stderrCapBytes,
      environment: resolved.environment,
    })
  }

  protected async [Service.init](): Promise<void> {
    const domain = await this.ctx.storageDomain.open(loopxBindingDomainSpec)
    this.table = domain.table('sessions')
    this.ctx.effect(() => async () => {
      this.mutationAdmissionOpen = false
      await this.cli.close()
      await Promise.all(this.operationTails.values())
      this.taskBodies.clear()
      this.switchConfirmations.clear()
      await domain.close()
      this.table = undefined
    }, 'dsh-loopx-plugin.domainClose')

    const now = Date.now()
    for (const [sessionId, stored] of this.table.entries()) {
      const restored = coldRestoreBinding(stored, now)
      if (restored !== stored && restored.generation !== stored.generation) {
        await this.table.put(sessionId, restored)
      }
    }
  }

  getBinding(session: LoopXSessionRef): LoopXResult<LoopXBindingRow | undefined> {
    const invalid = validateSession(session)
    if (invalid !== undefined) return rejected(invalid)
    const row = this.requireTable().get(session.id)
    if (row === undefined || !sameSessionIdentity(row.session, session.identity)) {
      return success(undefined)
    }
    return success(snapshotBinding(row))
  }

  start(
    session: LoopXSessionRef,
    goalText: string,
    signal?: AbortSignal,
    options?: LoopXStartOptions,
  ): Promise<LoopXResult<LoopXStartValue>> {
    const normalizedGoal = normalizedGoalText(goalText)
    if (normalizedGoal === undefined) {
      return Promise.resolve(rejected(failure(
        'LOOPX_INVALID_REQUEST',
        'A non-empty Goal description is required.',
        { operation: 'start' },
      )))
    }
    const normalizedOptions = normalizeStartOptions(options)
    if (!normalizedOptions.ok) return Promise.resolve(normalizedOptions)
    return this.queued(session, 'start', async () => {
      const row = this.currentRow(session)
      const request = normalizedOptions.value
      const digest = operationDigest({
        operation: 'start',
        goalText: normalizedGoal,
        goalId: request.goalId ?? null,
        agentId: request.agentId ?? null,
        newPeer: request.newPeer,
        newIndependent: request.newIndependent,
      })
      if (row !== undefined) {
        const pending = this.validSwitchRecord(session, request.switchConfirmation, digest)
        const requestedGoalId = request.newIndependent
          ? pending?.requestedGoalId ?? this.freshGoalId()
          : request.goalId ?? row.goalId
        const requestedAgentId = request.agentId
          ?? (requestedGoalId === row.goalId && !request.newPeer ? row.agentId : undefined)
        const changesIdentity = request.newIndependent
          || request.newPeer
          || requestedGoalId !== row.goalId
          || (requestedAgentId !== undefined && requestedAgentId !== row.agentId)

        if (changesIdentity) {
          if (request.switchConfirmation === undefined) {
            return success(this.prepareSwitch(session, row, {
              digest,
              operation: 'start',
              requestedGoalId,
              requestedAgentId,
              newPeer: request.newPeer,
              newIndependent: request.newIndependent,
            }))
          }
          if (pending === undefined || pending.requestedGoalId !== requestedGoalId) {
            return rejected(this.invalidSwitchConfirmation('start'))
          }
          return await this.commitStartSwitch(
            session,
            row,
            normalizedGoal,
            request,
            pending,
            signal,
          )
        }
        if (request.switchConfirmation !== undefined) {
          return rejected(this.invalidSwitchConfirmation('start'))
        }
        this.switchConfirmations.delete(session.id)
        return await this.startInsideQueue(session, normalizedGoal, {
          ...request,
          goalId: row.goalId,
          agentId: row.agentId,
        }, signal, row)
      }
      if (request.switchConfirmation !== undefined) {
        return rejected(this.invalidSwitchConfirmation('start'))
      }
      this.switchConfirmations.delete(session.id)
      return await this.startInsideQueue(
        session,
        normalizedGoal,
        request.newIndependent ? { ...request, goalId: this.freshGoalId() } : request,
        signal,
      )
    })
  }

  attach(
    session: LoopXSessionRef,
    request: LoopXAttachRequest,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXAttachValue>> {
    const goalId = present(request.goalId)
    const requestedAgent = present(request.agentId)
    const switchConfirmation = present(request.switchConfirmation)
    if (goalId === undefined || (request.newPeer === true && requestedAgent !== undefined)
      || !validGoalId(goalId)
      || (requestedAgent !== undefined && !PUBLIC_AGENT_ID.test(requestedAgent))
      || (request.agentId !== undefined && requestedAgent === undefined)
      || (request.switchConfirmation !== undefined && switchConfirmation === undefined)
      || (switchConfirmation !== undefined && switchConfirmation.length > 128)) {
      return Promise.resolve(rejected(failure(
        'LOOPX_INVALID_REQUEST',
        'Attach requires a Goal id, one compatible agent selection, and a valid confirmation when supplied.',
        { operation: 'attach' },
      )))
    }
    return this.queued(session, 'attach', async () => {
      const row = this.currentRow(session)
      const digest = operationDigest({
        operation: 'attach',
        goalId,
        agentId: requestedAgent ?? null,
        newPeer: request.newPeer === true,
      })
      if (row !== undefined) {
        const targetAgent = requestedAgent
          ?? (goalId === row.goalId && request.newPeer !== true ? row.agentId : undefined)
        const changesIdentity = goalId !== row.goalId
          || request.newPeer === true
          || (targetAgent !== undefined && targetAgent !== row.agentId)
        if (changesIdentity) {
          if (switchConfirmation === undefined) {
            return success(this.prepareSwitch(session, row, {
              digest,
              operation: 'attach',
              requestedGoalId: goalId,
              requestedAgentId: targetAgent,
              newPeer: request.newPeer === true,
              newIndependent: false,
            }))
          }
          const pending = this.validSwitchRecord(session, switchConfirmation, digest)
          if (pending === undefined || pending.requestedGoalId !== goalId) {
            return rejected(this.invalidSwitchConfirmation('attach'))
          }
          return await this.commitAttachSwitch(
            session,
            row,
            goalId,
            requestedAgent,
            request.newPeer === true,
            pending,
            signal,
          )
        }
        if (switchConfirmation !== undefined) {
          return rejected(this.invalidSwitchConfirmation('attach'))
        }
        this.switchConfirmations.delete(session.id)
        this.cli.abortScope(session.id)
        return await this.attachInsideQueue(
          session,
          goalId,
          row.agentId,
          false,
          signal,
          row,
          true,
        )
      }
      if (switchConfirmation !== undefined) {
        return rejected(this.invalidSwitchConfirmation('attach'))
      }
      this.switchConfirmations.delete(session.id)
      this.cli.abortScope(session.id)
      return await this.attachInsideQueue(
        session,
        goalId,
        requestedAgent,
        request.newPeer === true,
        signal,
        undefined,
        true,
      )
    })
  }

  private async attachInsideQueue(
    session: LoopXSessionRef,
    goalId: string,
    requestedAgent: string | undefined,
    newPeer: boolean,
    signal: AbortSignal | undefined,
    existingRow: LoopXBindingRow | undefined,
    persistFailure: boolean,
  ): Promise<LoopXResult<LoopXAttachValue>> {
      const project = existingRow?.projectLocator ?? this.projectFor(session)
      if (project === undefined) return rejected(this.projectRequired('attach'))
      let packet: BootstrapCommandPackPayload
      try {
        packet = await this.readCommandPack(
          session,
          project,
          goalId,
          requestedAgent,
          newPeer,
          signal,
        )
      } catch (error) {
        return await this.attachFailure(
          session,
          existingRow,
          persistFailure,
          project,
          undefined,
          goalId,
          requestedAgent,
          safeFailure(error, 'attach'),
        )
      }
      if (!packet.ok) {
        return await this.attachFailure(
          session,
          existingRow,
          persistFailure,
          project,
          undefined,
          goalId,
          requestedAgent,
          readbackFailure('attach', 'LoopX rejected the attach target.'),
        )
      }
      if (packet.goal_id !== goalId
        || packet.project_connection?.connection_state !== 'connected'
        || packet.project_connection.goal_id !== goalId
        || packet.project_connection.project !== packet.project) {
        return await this.attachFailure(
          session,
          existingRow,
          persistFailure,
          project,
          packet.project_connection?.registry,
          goalId,
          requestedAgent,
          readbackFailure('attach', 'LoopX rejected or could not verify the attach target.'),
        )
      }

      if (requestedAgent === undefined && !newPeer) {
        const gate = packet.host_loop_activation.identity_selection_gate
        if (gate !== null && gate !== undefined) {
          return success({
            kind: 'selection_required',
            goalId,
            selection: identitySelection(gate),
          })
        }
        if (packet.thread_agent_binding?.status !== 'bound') {
          return success({
            kind: 'selection_required',
            goalId,
            selection: Object.freeze({
              kind: 'agent',
              defaultAction: 'select_agent_identity',
              reason: 'This exact DSH Session has no LoopX thread binding.',
              choices: Object.freeze(
                packet.host_loop_activation.identity_contract.registered_agents
                  .map(value => Object.freeze({ agentId: value })),
              ),
            }),
          })
        }
      }

      let agentId = requestedAgent
      if (newPeer) {
        const fresh = packet.host_loop_activation.identity_selection_gate
          ?.fresh_agent_registration
        if (fresh === null || fresh === undefined) {
          return rejected(failure(
            'LOOPX_IDENTITY_CONFLICT',
            'LoopX did not authorize fresh peer registration for this Goal.',
            { operation: 'attach' },
          ))
        }
        agentId = this.freshAgentId()
        const registered = await this.registerFreshAgent(
          session,
          project,
          goalId,
          agentId,
          signal,
          false,
        )
        if (!registered.ok) {
          return await this.attachFailure(
            session,
            existingRow,
            persistFailure && registered.error.outcomeUncertain,
            project,
            packet.project_connection?.registry,
            goalId,
            agentId,
            registered.error,
          )
        }
        try {
          packet = await this.readCommandPack(
            session,
            project,
            goalId,
            agentId,
            false,
            signal,
          )
        } catch (error) {
          return rejected(safeFailure(error, 'attach-registration-readback'))
        }
        if (!packet.ok) {
          return await this.attachFailure(
            session,
            existingRow,
            persistFailure,
            project,
            undefined,
            goalId,
            agentId,
            readbackFailure(
              'attach-registration-readback',
              'LoopX rejected the fresh-agent authoritative reread.',
            ),
          )
        }
      }
      agentId ??= present(packet.agent_id ?? undefined)
      if (agentId === undefined || !PUBLIC_AGENT_ID.test(agentId)) {
        return rejected(readbackFailure('attach', 'LoopX did not resolve an exact agent identity.'))
      }
      if (!packet.host_loop_activation.identity_contract.registered_agents.includes(agentId)
        || !packet.host_loop_activation.activation_allowed
        || packet.agent_id !== agentId) {
        return rejected(failure(
          'LOOPX_IDENTITY_CONFLICT',
          'The requested LoopX agent is not an authoritative registered lane.',
          { operation: 'attach' },
        ))
      }
      const priorAgent = packet.thread_agent_binding?.status === 'bound'
        ? present(packet.thread_agent_binding.agent_id)
        : undefined
      if (packet.thread_agent_binding?.status === 'conflict') {
        return rejected(failure(
          'LOOPX_IDENTITY_CONFLICT',
          'The LoopX thread binding is conflicted and must be repaired before attach.',
          { operation: 'attach' },
        ))
      }
      if (priorAgent !== undefined && priorAgent !== agentId) {
        const unbound = await this.writeThreadBinding(
          session,
          project,
          goalId,
          priorAgent,
          false,
          signal,
        )
        if (!unbound.ok) {
          return await this.attachFailure(
            session,
            existingRow,
            persistFailure && unbound.error.outcomeUncertain,
            project,
            packet.project_connection?.registry,
            goalId,
            agentId,
            unbound.error,
          )
        }
      }
      if (priorAgent !== agentId) {
        const bound = await this.writeThreadBinding(
          session,
          project,
          goalId,
          agentId,
          true,
          signal,
        )
        if (!bound.ok) {
          return await this.attachFailure(
            session,
            existingRow,
            persistFailure && bound.error.outcomeUncertain,
            project,
            packet.project_connection?.registry,
            goalId,
            agentId,
            bound.error,
          )
        }
      }
      const registryBeforeAttachReread = packet.project_connection?.registry
      try {
        packet = await this.readCommandPack(session, project, goalId, agentId, false, signal)
      } catch (error) {
        return await this.attachFailure(
          session,
          existingRow,
          persistFailure,
          project,
          registryBeforeAttachReread,
          goalId,
          agentId,
          safeFailure(error, 'attach-readback'),
        )
      }
      if (!packet.ok) {
        return await this.attachFailure(
          session,
          existingRow,
          persistFailure,
          project,
          undefined,
          goalId,
          agentId,
          readbackFailure('attach-readback', 'LoopX rejected the authoritative attach reread.'),
        )
      }
      const finalConnection = packet.project_connection
      if (finalConnection?.connection_state !== 'connected'
        || finalConnection.goal_id !== goalId
        || finalConnection.project !== packet.project
        || !activationReadbackMatches(packet, session, goalId, agentId)) {
        return await this.attachFailure(
          session,
          existingRow,
          persistFailure,
          project,
          packet.project_connection?.registry,
          goalId,
          agentId,
          readbackFailure(
            'attach-readback',
            'The authoritative LoopX thread and activation readback did not match.',
          ),
          'identity_conflict',
        )
      }
      let body: string
      try {
        body = await this.readTaskBody(
          session.id,
          project,
          packet.project_connection?.registry,
          goalId,
          agentId,
          signal,
        )
      } catch (error) {
        return await this.attachFailure(
          session,
          existingRow,
          persistFailure,
          packet.project,
          packet.project_connection?.registry,
          goalId,
          agentId,
          safeFailure(error, 'attach-task-body'),
        )
      }
      const current = this.currentRow(session)
      if ((existingRow === undefined && current !== undefined)
        || (existingRow !== undefined
          && (current === undefined
            || current.goalId !== existingRow.goalId
            || current.agentId !== existingRow.agentId))) {
        return rejected(readbackFailure('attach', 'The Session binding changed during attach.'))
      }
      const row = existingRow === undefined
        ? createBinding({
            session,
            goalId,
            agentId,
            projectLocator: packet.project,
            registryLocator: finalConnection.registry,
            ...optional(present(this.config.runtimeRoot) !== undefined, {
              runtimeRootLocator: present(this.config.runtimeRoot) as string,
            }),
            phase: 'active_armed',
            now: Date.now(),
          })
        : transitionBinding(existingRow, 'active_armed', undefined, Date.now())
      await this.requireTable().put(session.id, row)
      this.taskBodies.set(session.id, { generation: row.generation, body })
      return success({ kind: 'attached', binding: row })
  }

  private async startInsideQueue(
    session: LoopXSessionRef,
    goalText: string,
    options: NormalizedStartOptions,
    signal: AbortSignal | undefined,
    existingRow?: LoopXBindingRow,
  ): Promise<LoopXResult<LoopXStartValue>> {
    const project = existingRow?.projectLocator ?? this.projectFor(session)
    if (project === undefined) return rejected(this.projectRequired('start'))

    let packet: StartGoalGuidedPayload
    try {
      packet = await this.readStartPacket(
        session,
        project,
        goalText,
        options.goalId,
        options.agentId,
        options.newPeer,
        signal,
      )
    } catch (error) {
      return rejected(safeFailure(error, 'start'))
    }
    const connected = await this.ensureStartConnection(
      session,
      project,
      goalText,
      options,
      packet,
      signal,
    )
    if (!connected.ok) return connected
    packet = connected.value.packet

    if (packet.goal_selection_gate !== undefined) {
      return success({
        kind: 'selection_required',
        selection: goalSelection(packet.goal_selection_gate),
      })
    }
    const connection = packet.project_connection
    const goalId = present(packet.goal_id ?? undefined)
    if (!packet.ok || connection?.connection_state !== 'connected'
      || goalId === undefined || connection.goal_id !== goalId
      || connection.project !== packet.project
      || (options.goalId !== undefined && options.goalId !== goalId)
      || (options.newIndependent && !connected.value.connectedNow)) {
      return rejected(readbackFailure(
        'start',
        'LoopX did not return one connected authoritative Goal target.',
      ))
    }

    let agentId = options.agentId
    let changedThread = false
    const gate = packet.guided_transaction?.identity_selection_gate ?? undefined
    if (agentId !== undefined) {
      const allowed = packet.agent_id === agentId
        || gate?.choices.some(choice => choice.agent_id === agentId) === true
      if (!allowed) {
        return rejected(failure(
          'LOOPX_IDENTITY_CONFLICT',
          'The selected LoopX agent is not present in the authoritative selection contract.',
          { operation: 'start' },
        ))
      }
    } else if (options.newPeer || gate?.default_action === 'register_fresh_agent') {
      if (gate?.fresh_agent_registration === null
        || gate?.fresh_agent_registration === undefined) {
        return rejected(failure(
          'LOOPX_IDENTITY_CONFLICT',
          'LoopX did not authorize fresh peer registration for this Goal.',
          { operation: 'start' },
        ))
      }
      agentId = this.freshAgentId()
      const registered = await this.registerFreshAgent(
        session,
        project,
        goalId,
        agentId,
        signal,
        false,
      )
      if (!registered.ok) return registered
      changedThread = true
    } else if (gate !== undefined) {
      return success({
        kind: 'selection_required',
        goalId,
        selection: identitySelection(gate),
      })
    } else {
      agentId = present(packet.agent_id ?? undefined)
    }

    if (agentId === undefined || !PUBLIC_AGENT_ID.test(agentId)) {
      return rejected(readbackFailure('start', 'LoopX did not resolve an exact agent identity.'))
    }
    const priorAgent = packet.thread_agent_binding?.status === 'bound'
      ? present(packet.thread_agent_binding.agent_id)
      : undefined
    if (packet.thread_agent_binding?.status === 'conflict') {
      return rejected(failure(
        'LOOPX_IDENTITY_CONFLICT',
        'The LoopX thread binding is conflicted and must be repaired before Goal start.',
        { operation: 'start' },
      ))
    }
    if (priorAgent !== agentId) {
      if (priorAgent !== undefined) {
        const unbound = await this.writeThreadBinding(
          session,
          project,
          goalId,
          priorAgent,
          false,
          signal,
        )
        if (!unbound.ok) return unbound
      }
      const bound = await this.writeThreadBinding(
        session,
        project,
        goalId,
        agentId,
        true,
        signal,
      )
      if (!bound.ok) return bound
      changedThread = true
    }
    if (changedThread) {
      try {
        packet = await this.readStartPacket(
          session,
          project,
          goalText,
          goalId,
          agentId,
          false,
          signal,
        )
      } catch (error) {
        return rejected(safeFailure(error, 'start-readback'))
      }
    }
    if (!packet.ok) {
      return rejected(readbackFailure(
        'start-readback',
        'LoopX rejected the authoritative Goal-start reread.',
      ))
    }

    const finalConnection = packet.project_connection
    const finalGoalId = present(packet.goal_id ?? undefined)
    const finalAgentId = present(packet.agent_id ?? undefined)
    const planning = finalGoalId === undefined || finalAgentId === undefined
      ? undefined
      : planningCheckpoint(packet, goalText, finalGoalId, finalAgentId)
    if (finalConnection?.connection_state !== 'connected'
      || finalConnection.goal_id !== goalId
      || finalConnection.project !== packet.project
      || finalGoalId !== goalId || finalAgentId !== agentId
      || planning === undefined
      || packet.guided_transaction?.identity_selection_gate != null
      || packet.host_surface !== HOST_SURFACE
      || packet.thread_id !== session.id
      || packet.thread_agent_binding?.status !== 'bound'
      || packet.thread_agent_binding.agent_id !== agentId) {
      return rejected(readbackFailure(
        'start-readback',
        'LoopX did not return one exact bound identity and model checkpoint.',
      ))
    }
    const current = this.currentRow(session)
    if ((existingRow === undefined && current !== undefined)
      || (existingRow !== undefined
        && (current === undefined
          || current.goalId !== existingRow.goalId
          || current.agentId !== existingRow.agentId))) {
      return rejected(readbackFailure('start', 'The Session binding changed during Goal start.'))
    }
    const row = existingRow === undefined
      ? createBinding({
          session,
          goalId,
          agentId,
          projectLocator: packet.project,
          registryLocator: finalConnection.registry,
          ...optional(present(this.config.runtimeRoot) !== undefined, {
            runtimeRootLocator: present(this.config.runtimeRoot) as string,
          }),
          phase: 'planning',
          now: Date.now(),
        })
      : transitionBinding(existingRow, 'planning', undefined, Date.now())
    await this.requireTable().put(session.id, row)
    this.taskBodies.delete(session.id)
    return success({
      kind: 'planning',
      binding: row,
      planning,
      modelCheckpoint: renderPlanningCheckpoint(planning),
    })
  }

  private async ensureStartConnection(
    session: LoopXSessionRef,
    project: string,
    goalText: string,
    options: NormalizedStartOptions,
    initial: StartGoalGuidedPayload,
    signal: AbortSignal | undefined,
  ): Promise<LoopXResult<ConnectedStartPacket>> {
    if (!initial.ok) {
      return rejected(readbackFailure('start', 'LoopX rejected the guided Goal start.'))
    }
    const connection = initial.project_connection
    if (connection === undefined || connection.project !== initial.project) {
      return rejected(readbackFailure('start', 'LoopX omitted the project connection contract.'))
    }
    if (connection.connection_state === 'connected'
      || connection.connection_state === 'goal_selection_required') {
      return success({ packet: initial, connectedNow: false })
    }
    if (connection.connection_state !== 'not_connected'
      && connection.connection_state !== 'registry_without_goal') {
      return rejected(readbackFailure(
        'start',
        'LoopX reported malformed project state that requires explicit repair.',
      ))
    }

    const goalId = present(initial.goal_id ?? undefined)
    const connectSteps = (initial.guided_transaction?.ordered_steps ?? [])
      .filter(step => step.id === 'connect_if_needed')
    const contract = connectSteps.length === 1 ? connectSteps[0]?.connect_contract : undefined
    if (goalId === undefined || connection.goal_id !== goalId
      || contract === undefined
      || contract.goal_id !== goalId
      || contract.objective !== goalText) {
      return rejected(readbackFailure(
        'bootstrap-connect',
        'LoopX did not return one exact structured connect contract.',
      ))
    }
    const bootstrapped = await this.bootstrapConnect(
      session,
      project,
      connection.project,
      connection.registry,
      contract,
      options.newIndependent,
      signal,
    )
    if (!bootstrapped.ok) return bootstrapped

    let reread: StartGoalGuidedPayload
    try {
      reread = await this.readStartPacket(
        session,
        project,
        goalText,
        goalId,
        options.agentId,
        options.newPeer,
        signal,
      )
    } catch (error) {
      return rejected(safeFailure(error, 'start-authoritative-reread'))
    }
    if (!reread.ok || reread.goal_id !== goalId
      || reread.project_connection?.connection_state !== 'connected'
      || reread.project_connection.goal_id !== goalId
      || reread.project_connection.registry !== connection.registry
      || reread.project_connection.project !== connection.project) {
      return rejected(readbackFailure(
        'start-authoritative-reread',
        'LoopX did not verify the connected Goal after bootstrap.',
      ))
    }
    return success({ packet: reread, connectedNow: true })
  }

  private async bootstrapConnect(
    session: LoopXSessionRef,
    cwd: string,
    expectedProject: string,
    expectedRegistry: string,
    contract: NonNullable<StartGoalGuidedSuccessPayload['guided_transaction']>['ordered_steps'][number]['connect_contract'],
    forkGoal: boolean,
    signal: AbortSignal | undefined,
  ): Promise<LoopXResult<undefined>> {
    if (contract === undefined) {
      return rejected(readbackFailure('bootstrap-connect', 'The connect contract is missing.'))
    }
    let payload: BootstrapResultPayload
    try {
      payload = await this.cli.runJson({
        operation: 'bootstrap-connect',
        kind: 'idempotent-write',
        args: [
          ...this.runtimeArgs(),
          'bootstrap',
          '--project', cwd,
          forkGoal ? '--fork-goal' : '--goal-id', contract.goal_id,
          '--objective', contract.objective,
          '--adapter-kind', contract.adapter_kind,
          '--adapter-status', contract.adapter_status,
          '--no-onboarding-scan',
          '--codex-app-heartbeat', 'ask',
          ...argsWhen(contract.fine_grained, '--fine-grained'),
        ],
        cwd,
        schema: bootstrapResultSchema,
        signal,
        scopeKey: session.id,
      })
    } catch (error) {
      return rejected(safeFailure(error, 'bootstrap-connect'))
    }
    if (!payload.ok) {
      return rejected(failure(
        'LOOPX_BOOTSTRAP_FAILED',
        'LoopX rejected the typed project connection request; resolve the LoopX project or global-registry gate, then call loopx_goal_start again.',
        { operation: 'bootstrap-connect' },
      ))
    }
    if (payload.project !== expectedProject
      || payload.goal_id !== contract.goal_id
      || payload.registry !== expectedRegistry
      || !payload.global_sync.synced_goal_ids.includes(contract.goal_id)) {
      return rejected(readbackFailure(
        'bootstrap-connect',
        'LoopX did not verify the requested project, Goal, registry, and global synchronization.',
      ))
    }
    return success(undefined)
  }

  private prepareSwitch(
    session: LoopXSessionRef,
    row: LoopXBindingRow,
    request: Omit<SwitchConfirmationRecord, 'token' | 'session' | 'currentGoalId' | 'currentAgentId' | 'expiresAt'>,
  ): LoopXSwitchRequired {
    const record: SwitchConfirmationRecord = Object.freeze({
      token: randomUUID(),
      session: Object.freeze({ ...session.identity }),
      currentGoalId: row.goalId,
      currentAgentId: row.agentId,
      ...request,
      expiresAt: Date.now() + SWITCH_CONFIRMATION_TTL_MS,
    })
    this.switchConfirmations.set(session.id, record)
    return Object.freeze({
      kind: 'switch_required',
      confirmationToken: record.token,
      requiresUserConfirmation: true,
      expiresAt: record.expiresAt,
      current: Object.freeze({ goalId: row.goalId, agentId: row.agentId }),
      requested: Object.freeze({
        operation: record.operation,
        ...optional(record.requestedGoalId !== undefined, {
          goalId: record.requestedGoalId as string,
        }),
        ...optional(record.requestedAgentId !== undefined, {
          agentId: record.requestedAgentId as string,
        }),
        ...optional(record.newPeer, { newPeer: true as const }),
        ...optional(record.newIndependent, { newIndependent: true as const }),
      }),
    })
  }

  private validSwitchRecord(
    session: LoopXSessionRef,
    token: string | undefined,
    digest: string,
  ): SwitchConfirmationRecord | undefined {
    const record = this.switchConfirmations.get(session.id)
    if (record === undefined) return undefined
    if (record.expiresAt <= Date.now()
      || !sameSessionIdentity(record.session, session.identity)
      || record.digest !== digest) {
      this.switchConfirmations.delete(session.id)
      return undefined
    }
    if (token === undefined || record.token !== token) return undefined
    const row = this.currentRow(session)
    if (row === undefined || row.goalId !== record.currentGoalId
      || row.agentId !== record.currentAgentId) {
      this.switchConfirmations.delete(session.id)
      return undefined
    }
    return record
  }

  private async commitStartSwitch(
    session: LoopXSessionRef,
    row: LoopXBindingRow,
    goalText: string,
    request: NormalizedStartOptions,
    confirmation: SwitchConfirmationRecord,
    signal: AbortSignal | undefined,
  ): Promise<LoopXResult<LoopXStartValue>> {
    this.switchConfirmations.delete(session.id)
    const detached = await this.detachForSwitch(session, row, signal)
    if (!detached.ok) return detached
    const result = await this.startInsideQueue(session, goalText, {
      ...request,
      goalId: confirmation.requestedGoalId,
      agentId: confirmation.requestedAgentId,
      switchConfirmation: undefined,
    }, signal)
    if (!result.ok) return rejected(this.switchIncomplete('start', result.error))
    return result
  }

  private async commitAttachSwitch(
    session: LoopXSessionRef,
    row: LoopXBindingRow,
    goalId: string,
    requestedAgent: string | undefined,
    newPeer: boolean,
    confirmation: SwitchConfirmationRecord,
    signal: AbortSignal | undefined,
  ): Promise<LoopXResult<LoopXAttachValue>> {
    this.switchConfirmations.delete(session.id)
    const detached = await this.detachForSwitch(session, row, signal)
    if (!detached.ok) return detached
    const result = await this.attachInsideQueue(
      session,
      goalId,
      requestedAgent ?? confirmation.requestedAgentId,
      newPeer,
      signal,
      undefined,
      false,
    )
    if (!result.ok) return rejected(this.switchIncomplete('attach', result.error))
    return result
  }

  private async detachForSwitch(
    session: LoopXSessionRef,
    row: LoopXBindingRow,
    signal: AbortSignal | undefined,
  ): Promise<LoopXResult<undefined>> {
    this.cli.abortScope(session.id)
    this.taskBodies.delete(session.id)
    const detached = await this.writeThreadBinding(
      session,
      row.projectLocator,
      row.goalId,
      row.agentId,
      false,
      signal,
    )
    if (!detached.ok) {
      if (detached.error.outcomeUncertain) {
        const current = this.currentRow(session)
        if (current !== undefined && current.goalId === row.goalId
          && current.agentId === row.agentId) {
          await this.requireTable().put(
            session.id,
            transitionBinding(current, 'uncertain', 'uncertain_write', Date.now()),
          )
        }
      }
      return detached
    }
    await this.requireTable().delete(session.id)
    return success(undefined)
  }

  private async attachFailure(
    session: LoopXSessionRef,
    existingRow: LoopXBindingRow | undefined,
    persistFailure: boolean,
    project: string,
    registry: string | undefined,
    goalId: string,
    agentId: string | undefined,
    cause: LoopXFailure,
    reason?: LoopXBindingReason,
  ): Promise<LoopXResult<LoopXAttachValue>> {
    if (existingRow !== undefined) {
      return await this.disarmInsideQueue(session, existingRow, cause)
    }
    if (persistFailure && agentId !== undefined) {
      return await this.persistAttachFailure(
        session,
        project,
        registry,
        goalId,
        agentId,
        cause,
        reason,
      )
    }
    return rejected(cause)
  }

  private invalidSwitchConfirmation(operation: 'start' | 'attach'): LoopXFailure {
    return failure(
      'LOOPX_SWITCH_CONFIRMATION_INVALID',
      'The LoopX switch confirmation is missing, expired, stale, or bound to another operation; repeat the same typed request without a token to prepare a new confirmation.',
      { operation },
    )
  }

  private switchIncomplete(operation: 'start' | 'attach', cause: LoopXFailure): LoopXFailure {
    return failure(
      'LOOPX_SWITCH_INCOMPLETE',
      'The old LoopX binding was detached, but the requested replacement did not complete; this DSH Session is unbound, so call loopx_goal_start or loopx_goal_attach again.',
      {
        operation: `switch-${operation}`,
        outcomeUncertain: cause.outcomeUncertain,
      },
    )
  }

  activate(
    session: LoopXSessionRef,
    goalId: string,
    agentId?: string,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXBindingRow>> {
    return this.queued(session, 'activate', async () => {
      const row = this.currentRow(session)
      if (row === undefined) return rejected(this.notBound('activate'))
      if (row.phase !== 'planning' || row.goalId !== present(goalId)
        || (present(agentId) !== undefined && row.agentId !== present(agentId))) {
        return rejected(failure(
          'LOOPX_IDENTITY_CONFLICT',
          'Activation must match the exact pending Goal and agent identity.',
          { operation: 'activate' },
        ))
      }
      const before = fenceOf(session.id, row)
      let packet: BootstrapCommandPackPayload
      let body: string
      let refreshVerified = false
      try {
        const refresh = await this.cli.runJson({
          operation: 'refresh-state',
          kind: 'write',
          args: [
            ...this.locatorArgs(row),
            'refresh-state',
            '--goal-id', row.goalId,
            '--project', row.projectLocator,
            '--agent-id', row.agentId,
            '--agent-lane', row.agentId,
            '--progress-scope', 'agent_lane',
            '--suppress-external-sinks',
          ],
          cwd: row.projectLocator,
          schema: refreshStateResultSchema,
          signal,
          scopeKey: session.id,
        })
        if (!refreshStateReadbackMatches(refresh, row)) {
          return await this.disarmInsideQueue(
            session,
            row,
            failure(
              'LOOPX_WRITE_UNCERTAIN',
              'LoopX refresh-state did not verify the exact suppressed-sink planning commit.',
              { operation: 'activate-refresh', outcomeUncertain: true },
            ),
          )
        }
        refreshVerified = true
        packet = await this.readCommandPack(
          session,
          row.projectLocator,
          row.goalId,
          row.agentId,
          false,
          signal,
        )
        if (!activationReadbackMatches(packet, session, row.goalId, row.agentId)) {
          return await this.disarmInsideQueue(
            session,
            row,
            failure(
              'LOOPX_WRITE_UNCERTAIN',
              'LoopX refresh-state succeeded, but activation readback did not match the pending binding.',
              { operation: 'activate-readback', outcomeUncertain: true },
            ),
          )
        }
        body = await this.readTaskBody(
          session.id,
          row.projectLocator,
          row.registryLocator ?? packet.project_connection?.registry,
          row.goalId,
          row.agentId,
          signal,
        )
      } catch (error) {
        const cause = safeFailure(error, refreshVerified ? 'activate-readback' : 'activate-refresh')
        return await this.disarmInsideQueue(
          session,
          row,
          refreshVerified && !cause.outcomeUncertain
            ? failure(
                'LOOPX_WRITE_UNCERTAIN',
                'LoopX refresh-state succeeded, but authoritative activation readback failed.',
                { operation: 'activate-readback', outcomeUncertain: true },
              )
            : cause,
        )
      }
      if (!this.fenceIsCurrent(before)) {
        return rejected(readbackFailure('activate', 'The pending binding changed during activation.'))
      }
      const armed = transitionBinding(row, 'active_armed', undefined, Date.now())
      await this.requireTable().put(session.id, armed)
      this.taskBodies.set(session.id, { generation: armed.generation, body })
      return success(armed)
    })
  }

  async status(
    session: LoopXSessionRef,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXStatusValue>> {
    const binding = this.getBinding(session)
    if (!binding.ok) return binding
    const host: LoopXHostStatus = Object.freeze({
      binarySource: this.cli.binarySource,
      ...optional(binding.value !== undefined, { binding: binding.value as LoopXBindingRow }),
    })
    if (binding.value === undefined) return success({ host })
    const row = binding.value
    const before = fenceOf(session.id, row)
    try {
      const payload = await this.cli.runJson({
        operation: 'status',
        kind: 'read',
        args: [
          ...this.locatorArgs(row),
          'status',
          '--goal-id', row.goalId,
          '--agent-id', row.agentId,
        ],
        cwd: row.projectLocator,
        schema: statusSchema,
        signal,
        scopeKey: session.id,
      })
      if (!payload.ok || (payload.goal_filter !== null && payload.goal_filter !== row.goalId)) {
        await this.pauseAfterReadFailure(session, before)
        return rejected(readbackFailure('status', 'LoopX status did not match the current binding.'))
      }
      if (!this.fenceIsCurrent(before)) {
        return rejected(readbackFailure('status', 'The binding changed during status readback.'))
      }
      return success({
        host,
        authority: boundedStatusProjection(payload, row.goalId),
      })
    } catch (error) {
      await this.pauseAfterReadFailure(session, before)
      return rejected(safeFailure(error, 'status'))
    }
  }

  pause(
    session: LoopXSessionRef,
    reason: LoopXBindingReason = 'user_pause',
    expectedFence?: LoopXBindingFence,
  ): Promise<LoopXResult<LoopXBindingRow>> {
    if (expectedFence === undefined) {
      this.cli.abortScope(session.id)
      this.taskBodies.delete(session.id)
    }
    return this.queued(session, 'pause', async () => {
      const row = this.currentRow(session)
      if (row === undefined) return rejected(this.notBound('pause'))
      if (expectedFence !== undefined
        && !fenceMatchesSession(session.id, row, expectedFence)) {
        return rejected(driverFenceFailure('pause'))
      }
      if (expectedFence !== undefined) {
        this.cli.abortScope(session.id)
        this.taskBodies.delete(session.id)
      }
      const phase = row.phase === 'planning' ? 'planning' : 'active_paused'
      const paused = transitionBinding(row, phase, reason, Date.now())
      await this.requireTable().put(session.id, paused)
      return success(paused)
    })
  }

  resume(
    session: LoopXSessionRef,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXBindingRow>> {
    return this.queued(session, 'resume', async () => {
      const row = this.currentRow(session)
      if (row === undefined) return rejected(this.notBound('resume'))
      if (row.phase === 'planning') {
        return rejected(failure(
          'LOOPX_DRIVER_NOT_ARMED',
          'The pending Goal must be activated before the driver can resume.',
          { operation: 'resume' },
        ))
      }
      let packet: BootstrapCommandPackPayload
      let body: string
      try {
        packet = await this.readCommandPack(
          session,
          row.projectLocator,
          row.goalId,
          row.agentId,
          false,
          signal,
        )
        if (!activationReadbackMatches(packet, session, row.goalId, row.agentId)) {
          return await this.disarmInsideQueue(
            session,
            row,
            readbackFailure('resume', 'LoopX binding readback did not match the paused driver.'),
          )
        }
        body = await this.readTaskBody(
          session.id,
          row.projectLocator,
          row.registryLocator ?? packet.project_connection?.registry,
          row.goalId,
          row.agentId,
          signal,
        )
      } catch (error) {
        return await this.disarmInsideQueue(session, row, safeFailure(error, 'resume'))
      }
      const armed = transitionBinding(row, 'active_armed', undefined, Date.now())
      await this.requireTable().put(session.id, armed)
      this.taskBodies.set(session.id, { generation: armed.generation, body })
      return success(armed)
    })
  }

  detach(
    session: LoopXSessionRef,
    signal?: AbortSignal,
  ): Promise<LoopXResult<{ readonly detached: true }>> {
    this.cli.abortScope(session.id)
    this.taskBodies.delete(session.id)
    this.switchConfirmations.delete(session.id)
    return this.queued(session, 'detach', async () => {
      const row = this.currentRow(session)
      if (row === undefined) return rejected(this.notBound('detach'))
      const result = await this.writeThreadBinding(
        session,
        row.projectLocator,
        row.goalId,
        row.agentId,
        false,
        signal,
      )
      if (!result.ok) {
        return await this.disarmInsideQueue(session, row, result.error)
      }
      await this.requireTable().delete(session.id)
      return success(Object.freeze({ detached: true as const }))
    })
  }

  todoAdd(
    session: LoopXSessionRef,
    request: LoopXTodoAddRequest,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXTodoAddValue>> {
    const normalized = normalizeTodoAddRequest(request)
    if (!normalized.ok) return Promise.resolve(normalized)
    return this.queued(session, 'todo-add', async () => {
      const row = this.currentRow(session)
      if (row === undefined) return rejected(this.notBound('todo-add'))
      if (row.phase !== 'planning') {
        return rejected(failure(
          'LOOPX_DRIVER_NOT_ARMED',
          'Todo add requires the current planning binding; call loopx_goal_start to create a new plan.',
          { operation: 'todo-add' },
        ))
      }
      const before = fenceOf(session.id, row)
      const todo = normalized.value
      const taskClass = todo.role === 'agent' ? 'advancement_task' : 'user_gate'
      const roleArgs = todo.role === 'agent'
        ? ['--claimed-by', row.agentId]
        : [
            '--agent-id', row.agentId,
            '--bound-agent', row.agentId,
            '--blocks-agent', row.agentId,
          ]
      try {
        const payload = await this.cli.runJson({
          operation: 'todo-add',
          kind: 'write',
          args: [
            ...this.locatorArgs(row),
            'todo', 'add',
            '--goal-id', row.goalId,
            '--project', row.projectLocator,
            '--role', todo.role,
            '--text', todo.normalizedTodo,
            '--status', 'open',
            '--task-class', taskClass,
            '--action-kind', todo.actionKind,
            ...roleArgs,
            ...argsWhen(todo.targetKey !== undefined, '--target-key', todo.targetKey ?? ''),
          ],
          cwd: row.projectLocator,
          schema: todoAddCommandSchema,
          signal,
          scopeKey: session.id,
        })
        if (!todoAddReadbackMatches(payload, row, todo)) {
          return await this.disarmInsideQueue(
            session,
            row,
            failure(
              'LOOPX_WRITE_UNCERTAIN',
              'LoopX did not verify the exact typed Todo add postcondition.',
              { operation: 'todo-add', outcomeUncertain: true },
            ),
          )
        }
        if (!this.fenceIsCurrent(before)) {
          return await this.disarmInsideQueue(
            session,
            row,
            failure(
              'LOOPX_WRITE_UNCERTAIN',
              'The planning binding changed after LoopX admitted the Todo write.',
              { operation: 'todo-add', outcomeUncertain: true },
            ),
          )
        }
        return success(Object.freeze({
          todoId: payload.todo_id,
          status: 'open' as const,
          priority: todo.priority,
          role: todo.role,
          payload: boundedTodoAddProjection(payload),
        }))
      } catch (error) {
        return await this.disarmInsideQueue(session, row, safeFailure(error, 'todo-add'))
      }
    })
  }

  todoClaim(
    session: LoopXSessionRef,
    request: LoopXTodoClaimRequest,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXTodoMutationValue>> {
    const todoId = present(request.todoId)
    if (todoId === undefined) return Promise.resolve(rejected(this.invalidTodo('todo-claim')))
    return this.todoMutation(session, 'todo-claim', [
      'todo', 'claim',
      '--todo-id', todoId,
      '--claimed-by', '__BOUND_AGENT__',
      ...argsWhen(request.role !== undefined, '--role', request.role ?? ''),
    ], todoId, signal)
  }

  todoUpdate(
    session: LoopXSessionRef,
    request: LoopXTodoUpdateRequest,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXTodoMutationValue>> {
    const todoId = present(request.todoId)
    const args = ['todo', 'update', '--todo-id', todoId ?? '']
    const fields: readonly [string, string | undefined][] = [
      ['--status', request.status],
      ['--note', present(request.note)],
      ['--evidence', present(request.evidence)],
      ['--reason', present(request.reason)],
      ['--task-class', request.taskClass],
    ]
    for (const [flag, value] of fields) if (value !== undefined) args.push(flag, value)
    if (request.clearClaim === true) args.push('--clear-claim')
    if (todoId === undefined || args.length === 4) {
      return Promise.resolve(rejected(this.invalidTodo('todo-update')))
    }
    return this.todoMutation(session, 'todo-update', args, todoId, signal)
  }

  todoComplete(
    session: LoopXSessionRef,
    request: LoopXTodoCompleteRequest,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXTodoMutationValue>> {
    const todoId = present(request.todoId)
    if (todoId === undefined
      || (request.taskLeaseExpectedVersion !== undefined
        && (!Number.isSafeInteger(request.taskLeaseExpectedVersion)
          || request.taskLeaseExpectedVersion < 0))) {
      return Promise.resolve(rejected(this.invalidTodo('todo-complete')))
    }
    const args = ['todo', 'complete', '--todo-id', todoId]
    const fields: readonly [string, string | undefined][] = [
      ['--note', present(request.note)],
      ['--evidence', present(request.evidence)],
      ['--turn-instance-id', present(request.turnInstanceId)],
      ['--task-lease-idempotency-key', present(request.taskLeaseIdempotencyKey)],
      [
        '--task-lease-expected-version',
        request.taskLeaseExpectedVersion === undefined
          ? undefined
          : String(request.taskLeaseExpectedVersion),
      ],
    ]
    for (const [flag, value] of fields) if (value !== undefined) args.push(flag, value)
    if (request.noFollowUp === true) args.push('--no-follow-up')
    return this.todoMutation(session, 'todo-complete', args, todoId, signal)
  }

  async quotaShouldRun(
    session: LoopXSessionRef,
    turnInstanceId: string,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXQuotaDecision>> {
    const turnId = present(turnInstanceId)
    const binding = this.getBinding(session)
    if (!binding.ok) return binding
    const row = binding.value
    if (row === undefined) return rejected(this.notBound('quota-should-run'))
    if (row.phase !== 'active_armed' || turnId === undefined) {
      return rejected(failure(
        'LOOPX_DRIVER_NOT_ARMED',
        'Quota evaluation requires an armed binding and one turn identity.',
        { operation: 'quota-should-run' },
      ))
    }
    const before = fenceOf(session.id, row)
    try {
      const payload = await this.cli.runJson({
        operation: 'quota-should-run',
        kind: 'idempotent-write',
        args: [
          ...this.locatorArgs(row),
          'quota', 'should-run',
          '--goal-id', row.goalId,
          '--agent-id', row.agentId,
          '--runtime-profile', RUNTIME_PROFILE,
          '--include-detail', 'scheduler',
          '--turn-instance-id', turnId,
        ],
        cwd: row.projectLocator,
        schema: quotaShouldRunSchema,
        signal,
        scopeKey: session.id,
      })
      if (!payload.ok || payload.goal_id !== row.goalId
        || payload.agent_identity.agent_id !== row.agentId
        || payload.heartbeat_receipt?.turn_instance_id !== turnId) {
        await this.pauseAfterReadFailure(session, before)
        return rejected(readbackFailure(
          'quota-should-run',
          'LoopX quota did not confirm the current Goal, agent, and turn identity.',
        ))
      }
      if (!this.fenceIsCurrent(before)) {
        return rejected(readbackFailure('quota-should-run', 'The binding changed during quota evaluation.'))
      }
      const hint = schedulerHint(payload)
      return success(Object.freeze({
        goalId: row.goalId,
        agentId: row.agentId,
        turnInstanceId: turnId,
        shouldRun: payload.should_run,
        effectiveAction: payload.effective_action,
        schedulerHint: hint,
        terminalNoFollowup: terminalClosureIsComplete(payload),
        payload: boundedQuotaProjection(payload),
      }))
    } catch (error) {
      const cause = safeFailure(error, 'quota-should-run')
      if (cause.outcomeUncertain) {
        await this.markUncertain(session, 'uncertain_write', before)
      } else if (!cause.retryable) {
        await this.pauseAfterReadFailure(session, before)
      }
      return rejected(cause)
    }
  }

  async taskBody(
    session: LoopXSessionRef,
    generation: number,
    refresh = false,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXTaskBody>> {
    const binding = this.getBinding(session)
    if (!binding.ok) return binding
    const row = binding.value
    if (row === undefined) return rejected(this.notBound('task-body'))
    if (row.phase !== 'active_armed' || row.generation !== generation) {
      return rejected(failure(
        'LOOPX_DRIVER_NOT_ARMED',
        'The requested task body generation is no longer armed.',
        { operation: 'task-body' },
      ))
    }
    const fence = fenceOf(session.id, row)
    const cached = this.taskBodies.get(session.id)
    if (!refresh && cached?.generation === generation) {
      return success({ fence, body: cached.body })
    }
    try {
      const body = await this.readTaskBody(
        session.id,
        row.projectLocator,
        row.registryLocator,
        row.goalId,
        row.agentId,
        signal,
      )
      if (!this.fenceIsCurrent(fence)) {
        return rejected(readbackFailure('task-body', 'The binding changed while task body was loading.'))
      }
      this.taskBodies.set(session.id, { generation, body })
      return success({ fence, body })
    } catch (error) {
      await this.pauseAfterReadFailure(session, fence)
      return rejected(safeFailure(error, 'task-body'))
    }
  }

  updateScheduler(
    session: LoopXSessionRef,
    fence: LoopXBindingFence,
    hint: LoopXSchedulerHint,
    unchangedPollCount: number,
    nextCheckAt?: number,
  ): Promise<LoopXResult<LoopXBindingRow>> {
    return this.queued(session, 'update-scheduler', async () => {
      const row = this.currentRow(session)
      if (!fenceMatchesSession(session.id, row, fence) || row?.phase !== 'active_armed'
        || !Number.isSafeInteger(unchangedPollCount) || unchangedPollCount < 0
        || (nextCheckAt !== undefined
          && (!Number.isSafeInteger(nextCheckAt) || nextCheckAt < 0))) {
        return rejected(failure(
          'LOOPX_DRIVER_NOT_ARMED',
          'The scheduler update no longer matches the armed binding.',
          { operation: 'update-scheduler' },
        ))
      }
      const updated = schedulerBinding(row, hint, unchangedPollCount, nextCheckAt, Date.now())
      await this.requireTable().put(session.id, updated)
      return success(updated)
    })
  }

  fence(session: LoopXSessionRef): LoopXResult<LoopXBindingFence> {
    const binding = this.getBinding(session)
    if (!binding.ok) return binding
    if (binding.value === undefined) return rejected(this.notBound('fence'))
    return success(fenceOf(session.id, binding.value))
  }

  fenceIsCurrent(fence: LoopXBindingFence): boolean {
    return fenceMatches(this.requireTable().get(fence.sessionId), fence)
  }

  markUncertain(
    session: LoopXSessionRef,
    reason: LoopXBindingReason = 'uncertain_write',
    expectedFence?: LoopXBindingFence,
  ): Promise<LoopXResult<LoopXBindingRow>> {
    if (expectedFence === undefined) {
      this.cli.abortScope(session.id)
      this.taskBodies.delete(session.id)
    }
    return this.queued(session, 'mark-uncertain', async () => {
      const row = this.currentRow(session)
      if (row === undefined) return rejected(this.notBound('mark-uncertain'))
      if (expectedFence !== undefined
        && !fenceMatchesSession(session.id, row, expectedFence)) {
        return rejected(driverFenceFailure('mark-uncertain'))
      }
      if (expectedFence !== undefined) {
        this.cli.abortScope(session.id)
        this.taskBodies.delete(session.id)
      }
      const uncertain = transitionBinding(row, 'uncertain', reason, Date.now())
      await this.requireTable().put(session.id, uncertain)
      return success(uncertain)
    })
  }

  async disposeSession(session: LoopXSessionRef): Promise<void> {
    this.cli.abortScope(session.id)
    this.taskBodies.delete(session.id)
    this.switchConfirmations.delete(session.id)
    if (!this.mutationAdmissionOpen || validateSession(session) !== undefined) return
    await this.enqueue(session.id, async () => {
      const row = this.currentRow(session)
      if (row === undefined) return
      const phase = row.phase === 'planning' ? 'planning' : 'active_paused'
      await this.requireTable().put(
        session.id,
        transitionBinding(row, phase, 'session_disposed', Date.now()),
      )
    })
  }

  private async readStartPacket(
    session: LoopXSessionRef,
    project: string,
    goalText: string,
    goalId: string | undefined,
    agentId: string | undefined,
    newPeer: boolean,
    signal: AbortSignal | undefined,
  ): Promise<StartGoalGuidedPayload> {
    return await this.cli.runJson({
      operation: 'start-goal',
      kind: 'read',
      args: [
        ...this.runtimeArgs(),
        'start-goal', '--guided',
        '--project', project,
        '--thread-id', session.id,
        '--host-surface', HOST_SURFACE,
        ...argsWhen(goalId !== undefined, '--goal-id', goalId ?? ''),
        ...argsWhen(agentId !== undefined, '--agent-id', agentId ?? ''),
        ...argsWhen(newPeer, '--new-peer'),
        '--goal-text', goalText,
      ],
      cwd: project,
      schema: startGoalGuidedSchema,
      signal,
      scopeKey: session.id,
    })
  }

  private async readCommandPack(
    session: LoopXSessionRef,
    project: string,
    goalId: string,
    agentId: string | undefined,
    newPeer: boolean,
    signal: AbortSignal | undefined,
  ): Promise<BootstrapCommandPackPayload> {
    return await this.cli.runJson({
      operation: 'bootstrap-command-pack',
      kind: 'read',
      args: [
        ...this.runtimeArgs(),
        'bootstrap-command-pack',
        '--project', project,
        '--goal-id', goalId,
        '--thread-id', session.id,
        '--host-surface', HOST_SURFACE,
        ...argsWhen(agentId !== undefined, '--agent-id', agentId ?? ''),
        ...argsWhen(newPeer, '--new-peer'),
      ],
      cwd: project,
      schema: bootstrapCommandPackSchema,
      signal,
      scopeKey: session.id,
    })
  }

  private async readTaskBody(
    scopeKey: string,
    project: string,
    registry: string | undefined,
    goalId: string,
    agentId: string,
    signal: AbortSignal | undefined,
  ): Promise<string> {
    const payload: HeartbeatPromptPayload = await this.cli.runJson({
      operation: 'heartbeat-prompt',
      kind: 'read',
      args: [
        ...this.locatorValues(registry, present(this.config.runtimeRoot)),
        'heartbeat-prompt', '--thin',
        '--goal-id', goalId,
        '--agent-id', agentId,
        '--agent-scope', AGENT_SCOPE,
        '--runtime-profile', RUNTIME_PROFILE,
      ],
      cwd: project,
      schema: heartbeatPromptSchema,
      signal,
      scopeKey,
    })
    const body = present(payload.task_body ?? undefined)
    if (!payload.ok || payload.goal_id !== goalId || payload.agent_id !== agentId
      || body === undefined) {
      throw new LoopXCliError(readbackFailure(
        'heartbeat-prompt',
        'LoopX did not return the bound heartbeat task body.',
      ))
    }
    return body
  }

  private async registerFreshAgent(
    session: LoopXSessionRef,
    project: string,
    goalId: string,
    agentId: string,
    signal: AbortSignal | undefined,
    bindThread = true,
  ): Promise<LoopXResult<undefined>> {
    try {
      const payload = await this.cli.runJson({
        operation: 'register-agent',
        kind: 'write',
        args: [
          ...this.runtimeArgs(),
          'register-agent',
          '--goal-id', goalId,
          '--agent-id', agentId,
          '--require-new',
          '--execute',
        ],
        cwd: project,
        schema: registerAgentSchema,
        signal,
        scopeKey: session.id,
      })
      if (!payload.ok) {
        if (!payload.written && !payload.partial_write) {
          return rejected(deterministicRegistrationFailure(payload.error_kind))
        }
        return rejected(failure(
          'LOOPX_WRITE_UNCERTAIN',
          'LoopX may have written the fresh agent to its source registry, but global sync or authoritative readback was not verified. Repair source/global registry consistency before retrying; do not create another fresh identity.',
          { operation: 'register-agent', outcomeUncertain: true },
        ))
      }
      const readback = payload.registration_readback
      if (payload.goal_id !== goalId
        || payload.requested_agents.length !== 1
        || payload.requested_agents[0] !== agentId
        || !payload.registered_agents.includes(agentId)
        || readback.requested_agents.length !== 1
        || readback.requested_agents[0] !== agentId
        || !readback.source_registered_agents.includes(agentId)
        || !readback.global_registered_agents.includes(agentId)
        || !sameAgentSet(
          readback.source_registered_agents,
          readback.global_registered_agents,
        )) {
        return rejected(failure(
          'LOOPX_WRITE_UNCERTAIN',
          'LoopX did not verify the exact fresh agent across source and global readback.',
          { operation: 'register-agent', outcomeUncertain: true },
        ))
      }
      if (!bindThread) return success(undefined)
      return await this.writeThreadBinding(
        session,
        project,
        goalId,
        agentId,
        true,
        signal,
      )
    } catch (error) {
      return rejected(safeFailure(error, 'register-agent'))
    }
  }

  private async writeThreadBinding(
    session: LoopXSessionRef,
    project: string,
    goalId: string,
    agentId: string,
    bind: boolean,
    signal: AbortSignal | undefined,
  ): Promise<LoopXResult<undefined>> {
    const operation = bind ? 'bind-agent-thread' : 'unbind-agent-thread'
    try {
      const payload = await this.cli.runJson({
        operation,
        kind: 'write',
        args: [
          ...this.runtimeArgs(),
          operation,
          '--goal-id', goalId,
          '--thread-id', session.id,
          '--host-surface', HOST_SURFACE,
          '--agent-id', agentId,
          '--execute',
        ],
        cwd: project,
        schema: threadBindingCommandSchema,
        signal,
        scopeKey: session.id,
      })
      const expected = bind ? 'bound' : 'missing'
      if (!payload.ok || payload.goal_id !== goalId
        || payload.thread_id !== session.id
        || payload.host_surface !== HOST_SURFACE
        || payload.agent_id !== agentId
        || payload.binding?.status !== expected
        || payload.binding.thread_id !== session.id
        || payload.binding.host_surface !== HOST_SURFACE
        || (bind && payload.binding.agent_id !== agentId)
        || (!bind && payload.binding.agent_id !== null)
        || payload.global_sync?.ok !== true
        || payload.registration_readback?.verified !== true) {
        return rejected(failure(
          'LOOPX_WRITE_UNCERTAIN',
          `LoopX did not verify the ${bind ? 'bound' : 'unbound'} thread postcondition.`,
          { operation, outcomeUncertain: true },
        ))
      }
      return success(undefined)
    } catch (error) {
      return rejected(safeFailure(error, operation))
    }
  }

  private todoMutation(
    session: LoopXSessionRef,
    operation: string,
    commandArgs: string[],
    todoId: string,
    signal: AbortSignal | undefined,
  ): Promise<LoopXResult<LoopXTodoMutationValue>> {
    return this.queued(session, operation, async () => {
      const row = this.currentRow(session)
      if (row === undefined) return rejected(this.notBound(operation))
      if (row.phase === 'uncertain') {
        return rejected(failure(
          'LOOPX_WRITE_UNCERTAIN',
          'Read back and resume the LoopX binding before another Todo mutation.',
          { operation, outcomeUncertain: true },
        ))
      }
      const args = commandArgs.map(value => value === '__BOUND_AGENT__' ? row.agentId : value)
      args.push('--goal-id', row.goalId, '--agent-id', row.agentId)
      try {
        const payload = await this.cli.runJson({
          operation,
          kind: 'write',
          args: [...this.locatorArgs(row), ...args],
          cwd: row.projectLocator,
          schema: todoCommandSchema,
          signal,
          scopeKey: session.id,
        })
        if (!payload.ok || payload.goal_id !== row.goalId || payload.todo_id !== todoId) {
          return await this.disarmInsideQueue(
            session,
            row,
            failure(
              'LOOPX_WRITE_UNCERTAIN',
              'The LoopX Todo write did not return a verified postcondition.',
              { operation, outcomeUncertain: true },
            ),
          )
        }
        return success(Object.freeze({
          todoId,
          ...optional(payload.status !== undefined, { status: payload.status as string }),
          payload: boundedTodoProjection(payload),
        }))
      } catch (error) {
        return await this.disarmInsideQueue(session, row, safeFailure(error, operation))
      }
    })
  }

  private async disarmInsideQueue<T>(
    session: LoopXSessionRef,
    observed: LoopXBindingRow,
    cause: LoopXFailure,
  ): Promise<LoopXResult<T>> {
    const current = this.currentRow(session)
    if (current !== undefined && current.generation === observed.generation) {
      const uncertain = cause.outcomeUncertain || observed.phase === 'uncertain'
      const phase = uncertain ? 'uncertain' : observed.phase === 'planning' ? 'planning' : 'active_paused'
      const reason: LoopXBindingReason = uncertain ? 'uncertain_write' : 'readback_failed'
      await this.requireTable().put(
        session.id,
        transitionBinding(current, phase, reason, Date.now()),
      )
      this.taskBodies.delete(session.id)
    }
    return rejected(cause)
  }

  private async persistAttachFailure(
    session: LoopXSessionRef,
    project: string,
    registry: string | undefined,
    goalId: string,
    agentId: string,
    cause: LoopXFailure,
    reason?: LoopXBindingReason,
  ): Promise<LoopXResult<LoopXAttachValue>> {
    if (this.currentRow(session) !== undefined) return rejected(cause)
    const now = Date.now()
    const candidate = createBinding({
      session,
      goalId,
      agentId,
      projectLocator: project,
      ...optional(registry !== undefined, { registryLocator: registry as string }),
      ...optional(present(this.config.runtimeRoot) !== undefined, {
        runtimeRootLocator: present(this.config.runtimeRoot) as string,
      }),
      phase: 'active_armed',
      now,
    })
    const outcomeUncertain = cause.outcomeUncertain
    const disarmed = transitionBinding(
      candidate,
      outcomeUncertain ? 'uncertain' : 'active_paused',
      reason ?? (outcomeUncertain ? 'uncertain_write' : 'readback_failed'),
      now,
    )
    await this.requireTable().put(session.id, disarmed)
    this.taskBodies.delete(session.id)
    return rejected(cause)
  }

  private async pauseAfterReadFailure(
    session: LoopXSessionRef,
    expectedFence: LoopXBindingFence,
  ): Promise<void> {
    if (!this.mutationAdmissionOpen) return
    await this.enqueue(session.id, async () => {
      const row = this.currentRow(session)
      if (!fenceMatchesSession(session.id, row, expectedFence)
        || row === undefined || row.phase === 'planning'
        || row.phase === 'active_paused' || row.phase === 'uncertain') return
      await this.requireTable().put(
        session.id,
        transitionBinding(row, 'active_paused', 'readback_failed', Date.now()),
      )
      this.taskBodies.delete(session.id)
    })
  }

  private queued<T>(
    session: LoopXSessionRef,
    operation: string,
    body: () => Promise<LoopXResult<T>>,
  ): Promise<LoopXResult<T>> {
    const invalid = validateSession(session)
    if (invalid !== undefined) return Promise.resolve(rejected(invalid))
    if (!this.mutationAdmissionOpen) {
      return Promise.resolve(rejected(failure(
        'LOOPX_SERVICE_CLOSED',
        'The LoopX Host service is shutting down.',
        { operation },
      )))
    }
    return this.enqueue(session.id, body).catch(() => rejected(failure(
      'LOOPX_CLI_FAILED',
      'The LoopX Host operation failed before its postcondition was stored.',
      { operation },
    )))
  }

  private enqueue<T>(sessionId: string, operation: () => Promise<T>): Promise<T> {
    const previous = this.operationTails.get(sessionId) ?? Promise.resolve()
    const result = previous.then(operation)
    const tail = result.then(() => undefined, () => undefined)
    this.operationTails.set(sessionId, tail)
    return result.finally(() => {
      if (this.operationTails.get(sessionId) === tail) this.operationTails.delete(sessionId)
    })
  }

  private currentRow(session: LoopXSessionRef): LoopXBindingRow | undefined {
    const row = this.requireTable().get(session.id)
    return row !== undefined && sameSessionIdentity(row.session, session.identity)
      ? row
      : undefined
  }

  private projectFor(session: LoopXSessionRef): string | undefined {
    return present(this.config.project) ?? present(session.identity.cwd)
  }

  private runtimeArgs(): string[] {
    const root = present(this.config.runtimeRoot)
    return root === undefined ? [] : ['--runtime-root', root]
  }

  private locatorArgs(row: LoopXBindingRow): string[] {
    return this.locatorValues(row.registryLocator, row.runtimeRootLocator)
  }

  private locatorValues(registry: string | undefined, runtimeRoot: string | undefined): string[] {
    return [
      ...argsWhen(present(registry) !== undefined, '--registry', present(registry) ?? ''),
      ...argsWhen(
        present(runtimeRoot) !== undefined,
        '--runtime-root',
        present(runtimeRoot) ?? '',
      ),
    ]
  }

  private freshAgentId(): string {
    return `dsh-${randomUUID().replaceAll('-', '').slice(0, 20)}`
  }

  private freshGoalId(): string {
    return `dsh-goal-${randomUUID().replaceAll('-', '').slice(0, 20)}`
  }

  private notBound(operation: string): LoopXFailure {
    return failure(
      'LOOPX_SESSION_NOT_BOUND',
      'The current DSH Session is not bound to a LoopX Goal; call loopx_goal_start or loopx_goal_attach first.',
      { operation },
    )
  }

  private invalidTodo(operation: string): LoopXFailure {
    return failure(
      'LOOPX_INVALID_REQUEST',
      'The bounded Todo operation requires a non-empty Todo id and supported fields.',
      { operation },
    )
  }

  private projectRequired(operation: string): LoopXFailure {
    return failure(
      'LOOPX_INVALID_REQUEST',
      'Configure a LoopX project or use a DSH Session with a working directory.',
      { operation },
    )
  }

  private requireTable(): KvTable<string, LoopXBindingRow> {
    if (this.table === undefined) throw new Error('dsh-loopx-plugin: service is not initialized')
    return this.table
  }
}

export default LoopXService
