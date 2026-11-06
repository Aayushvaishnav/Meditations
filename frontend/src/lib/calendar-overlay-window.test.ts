import { describe, expect, it } from "vitest"
import { calendarOverlayWindow, overlayWindowQuery } from "./calendar-overlay-window"
import { calendarRange } from "./calendar-range"

describe("REV-17 bounded overlay windows", () => {
  it("pads a leap year by exactly two days, producing 368 days within the 370-day API limit", () => {
    const window = calendarOverlayWindow(calendarRange(new Date(2024, 5, 15), "year").days)
    expect(window).toEqual({ start: "2023-12-31", end: "2025-01-02" })
    expect((Date.parse(window.end) - Date.parse(window.start)) / 86_400_000).toBe(368)
  })
  it.each([[2026, 2, 8], [2026, 10, 1]])("pads local days across DST boundaries %s/%s/%s", (year, month, day) => {
    expect(calendarOverlayWindow(calendarRange(new Date(year, month, day), "multi-day", 1).days)).toEqual({
      start: month === 2 ? "2026-03-07" : "2026-10-31",
      end: month === 2 ? "2026-03-10" : "2026-11-03",
    })
  })
  it("includes month grid spillover rather than only the nominal month", () => {
    expect(calendarOverlayWindow(calendarRange(new Date(2026, 2, 8), "month").days)).toEqual({ start: "2026-02-22", end: "2026-04-07" })
  })
  it("keeps legacy inventory requests unbounded and rejects an empty visible range", () => {
    expect(overlayWindowQuery()).toBe("")
    expect(overlayWindowQuery({ start: "2026-03-01", end: "2026-04-01" })).toBe("?start=2026-03-01&end=2026-04-01")
    expect(() => calendarOverlayWindow([])).toThrow()
  })
})
