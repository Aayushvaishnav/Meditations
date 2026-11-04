import type { CalendarMode } from "@/stores/ui"

export function addCalendarDays(date: Date, days: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days)
}

export function mondayOf(date: Date): Date {
  return addCalendarDays(date, -((date.getDay() + 6) % 7))
}

export function calendarMonthDays(anchor: Date): Date[] {
  const start = mondayOf(new Date(anchor.getFullYear(), anchor.getMonth(), 1))
  const last = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0)
  const end = addCalendarDays(mondayOf(last), 7)
  const days: Date[] = []
  for (let day = start; day < end; day = addCalendarDays(day, 1)) days.push(day)
  return days
}

export function calendarRange(anchor: Date, mode: CalendarMode, dayCount = 3, weekCount = 2) {
  const month = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
  let start = addCalendarDays(anchor, 0)
  let end: Date
  switch (mode) {
    case "month": start = month; end = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1); break
    case "year": start = new Date(anchor.getFullYear(), 0, 1); end = new Date(anchor.getFullYear() + 1, 0, 1); break
    case "week": start = mondayOf(anchor); end = addCalendarDays(start, 7); break
    case "multi-week": start = mondayOf(anchor); end = addCalendarDays(start, weekCount * 7); break
    case "multi-day": end = addCalendarDays(start, dayCount); break
    case "agenda": end = addCalendarDays(start, 14); break
  }
  const gridStart = mode === "month" ? mondayOf(month) : start
  const gridEnd = mode === "month" ? addCalendarDays(gridStart, 42) : end
  const days: Date[] = []
  for (let day = gridStart; day < gridEnd; day = addCalendarDays(day, 1)) days.push(day)
  return { start, end, days }
}

export function navigateCalendar(anchor: Date, mode: CalendarMode, direction: number, dayCount = 3, weekCount = 2): Date {
  if (mode === "month" || mode === "year") {
    const month = anchor.getMonth() + (mode === "year" ? 12 : 1) * direction
    const last = new Date(anchor.getFullYear(), month + 1, 0).getDate()
    return new Date(anchor.getFullYear(), month, Math.min(anchor.getDate(), last))
  }
  return addCalendarDays(anchor, direction * (mode === "week" ? 7 : mode === "multi-day" ? dayCount : mode === "multi-week" ? weekCount * 7 : 14))
}
