import { describe, expect, it } from "vitest"
import type { CalendarItem } from "./calendar-projection"
import { dayTimeLayout } from "./calendar-time-grid"

function event(id: string, start: string, end: string, kind: "timed" | "floating" | "date" = "timed"): CalendarItem {
  return { id, kind: "imported", editable: false, allDay: kind === "date", timing: kind === "date" ? { kind: "all-day" } : { kind: "timed", clock: start.slice(11) }, placement: "placed", event: { id, source_id: "file", uid: id, summary: id, status: "confirmed", interval: { kind, start, end } } }
}
const day = new Date(2026, 0, 15)
const at = (hour: number) => new Date(2026, 0, 15, hour).toISOString()
const span = (id: string, start: number, end: number) => event(id, at(start), at(end))
const layout = (items: CalendarItem[]) => dayTimeLayout({ day, items })

describe("day time grid", () => {
  it("partitions nesting and overlap chains per connected component; touching is separate", () => {
    const items = [span("a", 8, 12), span("b", 9, 10), span("c", 9, 11), span("d", 11, 13), span("e", 13, 14)]
    const result = layout(items)
    expect(result.intervals.map(({ item, column, columns }) => [item.id, column, columns])).toEqual([["a", 0, 3], ["b", 1, 3], ["c", 2, 3], ["d", 1, 3], ["e", 0, 1]])
    expect(layout([...items].reverse())).toEqual(result)
    expect(items.map(item => item.id)).toEqual(["a", "b", "c", "d", "e"])
  })
  it("clips to calendar midnights and honors exclusive ends", () => {
    const before = new Date(2026, 0, 14, 23).toISOString()
    const after = new Date(2026, 0, 16, 1).toISOString()
    const result = layout([event("both", before, after), event("ends", before, at(0)), event("starts", new Date(2026, 0, 16).toISOString(), after)])
    expect(result.intervals).toHaveLength(1)
    expect(result.intervals[0]).toMatchObject({ startMinute: 0, endMinute: 1440, continuesBefore: true, continuesAfter: true })
  })
  it("uses markers without invented durations and excludes all-day items", () => {
    const external = span("zero", 10, 10)
    const deadline = { ...external, id: "deadline", kind: "deadline", editable: true, task: { deadline: { kind: "timed", at: at(9) } } } as CalendarItem
    const result = layout([external, deadline, event("all", "2026-01-15", "2026-01-16", "date"), span("outside", 24, 24)])
    expect(result.intervals).toEqual([])
    expect(result.markers.map(marker => [marker.item.id, marker.minute])).toEqual([["deadline", 540], ["zero", 600]])
  })
  it("retains floating, reversed, invalid and offset-less external clocks separately", () => {
    const items = [event("floating", "2026-01-15T09:00:00", "2026-01-15T10:00:00", "floating"), span("reversed", 12, 11), event("invalid", "invalid", at(10)), event("zoneless", "2026-01-15T09:00:00", "2026-01-15T10:00:00")]
    expect(layout(items).sourceClock.map(item => item.id)).toEqual(["floating", "invalid", "reversed", "zoneless"])
    expect(layout(items).intervals).toEqual([])
  })
  it("maps instants through spring gaps and retains unsafe fold spans", () => {
    const spring = dayTimeLayout({ day: new Date(2026, 2, 8), items: [event("gap", "2026-03-08T06:30:00Z", "2026-03-08T07:30:00Z")] })
    const fold = dayTimeLayout({ day: new Date(2026, 10, 1), items: [event("fold", "2026-11-01T05:30:00Z", "2026-11-01T06:15:00Z")] })
    if (new Date(2026, 2, 8).getTimezoneOffset() === 300) {
      expect(spring.intervals[0]).toMatchObject({ startMinute: 90, endMinute: 210 })
      expect(fold.intervals).toEqual([])
      expect(fold.sourceClock.map(item => item.id)).toEqual(["fold"])
    } else {
      expect(spring.intervals).toHaveLength(1)
      expect(fold.intervals).toHaveLength(1)
    }
    for (const result of [spring, fold]) for (const interval of result.intervals) expect(interval.endMinute).toBeGreaterThan(interval.startMinute)
  })
})
