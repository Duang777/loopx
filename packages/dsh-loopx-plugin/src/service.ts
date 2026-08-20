import { randomUUID } from 'node:crypto'
import { resolve } from 'node:path'
import { Context, Service } from '@deepseek-ai/cordis'
import s from '@deepseek-ai/schemastery'
import {
  CoordinatorAdmissionCancelled,
  CoordinatorRegistry,
  installCoordinator,
  type LoopXBindingHome,
} from './coordinator.ts'
import { LoopXCliClient, LoopXCliError } from './cli-client.ts'
import { failure, rejected, success } from './errors.ts'
import {
  bootstrapCommandPackSchema,
  bootstrapResultSchema,
  heartbeatPromptSchema,
  hostThreadBindingCommandSchema,
  quotaShouldRunSchema,
  refreshStateResultSchema,
  registerAgentSchema,
  startGoalGuidedSchema,
  statusSchema,
  todoAddCommandSchema,
  todoCommandSchema,
} from './schemas.ts'
import type {
  BootstrapCommandPackPayload,
  BootstrapCommandPackSuccessPayload,
  HeartbeatPromptPayload,
  HostThreadBindingCommandPayload,
  HostThreadBindingPayload,
  QuotaShouldRunPayload,
  StartGoalGuidedPayload,
  StartGoalGuidedSuccessPayload,
  TodoAddCommandPayload,
  TodoCommandPayload,
} from './schemas.ts'
import type {
  LoopXAttachRequest,
  LoopXAttachValue,
  LoopXApplication,
  LoopXAppliedSubEffect,
  LoopXBoundHostThreadBindingV1,
  LoopXDetachValue,
  LoopXFailure,
  LoopXGoalAgentRef,
  LoopXHostStatus,
  LoopXHostThreadBindingV1,
  LoopXIdentitySelection,
  LoopXPauseValue,
  LoopXPlanningCheckpoint,
  LoopXQuotaDecision,
  LoopXQuotaAuthority,
  LoopXResult,
  LoopXServiceApi,
  LoopXSchedulerHint,
  LoopXSessionRef,
  LoopXStartOptions,
  LoopXStartValue,
  LoopXStatusValue,
  LoopXStatusAuthority,
  LoopXStatusAttentionItem,
  LoopXSwitchRequired,
  LoopXTaskBody,
  LoopXTodoAddRequest,
  LoopXTodoAddAuthority,
  LoopXTodoAddValue,
  LoopXTodoClaimRequest,
  LoopXTodoCompleteRequest,
  LoopXTodoMutationValue,
  LoopXTodoMutationAuthority,
  LoopXTodoUpdateRequest,
} from './types.ts'

const HOST_SURFACE = 'dsh'
const RUNTIME_PROFILE = 'generic_cli'
const AGENT_SCOPE = 'DeepSeek Harness same-session LoopX plugin gated by LoopX'
const PUBLIC_AGENT_ID = /^[a-z0-9][a-z0-9._-]{0,127}$/u
const PUBLIC_THREAD_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u
const PUBLIC_GOAL_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/u
const PUBLIC_CODE_TOKEN = /^[A-Za-z][A-Za-z0-9._:-]{0,127}$/u
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
  /** Child-process cwd fallback only when `runtimeRoot` explicitly selects authority. */
  readonly project?: string
  /** Optional explicit LoopX binding home. */
  readonly runtimeRoot?: string
  readonly readTimeoutMs?: number
  readonly writeTimeoutMs?: number
  readonly stdoutCapBytes?: number
  readonly stderrCapBytes?: number
  /** Explicit child-only variables. The ambient environment is not inherited. */
  readonly environment?: Readonly<Record<string, string>>
}

interface NormalizedTodoAddRequest {
  readonly priority: 'P0' | 'P1' | 'P2'
  readonly role: 'user' | 'agent'
  readonly actionKind: string
  readonly targetKey?: string | undefined
  readonly normalizedTodo: string
}

interface BindingMutationBase {
  readonly home: LoopXBindingHome
  readonly revision: number
  readonly binding?: LoopXHostThreadBindingV1 | undefined
}

type BindingAuthorityRead =
  | {
    readonly ok: true
    readonly binding: LoopXHostThreadBindingV1
  }
  | {
    readonly ok: false
    readonly error: LoopXFailure
    readonly application: LoopXApplication
    readonly binding?: LoopXHostThreadBindingV1 | undefined
  }

interface SwitchConfirmationRecord {
  readonly token: string
  readonly sessionObject: object
  readonly operation: 'start' | 'attach'
  readonly expiresAt: number
  readonly expectedRevision: number
  readonly current: LoopXGoalAgentRef
  readonly requested: LoopXGoalAgentRef
  readonly goalText?: string | undefined
  readonly newPeer: boolean
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

function optional<T extends object>(condition: boolean, value: T): T | Record<never, never> {
  return condition ? value : {}
}

function argsWhen(condition: boolean, ...values: string[]): string[] {
  return condition ? values : []
}

function isRecord(value: unknown): value is Readonly<Record<string, unknown>> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function normalizedGoalText(value: string): string | undefined {
  const normalized = value.trim().replace(/\s+/gu, ' ')
  return normalized.length === 0 ? undefined : normalized
}

function validGoalId(value: string | undefined): value is string {
  return value !== undefined && PUBLIC_GOAL_ID.test(value)
}

function validTodoId(value: string | undefined): value is string {
  return value !== undefined && PUBLIC_GOAL_ID.test(value)
}

function validateSession(session: LoopXSessionRef): LoopXFailure | undefined {
  if (typeof session.session !== 'object' || session.session === null
    || !PUBLIC_THREAD_ID.test(session.id)) {
    return failure('LOOPX_INVALID_REQUEST', 'The current DSH Session identity is invalid.')
  }
  if (!Number.isSafeInteger(session.identity.createdAt) || session.identity.createdAt < 0) {
    return failure('LOOPX_SESSION_LIFECYCLE_MISMATCH', 'The current DSH Session lifecycle is invalid.')
  }
  if (session.identity.cwd?.includes('\0')) {
    return failure('LOOPX_INVALID_REQUEST', 'The current DSH Session working directory is invalid.')
  }
  return undefined
}

function safeFailure(error: unknown, operation: string): LoopXFailure {
  if (error instanceof LoopXCliError) return error.failure
  return failure('LOOPX_CLI_FAILED', 'The LoopX operation could not be completed.', { operation })
}

function readbackFailure(operation: string, message: string): LoopXFailure {
  return failure('LOOPX_READBACK_FAILED', message, { operation })
}

function applied(operation: string, target?: LoopXGoalAgentRef): LoopXAppliedSubEffect {
  return Object.freeze({
    operation,
    application: 'yes' as const,
    ...optional(target !== undefined, { target: target as LoopXGoalAgentRef }),
  })
}

function resultWithEffects<T>(
  result: LoopXResult<T>,
  prior: readonly LoopXAppliedSubEffect[],
): LoopXResult<T> {
  const effects = Object.freeze([...prior, ...(result.subEffects ?? [])])
  const application: LoopXApplication = result.application === 'unknown'
    ? 'unknown'
    : effects.length > 0 ? 'yes' : result.application
  return result.ok
    ? success(result.value, application, effects)
    : rejected(result.error, application, effects)
}

function sameBinding(
  left: LoopXHostThreadBindingV1,
  right: LoopXHostThreadBindingV1,
): boolean {
  if (left.state !== right.state || left.threadId !== right.threadId
    || left.revision !== right.revision) return false
  if (left.state === 'unbound' || right.state === 'unbound') return true
  return left.target.goalId === right.target.goalId
    && left.target.agentId === right.target.agentId
}

function bindingFromPayload(payload: HostThreadBindingPayload): LoopXHostThreadBindingV1 {
  const base = {
    schemaVersion: 'loopx_host_thread_binding_v1' as const,
    hostSurface: 'dsh' as const,
    threadId: payload.thread_id,
    revision: payload.revision,
  }
  return payload.state === 'bound'
    ? Object.freeze({
        ...base,
        state: 'bound' as const,
        target: Object.freeze({
          goalId: payload.target.goal_id,
          agentId: payload.target.agent_id,
        }),
      })
    : Object.freeze({ ...base, state: 'unbound' as const })
}

function bindingFailure(payload: Extract<HostThreadBindingCommandPayload, { ok: false }>, operation: string): LoopXFailure {
  const codes = {
    binding_not_found: 'LOOPX_BINDING_NOT_FOUND',
    revision_conflict: 'LOOPX_REVISION_CONFLICT',
    invalid_target: 'LOOPX_INVALID_TARGET',
    binding_home_uninitialized: 'LOOPX_BINDING_HOME_UNINITIALIZED',
    binding_home_unavailable: 'LOOPX_BINDING_HOME_UNAVAILABLE',
    authority_corrupt: 'LOOPX_AUTHORITY_CORRUPT',
    authority_unhealthy: 'LOOPX_AUTHORITY_UNHEALTHY',
    authority_exhausted: 'LOOPX_AUTHORITY_EXHAUSTED',
  } as const
  const messages = {
    binding_not_found: 'No DSH Host binding exists for this exact Session.',
    revision_conflict: 'The DSH Host binding revision changed; read authority before deciding again.',
    invalid_target: 'LoopX rejected the exact Goal-Agent binding target.',
    binding_home_uninitialized: 'The selected LoopX binding home has not been initialized.',
    binding_home_unavailable: 'The selected LoopX binding home is unavailable.',
    authority_corrupt: 'The selected LoopX binding authority is corrupt.',
    authority_unhealthy: 'The selected LoopX binding authority is unhealthy.',
    authority_exhausted: 'The selected LoopX binding authority exhausted its revision space.',
  } as const
  return failure(codes[payload.error_kind], messages[payload.error_kind], {
    operation,
    outcomeUncertain: payload.application === 'unknown',
  })
}

function identitySelection(gate: {
  readonly default_action: string
  readonly reason?: string | undefined
  readonly choices: readonly { readonly agent_id: string; readonly label?: string | undefined }[]
  readonly fresh_agent_registration?: { readonly agent_id?: string | undefined } | null | undefined
}): LoopXIdentitySelection {
  const suggested = present(gate.fresh_agent_registration?.agent_id)
  return Object.freeze({
    kind: 'agent',
    defaultAction: PUBLIC_CODE_TOKEN.test(gate.default_action)
      ? gate.default_action
      : 'select_agent_identity',
    choices: Object.freeze(gate.choices.map(choice => Object.freeze({
      agentId: choice.agent_id,
    }))),
    ...optional(suggested !== undefined && PUBLIC_AGENT_ID.test(suggested), {
      freshAgentSuggestedId: suggested as string,
    }),
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
  const openEnded = planner?.profiles.open_ended_product_direction
  const bounded = planner?.profiles.clear_bounded_problem
  const required = planner?.required_fields ?? []
  if (contract === undefined || planner === undefined
    || contract.goal_text !== goalText || openEnded === undefined || bounded === undefined
    || openEnded.suggested_items_min > openEnded.suggested_items_max
    || !['priority', 'text', 'task_class', 'action_kind']
      .every(field => required.includes(field))) return undefined
  const limit = Math.min(
    planner.maximum_runnable_todos_written_ahead ?? PLANNING_TODO_LIMIT_CAP,
    PLANNING_TODO_LIMIT_CAP,
  )
  return Object.freeze({
    schemaVersion: 'dsh_loopx_planning_checkpoint_v1' as const,
    goalId,
    agentId,
    goalText,
    planner: Object.freeze({
      defaultProfile: planner.default_profile === 'open_ended_product_direction'
        ? 'open_ended_product_direction'
        : 'clear_bounded_problem',
      profileSelection: 'choose_by_problem_shape',
      openEndedProductDirection: Object.freeze({
        suggestedItemsMin: openEnded.suggested_items_min,
        suggestedItemsMax: openEnded.suggested_items_max,
        intent: 'Produce a bounded runnable plan before activation.',
      }),
      clearBoundedProblem: Object.freeze({
        itemCountPolicy: 'planner_sized',
        mayReuseCurrentTodoWhenItAlreadyRepresentsThePlan:
          bounded.may_reuse_current_todo_when_it_already_represents_the_plan,
        intent: 'Represent the complete bounded problem with runnable Todos.',
      }),
      allowedPriorities: Object.freeze(['P0', 'P1', 'P2'] as const),
      defaultRole: 'agent' as const,
      defaultTaskClass: 'advancement_task' as const,
      requiredFields: Object.freeze(['priority', 'text', 'task_class', 'action_kind']),
      publicSafeOnly: true as const,
      budgetPolicy: 'respect_loopx_quota',
    }),
    writeback: Object.freeze({
      todoTool: 'loopx_todo_add' as const,
      minimumTodos: 1 as const,
      maximumTodos: limit,
      ordering: 'priority_then_tool_call_order' as const,
      activationTool: 'loopx_goal_activate' as const,
      activationArguments: Object.freeze({ goalId, agentId }),
    }),
    stopConditions: Object.freeze([
      'user_gate',
      'no_runnable_agent_todo',
      'terminal_no_followup',
    ]),
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

function normalizeTodoAddRequest(request: LoopXTodoAddRequest): LoopXResult<NormalizedTodoAddRequest> {
  const allowed = new Set(['text', 'priority', 'role', 'actionKind', 'targetKey'])
  const text = present(request.text)
  const role = request.role ?? 'agent'
  const actionKind = present(request.actionKind)
    ?? (role === 'agent' ? 'advance' : 'owner_decision')
  const targetKey = present(request.targetKey)
  if (!Object.keys(request).every(key => allowed.has(key))
    || text === undefined || text.length > 1000 || UNSAFE_TODO_TEXT.test(text)
    || PRIORITY_PREFIX.test(text) || !['P0', 'P1', 'P2'].includes(request.priority)
    || !['user', 'agent'].includes(role) || !PUBLIC_ACTION_KIND.test(actionKind)
    || (request.actionKind !== undefined && present(request.actionKind) === undefined)
    || (request.targetKey !== undefined && targetKey === undefined)
    || (targetKey !== undefined && !PUBLIC_TARGET_KEY.test(targetKey))
    || (role === 'user' && targetKey !== undefined)) {
    return rejected(failure(
      'LOOPX_INVALID_REQUEST',
      'Todo add requires bounded public-safe text, one P0/P1/P2 priority, and supported bounded fields.',
      { operation: 'todo-add' },
    ))
  }
  return success(Object.freeze({
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
  binding: LoopXBoundHostThreadBindingV1,
): payload is BootstrapCommandPackSuccessPayload {
  if (!payload.ok) return false
  const activation = payload.host_loop_activation
  const input = activation.activation_input
  const forbidden = activation.host_mutation.forbidden_tool_arguments
  const projected = payload.host_thread_binding
  return payload.goal_id === binding.target.goalId
    && payload.agent_id === binding.target.agentId
    && payload.thread_id === session.id
    && projected !== undefined
    && sameBinding(bindingFromPayload(projected), binding)
    && activation.activation_allowed
    && activation.agent_id === binding.target.agentId
    && activation.goal_id === binding.target.goalId
    && input.arguments.goalId === binding.target.goalId
    && input.arguments.agentId === binding.target.agentId
    && [...FORBIDDEN_ACTIVATION_ARGUMENTS].every(field => forbidden.includes(field))
    && Object.keys(input.arguments).every(field => !FORBIDDEN_ACTIVATION_ARGUMENTS.has(field))
}

function schedulerHint(payload: QuotaShouldRunPayload): LoopXSchedulerHint | undefined {
  const hint = payload.scheduler_hint
  const resetToken = hint.reset_policy.reset_token
  if (!PUBLIC_CODE_TOKEN.test(hint.action) || !PUBLIC_CODE_TOKEN.test(hint.cadence_class)
    || !PUBLIC_CODE_TOKEN.test(resetToken)) return undefined
  const detail = payload.scheduler_hint.cold_path_detail.local_scheduler
  return Object.freeze({
    action: hint.action,
    cadenceClass: hint.cadence_class,
    resetToken,
    recommendedIntervalMinutes: detail.recommended_interval_minutes,
    ...optional(detail.unchanged_poll_limit !== null, {
      unchangedPollLimit: detail.unchanged_poll_limit as number,
    }),
  })
}

function terminalClosureIsComplete(payload: QuotaShouldRunPayload): boolean {
  const projection = payload.goal_frontier_projection
  return !payload.should_run && payload.effective_action === 'terminal_no_followup'
    && projection?.terminal_state?.kind === 'no_followup'
    && projection.terminal_state.derived === true
    && projection.source_completeness?.user_todos === 'valid'
    && projection.source_completeness.agent_todos === 'valid'
    && projection.acceptance_gaps?.length === 0
    && projection.autonomy_blockers?.length === 0
    && projection.replan_required === false
}

function boundedStatusProjection(
  payload: Readonly<Record<string, unknown>>,
  goalId: string,
): LoopXStatusAuthority {
  const queue = isRecord(payload.attention_queue) ? payload.attention_queue : undefined
  const rawItems = Array.isArray(queue?.items) ? queue.items : []
  const items: LoopXStatusAttentionItem[] = rawItems.flatMap((value) => {
    if (!isRecord(value) || String(value.goal_id ?? '') !== goalId) return []
    const projected: LoopXStatusAttentionItem = Object.freeze({
      goalId,
      ...optional(typeof value.status === 'string' && PUBLIC_CODE_TOKEN.test(value.status), {
        status: value.status as string,
      }),
      ...optional(typeof value.severity === 'string' && PUBLIC_CODE_TOKEN.test(value.severity), {
        severity: value.severity as string,
      }),
      ...optional(typeof value.lifecycle_phase === 'string'
        && PUBLIC_CODE_TOKEN.test(value.lifecycle_phase), {
        lifecyclePhase: value.lifecycle_phase as string,
      }),
    })
    return [Object.freeze(projected)]
  })
  return Object.freeze({
    schemaVersion: 'loopx_status_projection_v1' as const,
    ok: true as const,
    goalId,
    attention: Object.freeze(items),
  })
}

function boundedTodoProjection(
  payload: Extract<TodoCommandPayload, { ok: true }>,
): LoopXTodoMutationAuthority {
  const projected: {
    schemaVersion: 'loopx_todo_projection_v1'
    goalId: string
    todoId: string
    status?: string
    changed?: boolean
    claimedBy?: string
    taskClass?: string
    settlementResult?: string
  } = {
    schemaVersion: 'loopx_todo_projection_v1' as const,
    goalId: payload.goal_id,
    todoId: payload.todo_id,
  }
  if (typeof payload.status === 'string' && PUBLIC_CODE_TOKEN.test(payload.status)) {
    projected.status = payload.status
  }
  projected.changed = payload.changed
  if (typeof payload.claimed_by === 'string' && PUBLIC_AGENT_ID.test(payload.claimed_by)) {
    projected.claimedBy = payload.claimed_by
  }
  if (typeof payload.task_class === 'string' && PUBLIC_CODE_TOKEN.test(payload.task_class)) {
    projected.taskClass = payload.task_class
  }
  if (typeof payload.settlement_result === 'string'
    && PUBLIC_CODE_TOKEN.test(payload.settlement_result)) {
    projected.settlementResult = payload.settlement_result
  }
  return Object.freeze(projected)
}

function boundedTodoAddProjection(
  payload: Extract<TodoAddCommandPayload, { ok: true }>,
  todoId: string,
  taskClass: string,
  actionKind: string,
): LoopXTodoAddAuthority {
  return Object.freeze({
    schemaVersion: 'loopx_todo_projection_v1' as const,
    goalId: payload.goal_id,
    todoId,
    status: 'open' as const,
    role: payload.role,
    taskClass,
    actionKind,
    added: payload.added,
    alreadyExists: payload.already_exists,
  })
}

function boundedQuotaProjection(payload: QuotaShouldRunPayload): LoopXQuotaAuthority {
  const projected: {
    schemaVersion: 'loopx_quota_projection_v1'
    goalId: string
    shouldRun: boolean
    effectiveAction: string
    decision?: string
    state?: string
  } = {
    schemaVersion: 'loopx_quota_projection_v1' as const,
    goalId: payload.goal_id,
    shouldRun: payload.should_run,
    effectiveAction: payload.effective_action,
  }
  for (const key of ['decision', 'state'] as const) {
    if (typeof payload[key] === 'string' && PUBLIC_CODE_TOKEN.test(payload[key])) {
      projected[key] = payload[key]
    }
  }
  return Object.freeze(projected)
}

/** Host-only service. LoopX remains the sole durable authority. */
export class LoopXService extends Service implements LoopXServiceApi {
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

  private readonly config: Config
  private readonly cli: LoopXCliClient
  private readonly coordinators: CoordinatorRegistry
  private admissionOpen = true

  constructor(ctx: Context, config: Config) {
    super(ctx, 'loopx')
    this.config = config
    this.cli = new LoopXCliClient({
      ...optional(present(config.loopxBin) !== undefined, {
        loopxBin: present(config.loopxBin) as string,
      }),
      ...optional(config.readTimeoutMs !== undefined, {
        readTimeoutMs: config.readTimeoutMs as number,
      }),
      ...optional(config.writeTimeoutMs !== undefined, {
        writeTimeoutMs: config.writeTimeoutMs as number,
      }),
      ...optional(config.stdoutCapBytes !== undefined, {
        stdoutCapBytes: config.stdoutCapBytes as number,
      }),
      ...optional(config.stderrCapBytes !== undefined, {
        stderrCapBytes: config.stderrCapBytes as number,
      }),
      environment: config.environment ?? {},
    })
    this.coordinators = new CoordinatorRegistry(scopeKey => this.cli.abortScope(scopeKey))
    installCoordinator(this, this.coordinators)
  }

  protected async [Service.init](): Promise<void> {
    this.ctx.effect(() => async () => {
      this.admissionOpen = false
      const draining = this.coordinators.drainAll()
      this.coordinators.close()
      await this.cli.close()
      await draining
    }, 'dsh-loopx-plugin.close')
  }

  resolveBinding(
    session: LoopXSessionRef,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXHostThreadBindingV1>> {
    return this.queued(session, 'resolve-agent-thread', async () => {
      const home = this.bindingHome(session)
      if (!home.ok) return home
      return this.resolveBindingInside(session, home.value, signal)
    })
  }

  start(
    session: LoopXSessionRef,
    goalText: string,
    signal?: AbortSignal,
    options?: LoopXStartOptions,
  ): Promise<LoopXResult<LoopXStartValue>> {
    const objective = normalizedGoalText(goalText)
    const confirmationToken = present(options?.switchConfirmation)
    if (objective === undefined || !Object.keys(options ?? {}).every(key => key === 'switchConfirmation')
      || (options?.switchConfirmation !== undefined && confirmationToken === undefined)) {
      return Promise.resolve(rejected(failure(
        'LOOPX_INVALID_REQUEST',
        'Goal start requires one non-empty objective and an optional exact switch confirmation.',
        { operation: 'start' },
      )))
    }
    return this.queued(session, 'start', async () => {
      const current = await this.bindingForMutation(session, signal)
      if (!current.ok) return current
      let target: LoopXGoalAgentRef
      if (current.value.binding?.state === 'bound') {
        const record = confirmationToken === undefined
          ? undefined
          : this.validConfirmation(session, confirmationToken, 'start', current.value.binding, objective)
        if (record === undefined) {
          if (confirmationToken !== undefined) return rejected(this.invalidConfirmation('start'))
          target = Object.freeze({ goalId: this.freshGoalId(), agentId: this.freshAgentId() })
          return success(this.prepareSwitch(session, 'start', current.value.binding, target, false, objective))
        }
        target = record.requested
        this.coordinators.clearConfirmation(session)
      } else {
        if (confirmationToken !== undefined) return rejected(this.invalidConfirmation('start'))
        target = Object.freeze({ goalId: this.freshGoalId(), agentId: this.freshAgentId() })
      }

      this.coordinators.pause(session)
      const effects: LoopXAppliedSubEffect[] = []
      const bootstrapped = await this.bootstrapGoal(session, current.value.home, target.goalId, objective, signal)
      if (!bootstrapped.ok) return bootstrapped
      effects.push(...(bootstrapped.subEffects ?? []))
      const registered = await this.registerFreshAgent(session, current.value.home, target, signal)
      if (!registered.ok) return resultWithEffects(registered, effects)
      effects.push(...(registered.subEffects ?? []))
      const bound = await this.bindTarget(
        session,
        current.value.home,
        target,
        current.value.revision,
        signal,
      )
      if (!bound.ok) return resultWithEffects(bound, effects)
      effects.push(...(bound.subEffects ?? []))

      let packet: StartGoalGuidedPayload
      try {
        packet = await this.readStartPacket(session, current.value.home, objective, target, signal)
      } catch (error) {
        return resultWithEffects(rejected(safeFailure(error, 'start-readback')), effects)
      }
      if (!packet.ok || packet.goal_id !== target.goalId || packet.agent_id !== target.agentId
        || packet.host_thread_binding === undefined
        || !sameBinding(bindingFromPayload(packet.host_thread_binding), bound.value)) {
        return resultWithEffects(rejected(readbackFailure(
          'start-readback',
          'LoopX did not verify the fresh Goal-Agent binding.',
        )), effects)
      }
      const planning = planningCheckpoint(packet, objective, target.goalId, target.agentId)
      if (planning === undefined || modelCheckpoint(packet) === undefined) {
        return resultWithEffects(rejected(readbackFailure(
          'start-readback',
          'LoopX did not return one bounded planning contract.',
        )), effects)
      }
      const body = renderPlanningCheckpoint(planning)
      this.coordinators.observeBinding(session, current.value.home, bound.value)
      this.coordinators.cachePlanningBody(session, body)
      return resultWithEffects(success(Object.freeze({
        kind: 'planning' as const,
        binding: bound.value,
        planning,
        modelCheckpoint: body,
      })), effects)
    })
  }

  attach(
    session: LoopXSessionRef,
    request: LoopXAttachRequest,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXAttachValue>> {
    const goalId = present(request.goalId)
    const requestedAgent = present(request.agentId)
    const confirmationToken = present(request.switchConfirmation)
    const newPeer = request.newPeer === true
    if (!validGoalId(goalId) || (newPeer && requestedAgent !== undefined)
      || (request.agentId !== undefined && (requestedAgent === undefined || !PUBLIC_AGENT_ID.test(requestedAgent)))
      || (request.switchConfirmation !== undefined && confirmationToken === undefined)) {
      return Promise.resolve(rejected(failure(
        'LOOPX_INVALID_REQUEST',
        'Attach requires one exact Goal and a compatible exact-agent or new-peer selection.',
        { operation: 'attach' },
      )))
    }
    return this.queued(session, 'attach', async () => {
      const current = await this.bindingForMutation(session, signal)
      if (!current.ok) return current
      const currentBound = current.value.binding?.state === 'bound'
        ? current.value.binding
        : undefined
      let target: LoopXGoalAgentRef
      let createPeer = newPeer

      if (confirmationToken !== undefined) {
        if (currentBound === undefined) return rejected(this.invalidConfirmation('attach'))
        const record = this.validConfirmation(
          session,
          confirmationToken,
          'attach',
          currentBound,
          undefined,
          {
            goalId,
            ...optional(requestedAgent !== undefined, { agentId: requestedAgent as string }),
            newPeer,
          },
        )
        if (record === undefined) return rejected(this.invalidConfirmation('attach'))
        target = record.requested
        createPeer = record.newPeer
        this.coordinators.clearConfirmation(session)
      } else if (newPeer) {
        target = Object.freeze({ goalId, agentId: this.freshAgentId() })
      } else if (requestedAgent !== undefined) {
        target = Object.freeze({ goalId, agentId: requestedAgent })
      } else {
        let packet: BootstrapCommandPackPayload
        try {
          packet = await this.readCommandPack(session, current.value.home, goalId, undefined, false, signal)
        } catch (error) {
          return rejected(safeFailure(error, 'attach-selection'))
        }
        if (!packet.ok) return rejected(readbackFailure('attach-selection', 'LoopX rejected the attach Goal.'))
        const selected = present(packet.agent_id ?? undefined)
        if (selected === undefined || !packet.host_loop_activation.activation_allowed) {
          const gate = packet.host_loop_activation.identity_selection_gate
          return success({
            kind: 'selection_required' as const,
            goalId,
            selection: gate === null || gate === undefined
              ? Object.freeze({
                  kind: 'agent' as const,
                  defaultAction: 'select_agent_identity',
                  choices: Object.freeze(packet.host_loop_activation.identity_contract.registered_agents
                    .map(agentId => Object.freeze({ agentId }))),
                })
              : identitySelection(gate),
          })
        }
        target = Object.freeze({ goalId, agentId: selected })
      }

      const changesTarget = currentBound !== undefined
        && (currentBound.target.goalId !== target.goalId
          || currentBound.target.agentId !== target.agentId)
      if (changesTarget) {
        return success(this.prepareSwitch(session, 'attach', currentBound, target, createPeer))
      }

      this.coordinators.pause(session)
      const effects: LoopXAppliedSubEffect[] = []
      if (createPeer) {
        const registered = await this.registerFreshAgent(session, current.value.home, target, signal)
        if (!registered.ok) return registered
        effects.push(...(registered.subEffects ?? []))
      }
      const bound = await this.bindTarget(
        session,
        current.value.home,
        target,
        current.value.revision,
        signal,
      )
      if (!bound.ok) return resultWithEffects(bound, effects)
      effects.push(...(bound.subEffects ?? []))
      const armed = await this.armFromAuthority(
        session,
        current.value.home,
        bound.value,
        'attach',
        signal,
      )
      if (!armed.ok) return resultWithEffects(armed, effects)
      return resultWithEffects(success(
        Object.freeze({ kind: 'attached' as const, binding: armed.value }),
      ), effects)
    })
  }

  activate(
    session: LoopXSessionRef,
    goalId: string,
    agentId?: string,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXBoundHostThreadBindingV1>> {
    return this.queued(session, 'activate', async () => {
      const home = this.bindingHome(session)
      if (!home.ok) return home
      const resolved = await this.resolveBindingInside(session, home.value, signal)
      if (!resolved.ok) return resolved
      if (resolved.value.state !== 'bound' || resolved.value.target.goalId !== present(goalId)
        || (present(agentId) !== undefined && resolved.value.target.agentId !== present(agentId))) {
        return rejected(failure(
          'LOOPX_IDENTITY_CONFLICT',
          'Activation must match the exact authoritative Goal-Agent binding.',
          { operation: 'activate' },
        ))
      }
      this.coordinators.pause(session)
      const effects: LoopXAppliedSubEffect[] = []
      try {
        const payload = await this.cli.runJson({
          operation: 'activate-refresh',
          kind: 'write',
          args: [
            ...this.runtimeArgs(home.value),
            'refresh-state',
            '--goal-id', resolved.value.target.goalId,
            '--project', home.value.cwd,
            '--agent-id', resolved.value.target.agentId,
            '--agent-lane', resolved.value.target.agentId,
            '--progress-scope', 'agent_lane',
            '--suppress-external-sinks',
          ],
          cwd: home.value.cwd,
          schema: refreshStateResultSchema,
          signal,
          scopeKey: this.scopeFor(session),
        })
        const definitelyApplied = payload.appended
          || payload.global_sync?.wrote === true
        const application: LoopXApplication = definitelyApplied
          ? 'yes'
          : payload.partial_write === true ? 'unknown' : 'no'
        if (definitelyApplied) effects.push(applied('activate-refresh', resolved.value.target))
        if (!payload.ok || payload.goal_id !== resolved.value.target.goalId
          || payload.agent_id !== resolved.value.target.agentId
          || payload.external_sink_delivery_authorized !== false || !payload.global_sync.ok
          || payload.partial_write === true) {
          return rejected(readbackFailure(
            'activate-refresh',
            'LoopX did not verify the bounded suppressed-sink activation write.',
          ), application, effects)
        }
      } catch (error) {
        return rejected(safeFailure(error, 'activate-refresh'))
      }
      const reread = await this.resolveBindingInside(session, home.value, signal)
      if (!reread.ok) return resultWithEffects(reread, effects)
      if (reread.value.state !== 'bound' || !sameBinding(reread.value, resolved.value)) {
        return resultWithEffects(rejected(readbackFailure(
          'activate-readback',
          'The binding changed during activation.',
        )), effects)
      }
      return resultWithEffects(
        await this.armFromAuthority(session, home.value, reread.value, 'activate', signal),
        effects,
      )
    })
  }

  status(
    session: LoopXSessionRef,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXStatusValue>> {
    return this.queued(session, 'status', async () => {
      const home = this.bindingHome(session)
      if (!home.ok) return home
      const resolved = await this.resolveBindingInside(session, home.value, signal)
      const snapshot = this.coordinators.snapshot(session)
      const hostBase = {
        binarySource: this.cli.binarySource,
        activation: snapshot?.activation ?? 'disarmed',
        automaticFollowupSuppressed: snapshot?.automaticFollowupSuppressed ?? false,
      } as const
      if (!resolved.ok) {
        if (resolved.error.code === 'LOOPX_BINDING_NOT_FOUND') {
          return success({ host: Object.freeze(hostBase) })
        }
        return resolved
      }
      const host: LoopXHostStatus = Object.freeze({ ...hostBase, binding: resolved.value })
      if (resolved.value.state === 'unbound') return success({ host })
      try {
        const payload = await this.cli.runJson({
          operation: 'status',
          kind: 'read',
          args: [
            ...this.runtimeArgs(home.value),
            'status',
            '--goal-id', resolved.value.target.goalId,
            '--agent-id', resolved.value.target.agentId,
          ],
          cwd: home.value.cwd,
          schema: statusSchema,
          signal,
          scopeKey: this.scopeFor(session),
        })
        if (!payload.ok || (payload.goal_filter !== null
          && payload.goal_filter !== resolved.value.target.goalId)) {
          return rejected(readbackFailure('status', 'LoopX status did not match the authoritative binding.'))
        }
        return success({
          host,
          authority: boundedStatusProjection(payload, resolved.value.target.goalId),
        })
      } catch (error) {
        return rejected(safeFailure(error, 'status'))
      }
    })
  }

  pause(session: LoopXSessionRef): Promise<LoopXResult<LoopXPauseValue>> {
    const invalid = validateSession(session)
    if (invalid !== undefined) return Promise.resolve(rejected(invalid))
    const snapshot = this.coordinators.pause(session)
    return Promise.resolve(success(Object.freeze({
      paused: true as const,
      ...optional(snapshot.observedBinding !== undefined, {
        binding: snapshot.observedBinding as LoopXHostThreadBindingV1,
      }),
    })))
  }

  resume(
    session: LoopXSessionRef,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXBoundHostThreadBindingV1>> {
    return this.queued(session, 'resume', async () => {
      const home = this.bindingHome(session)
      if (!home.ok) return home
      const resolved = await this.resolveBindingInside(session, home.value, signal)
      if (!resolved.ok) return resolved
      if (resolved.value.state !== 'bound') return rejected(this.notBound('resume'))
      this.coordinators.pause(session)
      const observed = await this.readGoalStatus(session, home.value, resolved.value, signal)
      if (!observed.ok) return observed
      return this.armFromAuthority(session, home.value, resolved.value, 'resume', signal)
    })
  }

  detach(
    session: LoopXSessionRef,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXDetachValue>> {
    const invalid = validateSession(session)
    if (invalid !== undefined) return Promise.resolve(rejected(invalid))
    this.coordinators.pause(session)
    this.coordinators.clearConfirmation(session)
    return this.queued(session, 'detach', async () => {
      const home = this.bindingHome(session)
      if (!home.ok) return home
      const authority = await this.readBindingAuthority(session, home.value, signal)
      let binding: LoopXHostThreadBindingV1
      if (authority.ok) {
        binding = authority.binding
      } else {
        if (authority.error.code !== 'LOOPX_AUTHORITY_UNHEALTHY'
          || authority.application !== 'no' || authority.binding === undefined) {
          return rejected(authority.error, authority.application)
        }
        binding = authority.binding
      }
      const unbound = await this.unbindTarget(
        session,
        home.value,
        binding.revision,
        signal,
      )
      if (!unbound.ok) return unbound
      return success(
        Object.freeze({ detached: true as const, binding: unbound.value }),
        unbound.application,
        unbound.subEffects,
      )
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
      const snapshot = this.coordinators.snapshot(session)
      if (snapshot?.planningBody === undefined) {
        return rejected(failure(
          'LOOPX_DRIVER_NOT_ARMED',
          'Todo add requires the current process-local planning checkpoint.',
          { operation: 'todo-add' },
        ))
      }
      const bound = await this.requireFreshBound(session, 'todo-add', signal)
      if (!bound.ok) return bound
      const todo = normalized.value
      const taskClass = todo.role === 'agent' ? 'advancement_task' : 'user_gate'
      const roleArgs = todo.role === 'agent'
        ? ['--claimed-by', bound.value.binding.target.agentId]
        : [
            '--agent-id', bound.value.binding.target.agentId,
            '--bound-agent', bound.value.binding.target.agentId,
            '--blocks-agent', bound.value.binding.target.agentId,
          ]
      try {
        const payload = await this.cli.runJson({
          operation: 'todo-add',
          kind: 'write',
          args: [
            ...this.runtimeArgs(bound.value.home),
            'todo', 'add',
            '--goal-id', bound.value.binding.target.goalId,
            '--project', bound.value.home.cwd,
            '--role', todo.role,
            '--text', todo.normalizedTodo,
            '--status', 'open',
            '--task-class', taskClass,
            '--action-kind', todo.actionKind,
            ...roleArgs,
            ...argsWhen(todo.targetKey !== undefined, '--target-key', todo.targetKey ?? ''),
          ],
          cwd: bound.value.home.cwd,
          schema: todoAddCommandSchema,
          signal,
          scopeKey: this.scopeFor(session),
        })
        const effects = payload.ok && payload.added
          ? [applied('todo-add', bound.value.binding.target)]
          : []
        const application: LoopXApplication = payload.ok && payload.added ? 'yes' : 'no'
        if (!payload.ok || payload.goal_id !== bound.value.binding.target.goalId
          || payload.role !== todo.role || payload.todo !== todo.normalizedTodo
          || typeof payload.todo_id !== 'string' || !validTodoId(payload.todo_id)
          || payload.status !== 'open' || payload.action_kind !== todo.actionKind
          || payload.task_class !== taskClass || payload.added === payload.already_exists
          || payload.target_key !== (todo.targetKey ?? null)) {
          return rejected(
            readbackFailure('todo-add', 'LoopX did not verify the typed Todo postcondition.'),
            application,
            effects,
          )
        }
        return success(Object.freeze({
          todoId: payload.todo_id,
          status: 'open' as const,
          priority: todo.priority,
          role: todo.role,
          payload: boundedTodoAddProjection(payload, payload.todo_id, taskClass, todo.actionKind),
        }), application, effects)
      } catch (error) {
        return rejected(safeFailure(error, 'todo-add'))
      }
    })
  }

  todoClaim(
    session: LoopXSessionRef,
    request: LoopXTodoClaimRequest,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXTodoMutationValue>> {
    const todoId = present(request.todoId)
    if (!validTodoId(todoId)) return Promise.resolve(rejected(this.invalidTodo('todo-claim')))
    return this.todoMutation(session, 'todo-claim', [
      'todo', 'claim', '--todo-id', todoId, '--claimed-by', '__BOUND_AGENT__',
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
    if (!validTodoId(todoId) || args.length === 4) {
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
    if (!validTodoId(todoId) || (request.taskLeaseExpectedVersion !== undefined
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
      ['--task-lease-expected-version', request.taskLeaseExpectedVersion === undefined
        ? undefined : String(request.taskLeaseExpectedVersion)],
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
    const fence = this.coordinators.fence(session)
    if (turnId === undefined || fence === undefined) {
      return rejected(failure(
        'LOOPX_DRIVER_NOT_ARMED',
        'Quota evaluation requires an armed exact Session fence and turn identity.',
        { operation: 'quota-should-run' },
      ))
    }
    const bound = await this.requireFreshBound(session, 'quota-should-run', signal)
    if (!bound.ok) return bound
    if (!this.coordinators.isCurrent(fence)) {
      return rejected(failure('LOOPX_DRIVER_NOT_ARMED', 'The automatic attempt was fenced.', {
        operation: 'quota-should-run',
      }))
    }
    try {
      const payload = await this.cli.runJson({
        operation: 'quota-should-run',
        kind: 'idempotent-write',
        args: [
          ...this.runtimeArgs(bound.value.home),
          'quota', 'should-run',
          '--goal-id', bound.value.binding.target.goalId,
          '--agent-id', bound.value.binding.target.agentId,
          '--runtime-profile', RUNTIME_PROFILE,
          '--include-detail', 'scheduler',
          '--turn-instance-id', turnId,
        ],
        cwd: bound.value.home.cwd,
        schema: quotaShouldRunSchema,
        signal,
        scopeKey: this.scopeFor(session),
      })
      const application: LoopXApplication = payload.heartbeat_receipt?.status === 'committed'
        ? 'yes'
        : 'no'
      const effects = application === 'yes'
        ? [applied('quota-heartbeat-receipt', bound.value.binding.target)]
        : []
      const hint = schedulerHint(payload)
      if (!payload.ok || payload.goal_id !== bound.value.binding.target.goalId
        || payload.agent_identity.agent_id !== bound.value.binding.target.agentId
        || payload.heartbeat_receipt?.turn_instance_id !== turnId
        || !PUBLIC_CODE_TOKEN.test(payload.effective_action) || hint === undefined
        || !this.coordinators.isCurrent(fence)) {
        return rejected(
          readbackFailure(
            'quota-should-run',
            'LoopX quota did not confirm the exact current binding and turn.',
          ),
          application,
          effects,
        )
      }
      return success(Object.freeze({
        binding: bound.value.binding,
        goalId: bound.value.binding.target.goalId,
        agentId: bound.value.binding.target.agentId,
        turnInstanceId: turnId,
        shouldRun: payload.should_run,
        effectiveAction: payload.effective_action,
        schedulerHint: hint,
        terminalNoFollowup: terminalClosureIsComplete(payload),
        payload: boundedQuotaProjection(payload),
      }), application, effects)
    } catch (error) {
      return rejected(safeFailure(error, 'quota-should-run'))
    }
  }

  async taskBody(
    session: LoopXSessionRef,
    refresh = false,
    signal?: AbortSignal,
  ): Promise<LoopXResult<LoopXTaskBody>> {
    const fence = this.coordinators.fence(session)
    if (fence === undefined) return rejected(failure(
      'LOOPX_DRIVER_NOT_ARMED',
      'Task loading requires an armed exact Session fence.',
      { operation: 'task-body' },
    ))
    const cached = this.coordinators.snapshot(session)?.taskBody
    const observed = this.coordinators.snapshot(session)?.observedBinding
    if (!refresh && cached !== undefined && observed?.state === 'bound'
      && this.coordinators.isCurrent(fence)) {
      return success({ binding: observed, body: cached })
    }
    const bound = await this.requireFreshBound(session, 'task-body', signal)
    if (!bound.ok) return bound
    if (!this.coordinators.isCurrent(fence)) {
      return rejected(failure('LOOPX_DRIVER_NOT_ARMED', 'The task-body attempt was fenced.', {
        operation: 'task-body',
      }))
    }
    try {
      const body = await this.readTaskBody(session, bound.value.home, bound.value.binding, signal)
      if (!this.coordinators.isCurrent(fence)) {
        return rejected(failure('LOOPX_DRIVER_NOT_ARMED', 'The task body became stale before delivery.', {
          operation: 'task-body',
        }))
      }
      this.coordinators.cacheTaskBody(session, body)
      return success({ binding: bound.value.binding, body })
    } catch (error) {
      return rejected(safeFailure(error, 'task-body'))
    }
  }

  async disposeSession(session: LoopXSessionRef): Promise<void> {
    if (validateSession(session) !== undefined) return
    const draining = this.coordinators.drain(session)
    this.coordinators.clearConfirmation(session)
    this.cli.abortScope(this.scopeFor(session))
    this.coordinators.drop(session)
    await draining
  }

  private async resolveBindingInside(
    session: LoopXSessionRef,
    home: LoopXBindingHome,
    signal: AbortSignal | undefined,
  ): Promise<LoopXResult<LoopXHostThreadBindingV1>> {
    const authority = await this.readBindingAuthority(session, home, signal)
    return authority.ok
      ? success(authority.binding)
      : rejected(authority.error, authority.application)
  }

  private async readBindingAuthority(
    session: LoopXSessionRef,
    home: LoopXBindingHome,
    signal: AbortSignal | undefined,
  ): Promise<BindingAuthorityRead> {
    this.coordinators.observe(session, home)
    let payload: HostThreadBindingCommandPayload
    try {
      payload = await this.cli.runBindingJson({
        operation: 'resolve-agent-thread',
        kind: 'read',
        args: [
          'resolve-agent-thread',
          '--host-surface', HOST_SURFACE,
          '--thread-id', session.id,
        ],
        home,
        schema: hostThreadBindingCommandSchema,
        signal,
        scopeKey: this.scopeFor(session),
      })
    } catch (error) {
      this.coordinators.invalidate(session)
      const resolved = safeFailure(error, 'resolve-agent-thread')
      return Object.freeze({
        ok: false as const,
        error: resolved,
        application: resolved.outcomeUncertain ? 'unknown' as const : 'no' as const,
      })
    }
    if (!payload.ok) {
      const binding = payload.binding === undefined
        ? undefined
        : bindingFromPayload(payload.binding)
      if (payload.binding !== undefined) {
        if (binding?.threadId !== session.id) {
          this.coordinators.invalidate(session)
          return Object.freeze({
            ok: false as const,
            error: readbackFailure(
              'resolve-agent-thread',
              'LoopX returned a binding for another exact Session.',
            ),
            application: payload.application,
          })
        }
        this.coordinators.observeBinding(session, home, binding)
      }
      this.coordinators.invalidate(session)
      return Object.freeze({
        ok: false as const,
        error: bindingFailure(payload, 'resolve-agent-thread'),
        application: payload.application,
        ...optional(binding !== undefined, { binding: binding as LoopXHostThreadBindingV1 }),
      })
    }
    const binding = bindingFromPayload(payload.binding)
    if (binding.threadId !== session.id || payload.changed || payload.application !== 'no') {
      this.coordinators.invalidate(session)
      return Object.freeze({
        ok: false as const,
        error: readbackFailure(
          'resolve-agent-thread',
          'LoopX returned an invalid binding read projection.',
        ),
        application: payload.application,
      })
    }
    this.coordinators.observeBinding(session, home, binding)
    return Object.freeze({ ok: true as const, binding })
  }

  private async bindingForMutation(
    session: LoopXSessionRef,
    signal: AbortSignal | undefined,
  ): Promise<LoopXResult<BindingMutationBase>> {
    const home = this.bindingHome(session)
    if (!home.ok) return home
    const resolved = await this.resolveBindingInside(session, home.value, signal)
    if (resolved.ok) {
      return success({ home: home.value, binding: resolved.value, revision: resolved.value.revision })
    }
    if (resolved.error.code === 'LOOPX_BINDING_NOT_FOUND'
      || resolved.error.code === 'LOOPX_BINDING_HOME_UNINITIALIZED') {
      return success({ home: home.value, revision: 0 })
    }
    return resolved
  }

  private async bindTarget(
    session: LoopXSessionRef,
    home: LoopXBindingHome,
    target: LoopXGoalAgentRef,
    expectedRevision: number,
    signal: AbortSignal | undefined,
  ): Promise<LoopXResult<LoopXBoundHostThreadBindingV1>> {
    const result = await this.writeBinding(session, home, [
      'bind-agent-thread',
      '--host-surface', HOST_SURFACE,
      '--thread-id', session.id,
      '--goal-id', target.goalId,
      '--agent-id', target.agentId,
      '--expected-revision', String(expectedRevision),
      '--execute',
    ], 'bind-agent-thread', signal)
    if (!result.ok) return result
    if (result.value.state !== 'bound' || result.value.target.goalId !== target.goalId
      || result.value.target.agentId !== target.agentId) {
      return rejected(
        readbackFailure('bind-agent-thread', 'LoopX did not verify the exact binding target.'),
        result.application,
        result.subEffects,
      )
    }
    return success(result.value, result.application, result.subEffects)
  }

  private async unbindTarget(
    session: LoopXSessionRef,
    home: LoopXBindingHome,
    expectedRevision: number,
    signal: AbortSignal | undefined,
  ): Promise<LoopXResult<Extract<LoopXHostThreadBindingV1, { state: 'unbound' }>>> {
    const result = await this.writeBinding(session, home, [
      'unbind-agent-thread',
      '--host-surface', HOST_SURFACE,
      '--thread-id', session.id,
      '--expected-revision', String(expectedRevision),
      '--execute',
    ], 'unbind-agent-thread', signal)
    if (!result.ok) return result
    if (result.value.state !== 'unbound') {
      return rejected(
        readbackFailure('unbind-agent-thread', 'LoopX did not return an unbound tombstone.'),
        result.application,
        result.subEffects,
      )
    }
    return success(result.value, result.application, result.subEffects)
  }

  private async writeBinding(
    session: LoopXSessionRef,
    home: LoopXBindingHome,
    args: readonly string[],
    operation: 'bind-agent-thread' | 'unbind-agent-thread',
    signal: AbortSignal | undefined,
  ): Promise<LoopXResult<LoopXHostThreadBindingV1>> {
    let payload: HostThreadBindingCommandPayload
    try {
      payload = await this.cli.runBindingJson({
        operation,
        kind: 'write',
        args,
        home,
        schema: hostThreadBindingCommandSchema,
        signal,
        scopeKey: this.scopeFor(session),
      })
    } catch (error) {
      this.coordinators.invalidate(session)
      return rejected(safeFailure(error, operation))
    }
    if (!payload.ok) {
      const binding = payload.binding === undefined
        ? undefined
        : bindingFromPayload(payload.binding)
      if (binding !== undefined && binding.threadId !== session.id) {
        this.coordinators.invalidate(session)
        return rejected(
          readbackFailure(operation, 'LoopX returned a binding for another exact Session.'),
          payload.application,
        )
      }
      if (binding !== undefined) {
        this.coordinators.observeBinding(session, home, binding)
      } else {
        this.coordinators.invalidate(session)
      }
      const effects = payload.application === 'yes'
        ? [applied(operation, binding?.state === 'bound' ? binding.target : undefined)]
        : []
      return rejected(bindingFailure(payload, operation), payload.application, effects)
    }
    const binding = bindingFromPayload(payload.binding)
    const effects = payload.application === 'yes'
      ? [applied(operation, binding.state === 'bound' ? binding.target : undefined)]
      : []
    if (binding.threadId !== session.id
      || payload.application !== (payload.changed ? 'yes' : 'no')) {
      this.coordinators.invalidate(session)
      return rejected(
        readbackFailure(operation, 'LoopX returned an invalid binding mutation receipt.'),
        payload.application,
        effects,
      )
    }
    this.coordinators.observeBinding(session, home, binding)
    return success(binding, payload.application, effects)
  }

  private async armFromAuthority(
    session: LoopXSessionRef,
    home: LoopXBindingHome,
    binding: LoopXBoundHostThreadBindingV1,
    operation: 'activate' | 'attach' | 'resume',
    signal: AbortSignal | undefined,
  ): Promise<LoopXResult<LoopXBoundHostThreadBindingV1>> {
    let packet: BootstrapCommandPackPayload
    let body: string
    try {
      packet = await this.readCommandPack(
        session,
        home,
        binding.target.goalId,
        binding.target.agentId,
        false,
        signal,
      )
      if (!activationReadbackMatches(packet, session, binding)) {
        return rejected(readbackFailure(operation, 'LoopX did not verify Goal membership and binding authority.'))
      }
      body = await this.readTaskBody(session, home, binding, signal)
    } catch (error) {
      return rejected(safeFailure(error, operation))
    }
    const reread = await this.resolveBindingInside(session, home, signal)
    if (!reread.ok) return reread
    if (reread.value.state !== 'bound' || !sameBinding(reread.value, binding)) {
      return rejected(readbackFailure(operation, 'The authoritative binding changed before arming.'))
    }
    const armed = this.coordinators.arm(session, home, binding, { taskBody: body })
    if (armed === undefined) {
      return rejected(failure(
        'LOOPX_FOREIGN_COMMAND_ACTIVE',
        'The exact Session cannot arm while a foreign command is active.',
        { operation },
      ))
    }
    return success(binding)
  }

  private async requireFreshBound(
    session: LoopXSessionRef,
    operation: string,
    signal: AbortSignal | undefined,
  ): Promise<LoopXResult<{ readonly home: LoopXBindingHome; readonly binding: LoopXBoundHostThreadBindingV1 }>> {
    const home = this.bindingHome(session)
    if (!home.ok) return home
    const resolved = await this.resolveBindingInside(session, home.value, signal)
    if (!resolved.ok) return resolved
    if (resolved.value.state !== 'bound') return rejected(this.notBound(operation))
    return success({ home: home.value, binding: resolved.value })
  }

  private async readStartPacket(
    session: LoopXSessionRef,
    home: LoopXBindingHome,
    goalText: string,
    target: LoopXGoalAgentRef,
    signal: AbortSignal | undefined,
  ): Promise<StartGoalGuidedPayload> {
    return this.cli.runJson({
      operation: 'start-goal',
      kind: 'read',
      args: [
        ...this.runtimeArgs(home),
        'start-goal', '--guided',
        '--project', home.cwd,
        '--thread-id', session.id,
        '--host-surface', HOST_SURFACE,
        '--goal-id', target.goalId,
        '--agent-id', target.agentId,
        '--goal-text', goalText,
      ],
      cwd: home.cwd,
      schema: startGoalGuidedSchema,
      signal,
      scopeKey: this.scopeFor(session),
    })
  }

  private async readCommandPack(
    session: LoopXSessionRef,
    home: LoopXBindingHome,
    goalId: string,
    agentId: string | undefined,
    newPeer: boolean,
    signal: AbortSignal | undefined,
  ): Promise<BootstrapCommandPackPayload> {
    return this.cli.runJson({
      operation: 'bootstrap-command-pack',
      kind: 'read',
      args: [
        ...this.runtimeArgs(home),
        'bootstrap-command-pack',
        '--project', home.cwd,
        '--goal-id', goalId,
        '--thread-id', session.id,
        '--host-surface', HOST_SURFACE,
        ...argsWhen(agentId !== undefined, '--agent-id', agentId ?? ''),
        ...argsWhen(newPeer, '--new-peer'),
      ],
      cwd: home.cwd,
      schema: bootstrapCommandPackSchema,
      signal,
      scopeKey: this.scopeFor(session),
    })
  }

  private async readTaskBody(
    session: LoopXSessionRef,
    home: LoopXBindingHome,
    binding: LoopXBoundHostThreadBindingV1,
    signal: AbortSignal | undefined,
  ): Promise<string> {
    const payload: HeartbeatPromptPayload = await this.cli.runJson({
      operation: 'heartbeat-prompt',
      kind: 'read',
      args: [
        ...this.runtimeArgs(home),
        'heartbeat-prompt', '--thin',
        '--goal-id', binding.target.goalId,
        '--agent-id', binding.target.agentId,
        '--agent-scope', AGENT_SCOPE,
        '--runtime-profile', RUNTIME_PROFILE,
      ],
      cwd: home.cwd,
      schema: heartbeatPromptSchema,
      signal,
      scopeKey: this.scopeFor(session),
    })
    const body = present(payload.task_body ?? undefined)
    if (!payload.ok || payload.goal_id !== binding.target.goalId
      || payload.agent_id !== binding.target.agentId || body === undefined) {
      throw new LoopXCliError(readbackFailure(
        'heartbeat-prompt',
        'LoopX did not return the exact bound task body.',
      ))
    }
    return body
  }

  private async readGoalStatus(
    session: LoopXSessionRef,
    home: LoopXBindingHome,
    binding: LoopXBoundHostThreadBindingV1,
    signal: AbortSignal | undefined,
  ): Promise<LoopXResult<undefined>> {
    try {
      const payload = await this.cli.runJson({
        operation: 'resume-status',
        kind: 'read',
        args: [
          ...this.runtimeArgs(home),
          'status',
          '--goal-id', binding.target.goalId,
          '--agent-id', binding.target.agentId,
        ],
        cwd: home.cwd,
        schema: statusSchema,
        signal,
        scopeKey: this.scopeFor(session),
      })
      if (!payload.ok || (payload.goal_filter !== null
        && payload.goal_filter !== binding.target.goalId)) {
        return rejected(readbackFailure('resume-status', 'LoopX did not verify the bound Goal status.'))
      }
      return success(undefined)
    } catch (error) {
      return rejected(safeFailure(error, 'resume-status'))
    }
  }

  private async bootstrapGoal(
    session: LoopXSessionRef,
    home: LoopXBindingHome,
    goalId: string,
    objective: string,
    signal: AbortSignal | undefined,
  ): Promise<LoopXResult<undefined>> {
    try {
      const payload = await this.cli.runJson({
        operation: 'bootstrap-connect',
        kind: 'write',
        args: [
          ...this.runtimeArgs(home),
          'bootstrap',
          '--project', home.cwd,
          '--goal-id', goalId,
          '--objective', objective,
          '--adapter-kind', 'read_only_project_map_v0',
          '--adapter-status', 'connected-read-only',
          '--no-onboarding-scan',
          '--codex-app-heartbeat', 'ask',
        ],
        cwd: home.cwd,
        schema: bootstrapResultSchema,
        signal,
        scopeKey: this.scopeFor(session),
      })
      if (!payload.ok) {
        return rejected(failure(
          'LOOPX_REGISTRY_INTEGRITY',
          'LoopX rejected fresh Goal bootstrap before a verified write.',
          { operation: 'bootstrap-connect' },
        ))
      }
      const definitelyApplied = payload.registry_goal_action !== 'kept-existing'
        || payload.state_action !== 'kept-existing'
        || payload.global_sync.wrote === true
      const application: LoopXApplication = definitelyApplied ? 'yes' : 'no'
      const effects = definitelyApplied
        ? [applied('bootstrap-goal')]
        : []
      if (payload.goal_id !== goalId || payload.registry_goal_action !== 'appended'
        || payload.state_action !== 'created'
        || !payload.global_sync.synced_goal_ids.includes(goalId)) {
        return rejected(
          readbackFailure('bootstrap-connect', 'LoopX did not verify the fresh Goal.'),
          application,
          effects,
        )
      }
      return success(undefined, application, effects)
    } catch (error) {
      return rejected(safeFailure(error, 'bootstrap-connect'))
    }
  }

  private async registerFreshAgent(
    session: LoopXSessionRef,
    home: LoopXBindingHome,
    target: LoopXGoalAgentRef,
    signal: AbortSignal | undefined,
  ): Promise<LoopXResult<undefined>> {
    try {
      const payload = await this.cli.runJson({
        operation: 'register-agent',
        kind: 'write',
        args: [
          ...this.runtimeArgs(home),
          'register-agent',
          '--goal-id', target.goalId,
          '--agent-id', target.agentId,
          '--require-new',
          '--execute',
        ],
        cwd: home.cwd,
        schema: registerAgentSchema,
        signal,
        scopeKey: this.scopeFor(session),
      })
      if (!payload.ok) {
        const deterministic = !payload.written && !payload.partial_write
        const application: LoopXApplication = payload.written
          ? 'yes'
          : payload.partial_write ? 'unknown' : 'no'
        const effects = payload.written
          ? [applied('register-agent-source', target)]
          : []
        return rejected(
          failure(
            payload.error_kind === 'agent_identity_already_registered'
              ? 'LOOPX_IDENTITY_CONFLICT'
              : 'LOOPX_REGISTRY_INTEGRITY',
            deterministic
              ? 'LoopX rejected the fresh Goal-Agent identity before writing.'
              : 'LoopX did not verify fresh Goal-Agent membership across its authority.',
            { operation: 'register-agent', outcomeUncertain: application === 'unknown' },
          ),
          application,
          effects,
        )
      }
      const effects = [applied('register-agent', target)]
      const readback = payload.registration_readback
      if (payload.goal_id !== target.goalId || payload.requested_agents[0] !== target.agentId
        || !payload.registered_agents.includes(target.agentId)
        || !readback.source_registered_agents.includes(target.agentId)
        || !readback.global_registered_agents.includes(target.agentId)) {
        return rejected(
          readbackFailure('register-agent', 'LoopX did not verify fresh Goal-Agent membership.'),
          'yes',
          effects,
        )
      }
      return success(undefined, 'yes', effects)
    } catch (error) {
      return rejected(safeFailure(error, 'register-agent'))
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
      const bound = await this.requireFreshBound(session, operation, signal)
      if (!bound.ok) return bound
      const args = commandArgs.map(value => value === '__BOUND_AGENT__'
        ? bound.value.binding.target.agentId : value)
      args.push(
        '--goal-id', bound.value.binding.target.goalId,
        '--agent-id', bound.value.binding.target.agentId,
      )
      try {
        const payload = await this.cli.runJson({
          operation,
          kind: 'write',
          args: [...this.runtimeArgs(bound.value.home), ...args],
          cwd: bound.value.home.cwd,
          schema: todoCommandSchema,
          signal,
          scopeKey: this.scopeFor(session),
        })
        const definitelyApplied = payload.changed === true
        const effects = definitelyApplied
          ? [applied(operation, bound.value.binding.target)]
          : []
        const application: LoopXApplication = definitelyApplied
          ? 'yes'
          : !payload.ok && payload.partial_write === true ? 'unknown' : 'no'
        if (!payload.ok || payload.goal_id !== bound.value.binding.target.goalId
          || payload.todo_id !== todoId) {
          return rejected(
            readbackFailure(operation, 'LoopX did not verify the Todo postcondition.'),
            application,
            effects,
          )
        }
        return success(Object.freeze({
          todoId,
          ...optional(payload.status !== undefined, { status: payload.status as string }),
          payload: boundedTodoProjection(payload),
        }), application, effects)
      } catch (error) {
        return rejected(safeFailure(error, operation))
      }
    })
  }

  private prepareSwitch(
    session: LoopXSessionRef,
    operation: 'start' | 'attach',
    current: LoopXBoundHostThreadBindingV1,
    requested: LoopXGoalAgentRef,
    newPeer: boolean,
    goalText?: string,
  ): LoopXSwitchRequired {
    const record: SwitchConfirmationRecord = Object.freeze({
      token: randomUUID(),
      sessionObject: session.session,
      operation,
      expiresAt: Date.now() + SWITCH_CONFIRMATION_TTL_MS,
      expectedRevision: current.revision,
      current: current.target,
      requested,
      ...optional(goalText !== undefined, { goalText: goalText as string }),
      newPeer,
    })
    this.coordinators.setConfirmation(session, record)
    return Object.freeze({
      kind: 'switch_required' as const,
      confirmationToken: record.token,
      requiresUserConfirmation: true as const,
      expiresAt: record.expiresAt,
      expectedRevision: record.expectedRevision,
      current: record.current,
      requested: Object.freeze({
        operation,
        goalId: requested.goalId,
        agentId: requested.agentId,
        ...optional(newPeer, { newPeer: true as const }),
      }),
    })
  }

  private validConfirmation(
    session: LoopXSessionRef,
    token: string,
    operation: 'start' | 'attach',
    current: LoopXBoundHostThreadBindingV1,
    goalText?: string,
    request?: { readonly goalId: string; readonly agentId?: string; readonly newPeer: boolean },
  ): SwitchConfirmationRecord | undefined {
    const record = this.coordinators.confirmation<SwitchConfirmationRecord>(session)
    if (record === undefined || record.token !== token || record.operation !== operation
      || record.sessionObject !== session.session || record.expiresAt <= Date.now()
      || record.expectedRevision !== current.revision
      || record.current.goalId !== current.target.goalId
      || record.current.agentId !== current.target.agentId
      || record.goalText !== goalText
      || (request !== undefined && (record.requested.goalId !== request.goalId
        || record.newPeer !== request.newPeer
        || (!request.newPeer && record.requested.agentId !== request.agentId)))) {
      this.coordinators.clearConfirmation(session)
      return undefined
    }
    return record
  }

  private invalidConfirmation(operation: 'start' | 'attach'): LoopXFailure {
    return failure(
      'LOOPX_SWITCH_CONFIRMATION_INVALID',
      'The switch confirmation is missing, expired, stale, or bound to another exact request.',
      { operation },
    )
  }

  private bindingHome(session: LoopXSessionRef): LoopXResult<LoopXBindingHome> {
    const root = present(this.config.runtimeRoot)
    const cwd = root === undefined
      ? present(session.identity.cwd)
      : present(session.identity.cwd) ?? present(this.config.project) ?? root
    if (cwd === undefined) {
      return rejected(failure(
        'LOOPX_BINDING_HOME_UNAVAILABLE',
        'The exact DSH Session does not select one readable LoopX binding home.',
        { operation: 'binding-home' },
      ))
    }
    const canonicalCwd = resolve(cwd)
    const canonicalRoot = root === undefined ? undefined : resolve(root)
    return success(Object.freeze({
      cwd: canonicalCwd,
      key: canonicalRoot === undefined ? `session:${canonicalCwd}` : `runtime:${canonicalRoot}`,
      ...optional(canonicalRoot !== undefined, { runtimeRoot: canonicalRoot as string }),
    }))
  }

  private runtimeArgs(home: LoopXBindingHome): string[] {
    return home.runtimeRoot === undefined ? [] : ['--runtime-root', home.runtimeRoot]
  }

  private scopeFor(session: LoopXSessionRef): string {
    return this.coordinators.scopeKey(session)
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
      'The current DSH Session has no bound LoopX Goal-Agent target.',
      { operation },
    )
  }

  private invalidTodo(operation: string): LoopXFailure {
    return failure(
      'LOOPX_INVALID_REQUEST',
      'The Todo operation requires one non-empty Todo id and supported bounded fields.',
      { operation },
    )
  }

  private queued<T>(
    session: LoopXSessionRef,
    operation: string,
    body: () => Promise<LoopXResult<T>>,
  ): Promise<LoopXResult<T>> {
    const invalid = validateSession(session)
    if (invalid !== undefined) return Promise.resolve(rejected(invalid))
    if (!this.admissionOpen || this.coordinators.isClosed(session)) {
      return Promise.resolve(rejected(failure(
        'LOOPX_SERVICE_CLOSED',
        'The LoopX Host service is not accepting operations for this Session.',
        { operation },
      )))
    }
    const result: Promise<LoopXResult<T>> = this.coordinators
      .serialize(session, body)
      .catch<LoopXResult<T>>(error => rejected(error instanceof CoordinatorAdmissionCancelled
        ? failure(
            'LOOPX_SERVICE_CLOSED',
            'The LoopX Host operation was retired during lifecycle disposal.',
            { operation },
          )
        : failure(
            'LOOPX_CLI_FAILED',
            'The LoopX Host operation failed before a bounded result was available.',
            { operation },
          )))
    return result
  }
}

export default LoopXService
