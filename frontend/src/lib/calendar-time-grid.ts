import type { CalendarDay, CalendarItem } from "./calendar-projection"
import { parseUTC } from "./date-values"

export type TimeGridInterval = {
  item: CalendarItem
  startMinute: number
  endMinute: number
  column: number
  columns: number
  continuesBefore: boolean
  continuesAfter: boolean
}
export type TimeGridMarker = { item: CalendarItem; minute: number }
export type DayTimeLayout = { intervals: TimeGridInterval[]; markers: TimeGridMarker[]; sourceClock: CalendarItem[] }

const identityOrder = (a: CalendarItem, b: CalendarItem) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0
const minute = (instant: number) => {
  const date = new Date(instant)
  return date.getHours() * 60 + date.getMinutes() + date.getSeconds() / 60 + date.getMilliseconds() / 60000
}

// External timed values require an explicit offset; floating clocks never acquire a zone
function externalInstant(value: string): number {
  return /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? new Date(value).getTime() : NaN
}

export function dayTimeLayout(day: CalendarDay): DayTimeLayout {
  const result: DayTimeLayout = { intervals: [], markers: [], sourceClock: [] }
  const lower = new Date(day.day)
  lower.setHours(0, 0, 0, 0)
  const upper = new Date(lower)
  upper.setDate(upper.getDate() + 1)
  const lo = lower.getTime(), hi = upper.getTime()
  for (const item of day.items) {
    if (item.allDay || item.timing.kind === "all-day") continue
    let start: number, end: number
    if (item.kind === "deadline") {
      start = item.task.deadline.kind === "timed" ? parseUTC(item.task.deadline.at)?.getTime() ?? NaN : NaN
      end = start
    } else if (item.kind === "block") {
      start = item.block.kind === "timed" ? parseUTC(item.block.start_at)?.getTime() ?? NaN : NaN
      end = item.block.kind === "timed" ? parseUTC(item.block.end_at)?.getTime() ?? NaN : NaN
    } else {
      if (item.event.interval.kind === "floating") {
        result.sourceClock.push(item)
        continue
      }
      start = externalInstant(item.event.interval.start)
      end = externalInstant(item.event.interval.end)
    }
    if (![lo, hi, start, end].every(Number.isFinite) || end < start || (start === end && item.kind === "block")) {
      result.sourceClock.push(item)
      continue
    }
    if (start === end) {
      if (start >= lo && start < hi) result.markers.push({ item, minute: minute(start) })
      continue
    }
    if (start >= hi || end <= lo) continue
    const clippedStart = Math.max(start, lo), clippedEnd = Math.min(end, hi)
    const startMinute = minute(clippedStart), endMinute = clippedEnd === hi ? 1440 : minute(clippedEnd)
    // A wall-clock ruler expands spring gaps; fold-crossing spans retain their source clock
    if (endMinute <= startMinute || new Date(clippedEnd - 1).getTimezoneOffset() > new Date(clippedStart).getTimezoneOffset()) {
      result.sourceClock.push(item)
      continue
    }
    result.intervals.push({ item, startMinute, endMinute, column: 0, columns: 1, continuesBefore: start < lo, continuesAfter: end > hi })
  }
  result.intervals.sort((a, b) => a.startMinute - b.startMinute || a.endMinute - b.endMinute || identityOrder(a.item, b.item))
  let component: TimeGridInterval[] = [], ends: number[] = [], componentEnd = -Infinity
  const finish = () => { for (const interval of component) interval.columns = ends.length }
  for (const interval of result.intervals) {
    if (interval.startMinute >= componentEnd) {
      finish()
      component = []
      ends = []
    }
    let column = ends.findIndex(end => end <= interval.startMinute)
    if (column === -1) column = ends.length
    ends[column] = interval.endMinute
    interval.column = column
    component.push(interval)
    componentEnd = Math.max(component.length === 1 ? -Infinity : componentEnd, interval.endMinute)
  }
  finish()
  result.markers.sort((a, b) => a.minute - b.minute || identityOrder(a.item, b.item))
  result.sourceClock.sort(identityOrder)
  return result
}
