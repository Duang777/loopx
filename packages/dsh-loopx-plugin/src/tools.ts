import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { JsonValue, ToolRunContext } from '@deepseek-ai/dsh-tools'
import { deriveLoopXSessionRef } from './command.ts'
import {
  failureReceipt as sharedFailureReceipt,
  safeAttach,
  safeBinding,
  safeStart,
  safeStatus,
  serviceOperationReceipt as sharedServiceReceipt,
} from './receipts.ts'
import type { ReceiptValue } from './receipts.ts'
import type {
  LoopXAttachRequest,
  LoopXAppliedSubEffect,
  LoopXFailure,
  LoopXOperationReceipt,
  LoopXResult,
  LoopXServiceApi,
  LoopXSessionRef,
  LoopXStartOptions,
  LoopXTodoAddValue,
  LoopXTodoMutationValue,
} from './types.ts'

export const name = 'dsh-loopx-tools'
export const inject = ['tools', 'loopx']

const RECEIPT_SCHEMA_VERSION = 'dsh_loopx_operation_receipt_v1' as const

interface ToolReceipt {
  readonly schemaVersion: typeof RECEIPT_SCHEMA_VERSION
  readonly kind: 'operation_result'
  readonly operation: string
  readonly execution: LoopXOperationReceipt['execution']
  readonly application: LoopXOperationReceipt['application']
  readonly delivery: LoopXOperationReceipt['delivery']
  readonly recovery: LoopXOperationReceipt['recovery']
  readonly value?: JsonValue
  readonly error?: {
    readonly code: string
    readonly message: string
    readonly operation?: string
    readonly retryable: boolean
    readonly outcomeUncertain: boolean
  }
  readonly subEffects?: JsonValue
}

const TOOL_OUTPUT = {
  schema: {
    type: 'object',
    additionalProperties: false,
    properties: {
      schemaVersion: { type: 'string', const: RECEIPT_SCHEMA_VERSION, required: true },
      kind: { type: 'string', const: 'operation_result', required: true },
      operation: { type: 'string', required: true },
      execution: {
        type: 'string',
        enum: ['succeeded', 'rejected', 'indeterminate', 'not_attempted'],
        required: true,
      },
      application: { type: 'string', enum: ['yes', 'no', 'unknown'], required: true },
      delivery: {
        type: 'string',
        enum: ['steered', 'followup_queued', 'failed', 'not_needed'],
        required: true,
      },
      recovery: {
        type: 'string',
        enum: [
          'none', 'retry_same_tool', 'read_authority_then_decide',
          'correct_request', 'ask_user', 'stop',
        ],
        required: true,
      },
      value: { type: 'json' },
      error: {
        type: 'object',
        additionalProperties: false,
        properties: {
          code: { type: 'string', required: true },
          message: { type: 'string', required: true },
          operation: { type: 'string' },
          retryable: { type: 'boolean', required: true },
          outcomeUncertain: { type: 'boolean', required: true },
        },
      },
      subEffects: { type: 'json' },
    },
  },
  render: (_args: unknown, value: unknown) => [{
    type: 'text' as const,
    text: JSON.stringify(value),
  }],
} as const

function invalidRequest(message: string, operation: string): LoopXFailure {
  return Object.freeze({
    code: 'LOOPX_INVALID_REQUEST',
    message,
    operation,
    retryable: false,
    outcomeUncertain: false,
  })
}

function failureReceipt(
  operation: string,
  error: LoopXFailure,
  application?: LoopXOperationReceipt['application'],
  subEffects?: readonly LoopXAppliedSubEffect[],
): ToolReceipt {
  return sharedFailureReceipt(operation, error, application, subEffects) as unknown as ToolReceipt
}

async function serviceReceipt<T>(
  service: LoopXServiceApi,
  session: LoopXSessionRef,
  signal: AbortSignal,
  operation: string,
  invoke: () => Promise<LoopXResult<T>>,
  project: (value: T) => ReceiptValue,
): Promise<ToolReceipt> {
  return sharedServiceReceipt(
    service, session, signal, operation, invoke, project,
  ) as unknown as Promise<ToolReceipt>
}

function hasOnlyKeys(args: object, allowed: ReadonlySet<string>): boolean {
  return Object.keys(args).every(key => allowed.has(key))
}

function safeTodo(value: LoopXTodoMutationValue): ReceiptValue {
  const authority = value.payload
  return {
    todoId: value.todoId,
    status: value.status ?? null,
    loopxAuthority: {
      schemaVersion: authority.schemaVersion,
      goalId: authority.goalId,
      todoId: authority.todoId,
      ...(authority.status === undefined ? {} : { status: authority.status }),
      ...(authority.changed === undefined ? {} : { changed: authority.changed }),
      ...(authority.claimedBy === undefined ? {} : { claimedBy: authority.claimedBy }),
      ...(authority.taskClass === undefined ? {} : { taskClass: authority.taskClass }),
      ...(authority.settlementResult === undefined
        ? {}
        : { settlementResult: authority.settlementResult }),
    },
  }
}

function safeTodoAdd(value: LoopXTodoAddValue): ReceiptValue {
  const authority = value.payload
  return {
    todoId: value.todoId,
    status: value.status,
    priority: value.priority,
    role: value.role,
    loopxAuthority: {
      schemaVersion: authority.schemaVersion,
      goalId: authority.goalId,
      todoId: authority.todoId,
      status: authority.status,
      role: authority.role,
      taskClass: authority.taskClass,
      actionKind: authority.actionKind,
      added: authority.added,
      alreadyExists: authority.alreadyExists,
    },
  }
}

function strictInput(definition: ReturnType<typeof defineTool>): ReturnType<typeof defineTool> {
  return Object.freeze({
    ...definition,
    parameters: Object.freeze({ ...definition.parameters, additionalProperties: false }),
  })
}

function invalidKeys(operation: string): LoopXFailure {
  return invalidRequest(
    'Unsupported arguments are forbidden; Session identity and authority locators are derived by the plugin, and raw task bodies, argv, or shell commands are never accepted.',
    operation,
  )
}

function toolSession(
  exec: ToolRunContext,
  operation: string,
  args: object,
  keys: ReadonlySet<string>,
): LoopXResult<LoopXSessionRef> {
  const current = deriveLoopXSessionRef(exec.agent, operation)
  if (!current.ok) return current
  return hasOnlyKeys(args, keys)
    ? current
    : { ok: false, error: invalidKeys(operation), application: 'no' }
}

const START_KEYS = new Set(['goalText', 'switchConfirmation'])
const ATTACH_KEYS = new Set(['goalId', 'agentId', 'newPeer', 'switchConfirmation'])
const ACTIVATE_KEYS = new Set(['goalId', 'agentId'])
const TODO_ADD_KEYS = new Set(['text', 'priority', 'role', 'actionKind', 'targetKey'])
const EMPTY_KEYS = new Set<string>()
const CLAIM_KEYS = new Set(['todoId', 'role'])
const UPDATE_KEYS = new Set(['todoId', 'status', 'note', 'evidence', 'reason', 'taskClass', 'clearClaim'])
const COMPLETE_KEYS = new Set([
  'todoId', 'note', 'evidence', 'noFollowUp', 'turnInstanceId',
  'taskLeaseIdempotencyKey', 'taskLeaseExpectedVersion',
])

function loopXToolDefinitions(service: LoopXServiceApi): readonly ReturnType<typeof defineTool>[] {
  const goalStart = strictInput(defineTool({
    name: 'loopx_goal_start',
    description: 'Start a fresh LoopX Goal and lane for this DSH Session; activation remains disarmed.',
    parameters: {
      goalText: { type: 'string', required: true, description: 'Non-empty Goal objective.' },
      switchConfirmation: { type: 'string', description: 'Opaque confirmed-switch token.' },
    },
    output: TOOL_OUTPUT,
    async execute(args, exec): Promise<ToolReceipt> {
      const operation = 'goal-start'
      const current = toolSession(exec, operation, args, START_KEYS)
      if (!current.ok) return failureReceipt(operation, current.error)
      const options: LoopXStartOptions = {
        ...(args.switchConfirmation === undefined ? {} : { switchConfirmation: args.switchConfirmation }),
      }
      return serviceReceipt(service, current.value, exec.signal, operation,
        () => service.start(current.value, args.goalText, exec.signal, options),
        safeStart)
    },
  }))

  const goalAttach = strictInput(defineTool({
    name: 'loopx_goal_attach',
    description: 'Attach this DSH Session to one exact existing Goal-Agent lane.',
    parameters: {
      goalId: { type: 'string', required: true },
      agentId: { type: 'string' },
      newPeer: { type: 'boolean' },
      switchConfirmation: { type: 'string' },
    },
    output: TOOL_OUTPUT,
    async execute(args, exec): Promise<ToolReceipt> {
      const operation = 'goal-attach'
      const current = toolSession(exec, operation, args, ATTACH_KEYS)
      if (!current.ok) return failureReceipt(operation, current.error)
      const request: LoopXAttachRequest = {
        goalId: args.goalId,
        ...(args.agentId === undefined ? {} : { agentId: args.agentId }),
        ...(args.newPeer === true ? { newPeer: true } : {}),
        ...(args.switchConfirmation === undefined ? {} : { switchConfirmation: args.switchConfirmation }),
      }
      return serviceReceipt(service, current.value, exec.signal, operation,
        () => service.attach(current.value, request, exec.signal),
        safeAttach)
    },
  }))

  const goalActivate = strictInput(defineTool({
    name: 'loopx_goal_activate',
    description: 'Activate the exact pending Goal-Agent lane after fresh authority readback.',
    parameters: { goalId: { type: 'string', required: true }, agentId: { type: 'string' } },
    output: TOOL_OUTPUT,
    async execute(args, exec): Promise<ToolReceipt> {
      const operation = 'goal-activate'
      const current = toolSession(exec, operation, args, ACTIVATE_KEYS)
      if (!current.ok) return failureReceipt(operation, current.error)
      return serviceReceipt(service, current.value, exec.signal, operation,
        () => service.activate(current.value, args.goalId, args.agentId, exec.signal),
        binding => ({ binding: safeBinding(binding) }))
    },
  }))

  const loopxStatus = strictInput(defineTool({
    name: 'loopx_status',
    description: 'Read exact Host binding and LoopX authority without mutation or activation.',
    parameters: {},
    output: TOOL_OUTPUT,
    async execute(args, exec): Promise<ToolReceipt> {
      const operation = 'status'
      const current = toolSession(exec, operation, args, EMPTY_KEYS)
      if (!current.ok) return failureReceipt(operation, current.error)
      return serviceReceipt(service, current.value, exec.signal, operation,
        () => service.status(current.value, exec.signal), safeStatus)
    },
  }))

  const goalDetach = strictInput(defineTool({
    name: 'loopx_goal_detach',
    description: 'CAS-unbind this DSH Host thread and retain its revision tombstone.',
    parameters: {},
    output: TOOL_OUTPUT,
    async execute(args, exec): Promise<ToolReceipt> {
      const operation = 'goal-detach'
      const current = toolSession(exec, operation, args, EMPTY_KEYS)
      if (!current.ok) return failureReceipt(operation, current.error)
      return serviceReceipt(service, current.value, exec.signal, operation,
        () => service.detach(current.value, exec.signal),
        value => ({ detached: value.detached, binding: safeBinding(value.binding) }))
    },
  }))

  const driverPause = strictInput(defineTool({
    name: 'loopx_driver_pause',
    description: 'Disarm only process-local continuation; durable LoopX state is unchanged.',
    parameters: {},
    output: TOOL_OUTPUT,
    async execute(args, exec): Promise<ToolReceipt> {
      const operation = 'driver-pause'
      const current = toolSession(exec, operation, args, EMPTY_KEYS)
      if (!current.ok) return failureReceipt(operation, current.error)
      return serviceReceipt(service, current.value, exec.signal, operation,
        () => service.pause(current.value), value => ({
          paused: value.paused,
          ...(value.binding === undefined ? {} : { binding: safeBinding(value.binding) }),
        }))
    },
  }))

  const driverResume = strictInput(defineTool({
    name: 'loopx_driver_resume',
    description: 'Arm continuation only after fresh exact authority readback.',
    parameters: {},
    output: TOOL_OUTPUT,
    async execute(args, exec): Promise<ToolReceipt> {
      const operation = 'driver-resume'
      const current = toolSession(exec, operation, args, EMPTY_KEYS)
      if (!current.ok) return failureReceipt(operation, current.error)
      return serviceReceipt(service, current.value, exec.signal, operation,
        () => service.resume(current.value, exec.signal),
        binding => ({ binding: safeBinding(binding) }))
    },
  }))

  const todoAdd = strictInput(defineTool({
    name: 'loopx_todo_add',
    description: 'Add one bounded public-safe Todo to the currently bound lane.',
    parameters: {
      text: { type: 'string', required: true },
      priority: { type: 'string', required: true, enum: ['P0', 'P1', 'P2'] },
      role: { type: 'string', enum: ['agent', 'user'] },
      actionKind: { type: 'string' },
      targetKey: { type: 'string' },
    },
    output: TOOL_OUTPUT,
    async execute(args, exec): Promise<ToolReceipt> {
      const operation = 'todo-add'
      const current = toolSession(exec, operation, args, TODO_ADD_KEYS)
      if (!current.ok) return failureReceipt(operation, current.error)
      return serviceReceipt(service, current.value, exec.signal, operation,
        () => service.todoAdd(current.value, args, exec.signal), safeTodoAdd)
    },
  }))

  const todoClaim = strictInput(defineTool({
    name: 'loopx_todo_claim',
    description: 'Claim one Todo for the currently bound Goal-Agent lane.',
    parameters: {
      todoId: { type: 'string', required: true },
      role: { type: 'string', enum: ['user', 'agent'] },
    },
    output: TOOL_OUTPUT,
    async execute(args, exec): Promise<ToolReceipt> {
      const operation = 'todo-claim'
      const current = toolSession(exec, operation, args, CLAIM_KEYS)
      if (!current.ok) return failureReceipt(operation, current.error)
      return serviceReceipt(service, current.value, exec.signal, operation,
        () => service.todoClaim(current.value, args, exec.signal), safeTodo)
    },
  }))

  const todoUpdate = strictInput(defineTool({
    name: 'loopx_todo_update',
    description: 'Update bounded fields of one Todo for the currently bound lane.',
    parameters: {
      todoId: { type: 'string', required: true },
      status: { type: 'string', enum: ['open', 'done', 'blocked', 'deferred'] },
      note: { type: 'string' },
      evidence: { type: 'string' },
      reason: { type: 'string' },
      taskClass: {
        type: 'string',
        enum: ['advancement_task', 'continuous_monitor', 'user_gate', 'user_action', 'blocker'],
      },
      clearClaim: { type: 'boolean' },
    },
    output: TOOL_OUTPUT,
    async execute(args, exec): Promise<ToolReceipt> {
      const operation = 'todo-update'
      const current = toolSession(exec, operation, args, UPDATE_KEYS)
      if (!current.ok) return failureReceipt(operation, current.error)
      return serviceReceipt(service, current.value, exec.signal, operation,
        () => service.todoUpdate(current.value, args, exec.signal), safeTodo)
    },
  }))

  const todoComplete = strictInput(defineTool({
    name: 'loopx_todo_complete',
    description: 'Complete one Todo with bounded evidence for the currently bound lane.',
    parameters: {
      todoId: { type: 'string', required: true },
      note: { type: 'string' },
      evidence: { type: 'string' },
      noFollowUp: { type: 'boolean' },
      turnInstanceId: { type: 'string' },
      taskLeaseIdempotencyKey: { type: 'string' },
      taskLeaseExpectedVersion: { type: 'integer' },
    },
    output: TOOL_OUTPUT,
    async execute(args, exec): Promise<ToolReceipt> {
      const operation = 'todo-complete'
      const current = toolSession(exec, operation, args, COMPLETE_KEYS)
      if (!current.ok) return failureReceipt(operation, current.error)
      return serviceReceipt(service, current.value, exec.signal, operation,
        () => service.todoComplete(current.value, args, exec.signal), safeTodo)
    },
  }))

  return Object.freeze([
    goalStart, goalAttach, goalActivate, loopxStatus, goalDetach, driverPause,
    driverResume, todoAdd, todoClaim, todoUpdate, todoComplete,
  ])
}

/** Register the closed model-tool catalog over the current Host service. */
export function apply(ctx: Context): void {
  for (const definition of loopXToolDefinitions(ctx.loopx)) ctx.tools.register(definition)
}
