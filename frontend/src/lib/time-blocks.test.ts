import { describe, expect, it } from "vitest"
import type { TimeBlock } from "@/api/types"
import { blockOnDay, blockStartDay, moveTimeBlock, shiftBlockStart } from "./time-blocks"

const base = { id: "b", task_id: "t", created_at: "2026-01-01T00:00:00", updated_at: "2026-01-01T00:00:00" }
function timed(start: Date, end: Date): TimeBlock {
  return { ...base, kind: "timed", timezone: "Asia/Kolkata", start_at: start.toISOString().slice(0, -1), end_at: end.toISOString().slice(0, -1), start_date: null, end_date: null }
}
const allDay: TimeBlock = { ...base, kind: "all_day", start_date: "2026-03-07", end_date: "2026-03-10", timezone: null, start_at: null, end_at: null }

describe("calendar work block semantics", () => {
  it("uses date labels and exclusive ends for all-day intervals", () => {
    expect(blockOnDay(allDay, new Date(2026, 2, 6))).toBe(false)
    expect(blockOnDay(allDay, new Date(2026, 2, 7))).toBe(true)
    expect(blockOnDay(allDay, new Date(2026, 2, 9))).toBe(true)
    expect(blockOnDay(allDay, new Date(2026, 2, 10))).toBe(false)
    expect(moveTimeBlock(allDay, "2026-12-30")).toEqual({ kind: "all_day", task_id: "t", start_date: "2026-12-30", end_date: "2027-01-02" })
  })

  it("shows overnight blocks on each overlapping local day, excluding midnight end", () => {
    const block = timed(new Date(2026, 2, 7, 23), new Date(2026, 2, 9))
    expect(blockOnDay(block, new Date(2026, 2, 6))).toBe(false)
    expect(blockOnDay(block, new Date(2026, 2, 7))).toBe(true)
    expect(blockOnDay(block, new Date(2026, 2, 8))).toBe(true)
    expect(blockOnDay(block, new Date(2026, 2, 9))).toBe(false)
  })

  it("moves timed blocks with displayed clock, precise elapsed duration and saved zone intact", () => {
    const block = timed(new Date(2026, 2, 7, 9, 15, 42, 123), new Date(2026, 2, 7, 11, 25, 43, 456))
    const result = moveTimeBlock(block, "2026-03-08")
    expect(result.kind).toBe("timed")
    if (result.kind !== "timed") throw new Error("Expected timed input")
    expect(result.start_at).toBe(new Date(2026, 2, 8, 9, 15, 42, 123).toISOString())
    expect(new Date(result.end_at).getTime() - new Date(result.start_at).getTime()).toBe(7_801_333)
    expect(result.timezone).toBe("Asia/Kolkata")
    expect(result.task_id).toBe("t")
  })

  it("shifts continuation chips by the dragged-day delta", () => {
    expect(shiftBlockStart(allDay, "2026-03-09", "2026-03-12")).toBe("2026-03-10")
    const block = timed(new Date(2026, 2, 7, 23), new Date(2026, 2, 9))
    expect(blockStartDay(block)).toBe("2026-03-07")
    expect(shiftBlockStart(block, "2026-03-08", "2026-03-09")).toBe("2026-03-08")
  })

  it.each(["", "2026-02-30", "2026-13-01", "0000-01-01", "10000-01-01", "invalid"])("rejects invalid target %j", target => {
    expect(() => moveTimeBlock(allDay, target)).toThrow()
  })

  it("rejects overflow of interval ends and continuation moves", () => {
    expect(() => moveTimeBlock(allDay, "9999-12-30")).toThrow()
    expect(() => shiftBlockStart(allDay, "2026-03-08", "0001-01-01")).toThrow()
    const block = timed(new Date("9999-12-29T12:00:00Z"), new Date("9999-12-31T12:00:00Z"))
    expect(() => moveTimeBlock(block, "9999-12-31")).toThrow()
  })

  it("rejects nonexistent displayed times instead of silently shifting the clock", () => {
    // New York's spring transition supplies a concrete gap in the timezone matrix
    if (Intl.DateTimeFormat().resolvedOptions().timeZone !== "America/New_York") return
    const block = timed(new Date(2026, 2, 7, 2, 30), new Date(2026, 2, 7, 3, 30))
    expect(() => moveTimeBlock(block, "2026-03-08")).toThrow(/does not exist/)
  })

  it("uses the earlier occurrence of a repeated displayed time", () => {
    if (Intl.DateTimeFormat().resolvedOptions().timeZone !== "America/New_York") return
    const block = timed(new Date(2026, 9, 31, 1, 30), new Date(2026, 9, 31, 2, 30))
    const result = moveTimeBlock(block, "2026-11-01")
    expect(result.kind === "timed" && result.start_at).toBe("2026-11-01T05:30:00.000Z")
  })
})
