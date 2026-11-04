import { describe, expect, it } from "vitest"
import { addCalendarDays, calendarMonthDays, calendarRange, navigateCalendar } from "./calendar-range"
import { localDayParam } from "./task-deadlines"

describe("calendar ranges", () => {
  it.each([new Date(2026, 1, 1), new Date(2024, 1, 29), new Date(2026, 11, 31)])("keeps a six-week Monday-start month grid for %s", anchor => {
    const range = calendarRange(anchor, "month")
    expect(range.days).toHaveLength(42)
    expect(range.days[0].getDay()).toBe(1)
    expect(localDayParam(range.start)).toBe(localDayParam(new Date(anchor.getFullYear(), anchor.getMonth(), 1)))
    expect(range.end.getDate()).toBe(1)
    expect(range.days.every((day, index) => localDayParam(day) === localDayParam(addCalendarDays(range.days[0], index)))).toBe(true)
  })
  it("preserves local dates over a DST boundary and a year boundary", () => {
    for (const anchor of [new Date(2026, 2, 7, 18), new Date(2026, 11, 28, 18)]) {
      const range = calendarRange(anchor, "agenda")
      expect(range.days).toHaveLength(14)
      expect(range.days.every(day => day.getHours() === 0)).toBe(true)
      expect(localDayParam(navigateCalendar(anchor, "agenda", 1))).toBe(localDayParam(range.end))
    }
  })
  it("clamps month navigation without normalizing the anchor on mode switches", () => {
    const anchor = new Date(2024, 0, 31)
    expect(localDayParam(navigateCalendar(anchor, "month", 1))).toBe("2024-02-29")
    expect(localDayParam(calendarRange(anchor, "agenda").start)).toBe("2024-01-31")
    expect(localDayParam(anchor)).toBe("2024-01-31")
  })
  it("defines remaining mode windows independently", () => {
    const anchor = new Date(2024, 1, 29)
    expect(calendarRange(anchor, "week").days).toHaveLength(7)
    expect(calendarRange(anchor, "multi-day").days).toHaveLength(3)
    expect(calendarRange(anchor, "multi-week").days).toHaveLength(14)
    expect(calendarRange(anchor, "year").days).toHaveLength(366)
  })
})


describe("time-grid calendar navigation", () => {
  it.each([2, 3, 4, 5, 6, 7])("advances a %i-day window by calendar dates across DST and year boundaries", count => {
    for (const anchor of [new Date(2026, 2, 7, 18), new Date(2026, 9, 31), new Date(2026, 11, 30)]) {
      const range = calendarRange(anchor, "multi-day", count)
      expect(range.days).toHaveLength(count)
      expect(localDayParam(navigateCalendar(anchor, "multi-day", 1, count))).toBe(localDayParam(range.end))
      expect(localDayParam(navigateCalendar(anchor, "multi-day", -1, count))).toBe(localDayParam(addCalendarDays(anchor, -count)))
      expect(range.days.every(day => day.getHours() === 0)).toBe(true)
    }
  })
  it("keeps Week Monday-start through New Year and a DST change", () => {
    expect(localDayParam(calendarRange(new Date(2027, 0, 1), "week").start)).toBe("2026-12-28")
    expect(localDayParam(calendarRange(new Date(2026, 2, 8), "week").end)).toBe("2026-03-09")
    expect(localDayParam(navigateCalendar(new Date(2026, 2, 7), "week", 1))).toBe("2026-03-14")
  })
})


describe("configurable multi-week ranges", () => {
  it.each([2, 3, 4, 5, 6])("spans and navigates %i complete local weeks", weekCount => {
    for (const anchor of [new Date(2024, 1, 29, 18), new Date(2026, 2, 7, 18), new Date(2026, 9, 31, 18), new Date(2026, 11, 31, 18)]) {
      const range = calendarRange(anchor, "multi-week", 3, weekCount)
      expect(range.start.getDay()).toBe(1)
      expect(range.days).toHaveLength(weekCount * 7)
      expect(localDayParam(range.end)).toBe(localDayParam(addCalendarDays(range.start, weekCount * 7)))
      for (const [index, day] of range.days.entries()) {
        expect(localDayParam(day)).toBe(localDayParam(addCalendarDays(range.start, index)))
        expect([day.getHours(), day.getMinutes(), day.getSeconds(), day.getMilliseconds()]).toEqual([0, 0, 0, 0])
      }
      for (const direction of [-1, 1]) {
        const next = navigateCalendar(anchor, "multi-week", direction, 3, weekCount)
        expect(localDayParam(next)).toBe(localDayParam(addCalendarDays(anchor, direction * weekCount * 7)))
        expect(localDayParam(calendarRange(next, "multi-week", 3, weekCount).start)).toBe(
          localDayParam(addCalendarDays(range.start, direction * weekCount * 7)),
        )
      }
    }
  })
})

describe("actual month grids", () => {
  it.each([
    [2021, 1, 28, "2021-02-01", "2021-02-28"],
    [2024, 1, 35, "2024-01-29", "2024-03-03"],
    [2026, 2, 42, "2026-02-23", "2026-04-05"],
    [2026, 10, 42, "2026-10-26", "2026-12-06"],
    [2026, 11, 35, "2026-11-30", "2027-01-03"],
  ] as const)("uses only complete necessary weeks for %i/%i", (year, month, count, first, last) => {
    const anchor = new Date(year, month, 15, 18)
    const days = calendarMonthDays(anchor)
    expect(days).toHaveLength(count)
    expect(localDayParam(days[0])).toBe(first)
    expect(localDayParam(days.at(-1)!)).toBe(last)
    expect(days[0].getDay()).toBe(1)
    expect(days.at(-1)!.getDay()).toBe(0)
    expect(days.filter(day => day.getMonth() === month)).toHaveLength(new Date(year, month + 1, 0).getDate())
    expect(days.every((day, index) => day.getHours() === 0 && localDayParam(day) === localDayParam(addCalendarDays(days[0], index)))).toBe(true)
  })

  it("navigates months and years across December/January in both directions", () => {
    expect(localDayParam(navigateCalendar(new Date(2026, 11, 31), "month", 1))).toBe("2027-01-31")
    expect(localDayParam(navigateCalendar(new Date(2027, 0, 31), "month", -1))).toBe("2026-12-31")
    expect(localDayParam(navigateCalendar(new Date(2024, 1, 29), "year", 1))).toBe("2025-02-28")
  })
})
