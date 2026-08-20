#!/usr/bin/env node

import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { chmod, mkdir, mkdtemp, readFile, realpath, readdir, rm, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const dshBin = process.env.DSH_BIN || join(packageRoot, 'node_modules', '.bin', 'dsh')
const profileName = 'web'
const bundleRows = [
  ['loopx-service', 'dsh-loopx-plugin/service'],
  ['loopx-command', 'dsh-loopx-plugin/command'],
  ['loopx-tools', 'dsh-loopx-plugin/tools'],
  ['loopx-driver', 'dsh-loopx-plugin/driver'],
]

function parseSpecs(argv) {
  const specs = []
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index]
    if (flag === '--') continue
    if (flag !== '--package-path' && flag !== '--tarball') {
      throw new Error(`unsupported argument: ${flag}`)
    }
    const value = argv[index + 1]
    if (!value) throw new Error(`${flag} requires a path`)
    specs.push({ kind: flag === '--tarball' ? 'tarball' : 'path', value: resolve(value) })
    index += 1
  }
  if (specs.length === 0) throw new Error('pass --package-path and/or --tarball')
  return specs
}

function run(file, args, options = {}) {
  const result = spawnSync(file, args, {
    cwd: options.cwd ?? packageRoot,
    env: options.env ?? process.env,
    encoding: 'utf8',
    maxBuffer: 8 * 1024 * 1024,
    shell: false,
  })
  if (result.error) throw result.error
  if (result.status !== 0) {
    throw new Error([
      `${file} ${args.join(' ')} failed with ${String(result.status)}`,
      result.stdout,
      result.stderr,
    ].filter(Boolean).join('\n'))
  }
  return result.stdout
}

function assertPackedFiles(tarball) {
  const entries = run('tar', ['-tf', tarball]).trim().split('\n').filter(Boolean)
  assert(entries.length > 0, 'tarball is empty')
  for (const entry of entries) {
    assert.match(entry, /^package\/(?:package\.json|README\.md|LICENSE|NOTICE|cordis\.patch\.yml|lib\/[^/]+\.js|lib\/types\/[^/]+\.d\.ts)$/u)
  }
  for (const required of [
    'package/package.json',
    'package/README.md',
    'package/LICENSE',
    'package/NOTICE',
    'package/cordis.patch.yml',
    'package/lib/service.js',
    'package/lib/command.js',
    'package/lib/tools.js',
    'package/lib/driver.js',
    'package/lib/types/service.d.ts',
  ]) {
    assert(entries.includes(required), `tarball is missing ${required}`)
  }
}

function assertInstalledConfig(dump) {
  let previous = -1
  for (const [id, name] of bundleRows) {
    const position = dump.indexOf(`id: ${id}`)
    assert(position > previous, `missing or unordered bundle row ${id}`)
    assert(dump.includes(`name: ${name}`), `missing bundle module ${name}`)
    previous = position
  }
  assert.deepEqual(
    [...dump.matchAll(/^\s*(?:-\s+)?id:\s+(loopx-[^\s]+)\s*$/gmu)].map(match => match[1]),
    bundleRows.map(([id]) => id),
    'profile must contain exactly the four LoopX bundle rows',
  )
  assert.deepEqual(
    [...dump.matchAll(/^\s*(?:-\s+)?name:\s+(dsh-loopx-plugin\/[^\s]+)\s*$/gmu)].map(match => match[1]),
    bundleRows.map(([, module]) => module),
    'profile must not expose a fifth dsh-loopx-plugin face',
  )
  assert.match(dump, /id: storage-domain[\s\S]{0,240}backend: json/u)
  assert(!dump.includes('dsh.client: dsh-loopx-plugin'), 'v1 must not add a Client-plane row')
}

async function textTree(root) {
  let output = ''
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const path = join(root, entry.name)
    if (entry.isDirectory()) output += await textTree(path)
    else if (entry.isFile()) output += await readFile(path, 'utf8')
  }
  return output
}

const mockLoopXSource = String.raw`#!/usr/bin/env node
import { appendFile, readFile } from 'node:fs/promises'

const args = process.argv.slice(2)
const state = process.env.LOOPX_SMOKE_STATE
if (!state) throw new Error('LOOPX_SMOKE_STATE is required')
const value = flag => {
  const index = args.indexOf(flag)
  return index < 0 ? undefined : args[index + 1]
}
if (value('--format') !== 'json') throw new Error('JSON format is required')
const commands = new Set(['start-goal', 'bootstrap', 'bootstrap-command-pack', 'heartbeat-prompt', 'refresh-state', 'status', 'todo', 'quota'])
const index = args.findIndex(arg => commands.has(arg))
const command = args[index]
const subcommand = command === 'todo' || command === 'quota' ? args[index + 1] : undefined
const goalId = value('--goal-id') ?? value('--fork-goal') ?? 'goal-smoke'
const agentId = value('--agent-id') ?? 'agent-smoke'
const threadId = value('--thread-id') ?? 'session-smoke'
const project = value('--project') ?? process.cwd()
const registry = project + '/.loopx/registry.json'
const history = await readFile(state, 'utf8').catch(() => '')
const connected = history.split('\n').includes('bootstrap')
await appendFile(state, command + '\n')

const goalStartContract = {
  schema_version: 'loopx_goal_start_command_v0',
  goal_text: value('--goal-text'),
  planner: {
    required_before_todo_write: true,
    default_profile: 'clear_bounded_problem',
    profile_selection: 'Use the minimum sufficient bounded public-safe plan.',
    profiles: {
      open_ended_product_direction: {
        suggested_items_min: 2, suggested_items_max: 5,
        intent: 'Rank public-safe work before execution.',
      },
      clear_bounded_problem: {
        item_count_policy: 'planner_sized',
        may_reuse_current_todo_when_it_already_represents_the_plan: true,
        intent: 'Use the minimum sufficient explicit plan.',
      },
    },
    allowed_priorities: ['P0', 'P1', 'P2'],
    default_role: 'agent',
    default_task_class: 'advancement_task',
    required_fields: ['priority', 'text', 'task_class', 'action_kind'],
    public_safe_only: true,
    budget_policy: 'minimum sufficient plan; no fixed-count filler',
  },
  activation: { host_loop_required_after_todo_writeback: true },
  stop_conditions: ['private material is required', 'destructive authority is required'],
}

let output
if (command === 'start-goal') {
  output = {
    schema_version: 'loopx_start_goal_guided_v0', ok: true, read_only: true, guided: true,
    project, goal_id: goalId, agent_id: agentId,
    host_surface: 'deepseek-harness-native', thread_id: threadId,
    thread_agent_binding: { status: 'bound', agent_id: agentId },
    project_connection: {
      project, registry, goal_id: goalId,
      connection_state: connected ? 'connected' : 'not_connected',
    },
    command_pack: {
      schema_version: 'loopx_bootstrap_command_pack_v0',
      goal_start_contract: goalStartContract,
    },
    guided_transaction: {
      schema_version: 'loopx_start_goal_guided_v0',
      ordered_steps: [
        { id: 'inspect', kind: 'read_only' },
        ...(connected ? [] : [{
          id: 'connect_if_needed', kind: 'conditional_mutation',
          command: 'exit 86 # non-authoritative producer hint; never execute',
          connect_contract: {
            schema_version: 'loopx_start_goal_connect_v0', operation: 'bootstrap_connect',
            goal_id: goalId, objective: value('--goal-text'),
            adapter_kind: 'read_only_project_map_v0', adapter_status: 'connected-read-only',
            onboarding_scan_enabled: false, fine_grained: false,
          },
        }]),
        { id: 'plan', kind: 'model_checkpoint', prompt: 'Plan, refresh bounded Todos, then call loopx_goal_activate.' },
      ],
    },
  }
} else if (command === 'bootstrap') {
  output = {
    schema_version: 'loopx_bootstrap_result_v0', ok: true,
    project, goal_id: goalId, registry,
    state_file: project + '/.loopx/goals/' + goalId + '.json',
    registry_goal_action: 'created', state_action: 'created',
    global_sync: { ok: true, synced_goal_ids: [goalId], wrote: true },
  }
} else if (command === 'bootstrap-command-pack') {
  output = {
    schema_version: 'loopx_bootstrap_command_pack_v0', ok: true, read_only: true,
    project, goal_id: goalId, agent_id: agentId, agent_type: 'deepseek-harness-native',
    host_surface: 'deepseek-harness-native', thread_id: threadId,
    thread_agent_binding: { status: 'bound', agent_id: agentId },
    project_connection: { project, registry, goal_id: goalId, connection_state: 'connected' },
    host_loop_activation: {
      schema_version: 'loopx_host_loop_activation_v1', agent_type: 'deepseek-harness-native',
      goal_id: goalId, agent_id: agentId, activation_allowed: true,
      identity_contract: { schema_version: 'loopx_host_loop_identity_selection_v0', registered_agents: [agentId] },
      identity_selection_gate: null, host_surface: 'deepseek_harness_native_session',
      activation_method: 'current_session_host_tool',
      activation_input: {
        schema_version: 'loopx_deepseek_harness_native_activation_input_v0',
        tool: 'loopx_goal_activate', arguments: { goalId, agentId },
      },
      host_mutation: {
        owner: 'DSH LoopX plugin', host_tool: 'loopx_goal_activate', current_session_only: true,
        cli_can_mutate_directly: false,
        forbidden_tool_arguments: ['sessionId', 'registryPath', 'taskBody', 'argv'],
      },
    },
  }
} else if (command === 'heartbeat-prompt') {
  output = {
    schema_version: 'loopx_heartbeat_prompt_v0', ok: true, goal_id: goalId,
    agent_id: agentId, runtime_profile: 'generic_cli', task_body: 'SMOKE PRIVATE TASK BODY',
  }
} else if (command === 'todo' && subcommand === 'add') {
  const role = value('--role')
  output = {
    schema_version: 'loopx_todo_command_v0', ok: true, dry_run: false,
    added: true, already_exists: false, goal_id: goalId, role,
    todo: value('--text'), todo_id: 'todo-smoke', status: 'open',
    task_class: value('--task-class'), action_kind: value('--action-kind'),
    claimed_by: role === 'agent' ? value('--claimed-by') : null,
    bound_agent: role === 'user' ? value('--bound-agent') : null,
    agent_id: role === 'user' ? value('--agent-id') : null,
    blocks_agent: role === 'user' ? value('--blocks-agent') : null,
    target_key: value('--target-key') ?? null,
  }
} else if (command === 'refresh-state') {
  const sourceRegistry = value('--registry') ?? registry
  output = {
    schema_version: 'loopx_refresh_state_result_v0', ok: true, dry_run: false,
    appended: true, partial_write: false, registry: sourceRegistry,
    project: value('--project'), goal_id: goalId, agent_id: agentId,
    agent_lane: value('--agent-lane'), progress_scope: value('--progress-scope'),
    external_sink_delivery_authorized: false,
    global_sync: {
      ok: true, skipped: false, registry: sourceRegistry,
      global_registry: project + '/runtime/registry.global.json',
      synced_goal_ids: [goalId], wrote: true,
    },
  }
} else if (command === 'status') {
  output = {
    schema_version: 'loopx_status_v0', ok: true, goal_filter: goalId,
    attention_queue: { items: [{ goal_id: goalId, status: 'active', waiting_on: 'agent' }] },
  }
} else if (command === 'quota' && args[index + 1] === 'should-run') {
  output = {
    schema_version: 'loopx_quota_should_run_v0', ok: true, mode: 'should-run',
    goal_id: goalId, decision: 'run', should_run: true, effective_action: 'run_now',
    agent_identity: { agent_id: agentId },
    heartbeat_receipt: {
      schema_version: 'heartbeat_quota_receipt_v0',
      turn_instance_id: value('--turn-instance-id'), status: 'committed',
    },
    scheduler_hint: {
      schema_version: 'scheduler_hint_v0', source: 'quota.should-run', action: 'run_now',
      cadence_class: 'immediate', reset_policy: { reset_token: 'smoke-reset' },
      unchanged_poll: { limits: { local_scheduler: 2 }, after_limits: { local_scheduler: 'pause' } },
      cold_path_detail: {
        schema_version: 'scheduler_hint_detail_v0',
        local_scheduler: { recommended_interval_minutes: 3, unchanged_poll_limit: 2, after_limit: 'pause' },
      },
    },
  }
} else {
  output = { schema_version: 'unsupported_v0', ok: false }
}
process.stdout.write(JSON.stringify(output))
`

async function importFrom(requireFromPlugin, specifier) {
  return import(pathToFileURL(requireFromPlugin.resolve(specifier)).href)
}

async function exerciseInstalledPlugin(installedDir, home, mockLoopX, statePath) {
  const requireFromPlugin = createRequire(join(installedDir, 'package.json'))
  const [{ Context }, Storage, StorageDomain, StorageJson, serviceModule, commandModule, toolsModule, driverModule] = await Promise.all([
    importFrom(requireFromPlugin, '@deepseek-ai/cordis'),
    importFrom(requireFromPlugin, '@deepseek-ai/dsh-storage'),
    importFrom(requireFromPlugin, '@deepseek-ai/dsh-storage-domain'),
    importFrom(requireFromPlugin, '@deepseek-ai/dsh-storage-json'),
    import(pathToFileURL(join(installedDir, 'lib', 'service.js')).href),
    import(pathToFileURL(join(installedDir, 'lib', 'command.js')).href),
    import(pathToFileURL(join(installedDir, 'lib', 'tools.js')).href),
    import(pathToFileURL(join(installedDir, 'lib', 'driver.js')).href),
  ])
  const storageRoot = join(home, 'behavior-storage')
  const project = join(home, 'behavior-project')
  await mkdir(project, { recursive: true })
  const ctx = new Context()
  await ctx.plugin(Storage.default)
  await ctx.plugin(StorageJson, { root: storageRoot })
  await ctx.plugin(StorageDomain, { backend: 'json' })
  await ctx.plugin(serviceModule.LoopXService, {
    loopxBin: mockLoopX,
    project,
    environment: { LOOPX_SMOKE_STATE: statePath },
  })
  assert.equal(ctx.get('goals'), undefined, 'ctx.loopx must not mount or consume ctx.goals')
  const service = ctx.get('loopx')
  assert(service, 'LoopX service did not activate over storage-domain')

  const commands = new Map()
  const tools = new Map()
  const pluginContext = {
    loopx: service,
    commands: { register: value => commands.set(value.name, value) },
    tools: { register: value => tools.set(value.name, value) },
  }
  commandModule.apply(pluginContext)
  toolsModule.apply(pluginContext)
  assert.deepEqual([...tools.keys()].sort(), [
    'loopx_driver_pause',
    'loopx_driver_resume',
    'loopx_goal_activate',
    'loopx_goal_attach',
    'loopx_goal_detach',
    'loopx_goal_start',
    'loopx_status',
    'loopx_todo_add',
    'loopx_todo_claim',
    'loopx_todo_complete',
    'loopx_todo_update',
  ], 'packed plugin must expose exactly eleven bounded model tools')
  const followups = []
  const nextTurn = []
  let status = 'idle'
  let driver
  let agent
  agent = {
    id: 'session-smoke',
    session: {
      id: 'session-smoke',
      header: { version: 0, id: 'session-smoke', createdAt: 7, cwd: project, seedLength: 0 },
      events: [],
      surface: { nodes: [] },
    },
    get status() { return status },
    inbox: {
      nextTurn,
      nextStep: [],
      get hasPending() { return nextTurn.length > 0 },
      append(target, message) {
        if (target !== 'next-turn') throw new Error('smoke only appends next-turn messages')
        nextTurn.push(message)
      },
      remove(id) {
        const position = nextTurn.findIndex(message => message.id === id)
        if (position < 0) return false
        nextTurn.splice(position, 1)
        return true
      },
      replace(id, message) {
        const position = nextTurn.findIndex(value => value.id === id)
        if (position < 0) return false
        nextTurn.splice(position, 1, message)
        return true
      },
    },
    followup(message) {
      followups.push(message)
      nextTurn.push(message)
      if (driver) {
        driver.onInboxInserted(agent, message)
        status = 'running'
        driver.onAgentStatus(agent, 'running')
      }
    },
    cancel() { status = 'idle' },
    whenIdle() { status = 'idle'; return Promise.resolve() },
  }
  const command = commands.get('loopx')
  assert(command, '/loopx command was not registered')
  const signal = new AbortController().signal
  let commandOrdinal = 0
  const invoke = rawInput => command.handler({
    commandId: `smoke-command-${++commandOrdinal}`, agent, rawInput, signal,
  })
  const installedManifest = JSON.parse(await readFile(join(installedDir, 'package.json'), 'utf8'))
  assert.deepEqual(Object.keys(installedManifest.exports).sort(), [
    '.', './command', './cordis.patch.yml', './driver', './package.json', './service', './tools',
  ], 'manifest must expose exactly four runtime faces plus root metadata')
  const version = await invoke('version')
  assert.deepEqual(version, {
    kind: 'success',
    text: `dsh-loopx-plugin ${installedManifest.version}`,
  })
  assert.equal(await readFile(statePath, 'utf8'), '', 'version must not invoke the LoopX CLI')

  const semanticCommand = await invoke('smoke goal')
  assert.equal(semanticCommand.kind, 'success')
  assert.match(semanticCommand.text, /Queued the request/u)
  assert.equal(followups.length, 1, 'free text must queue exactly one same-Agent semantic follow-up')
  assert.equal(followups[0].source.kind, 'plugin')
  assert.equal(followups[0].source.plugin, 'dsh-loopx-plugin')
  const semanticText = followups[0].content[0].text
  assert.match(semanticText, /LoopX semantic routing policy/u)
  assert.match(semanticText, /registered `loopx_\*` tools/u)
  assert.match(semanticText, /"smoke goal"/u)
  assert.equal(
    [...tools.keys()].filter(toolName => semanticText.includes(toolName)).length,
    0,
    'semantic follow-up must not duplicate the registered tool-name catalog',
  )
  assert.equal(await readFile(statePath, 'utf8'), '', 'semantic command entry must not invoke LoopX')

  let toolCallOrdinal = 0
  const executeTool = async (name, args) => {
    const definition = tools.get(name)
    assert(definition, `missing tool ${name}`)
    const callId = `smoke-tool-${++toolCallOrdinal}`
    const execution = {
      name, callId, rootCallId: callId, arguments: args, agent, signal,
      token: Symbol(callId), concludeTurn() {},
    }
    return definition.execute(args, execution)
  }

  const planned = await executeTool('loopx_goal_start', { goalText: 'smoke goal' })
  assert.equal(planned.ok, true)
  assert.equal(planned.value.kind, 'planning')
  assert.match(planned.value.modelCheckpoint, /dsh_loopx_planning_checkpoint_v0/u)
  const connectCalls = (await readFile(statePath, 'utf8')).trim().split('\n').slice(0, 3)
  assert.deepEqual(connectCalls, ['start-goal', 'bootstrap', 'start-goal'])

  followups.length = 0
  nextTurn.length = 0
  status = 'idle'
  let turnOrdinal = 0
  driver = new driverModule.LoopXContinuationDriver({
    service,
    isLiveAgent: current => current === agent,
    makeTurnInstanceId: () => `turn-smoke-${++turnOrdinal}`,
  })
  driver.observeAgent(agent)
  driver.onAgentStatus(agent, 'idle')
  await driver.whenSettled()
  assert.equal(followups.length, 1, 'planning idle did not enqueue exactly one recovery')
  const planningFollowup = followups[0]
  assert.equal(planningFollowup.source.plugin, 'dsh-loopx-plugin/driver')
  assert.match(planningFollowup.content[0].text, /dsh_loopx_planning_checkpoint_v0/u)
  const planningCalls = (await readFile(statePath, 'utf8')).trim().split('\n')
  assert(!planningCalls.includes('quota'), 'planning recovery must not call delivery quota')
  assert(!planningCalls.includes('heartbeat-prompt'), 'planning recovery must not fetch a task body')
  driver.onInboxClaimed(agent, planningFollowup)
  nextTurn.length = 0
  const planningAdmission = await driver.onPreStep(
    agent,
    [planningFollowup],
    signal,
    async () => ({ kind: 'enter', messages: [planningFollowup] }),
  )
  assert.equal(planningAdmission.kind, 'enter', 'exact planning recovery was not admitted')

  const added = await executeTool('loopx_todo_add', {
    text: 'Validate the packaged semantic planning flow', priority: 'P0',
  })
  assert.equal(added.ok, true)
  assert.equal(added.value.todoId, 'todo-smoke')
  const activated = await executeTool('loopx_goal_activate', {
    goalId: 'goal-smoke', agentId: 'agent-smoke',
  })
  assert.equal(activated.ok, true)
  status = 'idle'
  const readback = await invoke('')
  assert.equal(readback.kind, 'success')
  assert.match(readback.text, /active_armed/u)
  assert.match(readback.text, /LoopX authoritative state/u)

  followups.length = 0
  nextTurn.length = 0
  status = 'idle'
  driver.onAgentStatus(agent, 'idle')
  await driver.whenSettled()
  assert.equal(followups.length, 1, 'idle continuation did not enqueue exactly one same-Agent follow-up')
  assert.equal(followups[0].source.kind, 'plugin')
  assert.equal(followups[0].source.plugin, 'dsh-loopx-plugin/driver')
  assert.equal(followups[0].content[0].text, 'SMOKE PRIVATE TASK BODY')

  const human = {
    id: 'human-smoke', role: 'user', content: [{ type: 'text', text: 'human preemption' }],
    source: { kind: 'user' },
  }
  nextTurn.push(human)
  driver.onInboxInserted(agent, human)
  await driver.whenSettled()
  assert.deepEqual(nextTurn, [human], 'human input must replace a queued automatic follow-up')
  const yielded = service.getBinding({ id: 'session-smoke', identity: { createdAt: 7, cwd: project } })
  assert.equal(yielded.ok, true)
  assert.equal(yielded.value?.phase, 'active_armed', 'ordinary human input must not persist a pause')
  driver.onSessionEvent(agent, { type: 'user/message', data: human })
  nextTurn.length = 0
  followups.length = 0
  status = 'idle'
  driver.onAgentStatus(agent, 'idle')
  await driver.whenSettled()
  assert.equal(followups.length, 1, 'armed binding did not continue after the human turn')
  assert.equal(followups[0].content[0].text, 'SMOKE PRIVATE TASK BODY')
  assert.equal(turnOrdinal, 2, 'human yield must trigger a fresh quota turn identity')
  await driver.dispose()
  await ctx.fiber.dispose()

  const stored = await textTree(storageRoot)
  assert(!stored.includes('SMOKE PRIVATE TASK BODY'), 'task body leaked into Host sidecar')
  assert(!stored.includes('smoke goal'), 'raw Goal text leaked into Host sidecar')
}

async function runProfileSmoke(spec, ordinal) {
  if (spec.kind === 'tarball') assertPackedFiles(spec.value)
  const home = await mkdtemp(join(tmpdir(), `dsh-loopx-profile-${ordinal}-`))
  const mockLoopX = join(home, 'loopx-smoke.mjs')
  const statePath = join(home, 'loopx-calls.txt')
  await writeFile(mockLoopX, mockLoopXSource)
  await chmod(mockLoopX, 0o755)
  await writeFile(statePath, '')
  const env = { ...process.env, DSH_HOME: home, LOOPX_BIN: mockLoopX }
  try {
    run(dshBin, ['plugin', '--profile', profileName, 'add', spec.value, '--offline', '--ignore-scripts'], { env })
    const dump = run(dshBin, ['--profile', profileName, '--dump-config'], { env })
    assertInstalledConfig(dump)
    const installed = await realpath(join(home, 'profiles', profileName, 'node_modules', 'dsh-loopx-plugin'))
    await exerciseInstalledPlugin(installed, home, mockLoopX, statePath)
    run(dshBin, ['plugin', '--profile', profileName, 'remove', 'dsh-loopx-plugin'], { env })
    const removed = run(dshBin, ['--profile', profileName, '--dump-config'], { env })
    for (const [id] of bundleRows) assert(!removed.includes(`id: ${id}`), `remove retained ${id}`)
  } finally {
    await rm(home, { recursive: true, force: true })
  }
}

const specs = parseSpecs(process.argv.slice(2))
for (const [index, spec] of specs.entries()) await runProfileSmoke(spec, index + 1)
process.stdout.write(`dsh-loopx profile smoke passed (${specs.map(spec => spec.kind).join(', ')})\n`)
