// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { CalendarDay } from "@/lib/calendar-projection"
import { calendarRange } from "@/lib/calendar-range"
import { CalendarYear } from "./year"

beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date(2024, 1, 29, 12)) })
afterEach(() => { cleanup(); vi.useRealTimers() })
const emptyYear = (anchor: Date): CalendarDay[] => calendarRange(anchor, "year").days.map(day => ({ day, items: [] }))

describe("annual calendar", () => {
  it.each([2023, 2024])("shows every real date once in %i, with twelve month drill-downs", year => {
    const anchor = new Date(year, 1, 15)
    const onMonth = vi.fn()
    render(<CalendarYear days={emptyYear(anchor)} anchor={anchor} onOpen={vi.fn()} onMonth={onMonth} />)
    expect(screen.getAllByRole("button", { name: /^\d{4}-\d{2}-\d{2},/ })).toHaveLength(year === 2024 ? 366 : 365)
    expect(screen.getAllByRole("button", { name: / in Month$/ })).toHaveLength(12)
    fireEvent.click(screen.getByRole("button", { name: `Open December ${year} in Month` }))
    expect(onMonth).toHaveBeenCalledExactlyOnceWith(new Date(year, 11, 1))
  })

  it("exposes today, selection, exact zero counts and keyboard day drill-down without drag handles", () => {
    const anchor = new Date(2024, 1, 29)
    const onOpen = vi.fn()
    render(<CalendarYear days={emptyYear(anchor)} anchor={anchor} onOpen={onOpen} onMonth={vi.fn()} />)
    const february = within(screen.getByRole("region", { name: "February 2024" }))
    const today = february.getByRole("button", { name: /^2024-02-29, 0 items:/ })
    expect(today.getAttribute("aria-current")).toBe("date")
    expect(today.getAttribute("aria-pressed")).toBe("true")
    expect(february.getAllByRole("button").filter(button => button.tabIndex === 0)).toHaveLength(2)
    today.focus()
    fireEvent.keyDown(today, { key: "ArrowUp" })
    const previous = february.getByRole("button", { name: /^2024-02-22,/ })
    expect(document.activeElement).toBe(previous)
    fireEvent.keyDown(previous, { key: "ArrowLeft" })
    expect(document.activeElement).toBe(february.getByRole("button", { name: /^2024-02-21,/ }))
    fireEvent.click(document.activeElement!)
    expect(onOpen).toHaveBeenCalledExactlyOnceWith(new Date(2024, 1, 21))
    expect(today.getAttribute("aria-roledescription")).toBeNull()
  })

  it("keeps boundary arrow movement within the month instead of losing focus", () => {
    const anchor = new Date(2024, 0, 1)
    render(<CalendarYear days={emptyYear(anchor)} anchor={anchor} onOpen={vi.fn()} onMonth={vi.fn()} />)
    const first = screen.getByRole("button", { name: /^2024-01-01,/ })
    first.focus()
    fireEvent.keyDown(first, { key: "ArrowLeft" })
    expect(document.activeElement).toBe(first)
    fireEvent.keyDown(first, { key: "ArrowDown" })
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /^2024-01-08,/ }))
  })
})
