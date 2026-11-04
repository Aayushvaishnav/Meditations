import { describe, expect, it } from "vitest"
import type { Task, TimeBlock } from "@/api/types"
import type { ImportedOverlayItem } from "@/api/calendar-overlay-types"
import type { InboundOverlayItem } from "@/api/calendar-inbound-types"
import { projectCalendar } from "./calendar-projection"
import { calendarRange } from "./calendar-range"

const task: Task = { id: "t", title: "Task", description: null, list_id: null, parent_id: null, priority: 0, status: "todo", due_date: null, deadline: { kind: "date", date: "2026-03-08" }, estimated_minutes: null, actual_minutes: 0, recurrence_rule: null, recurrence_series_id: null, recurrence_occurrence: null, tags: [], order_index: 0, completed_at: null, created_at: "2026-03-01", updated_at: "2026-03-01" }
const block: TimeBlock = { id: "b", task_id: "t", kind: "all_day", start_date: "2026-03-08", end_date: "2026-03-10", start_at: null, end_at: null, timezone: null, created_at: "2026-03-01", updated_at: "2026-03-01" }
const imported: ImportedOverlayItem = { id: "same", source_id: "file", uid: "uid", summary: "Floating", status: "confirmed", interval: { kind: "floating", start: "2026-03-08T09:00:00", end: "2026-03-08T10:00:00" } }
const live: InboundOverlayItem = { id: "same", connection_id: "remote", uid: "uid", summary: "Live", status: "confirmed", interval: { kind: "date", start: "2026-03-08", end: "2026-03-09" } }

describe("calendar item projection", () => {
  it("preserves kinds, identity, permissions and original source clocks", () => {
    const [{ items }] = projectCalendar([new Date(2026, 2, 8)], [task], [block], [imported], [live])
    expect(items.map(item => item.kind).sort()).toEqual(["block", "deadline", "imported", "live"])
    expect(new Set(items.map(item => item.id)).size).toBe(4)
    expect(items.find(item => item.kind === "imported")).toMatchObject({ event: imported, editable: false, allDay: false, timing: { kind: "timed", clock: "09:00:00" } })
    expect(items.find(item => item.kind === "block")).toMatchObject({ task, block, editable: true })
  })
  it("honors exclusive all-day ends and omits undated tasks and orphan blocks", () => {
    const days = [new Date(2026, 2, 8), new Date(2026, 2, 9), new Date(2026, 2, 10)]
    const result = projectCalendar(days, [{ ...task, deadline: { kind: "none" } }], [block, { ...block, id: "orphan", task_id: "missing" }], [], [live])
    expect(result.map(day => day.items.map(item => item.kind))).toEqual([["block", "live"], ["block"], []])
  })
  it("orders timed rows deterministically and keeps all-day rows separate", () => {
    const timed = { ...task, id: "timed", deadline: { kind: "timed" as const, at: new Date(2026, 2, 8, 8).toISOString() } }
    const result = projectCalendar([new Date(2026, 2, 8)], [timed, task], [], [imported], [])
    expect(result[0].items.map(item => item.kind)).toEqual(["deadline", "deadline", "imported"])
    expect(result[0].items[0].allDay).toBe(true)
    expect(projectCalendar([new Date(2026, 2, 8)], [task, timed], [], [imported], [])).toEqual(result)
  })
  it("agrees between Month and Agenda on overlapping dates", () => {
    const anchor = new Date(2026, 2, 8)
    const month = projectCalendar(calendarRange(anchor, "month").days, [task], [block], [imported], [live])
    const agenda = projectCalendar(calendarRange(anchor, "agenda").days, [task], [block], [imported], [live])
    for (const day of agenda) expect(month.find(candidate => candidate.day.getTime() === day.day.getTime())).toEqual(day)
  })
})
