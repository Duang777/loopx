import { selectLatestResumableChatSession } from "../src/data/chat-session-selection.js";

function assertEqual(actual: unknown, expected: unknown, message: string) {
  if (actual !== expected) throw new Error(`${message}: expected ${String(expected)}, got ${String(actual)}`);
}

const selected = selectLatestResumableChatSession([
  { session_id: "failed-newer", resumable: false },
  { session_id: "ready-older", resumable: true },
]);

assertEqual(
  selected?.session_id,
  "ready-older",
  "Session discovery ignores a newer failed Session",
);
assertEqual(
  selectLatestResumableChatSession([
    { session_id: "failed-only", resumable: false },
  ]),
  null,
  "Session discovery does not reinterpret a failed Session as resumable",
);
