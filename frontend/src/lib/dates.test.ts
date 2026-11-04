import { deadlineFromLegacy } from "./task-deadlines"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { Task } from "@/api/types"
import {
  daysBetween, formatDue, formatDuration, GROUP_ORDER, groupOf,
  isSameLocalDay, parseUTC, sortTasks, startOfDay, toISO,
} from "./dates"

function task(overrides: Partial<Task> = {}): Task {
  return {
    id: "task", title: "Task", list_id: null, parent_id: null, description: null,
    priority: 0, importance: "unassigned", urgency: "unassigned", status: "todo", due_date: null, estimated_minutes: null,
    actual_minutes: 0, recurrence_rule: null, recurrence_series_id: null,
    recurrence_occurrence: null, tags: [], order_index: 0, completed_at: null,
    created_at: "2026-01-01T00:00:00", updated_at: "2026-01-01T00:00:00",
    deadline: deadlineFromLegacy(overrides.due_date ?? null), ...overrides,
  }
}

afterEach(() => vi.useRealTimers())

describe("UTC transport", () => {
  it.each([
    "2026-10-14T12:34:56.123", "2026-10-14T12:34:56.123Z",
    "2026-10-14T18:04:56.123+05:30", "2026-10-14T08:34:56.123-0400",
  ])("parses %s as the same UTC instant", (input) => {
    expect(parseUTC(input)?.toISOString()).toBe("2026-10-14T12:34:56.123Z")
  })

  it.each([null, undefined, "", "not-a-date", "2026-13-40T25:00:00"])(
    "rejects absent or invalid input %s", (input) => expect(parseUTC(input)).toBeNull(),
  )

  it("serializes local dates as ISO UTC instants without losing precision", () => {
    const date = new Date(2026, 9, 14, 9, 30, 12, 345)
    expect(toISO(date)).toBe(date.toISOString())
    expect(toISO(date)).toMatch(/Z$/)
    expect(parseUTC(toISO(date))).toEqual(date)
  })
})

describe("local calendar arithmetic", () => {
  it("finds local midnight without mutating the input", () => {
    const date = new Date(2026, 9, 14, 23, 59, 59, 999)
    const original = date.getTime()
    expect(startOfDay(date)).toEqual(new Date(2026, 9, 14))
    expect(date.getTime()).toBe(original)
    expect(isSameLocalDay(date, new Date(2026, 9, 14))).toBe(true)
    expect(isSameLocalDay(date, new Date(2026, 9, 15))).toBe(false)
    expect(isSameLocalDay(date, new Date(2025, 9, 14))).toBe(false)
  })

  it("counts calendar boundaries rather than elapsed partial days", () => {
    const before = new Date(2026, 11, 31, 23, 59)
    const after = new Date(2027, 0, 1, 0, 1)
    expect(daysBetween(before, after)).toBe(1)
    expect(daysBetween(after, before)).toBe(-1)
    expect(daysBetween(before, new Date(2026, 11, 31))).toBe(0)
  })

  it.each([[2, 8], [10, 1]])("handles the DST boundary at month %i day %i", (month, day) => {
    const before = new Date(2026, month, day)
    const after = new Date(2026, month, day + 1)
    const offsetChange = after.getTimezoneOffset() - before.getTimezoneOffset()
    expect(after.getTime() - before.getTime()).toBe(86_400_000 + offsetChange * 60_000)
    expect(daysBetween(before, after)).toBe(1)
    expect(daysBetween(after, before)).toBe(-1)
    expect(startOfDay(new Date(2026, month, day, 23))).toEqual(before)
    expect(groupOf(task({ due_date: toISO(after) }), before)).toBe("tomorrow")
    expect(groupOf(task({ due_date: toISO(before) }), after)).toBe("overdue")
  })
})

describe("task date groups", () => {
  const now = new Date(2026, 9, 14, 12)
  it.each([
    [new Date(2026, 9, 13, 23, 59), "overdue"],
    [new Date(2026, 9, 14), "today"],
    [new Date(2026, 9, 14, 23, 59), "today"],
    [new Date(2026, 9, 15), "tomorrow"],
    [new Date(2026, 9, 16), "upcoming"],
  ] as const)("groups local due instant %s as %s", (due, group) => {
    expect(groupOf(task({ due_date: toISO(due) }), now)).toBe(group)
  })

  it("uses the clock default and prioritizes completion over due dates", () => {
    vi.useFakeTimers()
    vi.setSystemTime(now)
    expect(groupOf(task({ due_date: toISO(now) }))).toBe("today")
    expect(groupOf(task({ status: "completed", due_date: "invalid" }))).toBe("completed")
    expect(groupOf(task())).toBe("nodate")
    expect(groupOf(task({ due_date: "invalid" }))).toBe("nodate")
    expect(GROUP_ORDER).toEqual(["overdue", "today", "tomorrow", "upcoming", "nodate", "completed"])
  })
})

describe("due labels", () => {
  it.each([
    [2026, 9, 13, "Yesterday"], [2026, 9, 14, "Today"], [2026, 9, 15, "Tomorrow"],
    [2026, 9, 16, "weekday"], [2026, 9, 20, "weekday"],
    [2026, 9, 21, "date"], [2026, 9, 12, "date"], [2027, 0, 1, "year"],
  ] as const)("classifies %i/%i/%i as %s", (year, month, day, classification) => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 9, 14, 23, 59))
    const due = new Date(year, month, day, 9, 5)
    const time = due.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
    const label = ["Today", "Tomorrow", "Yesterday"].includes(classification)
      ? classification
      : due.toLocaleDateString(undefined, {
        weekday: classification === "weekday" ? "short" : undefined,
        month: "short", day: "numeric", year: classification === "year" ? "numeric" : undefined,
      })
    expect(formatDue(due)).toBe(`${label} ${time}`)
  })
})

describe("duration and ordering", () => {
  it.each([[0, "0m"], [1, "1m"], [59, "59m"], [60, "1h"], [61, "1h 1m"], [120, "2h"], [150, "2h 30m"]] as const)(
    "formats %i minutes", (minutes, expected) => expect(formatDuration(minutes)).toBe(expected),
  )

  it("sorts due instants, manual order, then creation with undated tasks last", () => {
    const earlier = task({ id: "earlier", due_date: "2026-10-14T08:00:00", order_index: 99 })
    const createdFirst = task({ id: "created-first", due_date: "2026-10-14T15:00:00+05:30", order_index: 1 })
    const createdLast = task({ ...createdFirst, id: "created-last", created_at: "2026-02-01T00:00:00" })
    const manualLast = task({ ...createdFirst, id: "manual-last", order_index: 2 })
    const undatedFirst = task({ id: "undated-first", order_index: 0 })
    const undatedLast = task({ id: "undated-last", order_index: 1 })
    expect([undatedLast, manualLast, createdLast, earlier, undatedFirst, createdFirst].sort(sortTasks).map((t) => t.id))
      .toEqual(["earlier", "created-first", "created-last", "manual-last", "undated-first", "undated-last"])
    expect(sortTasks(createdFirst, { ...createdFirst })).toBe(0)
  })
})
