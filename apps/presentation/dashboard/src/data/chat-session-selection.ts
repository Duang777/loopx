export type ResumableChatSession = {
  resumable: boolean;
};

export function selectLatestResumableChatSession<T extends ResumableChatSession>(
  sessions: readonly T[],
): T | null {
  return sessions.find((session) => session.resumable) ?? null;
}
