import { randomUUID } from 'node:crypto'
import { createRequire } from 'node:module'
import type { Context } from '@deepseek-ai/cordis'
import type { Agent } from '@deepseek-ai/dsh-agent'
import type { CommandInvocation, CommandResult } from '@deepseek-ai/dsh-commands'
import type { UserMessage } from '@deepseek-ai/dsh-session'
import {
  CoordinatorAdmissionCancelled,
  coordinatorFor,
} from './coordinator.ts'
import type { CoordinatorRegistry } from './coordinator.ts'
import {
  failureReceipt as operationFailure,
  safeAttach,
  safeBinding,
  safeStart,
  safeStatus,
  serviceOperationReceipt,
  successReceipt as succeeded,
  unexpectedFailure,
} from './receipts.ts'
import type {
  LoopXFailure,
  LoopXOperationReceipt,
  LoopXResult,
  LoopXServiceApi,
  LoopXSessionRef,
} from './types.ts'

export const name = 'dsh-loopx-command'
export const inject = ['commands', 'loopx']

const PLUGIN_ID = 'dsh-loopx-plugin'
const manifest = createRequire(import.meta.url)('../package.json') as {
  readonly name?: unknown
  readonly version?: unknown
}
if (manifest.name !== PLUGIN_ID || typeof manifest.version !== 'string' || manifest.version.length === 0) {
  throw new TypeError('dsh-loopx-plugin package version is unavailable')
}
export const PLUGIN_VERSION = manifest.version

const USAGE = 'Usage: /loopx [status|version|pause|resume|detach|start <objective>|attach <goal-id> [<agent-id>|--new-peer]]'
const SEMANTIC_ROUTING_POLICY = [
  'Interpret the quoted request through the registered `loopx_*` tools; never invoke a raw LoopX CLI or edit registries.',
  'Do not guess or fuzzy-match a Goal or Agent id.',
  'If no safe typed operation follows from the request, ask the user without mutating authority.',
].map((rule, index) => `${index + 1}. ${rule}`).join('\n')

type ParsedLoopXCommand =
  | { readonly kind: 'status'; readonly includeUsage: boolean }
  | { readonly kind: 'version' }
  | { readonly kind: 'pause' }
  | { readonly kind: 'resume' }
  | { readonly kind: 'detach' }
  | { readonly kind: 'start'; readonly objective: string }
  | {
    readonly kind: 'attach'
    readonly goalId: string
    readonly agentId?: string | undefined
    readonly newPeer?: true | undefined
  }
  | { readonly kind: 'semantic'; readonly originalInput: string }

type ServiceCommand = Exclude<ParsedLoopXCommand, { kind: 'version' | 'pause' | 'semantic' }>

/** Closed `/loopx` grammar; semantic fallthrough retains every input byte. */
function parseLoopXCommand(rawInput: string): ParsedLoopXCommand {
  if (rawInput.includes('\n') || rawInput.includes('\r')) {
    return { kind: 'semantic', originalInput: rawInput }
  }
  const input = rawInput.trim()
  if (input.length === 0) return { kind: 'status', includeUsage: true }
  if (input === 'status') return { kind: 'status', includeUsage: false }
  if (input === 'version') return { kind: 'version' }
  if (input === 'pause') return { kind: 'pause' }
  if (input === 'resume') return { kind: 'resume' }
  if (input === 'detach') return { kind: 'detach' }

  const start = /^start[\t ]+([^\r\n]+)$/u.exec(input)
  if (start !== null) {
    const objective = start[1]?.trim()
    if (objective !== undefined && objective.length > 0) return { kind: 'start', objective }
  }

  const attach = input.split(/[\t ]+/u)
  if (attach[0] === 'attach' && attach.length === 2) {
    const goalId = attach[1]
    if (goalId !== undefined && !goalId.startsWith('--')) return { kind: 'attach', goalId }
  }
  if (attach[0] === 'attach' && attach.length === 3) {
    const goalId = attach[1]
    const peer = attach[2]
    if (goalId !== undefined && peer !== undefined && !goalId.startsWith('--')) {
      if (peer === '--new-peer') return { kind: 'attach', goalId, newPeer: true }
      if (!peer.startsWith('--')) return { kind: 'attach', goalId, agentId: peer }
    }
  }
  return { kind: 'semantic', originalInput: rawInput }
}

function lifecycleMismatch(message: string, operation: string): LoopXFailure {
  return Object.freeze({
    code: 'LOOPX_SESSION_LIFECYCLE_MISMATCH',
    message,
    operation,
    retryable: false,
    outcomeUncertain: false,
  })
}

/** Derive the only exact live Session identity a command or tool may operate on. */
export function deriveLoopXSessionRef(
  agent: Agent | undefined,
  operation: string,
): LoopXResult<LoopXSessionRef> {
  if (agent === undefined) {
    return {
      ok: false,
      application: 'no',
      error: {
        code: 'LOOPX_INVALID_REQUEST',
        message: 'LoopX operations require the current DSH Agent execution.',
        operation,
        retryable: false,
        outcomeUncertain: false,
      },
    }
  }
  const agentId: unknown = agent.id
  const sessionId: unknown = agent.session.id
  const headerId: unknown = agent.session.header.id
  if (typeof agentId !== 'string' || typeof sessionId !== 'string'
    || typeof headerId !== 'string' || sessionId.length === 0
    || agentId !== sessionId || headerId !== sessionId) {
    return { ok: false, application: 'no', error: lifecycleMismatch(
      'The current Agent and DSH Session identities do not match.', operation,
    ) }
  }
  const { createdAt, cwd } = agent.session.header
  if (!Number.isSafeInteger(createdAt) || createdAt < 0) {
    return { ok: false, application: 'no', error: lifecycleMismatch(
      'The current DSH Session lifecycle identity is invalid.', operation,
    ) }
  }
  return {
    ok: true,
    application: 'no',
    value: Object.freeze({
      id: sessionId,
      session: agent.session,
      identity: Object.freeze({ createdAt, ...(cwd === undefined ? {} : { cwd }) }),
    }),
  }
}

function typedIntent(parsed: Exclude<ServiceCommand, { kind: 'status' }>, request: string): LoopXOperationReceipt {
  const operation = parsed.kind === 'start' ? 'goal-start'
    : parsed.kind === 'attach' ? 'goal-attach'
    : parsed.kind === 'resume' ? 'driver-resume'
    : 'goal-detach'
  const args = parsed.kind === 'start' ? { goalText: parsed.objective }
    : parsed.kind === 'attach' ? {
        goalId: parsed.goalId,
        ...(parsed.agentId === undefined ? {} : { agentId: parsed.agentId }),
        ...(parsed.newPeer === true ? { newPeer: true } : {}),
      }
    : {}
  return Object.freeze({
    schemaVersion: 'dsh_loopx_operation_receipt_v1',
    kind: 'typed_intent',
    operation,
    request,
    arguments: Object.freeze(args),
    execution: 'not_attempted',
    application: 'no',
    delivery: 'not_needed',
    recovery: 'none',
  })
}

function semanticRequest(request: string): LoopXOperationReceipt {
  return Object.freeze({
    schemaVersion: 'dsh_loopx_operation_receipt_v1',
    kind: 'semantic_request',
    operation: 'semantic-routing',
    request,
    execution: 'not_attempted',
    application: 'no',
    delivery: 'not_needed',
    recovery: 'none',
  })
}

function pluginMessage(receipt: LoopXOperationReceipt): UserMessage {
  const prefix = receipt.kind === 'semantic_request'
    ? `LoopX semantic routing policy (fixed plugin instruction):\n${SEMANTIC_ROUTING_POLICY}\n\n`
    : receipt.kind === 'typed_intent'
      ? 'Execute this validated, not-yet-attempted intent through the matching registered `loopx_*` tool.\n\n'
      : 'Interpret this completed LoopX operation receipt. Do not repeat an applied write because delivery was delayed.\n\n'
  return Object.freeze({
    id: randomUUID(),
    role: 'user' as const,
    content: Object.freeze([{ type: 'text' as const, text: `${prefix}${JSON.stringify(receipt)}` }]),
    source: Object.freeze({ kind: 'plugin' as const, plugin: PLUGIN_ID }),
  }) as unknown as UserMessage
}

function withDelivery(
  receipt: LoopXOperationReceipt,
  delivery: LoopXOperationReceipt['delivery'],
): LoopXOperationReceipt {
  return Object.freeze({ ...receipt, delivery })
}

function withFailureRequest(
  receipt: LoopXOperationReceipt,
  request: string,
): LoopXOperationReceipt {
  return receipt.execution === 'rejected' || receipt.execution === 'indeterminate'
    ? Object.freeze({ ...receipt, request })
    : receipt
}

function deliver(
  agent: Agent,
  receipt: LoopXOperationReceipt,
  route: 'steer' | 'followup',
): LoopXOperationReceipt {
  const queued = withDelivery(receipt, route === 'steer' ? 'steered' : 'followup_queued')
  try {
    if (route === 'steer') agent.steer(pluginMessage(queued))
    else agent.followup(pluginMessage(queued))
    return queued
  } catch {
    return withDelivery(receipt, 'failed')
  }
}

function asCommandResult(receipt: LoopXOperationReceipt, includeUsage = false): CommandResult {
  const suffix = includeUsage ? `\n\n${USAGE}` : ''
  const text = `${JSON.stringify(receipt)}${suffix}`
  return receipt.delivery === 'failed'
    || receipt.execution === 'rejected'
    || receipt.execution === 'indeterminate'
    ? { kind: 'error', text }
    : { kind: 'success', text }
}

async function runServiceCommand(
  service: LoopXServiceApi,
  session: LoopXSessionRef,
  parsed: ServiceCommand,
  signal: AbortSignal,
): Promise<LoopXOperationReceipt> {
  if (parsed.kind === 'status') {
    return serviceOperationReceipt(
      service, session, signal, 'status',
      () => service.status(session, signal),
      safeStatus,
    )
  }
  if (parsed.kind === 'start') {
    return serviceOperationReceipt(
      service, session, signal, 'goal-start',
      () => service.start(session, parsed.objective, signal),
      safeStart,
    )
  }
  if (parsed.kind === 'attach') {
    return serviceOperationReceipt(
      service, session, signal, 'goal-attach',
      () => service.attach(session, {
        goalId: parsed.goalId,
        ...(parsed.agentId === undefined ? {} : { agentId: parsed.agentId }),
        ...(parsed.newPeer === true ? { newPeer: true } : {}),
      }, signal),
      safeAttach,
    )
  }
  if (parsed.kind === 'resume') {
    return serviceOperationReceipt(
      service, session, signal, 'driver-resume',
      () => service.resume(session, signal),
      value => ({ binding: safeBinding(value) }),
    )
  }
  return serviceOperationReceipt(
    service, session, signal, 'goal-detach',
    () => service.detach(session, signal),
    value => ({ detached: value.detached, binding: safeBinding(value.binding) }),
  )
}

function exactSession(agent: Agent, session: LoopXSessionRef): boolean {
  return agent.session === session.session
    && agent.id === session.id
    && agent.session.id === session.id
}

async function executeLoopXCommand(
  service: LoopXServiceApi,
  coordinators: CoordinatorRegistry,
  invocation: CommandInvocation,
): Promise<CommandResult> {
  const parsed = parseLoopXCommand(invocation.rawInput)
  if (parsed.kind === 'version') {
    return { kind: 'success', text: `${PLUGIN_ID} ${PLUGIN_VERSION}` }
  }
  const current = deriveLoopXSessionRef(invocation.agent, 'command')
  if (!current.ok) return asCommandResult(operationFailure('command', current.error))
  const session = current.value

  if (parsed.kind === 'pause') {
    coordinators.pause(session)
    const receipt = succeeded('driver-pause', 'no', { paused: true })
    return asCommandResult(invocation.agent.status === 'running'
      ? deliver(invocation.agent, receipt, 'steer')
      : receipt)
  }

  const routeRunning = async (): Promise<CommandResult> => {
    if (parsed.kind === 'semantic') {
      return asCommandResult(deliver(invocation.agent, semanticRequest(parsed.originalInput), 'steer'))
    }
    if (parsed.kind !== 'status') {
      return asCommandResult(deliver(
        invocation.agent,
        typedIntent(parsed, invocation.rawInput),
        'steer',
      ))
    }
    const receipt = withFailureRequest(
      await runServiceCommand(service, session, parsed, invocation.signal),
      invocation.rawInput,
    )
    return asCommandResult(deliver(invocation.agent, receipt, 'steer'), parsed.includeUsage)
  }

  if (invocation.agent.status === 'running') return routeRunning()

  try {
    const admitted = await coordinators.admitWhenIdle(
      invocation.agent,
      invocation.signal,
      () => exactSession(invocation.agent, session),
      async maintenanceSignal => {
        const signal = AbortSignal.any([invocation.signal, maintenanceSignal])
        if (parsed.kind === 'semantic') {
          return deliver(invocation.agent, semanticRequest(parsed.originalInput), 'followup')
        }
        const receipt = withFailureRequest(
          await runServiceCommand(service, session, parsed, signal),
          invocation.rawInput,
        )
        return deliver(invocation.agent, receipt, 'followup')
      },
    )
    if (admitted.route === 'running') return routeRunning()
    return asCommandResult(
      admitted.value,
      parsed.kind === 'status' && parsed.includeUsage,
    )
  } catch (error: unknown) {
    if (error instanceof CoordinatorAdmissionCancelled || invocation.signal.aborted) {
      return asCommandResult(operationFailure('command', {
        code: 'LOOPX_CLI_ABORTED',
        message: 'The LoopX command was cancelled before Service admission.',
        operation: 'command',
        retryable: false,
        outcomeUncertain: false,
      }))
    }
    return asCommandResult(operationFailure('command', unexpectedFailure('command')))
  }
}

/** Register the global command and claim its provisional barrier synchronously. */
export function apply(ctx: Context): void {
  const coordinators = coordinatorFor(ctx.loopx)
  ctx.commands.register({
    name: 'loopx',
    description: 'route exact LoopX controls or a semantic request in this Session',
    input: { hint: '[status|version|pause|resume|detach|start ...|attach ...]' },
    handler(invocation) {
      const claimed = coordinators.claimCommand(
        String(invocation.commandId), invocation.agent.session, invocation.agent,
      )
      if (!claimed) {
        return {
          kind: 'error',
          text: 'LOOPX_COMMAND_BARRIER_MISSING: The resolved command did not own its provisional barrier.',
        }
      }
      const commandId = String(invocation.commandId)
      const operation = executeLoopXCommand(ctx.loopx, coordinators, invocation)
      const settle = (): void => coordinators.settleOwned(commandId, invocation.agent.session)
      void operation.then(settle, settle)
      return operation
    },
  })
}
