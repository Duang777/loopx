import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Context } from '@deepseek-ai/cordis'
import Storage from '@deepseek-ai/dsh-storage'
import * as StorageDomain from '@deepseek-ai/dsh-storage-domain'
import * as StorageJson from '@deepseek-ai/dsh-storage-json'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LoopXCliClient } from '../src/cli-client.ts'
import LoopXService from '../src/service.ts'
import type { LoopXSessionRef } from '../src/types.ts'

const cleanups: Array<() => Promise<void>> = []

afterEach(async () => {
  vi.restoreAllMocks()
  await Promise.all(cleanups.splice(0).map(cleanup => cleanup()))
})

function startPacket(project: string, threadId: string, goalText: string) {
  return {
    schema_version: 'loopx_start_goal_guided_v0',
    ok: true,
    read_only: true,
    guided: true,
    project,
    goal_id: 'goal-a',
    agent_id: 'agent-a',
    host_surface: 'deepseek-harness-native',
    thread_id: threadId,
    thread_agent_binding: { status: 'bound', agent_id: 'agent-a' },
    project_connection: {
      project,
      registry: `${project}/.loopx/registry.json`,
      goal_id: 'goal-a',
      connection_state: 'connected',
    },
    command_pack: {
      schema_version: 'loopx_bootstrap_command_pack_v0',
      goal_start_contract: {
        schema_version: 'loopx_goal_start_command_v0',
        goal_text: goalText,
        planner: {
          required_before_todo_write: true,
          default_profile: 'open_ended_product_direction',
          profile_selection: 'Select the bounded planning profile.',
          profiles: {
            open_ended_product_direction: {
              suggested_items_min: 2,
              suggested_items_max: 5,
              intent: 'Rank work before execution.',
            },
            clear_bounded_problem: {
              item_count_policy: 'planner_sized',
              may_reuse_current_todo_when_it_already_represents_the_plan: true,
              intent: 'Use the minimum sufficient plan.',
            },
          },
          allowed_priorities: ['P0', 'P1', 'P2'],
          default_role: 'agent',
          default_task_class: 'advancement_task',
          required_fields: ['priority', 'text', 'task_class', 'action_kind'],
          public_safe_only: true,
          budget_policy: 'minimum sufficient plan',
        },
        activation: { host_loop_required_after_todo_writeback: true },
        stop_conditions: ['authority is missing'],
      },
    },
    guided_transaction: {
      schema_version: 'loopx_start_goal_guided_v0',
      ordered_steps: [
        { id: 'inspect', kind: 'read_only' },
        { id: 'plan', kind: 'model_checkpoint', prompt: 'Write bounded Todos.' },
      ],
    },
  }
}

async function setup() {
  const root = await mkdtemp(join(tmpdir(), 'dsh-loopx-planning-service-'))
  const project = join(root, 'project')
  const current: LoopXSessionRef = Object.freeze({
    id: 'session-a',
    identity: Object.freeze({ createdAt: 1, cwd: project }),
  })
  vi.spyOn(LoopXCliClient.prototype, 'runJson').mockImplementation(async request => {
    const goalText = request.args[request.args.indexOf('--goal-text') + 1] ?? ''
    return startPacket(project, current.id, goalText) as never
  })
  const ctx = new Context()
  await ctx.plugin(Storage)
  await ctx.plugin(StorageJson, { root: join(root, 'storage') })
  await ctx.plugin(StorageDomain, { backend: 'json' })
  let fiber = await ctx.plugin(LoopXService, { loopxBin: 'loopx', project })
  cleanups.push(async () => {
    await ctx.fiber.dispose()
    await rm(root, { recursive: true, force: true })
  })
  return {
    ctx,
    current,
    async reload() {
      await fiber.dispose()
      fiber = await ctx.plugin(LoopXService, { loopxBin: 'loopx', project })
    },
  }
}

describe('LoopXService planning continuation', () => {
  it('reads only the exact process-local planning generation', async () => {
    const { ctx, current } = await setup()
    const started = await ctx.loopx.start(current, 'Plan one bounded change')
    if (!started.ok || started.value.kind !== 'planning') throw new Error('start failed')

    expect(ctx.loopx.planningContinuation(current, 0)).toMatchObject({
      ok: false,
      error: { code: 'LOOPX_DRIVER_NOT_ARMED' },
    })
    expect(ctx.loopx.planningContinuation(current, started.value.binding.generation)).toEqual({
      ok: true,
      value: {
        kind: 'planning',
        fence: {
          sessionId: current.id,
          session: current.identity,
          goalId: 'goal-a',
          agentId: 'agent-a',
          generation: started.value.binding.generation,
        },
        body: started.value.modelCheckpoint,
      },
    })
  })

  it('does not rebuild planning authority after lifecycle loss or reload', async () => {
    const harness = await setup()
    const started = await harness.ctx.loopx.start(harness.current, 'Plan once')
    if (!started.ok || started.value.kind !== 'planning') throw new Error('start failed')
    const generation = started.value.binding.generation

    expect(harness.ctx.loopx.planningContinuation({
      ...harness.current,
      identity: { ...harness.current.identity, createdAt: 2 },
    }, generation)).toMatchObject({
      ok: false,
      error: { code: 'LOOPX_SESSION_LIFECYCLE_MISMATCH' },
    })
    expect(harness.ctx.loopx.planningContinuation(harness.current, generation)).toMatchObject({
      ok: false,
      error: { code: 'LOOPX_DRIVER_NOT_ARMED' },
    })

    await harness.ctx.loopx.start(harness.current, 'Plan after lifecycle rejection')
    await harness.reload()
    const restored = harness.ctx.loopx.getBinding(harness.current)
    if (!restored.ok || restored.value === undefined) throw new Error('restore failed')
    expect(harness.ctx.loopx.planningContinuation(
      harness.current,
      restored.value.generation,
    )).toMatchObject({ ok: false, error: { code: 'LOOPX_DRIVER_NOT_ARMED' } })
  })

  it('invalidates planning authority on an explicit pause', async () => {
    const { ctx, current } = await setup()
    const started = await ctx.loopx.start(current, 'Plan before pause')
    if (!started.ok || started.value.kind !== 'planning') throw new Error('start failed')

    await ctx.loopx.pause(current)
    expect(ctx.loopx.planningContinuation(current, started.value.binding.generation)).toMatchObject({
      ok: false,
      error: { code: 'LOOPX_DRIVER_NOT_ARMED' },
    })
  })

  it('actively invalidates planning authority on a failed planning write', async () => {
    const { ctx, current } = await setup()
    const started = await ctx.loopx.start(current, 'Plan before write failure')
    if (!started.ok || started.value.kind !== 'planning') throw new Error('start failed')

    await expect(ctx.loopx.todoAdd(current, {
      text: 'Write one bounded Todo',
      priority: 'P0',
    })).resolves.toMatchObject({
      ok: false,
      error: { code: 'LOOPX_WRITE_UNCERTAIN' },
    })
    expect(ctx.loopx.planningContinuation(current, started.value.binding.generation)).toMatchObject({
      ok: false,
      error: { code: 'LOOPX_DRIVER_NOT_ARMED' },
    })
  })
})
