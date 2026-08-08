# LoopX Personal Goal Workspace Design

## Status

- Product surface: personal Goal workspace
- Primary interaction: Chat
- Default Agent: Codex
- Audience: an individual managing personal Goals and delegated Agent work
- Scope: product and interaction contract for the dashboard presentation app

## Product Intent

LoopX should help one person answer four questions with minimal effort:

1. What Goals exist?
2. What needs my attention now?
3. What is each Agent doing?
4. What should happen next?

The daily experience uses one stable workspace: select a Goal on the left and
work with an Agent in Chat on the right. Control-plane internals remain
available through a secondary running-details surface.

## Design Principles

1. **Chat is the workspace.** Goal status, decisions, instructions, and Agent
   progress share one conversation timeline.
2. **User action has the highest priority.** An open user Todo becomes the most
   prominent card. Empty user-Todo sections are hidden.
3. **Show conclusions first.** Translate control-plane fields into current
   progress, required user action, and next step.
4. **Progressive disclosure.** Evidence, event history, quota, raw state, and
   full Todo lists live in running details.
5. **One primary action per state.** The main action is either respond to a
   decision, enter Chat, or inspect an abnormal run.
6. **Agent identity is always visible.** The active Agent appears in the Chat
   header and composer and can be changed before sending a message.
7. **State remains attributable.** Every summary or action keeps a link to its
   source Goal, Todo, run, or finding without exposing raw internals by default.

## Information Architecture

```text
Personal Goal Workspace
├── Manager Chat
│   ├── cross-Goal summary
│   ├── needs-your-attention queue
│   ├── Agent activity summary
│   └── create or redirect work
├── Goal Chat
│   ├── current progress
│   ├── needs you
│   ├── next step
│   ├── conversation
│   └── Agent execution cards
└── Running details
    ├── diagnosis summary
    ├── full Todo projection
    ├── Agent runs
    ├── evidence and timeline
    └── control-plane state
```

There is no separate daily Goal-management dashboard. The former operator
console becomes the secondary running-details surface.

## Desktop Shell

```text
┌────────┬──────────────────────┬──────────────────────────────────────┐
│ Global │ Goals                │ Chat                                 │
│ rail   │                      │                                      │
│        │ ● Launch Chat v1     │ LoopX Manager   Codex ▾   Live      │
│ Chat   │   Needs you          │                                      │
│ Goals  │ ○ Reading plan       │ Conversation and structured cards    │
│        │   In progress        │                                      │
│        │ ○ Health routine     │                                      │
│        │   Quiet              │                                      │
│        │                      │ [Codex ▾] [Current Goal]  Composer   │
│        │ + New Goal           │                                      │
└────────┴──────────────────────┴──────────────────────────────────────┘
```

### Global rail

Keep the rail narrow. The MVP needs only:

- Chat
- Goals
- Settings

History and advanced product areas can arrive later. Goal and Chat selection
remain in the second column.

### Goal list

Each Goal row shows:

- a human-readable Goal title;
- one short status sentence;
- one semantic status: `Needs you`, `In progress`, `Waiting`, `Quiet`,
  `Needs repair`, or `Complete`;
- an optional unread or attention dot.

Raw Goal ids stay available to running details and accessible labels. They do
not lead the visible row.

## Manager Chat

Manager Chat is the default state when no Goal is selected. It summarizes all
active Goals and accepts cross-Goal questions or instructions.

### Empty conversation state

```text
LoopX Manager   Codex ▾   Live

Good morning. You have 2 items to handle, and 3 Agents are working.

[What should I do now?]
[Which Goals are waiting for me?]
[What are the Agents doing?]

Ask about Goals, or assign a task...
```

### Supported interaction classes

- status lookup;
- priority recommendation;
- cross-Goal comparison;
- Goal creation;
- Todo creation or revision;
- Agent assignment;
- pause, resume, archive, or repair requests subject to LoopX authority.

Fast status lookups may use a deterministic local projection. Requests that
need planning, judgment, or execution go to the selected Agent.

## Goal Chat

Selecting a Goal keeps the same shell and binds the conversation to that
Goal's context.

### Header

```text
Launch Chat v1
Codex · In progress 2/4 · 1 item needs you          Goal progress
```

The header compresses the selected Goal's interaction contract into one line:
active Agent, projected Agent-Todo progress, and open user-Todo count. The
`Goal progress` action opens running details. Repository, quota, boundary, and
raw runtime metadata stay out of the first screen.

### Projection timeline

Goal Chat renders durable LoopX projections as structured timeline cards. It
does not invent prior user messages or treat transient Chat text as completed
work.

```text
Codex

Plan progress                                               2/4
✓ Inspect the concurrent refresh path
✓ Update the refresh implementation
● Run regression tests
○ Prepare the change for review

Recent run
Regression evidence is available                            View details

Needs you
Confirm whether the validated change may continue     [Later] [Respond]
```

Rules:

- The plan card is built from the selected Goal's structured `agent_todos`.
- Completed and open Todo rows preserve their source `todo_id`.
- When a user action exists, limit the first-screen plan preview to three rows
  so the complete needs-you card remains visible at compact desktop heights.
- The user-action card is built from an open `user_todo` or an explicit
  operator gate. Hide it when no user action exists.
- The recent-run card uses compact `run_history` or event-ledger evidence.
- Each visible sentence stays public-safe and traceable to its source Goal,
  Todo, run, or event summary.
- Raw classifications, commands, file paths, and logs remain in running
  details.

### Conversation timeline

The timeline supports six item types:

1. user message;
2. Agent response;
3. user-action card;
4. Agent Todo plan card;
5. Agent execution card;
6. run-evidence card.

Example execution card:

```text
Codex is working
Connecting discovered Agents and preserving Codex as the default

In progress                                      View details
```

The execution card shows a compact state and latest meaningful progress. Full
logs stay in running details.

### User-action card

```text
Needs you
Confirm the updated first screen

[Approve] [Tell the Agent what to change]
```

Rules:

- Render only open user Todos or explicit authority gates.
- Use the Todo's exact decision scope for actions.
- Preserve reject and cancel paths when the underlying contract supports them.
- Confirm material writes or protected actions before execution.

## Agent Discovery And Selection

The Chat header and composer expose the active Agent through a compact
selector. New conversations select Codex when Codex is available.

```text
Choose Agent

✓ Codex           Default · code and project execution
  Claude Code     Complex analysis and long tasks
  Trae CLI Agent  Frontend and interaction implementation
  Coco Agent      General tasks
  Status only     No model call

  Manage discovered Agents
```

### Agent list contract

Each discovered Agent row should provide:

- stable Agent id;
- display name;
- provider and model label when available;
- availability state;
- short capability summary;
- supported permission boundary;
- workspace or repository compatibility when relevant.

### Selection behavior

- Default to Codex for a new Chat.
- Persist the selected Agent per Chat.
- Allow switching before the next message.
- Keep earlier messages attributed to the Agent that produced them.
- Explain unavailable Agents and suggest an eligible alternative.
- Do not silently transfer a running execution to another Agent.
- Treat `Status only` as a deterministic read-only route.

## Chat Execution And Todo Decisions

The selected Chat route and the durable Todo owner remain separate fields:

- the Agent selector routes the next message;
- `claimed_by` identifies the Agent that owns an existing Todo;
- changing the selector does not rewrite `claimed_by`;
- the projection author always uses durable Todo ownership;
- the Chat header and composer use the currently selected route.

The MVP connects Codex through the local LoopX Chat server with a read-only
sandbox and `never` approval policy. `Status only` stays local and makes no
model call. A discovered Agent without a compatible Chat adapter remains
visible with a clear unavailable explanation and a Codex fallback.

When the selected Agent suggests new work, Chat adds a compact candidate card
to the timeline:

```text
P1  Candidate Todo                         Launch Chat v1
Run the focused Todo writeback smoke

[Generate preview] [Reject] [Cancel]
```

The write path is deliberately two-stage:

1. `Generate preview` calls the LoopX dry-run endpoint and locks the Goal
   revision plus candidate identity.
2. `Approve write` applies that exact preview and returns a Todo id and receipt.
3. `Reject` and `Cancel` create local decision history only and perform zero
   Goal writes.
4. A stale preview returns a no-write receipt, clears the preview, and asks the
   user to preview again.

Candidate prose never counts as a durable Todo. Only a verified apply receipt
and refreshed status projection establish that the Todo exists.

## Simplified Goal Detail

The optional compact detail view contains four sections:

1. Manager summary
2. Needs you
3. Agent current work
4. Recent activity

```text
← My Goals

Launch Chat v1                                  In progress

Manager summary
Codex is validating Todo writeback. A PR follows successful validation.

Needs you                                                       1
Confirm the updated first screen                  [Approve] [Give feedback]

Agent current work
Codex · Running   Validate local Todo writeback              [Enter Chat]

Recent activity                                                View all
```

This view can be reached from a Goal row or shared as a compact status page.
Its primary action always returns to Chat.

## Running Details

Running details serve diagnosis and audit use cases. The entry stays quiet
while a Goal is healthy and becomes a visible `View cause` action when LoopX
reports an abnormal condition.

### First screen

The first screen starts with a diagnosis, not a data inventory:

```text
Running diagnosis

Issue       Goal state has not refreshed recently
Impact      Work may continue, but visible progress can be stale
Suggestion  Refresh LoopX state
Owner       LoopX automatic repair

[Repair now]
```

### Expandable technical sections

- full user and Agent Todo lists;
- Agent run history;
- evidence and validation receipts;
- state transition timeline;
- registry and status-source health;
- quota and execution-boundary details;
- public-safe raw projection.

The technical sections remain collapsed until requested.

## LoopX Projection Mapping

| LoopX projection | User-facing surface |
| --- | --- |
| Goal directory / run-history Goal | Goal list and selected Goal context |
| Goal objective and boundary | Goal identity; boundary stays in running details |
| Structured `user_todos` | Needs-you card and exact response scope |
| Structured `agent_todos` | Plan progress card and current work |
| Todo `claimed_by` | Agent ownership attribution |
| Latest run / event-ledger summary | Recent-run and evidence cards |
| `interaction_contract.user_channel` | Whether the user-action card is visible |
| `interaction_contract.agent_channel` | Whether the Goal reads as in progress or quiet |
| `interaction_contract.cli_channel` | Available transitions in running details |
| Recommended action | Compact next-step copy when no structured Todo is available |
| Waiting-on state | Goal semantic status |
| Agent-management projection | Discovered-Agent selector and activity attribution |
| Registry finding / stale warning | Needs-repair state and View-cause action |
| Evidence and event ledger | Running details |
| Quota and execution contract | Running details and action availability |

Presentation code must consume public-safe projection fields. It must not parse
private planning files, raw logs, local absolute paths, or provider payloads.

## Business Object Contract

The workspace is a read model over five durable LoopX concepts:

```text
Goal
├── objective and goal_boundary
├── user_todos
├── agent_todos
├── registered or discovered Agents
└── runs and evidence events

interaction_contract = who acts next
Goal Chat = public-safe presentation of that contract and its evidence
```

The presentation layer follows these rules:

1. A Goal is the durable container. Chat selection only changes the active
   view and does not mutate Goal truth.
2. A Todo is the work unit. A visual plan row must map to a structured Todo or
   be clearly labeled as an unavailable projection.
3. An Agent is an execution identity. Agent selection routes the next message
   or newly created work; it does not silently transfer an existing claim.
4. A run or event is evidence that work happened. Chat prose alone cannot mark
   a Todo complete.
5. The interaction contract decides whether the next transition belongs to
   the user, Agent, or LoopX CLI.
6. Running details preserve source lineage and expose the technical contract
   without making it first-screen content.

### Visible status derivation

| Visible state | Durable signal |
| --- | --- |
| Needs repair | High-severity registry finding, stale projection, or failed health state |
| Needs you | Open user Todo or user-channel action requirement |
| Waiting | External-evidence or monitor wait |
| In progress | Runnable or claimed Agent Todo, or agent-channel work obligation |
| Complete | Terminal Goal state with no open work |
| Quiet | No user action and no current Agent work obligation |

Only the highest-priority state appears in the Goal list. Secondary state and
evidence remain available in the selected Goal timeline and running details.

## State Priority

When several states apply to one Goal, use this visible priority:

1. Needs repair
2. Needs you
3. Waiting for an external condition
4. In progress
5. Complete
6. Quiet

Only the highest-priority state appears in the Goal list. Additional context
remains available in the Goal summary or running details.

## Responsive Behavior

### Tablet

- Collapse the global rail to icons.
- Keep the Goal list as a resizable column.
- Preserve the full Chat composer.

### Mobile

- Show either the Goal list or Chat.
- Use a back action to return from Chat to Goals.
- Open the Agent selector as a bottom sheet.
- Keep user-action buttons reachable without horizontal scrolling.
- Open running details as a full-screen sheet.

## Accessibility

- Support keyboard navigation for Goal and Agent lists.
- Expose Agent availability and Goal state as text, not color alone.
- Move focus into dialogs and restore it when they close.
- Announce new Agent messages and state changes through a polite live region.
- Keep touch targets at least 44 by 44 CSS pixels on mobile.
- Respect reduced-motion preferences.

## MVP Scope

The first implementation should include:

- two-column Goal and Chat workspace plus narrow global rail;
- Manager Chat and Goal Chat contexts;
- discovered-Agent selector with Codex default;
- deterministic `Status only` route;
- compact header status derived from current Todo ownership;
- Agent-Todo plan card with progress and source lineage;
- user-action card derived from a user Todo or explicit gate;
- recent-run evidence card derived from public-safe run history;
- compact running-details entry;
- responsive desktop and mobile layouts;
- public-safe LoopX status projection.

The MVP does not need:

- collaboration or shared ownership;
- analytics charts;
- a visual workflow builder;
- arbitrary raw-log rendering;
- automatic mid-run Agent transfer;
- a standalone daily management dashboard.

## Acceptance Criteria

1. A user can identify the next required action within five seconds.
2. A user can see which Agent owns the current work without opening details.
3. New Chats use Codex when it is available.
4. A user can switch to another discovered Agent before sending a message.
5. Selecting a Goal opens its Chat without navigating to the operator console.
6. A Goal with no user action does not render an empty user-Todo panel.
7. A Goal with an open user action exposes one clear primary response.
8. Healthy Goals do not expose quota, evidence, or raw state on the first
   screen.
9. Abnormal Goals expose a concise cause, impact, suggested action, and owner.
10. Every summary and action remains traceable to a public-safe LoopX
    projection.
11. Plan progress never relies on fabricated Chat history.
12. A run card distinguishes recorded evidence from a planned Todo.

## Chosen Defaults

- Show active Goals in the left column; completed Goals live behind a filter.
- Save Agent selection per Chat.
- Use Codex as the default Agent.
- Keep Manager Chat as the initial workspace.
- Keep Goal detail and running details secondary to Chat.
- Keep advanced control-plane data collapsed.
