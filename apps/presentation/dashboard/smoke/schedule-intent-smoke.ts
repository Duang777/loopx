import { unsupportedCalendarScheduleReason } from "../src/data/schedule-intent.js";

function assert(condition: boolean, message: string) {
  if (!condition) throw new Error(message);
}

assert(
  unsupportedCalendarScheduleReason("每天上午 9 点检查一次") !== null,
  "Chinese wall-clock schedules must fail closed",
);
assert(
  unsupportedCalendarScheduleReason("每天 09:00 检查一次") !== null,
  "Colon wall-clock schedules must fail closed",
);
assert(
  unsupportedCalendarScheduleReason("每 2 小时检查一次") === null,
  "Supported fixed intervals remain eligible for preview",
);
