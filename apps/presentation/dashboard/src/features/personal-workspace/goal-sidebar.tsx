import { Bell, Bot, ChevronRight, CircleUserRound, Clock3, FileCheck2, ListChecks, Palette, Plus, Settings2 } from "lucide-react";

import type { WorkspaceChannel, WorkspaceGoal } from "./personal-workspace-model";

const goalStateClass: Record<WorkspaceGoal["state"], string> = {
  "需修复": "is-danger",
  "等你": "is-warning",
  "等待条件": "is-info",
  "推进中": "is-success",
  "安静运行": "is-quiet",
  "已完成": "is-quiet",
};

export function GoalSidebar({
  attentionCount,
  activeRunCount,
  goals,
  onRequestGoalCreate,
  onOpenNotifications,
  onOpenSettings,
  onSelectChannel,
  onSelectGoal,
  onToggleTheme,
  ownerLabel = "个人工作区",
  recentOutputCount,
  selectedChannel,
  selectedGoalId,
  theme = "paper",
}: {
  attentionCount: number;
  activeRunCount: number;
  goals: WorkspaceGoal[];
  onRequestGoalCreate?: () => void;
  onOpenNotifications?: () => void;
  onOpenSettings: () => void;
  onSelectChannel: (channel: WorkspaceChannel) => void;
  onSelectGoal: (goalId: string | null) => void;
  onToggleTheme?: () => void;
  ownerLabel?: string;
  recentOutputCount: number;
  selectedChannel: WorkspaceChannel;
  selectedGoalId: string | null;
  theme?: "brutal" | "paper";
}) {
  return (
    <div className="personal-goal-directory">
      <div className="personal-sidebar-brand">
        <span className="personal-brand-mark"><Bot size={18} /></span>
        <span><strong>LoopX</strong><small>个人 Agent 工作区</small></span>
      </div>

      <nav aria-label="工作区频道" className="personal-sidebar-nav">
        <button
          aria-current={selectedGoalId === null ? "page" : undefined}
          className="personal-manager-link"
          onClick={() => onSelectGoal(null)}
          type="button"
        >
          <span className="personal-manager-icon"><Bot size={17} /></span>
          <span>LoopX 管家</span>
          {attentionCount > 0 ? <span className="personal-sidebar-count">{attentionCount}</span> : null}
          <ChevronRight size={15} />
        </button>

        <div className="personal-manager-channels">
          <button aria-current={selectedGoalId === null && selectedChannel === "attention" ? "page" : undefined} onClick={() => onSelectChannel("attention")} type="button">
            <ListChecks size={16} /><span>需要你</span><small>{attentionCount}</small>
          </button>
          <button aria-current={selectedGoalId === null && selectedChannel === "running" ? "page" : undefined} onClick={() => onSelectChannel("running")} type="button">
            <Clock3 size={16} /><span>执行中</span><small>{activeRunCount}</small>
          </button>
          <button aria-current={selectedGoalId === null && selectedChannel === "outputs" ? "page" : undefined} onClick={() => onSelectChannel("outputs")} type="button">
            <FileCheck2 size={16} /><span>产出</span><small>{recentOutputCount}</small>
          </button>
        </div>

        <div className="personal-sidebar-section-title">
          <span>Goals</span>
          <span className="personal-sidebar-title-actions"><small>{goals.length}</small><button aria-label="创建 Goal" onClick={onRequestGoalCreate} type="button"><Plus size={15} /></button></span>
        </div>
        <div className="personal-goal-list">
          {goals.map((goal) => (
            <button
              aria-current={selectedGoalId === goal.goalId ? "page" : undefined}
              className="personal-goal-link"
              key={goal.goalId}
              onClick={() => onSelectGoal(goal.goalId)}
              type="button"
            >
              <span className={`personal-goal-state-dot ${goalStateClass[goal.state]}`} />
              <span className="personal-goal-link-copy">
                <strong>{goal.title}</strong>
                <small>{goal.state}{goal.needsYou ? " · 需要你" : ""}</small>
              </span>
              <ChevronRight size={15} />
            </button>
          ))}
        </div>
      </nav>

      <div className="personal-sidebar-footer">
        {onToggleTheme ? (
          <button aria-pressed={theme === "brutal"} className="personal-sidebar-utility" onClick={onToggleTheme} type="button"><Palette size={17} /><span>{theme === "brutal" ? "默认主题" : "野兽主题"}</span></button>
        ) : null}
        <button className="personal-sidebar-utility" onClick={onOpenSettings} type="button"><Settings2 size={17} /><span>Agent 设置</span></button>
        {onOpenNotifications ? (
          <button className="personal-sidebar-utility" onClick={onOpenNotifications} type="button"><Bell size={17} /><span>通知设置</span></button>
        ) : null}
        <div className="personal-owner-row"><CircleUserRound size={22} /><span>{ownerLabel}</span></div>
      </div>
    </div>
  );
}
