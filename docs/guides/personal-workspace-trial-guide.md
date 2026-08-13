# LoopX 个人 Agent 工作区 · 试用手册

一句话：**所有 Goal 和 Agent 收进一个页面，像聊天一样管理它们；所有写操作都走"预览 → 你确认"，Agent 不会背着你改状态。**

## 快速开始

```bash
# 仓库根目录，一条命令起齐 dashboard + status + chat 三个本地服务
bash scripts/dashboard-dev.sh
```

然后打开 http://127.0.0.1:5173/ 。

## 页面长什么样

- **左侧栏**：LoopX 管家入口、Goal 列表（带状态：推进中 / 等你 / 需修复…）、底部的主题开关和 Agent 设置
- **中间频道区**：选定 Goal 后有三个页签 —— Chat（对话时间线）、Tasks（任务看板）、Files（产出文件）
- **右侧抽屉**：点任何卡片/行弹出详情和操作，Esc 或点 × 关闭

## 能做什么

### 1. 管家首页：一眼看到"需要你"的事

不选任何 Goal 时就是管家视图：需要你确认的事项（带"已等待 N 天"）、正在跑的 Run、最近产出。点任何一行直接进对应处理界面。

### 2. 对话式指挥（Chat 页签）

底部输入框直接说人话，LoopX 会识别意图并生成**变更预览**：

- "创建一个 xxx 的 Goal" → goal.create 预览
- "每天推进这个 Goal" → heartbeat.bind 预览
- "标记完成 / 阻塞 / 暂缓某个 todo" → todo.update 预览
- "把这个任务交给 Kimi" → todo.update reassign 预览

预览弹窗里**确认并应用**才真正写入；稍后 / 拒绝 / 取消都不落库。

输入技巧：Enter 发送，**Shift+Enter 换行**；中文输入法选词的回车不会误发。

### 3. 任务看板（Tasks 页签）

四列状态：待确认 / 进行中 / 定时与持续 / 已完成。

- **鼠标悬停"进行中"卡片**：浮出 ✓（直接发起完成预览）和 ⋯（打开详情）
- **点开卡片**进抽屉，操作区分三级：大按钮"标记完成"、"改派给"（下拉选 Agent + 生成预览）、"更多操作"（标记阻塞 / 暂缓 / 创建后续 Todo）

### 4. 多 Agent

右上角下拉切换当前 Agent。内置 Codex、Claude Code（检测到本机 `claude` 即可用）、Claude API / OpenAI API（启动服务时带对应 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` 环境变量点亮）。

接入任何支持 ACP 协议的 CLI（以 Kimi 为例）：

```json
{
  "agent_id": "kimi",
  "display_name": "Kimi",
  "adapter_kind": "acp",
  "transport": "stdio",
  "command": ["/path/to/kimi", "acp"]
}
```

```bash
python3.13 -m loopx.cli chat-endpoint add --config kimi.json   # 添加
python3.13 -m loopx.cli chat-endpoint list                     # 查看
python3.13 -m loopx.cli chat-endpoint remove --agent-id kimi   # 移除
```

自定义 Agent 信任范围是 read_only，写入同样走预览确认。

### 5. 定时与持续任务

快捷按钮"创建定时检查"，或在对话里说"每天检查一次"。生成预览确认后出现在看板"定时与持续"列，可暂停 / 恢复。

### 6. Goal 用量

频道头部副标题会显示该 Goal 的 7 天 token 数和成本（如 `7d 159.3k tokens · $3.17`），Goal 详情抽屉里有 24h/7d 的 tokens、成本、运行时长明细。**还没上报用量的 Goal 不显示**（避免误导性的 0）。

### 7. 主题切换

左下角"野兽主题"开关：默认暖纸风 ↔ slock 式新野兽风（黄侧栏、黑边、硬阴影）。选择会被记住，刷新不丢。

## 五分钟体验路线

1. 打开页面，先看管家首页"需要你"里有没有等你批的事项
2. 点进一个 Goal，在输入框发"我现在该做什么？"
3. 发"创建一个巡检 xxx 的定时任务"，体验预览 → 确认/取消
4. 切到 Tasks 页签，悬停一张卡片点 ✓，看完预览点取消
5. 点卡片进抽屉，试"改派给"换一个 Agent
6. 左下角切到野兽主题，再切回来

## 安全边界

- 所有写操作（建 Goal、改 todo、绑 heartbeat…）都必须经预览弹窗由你确认
- 受保护操作（发布、删除、付款类）有额外的宿主确认门禁
- 页面不展示原始 runtime id、本地路径、凭证等内部细节（"高级诊断"折叠区除外）
