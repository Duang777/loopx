import { z } from 'zod'
import { defineDomain, domainTable } from '@deepseek-ai/dsh-storage-domain'
import type { LoopXBindingRow } from './types.ts'

const safeInteger = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER)
const nonEmpty = z.string().min(1)
const publicAgentId = z.string().regex(/^[a-z0-9][a-z0-9._-]{0,127}$/u)

export const loopxSessionIdentitySchema = z.object({
  createdAt: safeInteger,
  cwd: nonEmpty.optional(),
})

export const loopxBindingPhaseSchema = z.enum([
  'planning',
  'active_paused',
  'active_armed',
  'uncertain',
])

export const loopxBindingReasonSchema = z.enum([
  'cold_restore',
  'user_pause',
  'foreign_input',
  'loopx_terminal_observed',
  'identity_conflict',
  'readback_failed',
  'uncertain_write',
  'session_disposed',
  'manual_resume_required',
])

export const loopxBindingRowSchema = z.object({
  schemaVersion: z.literal('loopx_dsh_binding_row_v0'),
  session: loopxSessionIdentitySchema,
  hostSurface: z.literal('deepseek-harness-native'),
  goalId: nonEmpty.max(256),
  agentId: publicAgentId,
  projectLocator: nonEmpty.max(4096),
  registryLocator: nonEmpty.max(4096).optional(),
  runtimeRootLocator: nonEmpty.max(4096).optional(),
  phase: loopxBindingPhaseSchema,
  generation: safeInteger.min(1),
  schedulerResetToken: nonEmpty.max(256).optional(),
  unchangedPollCount: safeInteger,
  nextCheckAt: safeInteger.optional(),
  reason: loopxBindingReasonSchema.optional(),
  bindingCreatedAt: safeInteger,
  updatedAt: safeInteger,
}).refine(row => row.updatedAt >= row.bindingCreatedAt, {
  path: ['updatedAt'],
  message: 'updatedAt must not precede bindingCreatedAt',
}) satisfies z.ZodType<LoopXBindingRow>

export const loopxBindingDomainSpec = defineDomain({
  name: 'dsh_loopx_plugin',
  version: 0,
  tables: {
    sessions: domainTable<string, LoopXBindingRow>(loopxBindingRowSchema),
  },
})

const selectionChoiceSchema = z.looseObject({
  agent_id: publicAgentId,
  label: nonEmpty.optional(),
})

export const identitySelectionGateSchema = z.looseObject({
  schema_version: z.literal('loopx_host_loop_identity_selection_v0'),
  default_action: nonEmpty,
  reason: nonEmpty.optional(),
  choices: z.array(selectionChoiceSchema).default([]),
  fresh_agent_registration: z.looseObject({
    agent_id: nonEmpty.optional(),
  }).nullish(),
})

export const goalSelectionGateSchema = z.looseObject({
  schema_version: z.literal('loopx_goal_selection_gate_v0'),
  state: z.literal('selection_required'),
  reason: nonEmpty,
  choices: z.array(z.looseObject({
    goal_id: nonEmpty,
  })),
})

export const threadBindingProjectionSchema = z.looseObject({
  status: z.enum(['bound', 'missing', 'conflict', 'unavailable']),
  agent_id: publicAgentId.nullish(),
})

export const startGoalConnectContractSchema = z.looseObject({
  schema_version: z.literal('loopx_start_goal_connect_v0'),
  operation: z.literal('bootstrap_connect'),
  goal_id: nonEmpty.max(256),
  objective: nonEmpty,
  adapter_kind: z.literal('read_only_project_map_v0'),
  adapter_status: z.literal('connected-read-only'),
  onboarding_scan_enabled: z.literal(false),
  fine_grained: z.boolean(),
})

const goalStartPlannerSchema = z.looseObject({
  required_before_todo_write: z.literal(true),
  default_profile: nonEmpty,
  profile_selection: nonEmpty,
  profiles: z.looseObject({
    open_ended_product_direction: z.looseObject({
      suggested_items_min: safeInteger.min(1),
      suggested_items_max: safeInteger.min(1),
      intent: nonEmpty,
    }),
    clear_bounded_problem: z.looseObject({
      item_count_policy: nonEmpty,
      may_reuse_current_todo_when_it_already_represents_the_plan: z.boolean(),
      intent: nonEmpty,
    }),
  }),
  allowed_priorities: z.tuple([
    z.literal('P0'),
    z.literal('P1'),
    z.literal('P2'),
  ]),
  default_role: z.literal('agent'),
  default_task_class: z.literal('advancement_task'),
  required_fields: z.array(nonEmpty).min(1),
  public_safe_only: z.literal(true),
  budget_policy: nonEmpty,
  fine_grained_plan_horizon: nonEmpty.optional(),
  maximum_runnable_todos_written_ahead: safeInteger.min(1).optional(),
})

export const goalStartCommandContractSchema = z.looseObject({
  schema_version: z.literal('loopx_goal_start_command_v0'),
  goal_text: nonEmpty.nullable(),
  planner: goalStartPlannerSchema,
  activation: z.looseObject({
    host_loop_required_after_todo_writeback: z.literal(true),
  }),
  stop_conditions: z.array(nonEmpty).min(1),
})

const guidedCommandPackSchema = z.looseObject({
  schema_version: z.literal('loopx_bootstrap_command_pack_v0'),
  goal_start_contract: goalStartCommandContractSchema,
})

const guidedStepSchema = z.looseObject({
  id: nonEmpty,
  kind: nonEmpty,
  prompt: nonEmpty.optional(),
  connect_contract: startGoalConnectContractSchema.optional(),
})

export const projectConnectionSchema = z.looseObject({
  project: nonEmpty,
  registry: nonEmpty,
  goal_id: nonEmpty.nullish(),
  connection_state: z.enum([
    'not_connected',
    'registry_without_goal',
    'registry_invalid',
    'registry_goal_missing_state_file',
    'state_file_missing',
    'connected',
    'goal_selection_required',
  ]),
})

const startGoalGuidedSuccessSchema = z.looseObject({
  schema_version: z.literal('loopx_start_goal_guided_v0'),
  ok: z.literal(true),
  read_only: z.literal(true).optional(),
  guided: z.literal(true).optional(),
  project: nonEmpty.optional(),
  goal_id: nonEmpty.nullish(),
  agent_id: publicAgentId.nullish(),
  host_surface: z.literal('deepseek-harness-native').optional(),
  thread_id: nonEmpty.optional(),
  thread_agent_binding: threadBindingProjectionSchema.optional(),
  goal_selection_gate: goalSelectionGateSchema.optional(),
  host_surface_selection_gate: z.looseObject({}).optional(),
  project_connection: projectConnectionSchema.optional(),
  command_pack: guidedCommandPackSchema.optional(),
  guided_transaction: z.looseObject({
    schema_version: z.literal('loopx_start_goal_guided_v0'),
    blocked_by: nonEmpty.optional(),
    identity_selection_gate: identitySelectionGateSchema.nullish(),
    ordered_steps: z.array(guidedStepSchema),
  }).optional(),
})

export const startGoalGuidedSchema = z.discriminatedUnion('ok', [
  startGoalGuidedSuccessSchema,
  z.looseObject({
    schema_version: z.literal('loopx_start_goal_guided_v0'),
    ok: z.literal(false),
    error: nonEmpty,
    suggested_command: nonEmpty.optional(),
  }),
])

const nativeActivationFields = {
  host_surface: z.literal('deepseek_harness_native_session'),
  activation_method: z.literal('current_session_host_tool'),
  activation_input: z.looseObject({
    schema_version: z.literal('loopx_deepseek_harness_native_activation_input_v0'),
    tool: z.literal('loopx_goal_activate'),
    arguments: z.looseObject({
      goalId: nonEmpty,
      agentId: publicAgentId.optional(),
    }),
  }),
  host_mutation: z.looseObject({
    owner: z.literal('DSH LoopX plugin'),
    host_tool: z.literal('loopx_goal_activate'),
    current_session_only: z.literal(true),
    cli_can_mutate_directly: z.literal(false),
    forbidden_tool_arguments: z.array(z.string()),
  }),
} as const

const bootstrapCommandPackSuccessSchema = z.looseObject({
  schema_version: z.literal('loopx_bootstrap_command_pack_v0'),
  ok: z.literal(true),
  read_only: z.literal(true),
  project: nonEmpty,
  goal_id: nonEmpty,
  agent_id: publicAgentId.nullish(),
  agent_type: z.literal('deepseek-harness-native'),
  host_surface: z.literal('deepseek-harness-native'),
  thread_id: nonEmpty.optional(),
  thread_agent_binding: threadBindingProjectionSchema.optional(),
  project_connection: projectConnectionSchema.optional(),
  host_loop_activation: z.looseObject({
    schema_version: z.literal('loopx_host_loop_activation_v1'),
    agent_type: z.literal('deepseek-harness-native'),
    goal_id: nonEmpty,
    agent_id: publicAgentId.nullish(),
    activation_allowed: z.boolean(),
    identity_contract: z.looseObject({
      schema_version: z.literal('loopx_host_loop_identity_selection_v0'),
      registered_agents: z.array(publicAgentId),
    }),
    identity_selection_gate: identitySelectionGateSchema.nullish(),
    ...nativeActivationFields,
  }),
})

export const bootstrapCommandPackSchema = z.discriminatedUnion('ok', [
  bootstrapCommandPackSuccessSchema,
  z.looseObject({
    schema_version: z.literal('loopx_bootstrap_command_pack_v0'),
    ok: z.literal(false),
    error: nonEmpty,
    error_kind: nonEmpty.optional(),
  }),
])

export const heartbeatPromptSchema = z.discriminatedUnion('ok', [
  z.looseObject({
    schema_version: z.literal('loopx_heartbeat_prompt_v0'),
    ok: z.literal(true),
    goal_id: nonEmpty,
    agent_id: publicAgentId.nullish(),
    runtime_profile: z.literal('generic_cli').optional(),
    task_body: nonEmpty,
  }),
  z.looseObject({
    schema_version: z.literal('loopx_heartbeat_prompt_v0'),
    ok: z.literal(false),
    goal_id: nonEmpty,
    agent_id: publicAgentId.nullish(),
    error: nonEmpty,
    task_body: z.null(),
  }),
])

export const statusSchema = z.looseObject({
  schema_version: z.literal('loopx_status_v0'),
  ok: z.boolean(),
  goal_filter: nonEmpty.nullish(),
})

const schedulerHintSchema = z.looseObject({
  schema_version: z.literal('scheduler_hint_v0'),
  source: z.literal('quota.should-run'),
  action: nonEmpty,
  cadence_class: nonEmpty,
  reset_policy: z.looseObject({
    reset_token: nonEmpty,
  }),
  unchanged_poll: z.looseObject({
    limits: z.looseObject({
      local_scheduler: safeInteger.nullish(),
    }).optional(),
    after_limits: z.looseObject({
      local_scheduler: nonEmpty.optional(),
    }).optional(),
  }).optional(),
  cold_path_detail: z.looseObject({
    schema_version: z.literal('scheduler_hint_detail_v0'),
    local_scheduler: z.looseObject({
      recommended_interval_minutes: safeInteger.min(1),
      unchanged_poll_limit: safeInteger.nullish(),
      after_limit: nonEmpty,
    }),
  }),
})

const terminalStateSchema = z.looseObject({
  schema_version: z.literal('goal_terminal_state_v0'),
  kind: z.literal('no_followup'),
  derived: z.literal(true),
  source: z.literal('validated_goal_closure'),
})

const sourceCompletenessSchema = z.looseObject({
  schema_version: z.literal('goal_terminal_source_completeness_v0'),
  user_todos: z.literal('valid'),
  agent_todos: z.literal('valid'),
})

export const quotaShouldRunSchema = z.looseObject({
  schema_version: z.literal('loopx_quota_should_run_v0'),
  ok: z.boolean(),
  mode: z.literal('should-run'),
  goal_id: nonEmpty,
  should_run: z.boolean(),
  effective_action: nonEmpty,
  agent_identity: z.looseObject({
    agent_id: publicAgentId,
  }),
  scheduler_hint: schedulerHintSchema,
  heartbeat_receipt: z.looseObject({
    schema_version: z.literal('heartbeat_quota_receipt_v0'),
    turn_instance_id: nonEmpty,
    status: z.enum(['committed', 'replayed']),
  }).optional(),
  goal_frontier_projection: z.looseObject({
    terminal_state: terminalStateSchema.optional(),
    source_completeness: sourceCompletenessSchema.optional(),
    acceptance_gaps: z.array(z.unknown()).optional(),
    autonomy_blockers: z.array(z.unknown()).optional(),
    replan_required: z.boolean().optional(),
  }).optional(),
})

export const todoCommandSchema = z.discriminatedUnion('ok', [
  z.looseObject({
    schema_version: z.literal('loopx_todo_command_v0'),
    ok: z.literal(true),
    goal_id: nonEmpty,
    todo_id: nonEmpty,
    status: nonEmpty.optional(),
    written: z.boolean().optional(),
  }),
  z.looseObject({
    schema_version: z.literal('loopx_todo_command_v0'),
    ok: z.literal(false),
    goal_id: nonEmpty,
    error: nonEmpty.optional(),
    error_code: nonEmpty.optional(),
  }),
])

export const todoAddCommandSchema = z.discriminatedUnion('ok', [
  z.looseObject({
    schema_version: z.literal('loopx_todo_command_v0'),
    ok: z.literal(true),
    dry_run: z.boolean(),
    added: z.boolean(),
    already_exists: z.boolean(),
    goal_id: nonEmpty,
    role: z.enum(['user', 'agent']),
    todo: nonEmpty,
    todo_id: nonEmpty.nullable(),
    status: z.enum(['open', 'done', 'blocked', 'deferred']).nullable(),
    task_class: nonEmpty.nullable(),
    action_kind: nonEmpty.nullable(),
    claimed_by: publicAgentId.nullable(),
    bound_agent: publicAgentId.nullable(),
    agent_id: publicAgentId.nullable(),
    blocks_agent: publicAgentId.nullable(),
    target_key: nonEmpty.nullable(),
  }),
  z.looseObject({
    schema_version: z.literal('loopx_todo_command_v0'),
    ok: z.literal(false),
    dry_run: z.boolean(),
    added: z.literal(false),
    already_exists: z.literal(false),
    goal_id: nonEmpty,
    role: z.enum(['user', 'agent']).nullish(),
    todo: z.string(),
    error: nonEmpty,
    error_kind: nonEmpty.optional(),
    error_code: nonEmpty.optional(),
  }),
])

const refreshGlobalSyncSchema = z.looseObject({
  ok: z.boolean(),
  skipped: z.boolean().optional(),
  reason: nonEmpty.optional(),
  registry: nonEmpty.optional(),
  global_registry: nonEmpty,
  synced_goal_ids: z.array(nonEmpty),
  wrote: z.boolean().optional(),
})

const refreshStateResultSuccessSchema = z.looseObject({
    schema_version: z.literal('loopx_refresh_state_result_v0'),
    ok: z.literal(true),
    dry_run: z.boolean(),
    appended: z.boolean(),
    idempotent_replay: z.boolean().optional(),
    partial_write: z.boolean().optional(),
    registry: nonEmpty,
    project: nonEmpty,
    goal_id: nonEmpty,
    agent_id: publicAgentId,
    agent_lane: publicAgentId,
    progress_scope: z.literal('agent_lane'),
    external_sink_delivery_authorized: z.boolean(),
    global_sync: refreshGlobalSyncSchema,
  })

export const refreshStateResultSchema = z.discriminatedUnion('ok', [
  refreshStateResultSuccessSchema,
  z.looseObject({
    schema_version: z.literal('loopx_refresh_state_result_v0'),
    ok: z.literal(false),
    dry_run: z.boolean(),
    appended: z.boolean(),
    registry: nonEmpty,
    runtime_root: z.string().nullish(),
    goal_id: nonEmpty,
    classification: nonEmpty.optional(),
    project: nonEmpty.optional(),
    agent_id: publicAgentId.optional(),
    agent_lane: publicAgentId.optional(),
    progress_scope: z.literal('agent_lane').optional(),
    external_sink_delivery_authorized: z.boolean().optional(),
    global_sync: refreshGlobalSyncSchema.optional(),
    idempotent_replay: z.boolean().optional(),
    error: nonEmpty.optional(),
    error_kind: nonEmpty.optional(),
    partial_write: z.boolean().optional(),
  }),
])

const agentRegistrationReadbackSchema = z.looseObject({
  schema_version: z.literal('loopx_agent_registration_readback_v0'),
  performed: z.boolean(),
  verified: z.boolean(),
  requested_agents: z.array(publicAgentId).optional(),
  source_registered_agents: z.array(publicAgentId).optional(),
  global_registered_agents: z.array(publicAgentId).optional(),
})

const agentRegistrationGlobalSyncSchema = z.looseObject({
  ok: z.boolean(),
  wrote: z.boolean().optional(),
  phase: z.enum(['preflight', 'commit']).optional(),
  error_kind: nonEmpty.optional(),
})

export const registerAgentSchema = z.discriminatedUnion('ok', [
  z.looseObject({
    schema_version: z.literal('loopx_register_agent_v0'),
    ok: z.literal(true),
    goal_id: nonEmpty,
    changed: z.literal(true),
    written: z.literal(true),
    partial_write: z.literal(false),
    requested_agents: z.array(publicAgentId).min(1),
    registered_agents: z.array(publicAgentId),
    registration_readback: agentRegistrationReadbackSchema.extend({
      performed: z.literal(true),
      verified: z.literal(true),
      requested_agents: z.array(publicAgentId).min(1),
      source_registered_agents: z.array(publicAgentId),
      global_registered_agents: z.array(publicAgentId),
    }),
    global_sync: agentRegistrationGlobalSyncSchema.extend({
      ok: z.literal(true),
    }),
  }),
  z.looseObject({
    schema_version: z.literal('loopx_register_agent_v0'),
    ok: z.literal(false),
    goal_id: nonEmpty,
    changed: z.boolean(),
    written: z.boolean(),
    partial_write: z.boolean(),
    error_kind: nonEmpty,
    requested_agents: z.array(publicAgentId).optional(),
    registered_agents: z.array(publicAgentId).optional(),
    registration_readback: agentRegistrationReadbackSchema,
    global_sync: agentRegistrationGlobalSyncSchema,
  }),
])

export const threadBindingCommandSchema = z.discriminatedUnion('ok', [
  z.looseObject({
    schema_version: z.literal('loopx_thread_agent_binding_command_v0'),
    ok: z.literal(true),
    goal_id: nonEmpty,
    thread_id: nonEmpty,
    host_surface: z.literal('deepseek-harness-native'),
    agent_id: publicAgentId,
    changed: z.boolean(),
    written: z.boolean(),
    binding: z.looseObject({
      schema_version: z.literal('loopx_thread_agent_binding_v0'),
      status: z.enum(['bound', 'missing']),
      thread_id: nonEmpty,
      host_surface: z.literal('deepseek-harness-native'),
      agent_id: publicAgentId.nullish(),
    }),
    global_sync: z.looseObject({ ok: z.literal(true) }),
    registration_readback: z.looseObject({ verified: z.literal(true) }),
  }),
  z.looseObject({
    schema_version: z.literal('loopx_thread_agent_binding_command_v0'),
    ok: z.literal(false),
    goal_id: nonEmpty,
    changed: z.boolean(),
    written: z.boolean(),
    error: nonEmpty.optional(),
    error_kind: nonEmpty.optional(),
  }),
])

const bootstrapGlobalSyncSchema = z.looseObject({
  ok: z.literal(true),
  synced_goal_ids: z.array(nonEmpty),
  wrote: z.boolean().optional(),
})

export const bootstrapResultSchema = z.discriminatedUnion('ok', [
  z.looseObject({
    schema_version: z.literal('loopx_bootstrap_result_v0'),
    ok: z.literal(true),
    project: nonEmpty,
    goal_id: nonEmpty,
    registry: nonEmpty,
    state_file: nonEmpty,
    registry_goal_action: nonEmpty,
    state_action: nonEmpty,
    global_sync: bootstrapGlobalSyncSchema,
  }),
  z.looseObject({
    schema_version: z.literal('loopx_bootstrap_result_v0'),
    ok: z.literal(false),
    error_kind: nonEmpty,
  }),
])

export type StartGoalGuidedPayload = z.infer<typeof startGoalGuidedSchema>
export type StartGoalGuidedSuccessPayload = z.infer<typeof startGoalGuidedSuccessSchema>
export type BootstrapCommandPackPayload = z.infer<typeof bootstrapCommandPackSchema>
export type BootstrapCommandPackSuccessPayload = z.infer<typeof bootstrapCommandPackSuccessSchema>
export type BootstrapResultPayload = z.infer<typeof bootstrapResultSchema>
export type HeartbeatPromptPayload = z.infer<typeof heartbeatPromptSchema>
export type QuotaShouldRunPayload = z.infer<typeof quotaShouldRunSchema>
export type TodoCommandPayload = z.infer<typeof todoCommandSchema>
export type TodoAddCommandPayload = z.infer<typeof todoAddCommandSchema>
export type RefreshStateResultPayload = z.infer<typeof refreshStateResultSchema>
export type RefreshStateResultSuccessPayload = z.infer<typeof refreshStateResultSuccessSchema>
