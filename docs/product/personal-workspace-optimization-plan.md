# 个人 Agent 工作区 · 优化计划

目标场景（来自胡的反馈）：**睡前下指令，醒来收摘要，修一修继续跑**。页面管四样：审批、目标、限额、配置。

## 第一梯队：首页与看板体验（纯前端，本批实施）

1. **晨间摘要卡**——管家首页顶部"你不在的时候"：自上次访问以来 完成 X / 异常 Y / 等你确认 Z，点击跳转对应区域。数据：run_history + attention_queue；上次访问时间存 localStorage。
2. **Agent 全景卡**——管家首页增加执行体卡片：状态、当前任务、所属 Goal。数据：`agent_management_projection`（现成的）。
3. **会话状态提示**——Goal 频道输入区上方一行："Codex 正在执行 N 个任务 · 你的消息作为纠偏进入本会话"，消除"发消息会不会抢任务"的疑虑。
4. **看板优先级**——进行中卡片显示 P0/P1 徽章，列内按优先级排序。
5. **首页降噪**——"原 Agent Session 无法恢复"等技术行改人话文案。

## 第二梯队：需后端配合（后续 PR）

6. **干活线执行记录可见**——后端把执行进程事件流脱敏投影进 status（步级粒度："读取 2 个文件 · 运行 8 条命令 · 1 个失败"）；前端 Run 抽屉加"执行过程"折叠区。守住边界：原始日志/路径/凭证不上页面。
7. **限额管理**——Goal 抽屉加限额区（用量 vs 上限），后端补 quota 配置 action。#3159 已铺用量展示。
8. **配置可写**——Agent 设置加端点启用/停用（registry 已有 `enabled` 字段），走预览确认。
9. **飞书通知配置**（2026-08-13 调查结论）——发送链路已就绪：`loopx goal-channel setup/attach/configure/notify-gate`，经 lark-cli 子进程发消息，挂在 refresh-state 的 human-gate 自动通知上，带幂等回执。**缺口**：绑定状态（`.loopx/goal-channel.json`）没有投影进 status.json，且没有 typed action 能写配置。接入路径：
   - 后端新增 public-safe 投影：每 Goal 的 `enabled` / `human_gate_auto_notify_enabled` / 最近回执时间 / doctor 阻塞原因（`chat_id`、`bot_app_id`、`message_id` 等私有字段一律不进投影，见 `goal_channel_contracts.py` 的 `assert_public_packet` 约定）
   - 新增 typed action `goal_channel.configure`，apply 路由到 `configure_lark_goal_channel_automation`（只写 automation 开关，不外呼）
   - 前端 Goal 抽屉加"飞书通知"区：状态 + 开关（走预览确认）；首次绑定（建群/绑群）仍走 CLI，页面只做引导


## 第三梯队：工程健康

9. **main → 集成分支同步**——约 40 commit 落差，含 CORS / 路径校验 / shell 注入三个安全修复。
10. **纠偏已读回执**——纠偏消息标记"已被第 N 轮执行读取"。缓做。

## 在途 PR

- #3159 Goal 用量展示（tokens/成本/时长）
- #3160 试用手册 + FAQ

## 长线（不排期）

- 多 Agent 自动领活：Kimi/Claude 目前是对话伙伴，自动执行仍是 Codex。
- Agent 关系图：等有多 agent 协作（handoff）数据后再做，当前星型拓扑用卡片即可。
