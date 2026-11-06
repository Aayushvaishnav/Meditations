import { addCalendarDays } from "./calendar-range"
import { localDayParam } from "./task-deadlines"

export interface CalendarOverlayWindow {
  start: string
  end: string
}

export function calendarOverlayWindow(days: Date[]): CalendarOverlayWindow {
  if (days.length === 0) throw new Error("An overlay requires visible calendar days")
  // UTC date bounds include local days at every supported timezone offset
  return { start: localDayParam(addCalendarDays(days[0], -1)), end: localDayParam(addCalendarDays(days[days.length - 1], 2)) }
}

export function overlayWindowQuery(window?: CalendarOverlayWindow): string {
  return window ? `?${new URLSearchParams({ start: window.start, end: window.end })}` : ""
}
