import { Check, MoreHorizontal } from "lucide-react";

import type {
  WorkspaceDrawerSelection,
  WorkspaceGoal,
  WorkspaceModel,
  WorkspaceTimelineItem,
} from "./personal-workspace-model";
import { attentionAgeLabel } from "./personal-workspace-model";

/**
 * Goal Tasks tab: one kanban surface that merges owner decisions ("待确认")
 * with Agent work, scheduled monitors, and completed items — mirroring the
 * board insight that confirmation is a task state, not a separate list.
 * Columns are states; cards open the same typed-preview drawer as the chat.
 */
export function GoalTasksView({
  goal,
  items,
  onQuickComplete,
  onSelect,
  userTodos,
}: {
  goal: WorkspaceGoal;
  items: WorkspaceTimelineItem[];
  onQuickComplete?: (todo: WorkspaceGoal["agentTodos"][number] & { goalId: string; goalTitle: string; ownerLabel: string }) => void;
  onSelect: (selection: WorkspaceDrawerSelection) => void;
  userTodos: WorkspaceModel["userTodos"];
}) {
  const attentionItems = userTodos
    .filter((todo) => todo.goalId === goal.goalId)
    .map((todo) => ({ ...todo, goalTitle: goal.title }));
  const openAgentTodos = goal.agentTodos.filter((todo) => todo.taskClass !== "continuous_monitor" && !todo.done);
  const doneAgentTodos = goal.agentTodos.filter((todo) => todo.taskClass !== "continuous_monitor" && todo.done);
  const scheduleItems = items.filter((item): item is Extract<WorkspaceTimelineItem, { kind: "schedule" }> => item.kind === "schedule");
  const isEmpty = !attentionItems.length && !openAgentTodos.length && !doneAgentTodos.length && !scheduleItems.length;

  return (
    <div className="personal-task-kanban">
      <section className="personal-object-list">
        <header>
          <strong><i className="personal-kanban-dot tone-attention" />待确认</strong>
          <span>{attentionItems.length}</span>
        </header>
        {attentionItems.map((attention) => {
          const age = attentionAgeLabel(attention.updatedAt);
          return (
            <button key={attention.todoId} onClick={() => onSelect({ item: attention, kind: "attention" })} type="button">
              <span className="is-attention">!</span>
              <strong>{attention.text}</strong>
              <small>
                <span className={`personal-row-status ${attention.blocking ? "is-blocking" : "is-pending"}`}>{attention.blocking ? "阻塞" : "待处理"}</span>
                {age ? <span className="personal-task-age">已等待 {age}</span> : null}
              </small>
            </button>
          );
        })}
        {!attentionItems.length ? <p className="personal-task-empty">没有待确认的任务。</p> : null}
      </section>
      <section className="personal-object-list">
        <header>
          <strong><i className="personal-kanban-dot tone-progress" />进行中</strong>
          <span>{openAgentTodos.length}</span>
        </header>
        {openAgentTodos.map((todo) => {
          const enriched = { ...todo, goalId: goal.goalId, goalTitle: goal.title, ownerLabel: todo.claimedBy ?? goal.agentLabel ?? goal.agentId };
          return (
            <div className="personal-task-card" key={todo.todoId}>
              <button onClick={() => onSelect({ item: enriched, kind: "todo" })} type="button">
                <span>○</span><strong>{todo.text}</strong><small>{todo.claimedBy ?? goal.agentLabel ?? goal.agentId}</small>
              </button>
              <div className="personal-task-card-actions">
                <button aria-label={`标记完成：${todo.text}`} onClick={() => onQuickComplete?.(enriched)} title="标记完成" type="button"><Check size={14} /></button>
                <button aria-label={`更多操作：${todo.text}`} onClick={() => onSelect({ item: enriched, kind: "todo" })} title="更多操作" type="button"><MoreHorizontal size={14} /></button>
              </div>
            </div>
          );
        })}
        {!openAgentTodos.length ? <p className="personal-task-empty">没有进行中的任务。</p> : null}
      </section>
      <section className="personal-object-list">
        <header>
          <strong><i className="personal-kanban-dot tone-schedule" />定时与持续</strong>
          <span>{scheduleItems.length}</span>
        </header>
        {scheduleItems.map((item) => (
          <button key={item.id} onClick={() => onSelect({ item: item.schedule, kind: "schedule" })} type="button">
            <span>◷</span><strong>{item.schedule.label}</strong><small>{item.schedule.status === "paused" ? "已暂停" : "运行中"}</small>
          </button>
        ))}
        {!scheduleItems.length ? <p className="personal-task-empty">没有定时任务。</p> : null}
      </section>
      <section className="personal-object-list">
        <header>
          <strong><i className="personal-kanban-dot tone-done" />已完成</strong>
          <span>{doneAgentTodos.length}</span>
        </header>
        {doneAgentTodos.map((todo) => (
          <button key={todo.todoId} onClick={() => onSelect({ item: { ...todo, goalId: goal.goalId, goalTitle: goal.title, ownerLabel: todo.claimedBy ?? goal.agentLabel ?? goal.agentId }, kind: "todo" })} type="button">
            <span className="is-done">✓</span><strong>{todo.text}</strong><small>{todo.claimedBy ?? goal.agentLabel ?? goal.agentId}</small>
          </button>
        ))}
        {!doneAgentTodos.length ? <p className="personal-task-empty">还没有完成的任务。</p> : null}
      </section>
      {isEmpty ? (
        <p className="personal-task-empty" style={{ gridColumn: "1 / -1", border: 0, textAlign: "left" }}>
          这个 Goal 还没有任务。用下面的输入框描述下一步，LoopX 会生成预览。
        </p>
      ) : null}
    </div>
  );
}
