const unsupportedCalendarSchedule = /(每周|星期|周[一二三四五六日天]|\d{1,2}\s*[：:]\s*\d{2}|\d{1,2}\s*点(?:\s*\d{1,2}\s*分)?)/u;

export function unsupportedCalendarScheduleReason(message: string) {
  if (unsupportedCalendarSchedule.test(message)) {
    return "当前定时检查不支持精确到星期或时刻的日历计划。请改用固定间隔，例如“每 30 分钟”“每 2 小时”或“每天”；草稿已保留，没有生成待确认操作。";
  }
  return null;
}
