import type { TimeBlock, TimeBlockInput } from "@/api/types"
import { parseUTC } from "./date-values"
import { calendarDayDistance, localDayParam } from "./task-deadlines"

export function blockOnDay(block: TimeBlock, day: Date): boolean {
  const label = localDayParam(day)
  if (block.kind === "all_day") return block.start_date <= label && label < block.end_date
  const start = new Date(day)
  start.setHours(0, 0, 0, 0)
  const end = new Date(start)
  end.setDate(end.getDate() + 1)
  return parseUTC(block.start_at)!.getTime() < end.getTime() && parseUTC(block.end_at)!.getTime() > start.getTime()
}

export function blockStartDay(block: TimeBlock): string {
  return block.kind === "all_day" ? block.start_date : localDayParam(parseUTC(block.start_at)!)
}

export function moveTimeBlock(block: TimeBlock, target: string): TimeBlockInput {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(target)) throw new Error("Choose a valid calendar date.")
  const civil = new Date(`${target}T00:00:00Z`)
  if (!Number.isFinite(civil.getTime()) || civil.toISOString().slice(0, 10) !== target || target < "0001-01-01") {
    throw new Error("Choose a valid calendar date.")
  }
  if (block.kind === "all_day") {
    civil.setUTCDate(civil.getUTCDate() + calendarDayDistance(block.start_date, block.end_date))
    if (civil.getUTCFullYear() > 9999) throw new Error("The block would end outside the supported date range.")
    return { kind: "all_day", task_id: block.task_id, start_date: target, end_date: civil.toISOString().slice(0, 10) }
  }
  const start = parseUTC(block.start_at)!
  const moved = new Date(start)
  const [year, month, day] = target.split("-").map(Number)
  moved.setFullYear(year, month - 1, day)
  if (localDayParam(moved) !== target || moved.getHours() !== start.getHours() || moved.getMinutes() !== start.getMinutes()) {
    throw new Error("That local time does not exist on the selected date. Choose another date.")
  }
  const end = new Date(moved.getTime() + parseUTC(block.end_at)!.getTime() - start.getTime())
  if ([moved, end].some(value => !Number.isFinite(value.getTime()) || value.getUTCFullYear() < 1 || value.getUTCFullYear() > 9999)) {
    throw new Error("The block would fall outside the supported date range.")
  }
  return { kind: "timed", task_id: block.task_id, timezone: block.timezone, start_at: moved.toISOString(), end_at: end.toISOString() }
}

export function blockTimeLabel(block: TimeBlock): string {
  if (block.kind === "all_day") return "All day"
  const options: Intl.DateTimeFormatOptions = { hour: "numeric", minute: "2-digit" }
  const start = parseUTC(block.start_at)!
  const end = parseUTC(block.end_at)!
  const endLabel = localDayParam(start) === localDayParam(end)
    ? end.toLocaleTimeString(undefined, options)
    : end.toLocaleString(undefined, { month: "short", day: "numeric", ...options })
  return `${start.toLocaleTimeString(undefined, options)} – ${endLabel}`
}

export function shiftBlockStart(block: TimeBlock, fromDay: string, toDay: string): string {
  const date = new Date(`${blockStartDay(block)}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + calendarDayDistance(fromDay, toDay))
  if (date.getUTCFullYear() < 1 || date.getUTCFullYear() > 9999) throw new Error("The block would fall outside the supported date range.")
  return date.toISOString().slice(0, 10)
}
