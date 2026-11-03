import { describe, expect, it } from "vitest"
import type { ImportedOverlayItem } from "@/api/calendar-overlay-types"
import { importedEventLabel, importedEventOnDay } from "./calendar-overlay"

function event(kind: ImportedOverlayItem["interval"]["kind"], start: string, end = start): ImportedOverlayItem {
  return { id: "event", source_id: "source", uid: "uid", summary: "Appointment", status: "CONFIRMED", interval: { kind, start, end } }
}
const day = (n: number) => new Date(2026, 2, n, 12)

describe("imported appointment calendar dates", () => {
  it("uses local calendar labels for all-day multi-day exclusive ends", () => {
    const item = event("date", "2026-03-07", "2026-03-10")
    expect([6, 7, 8, 9, 10].map(n => importedEventOnDay(item, day(n)))).toEqual([false, true, true, true, false])
    expect(importedEventLabel(item)).toContain("2026-03-10 (end exclusive)")
  })
  it("keeps floating DST-gap labels without normalizing nonexistent clock times", () => {
    const item = event("floating", "2026-03-08T02:15:00", "2026-03-08T02:45:00")
    expect(importedEventOnDay(item, day(8))).toBe(true)
    expect(importedEventOnDay(item, day(9))).toBe(false)
    expect(importedEventLabel(item)).toBe("2026-03-08 02:15:00 to 2026-03-08 02:45:00 (floating local time)")
  })
  it("handles floating midnight exclusive ends and point events", () => {
    const span = event("floating", "2026-03-07T23:00:00", "2026-03-09T00:00:00")
    expect([7, 8, 9].map(n => importedEventOnDay(span, day(n)))).toEqual([true, true, false])
    const point = event("floating", "2026-03-09T00:00:00")
    expect([8, 9].map(n => importedEventOnDay(point, day(n)))).toEqual([false, true])
  })
  it("intersects timed instants with local midnight boundaries, including exact points", () => {
    const midnight = new Date(2026, 2, 9).toISOString()
    const start = new Date(2026, 2, 7, 23).toISOString()
    const span = event("timed", start, midnight)
    expect([6, 7, 8, 9].map(n => importedEventOnDay(span, day(n)))).toEqual([false, true, true, false])
    const point = event("timed", midnight)
    expect([8, 9, 10].map(n => importedEventOnDay(point, day(n)))).toEqual([false, true, false])
  })
})
