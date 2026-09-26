import { object } from "./usage_statistics_contract.ts";

export const GOAL_SCHEMA = "loopx_goal_usage_aggregate_v1";
export const GOAL_DURATIONS = ["lt_1m", "lt_10m", "lt_1h", "lt_6h", "lt_1d", "lt_7d", "lt_30d", "gte_30d"] as const;
export type GoalDuration = typeof GOAL_DURATIONS[number];
export type GoalCount = { span: GoalDuration; execution: GoalDuration; count: number };
export type GoalAggregate = { schema: typeof GOAL_SCHEMA; counters: GoalCount[] };
export type GoalObservation = { key: string; start: number; end: number };
const DAY = 86400000;
export function goalDuration(ms: number): GoalDuration {
  const limits = [60000, 600000, 3600000, 21600000, DAY, 7 * DAY, 30 * DAY];
  return GOAL_DURATIONS[limits.findIndex(limit => ms < limit)] ?? "gte_30d";
}
export function validGoalAggregate(value: unknown): value is GoalAggregate {
  if (!object(value) || Object.keys(value).sort().join() !== "counters,schema" || value.schema !== GOAL_SCHEMA
    || !Array.isArray(value.counters) || !value.counters.length || value.counters.length > 64) return false;
  const keys = new Set<string>();
  return value.counters.every(row => {
    if (!object(row) || Object.keys(row).sort().join() !== "count,execution,span"
      || !(GOAL_DURATIONS as readonly unknown[]).includes(row.span) || !(GOAL_DURATIONS as readonly unknown[]).includes(row.execution)
      || !Number.isInteger(row.count) || Number(row.count) < 1 || Number(row.count) > 128) return false;
    const key = `${row.span}:${row.execution}`;
    if (keys.has(key)) return false;
    keys.add(key); return true;
  });
}
export function validGoalObservation(value: unknown, now: number): value is GoalObservation {
  return object(value) && Object.keys(value).sort().join() === "end,key,start"
    && typeof value.key === "string" && /^[a-f0-9]{64}$/.test(value.key)
    && Number.isSafeInteger(value.start) && Number.isSafeInteger(value.end)
    && Number(value.start) > 0 && Number(value.start) <= Number(value.end)
    && Number(value.end) <= now + 1000 && Number(value.end) >= now - DAY
    && Number(value.end) - Number(value.start) <= 120000;
}
