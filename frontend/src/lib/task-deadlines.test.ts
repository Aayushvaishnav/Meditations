import { afterEach, describe, expect, it, vi } from "vitest"
import type { Task, TaskDeadline } from "@/api/types"
import { groupOf, sortTasks } from "./dates"
import { calendarDayDistance, deadlineCalendarDate, deadlineCutoff, deadlineDayKey, deadlineFromLegacy, formatDeadline, localDayParam, moveDeadline } from "./task-deadlines"

afterEach(() => vi.useRealTimers())
const day = (date: string): TaskDeadline => ({ kind: "date", date })
const timed = (at: string): TaskDeadline => ({ kind: "timed", at })
const task = (deadline: TaskDeadline, order_index = 0): Task => ({
  id: "task", title: "Task", list_id: null, parent_id: null, description: null,
  priority: 0, importance: "unassigned", urgency: "unassigned", status: "todo", deadline, due_date: null, estimated_minutes: null,
  actual_minutes: 0, recurrence_rule: null, recurrence_series_id: null, recurrence_occurrence: null,
  tags: [], order_index, completed_at: null, created_at: "2026-01-01T00:00:00", updated_at: "2026-01-01T00:00:00",
})

describe("deadline domain", () => {
  it("preserves local labels and parses timed UTC without inferring kind from 09:00", () => {
    expect(localDayParam(new Date(2026, 9, 14, 23))).toBe("2026-10-14")
    expect(deadlineCalendarDate(day("2026-10-14"))).toEqual(new Date(2026, 9, 14))
    expect(deadlineDayKey(day("2026-10-14"))).toBe("2026-10-14")
    const legacy = "2026-10-14T09:00:00"
    expect(deadlineFromLegacy(legacy)).toEqual(timed(legacy))
    expect(deadlineCalendarDate(timed(legacy))?.toISOString()).toBe(`${legacy}.000Z`)
    expect(deadlineDayKey(timed(legacy))).toBe(localDayParam(new Date(`${legacy}Z`)))
    expect(deadlineFromLegacy(null)).toEqual({ kind: "none" })
  })

  it.each(["2026-03-08", "2026-11-01", "2026-10-14", "2018-11-04"])("expires %s only at the next local midnight, including DST", (label) => {
    const [year, month, date] = label.split("-").map(Number)
    const next = new Date(year, month - 1, date + 1)
    const cutoff = deadlineCutoff(day(label))!
    expect(cutoff).toBe(next.getTime() - 1)
    expect(cutoff < next.getTime() - 1).toBe(false)
    expect(cutoff < next.getTime()).toBe(true)
  })

  it("keeps timed cutoffs exact and none explicitly absent", () => {
    expect(deadlineCutoff(timed("2026-10-14T09:00:12.345+05:30"))).toBe(Date.parse("2026-10-14T03:30:12.345Z"))
    const none: TaskDeadline = { kind: "none" }
    expect(deadlineCalendarDate(none)).toBeNull()
    expect(deadlineDayKey(none)).toBeNull()
    expect(deadlineCutoff(none)).toBeNull()
    expect(formatDeadline(none)).toBe("")
    expect(moveDeadline(none, new Date())).toEqual(none)
  })

  it("moves labels and preserves local time precision using Date DST resolution", () => {
    const original = new Date(2026, 2, 7, 2, 30, 12, 345)
    const target = new Date(2026, 2, 8)
    const expected = new Date(original)
    expected.setFullYear(2026, 2, 8)
    expect(moveDeadline(timed(original.toISOString()), target)).toEqual(timed(expected.toISOString()))
    expect(moveDeadline(day("2026-10-14"), target)).toEqual(day("2026-03-08"))
    expect(original).toEqual(new Date(2026, 2, 7, 2, 30, 12, 345))
  })

  it("formats date-only days without a synthetic time", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 9, 14, 16))
    expect(formatDeadline(day("2026-10-14"))).toBe("Today")
    expect(formatDeadline(day("2026-10-15"))).toBe("Tomorrow")
    expect(formatDeadline(day("2027-02-10"))).toBe(new Date(2027, 1, 10).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }))
    expect(formatDeadline(timed(new Date(2026, 9, 14, 9).toISOString()))).toContain(new Date(2026, 9, 14, 9).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }))
  })

  it("groups labels by calendar day and sorts them before same-day timed tasks", () => {
    const date = task(day("2026-10-14"), 99)
    const instant = task(timed(new Date(2026, 9, 14).toISOString()))
    const tomorrow = task(day("2026-10-15"))
    const none = task({ kind: "none" })
    expect(groupOf(date, new Date(2026, 9, 14, 23))).toBe("today")
    expect(groupOf(date, new Date(2026, 9, 15))).toBe("overdue")
    expect([none, tomorrow, instant, date].sort(sortTasks)).toEqual([date, instant, tomorrow, none])
    expect(sortTasks(date, { ...date })).toBe(0)
  })
})

it("preserves calendar labels even when a timezone skipped that entire local date", () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date(2026, 10, 2, 12))
  const deadline = day("2011-12-30")
  expect(deadlineDayKey(deadline)).toBe("2011-12-30")
  expect(formatDeadline(deadline)).toBe(new Date("2011-12-30T00:00:00Z").toLocaleDateString(undefined, {
    timeZone: "UTC", month: "short", day: "numeric", year: "numeric",
  }))
  expect(groupOf(task(deadline), new Date(2011, 11, 29, 12))).toBe("tomorrow")
  expect(deadlineCutoff(deadline)).toBe(new Date(2011, 11, 31).getTime() - 1)
})

it("groups and sorts valid boundary-year instants even when the local year exceeds four digits", () => {
  const at = "9999-12-31T23:00:00Z"
  const latest = task(timed(at))
  const earlier = task(timed("9999-12-30T23:00:00Z"))
  expect(groupOf(latest, new Date(at))).toBe("today")
  expect([latest, earlier].sort(sortTasks)).toEqual([earlier, latest])
  expect(calendarDayDistance("0001-01-01", "0001-01-02")).toBe(1)
})
