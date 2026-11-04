// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { Task, TimeBlock } from "@/api/types"
import type { ImportedOverlayItem } from "@/api/calendar-overlay-types"
import { projectCalendar } from "@/lib/calendar-projection"
import { CalendarTimeGrid } from "./time-grid"

const day = new Date(2026, 2, 7)
function task(id: string, at?: string): Task {
  return { id, title: id, deadline: at ? { kind: "timed", at } : { kind: "date", date: "2026-03-07" } } as Task
}
function block(id: string, start: number, end: number): TimeBlock {
  return { id, task_id: "Planning", kind: "timed", start_at: new Date(2026, 2, 7, start).toISOString(), end_at: new Date(2026, 2, 7, end).toISOString(), timezone: "UTC" } as TimeBlock
}
const external = (id: string, kind: "date" | "floating" | "timed", start: string, end: string): ImportedOverlayItem => ({ id, source_id: "file", uid: id, summary: id, status: "CONFIRMED", interval: { kind, start, end } })
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date(2026, 2, 7, 12)) })
afterEach(() => { cleanup(); vi.useRealTimers() })

describe("calendar time grid", () => {
  it("separates all-day items, deadline flags and actual interval buttons with access to details", () => {
    const onOpen = vi.fn()
    const tasks = [task("Planning", new Date(2026, 2, 7, 10).toISOString()), task("Date only")]
    const items = [external("Conference", "date", "2026-03-07", "2026-03-08")]
    render(<CalendarTimeGrid days={projectCalendar([day], tasks, [block("a", 9, 11), block("b", 10, 12)], items, [])} onOpen={onOpen} />)
    const allDay = within(screen.getByRole("region", { name: "All-day items" }))
    expect(allDay.getByRole("button", { name: /Date only, Task deadline, All day/ })).toBeTruthy()
    expect(allDay.getByRole("button", { name: /Conference, Imported event · read-only/ })).toBeTruthy()
    const timed = within(screen.getByRole("region", { name: "2026-03-07" }))
    expect(timed.getByRole("button", { name: /Planning, Task deadline, Due 10:00/ })).toBeTruthy()
    const blocks = timed.getAllByRole("button", { name: /Planning, Work block/ })
    expect(blocks).toHaveLength(2)
    for (const button of blocks) {
      button.focus()
      expect(document.activeElement).toBe(button)
      fireEvent.click(button)
    }
    expect(onOpen).toHaveBeenCalledTimes(2)
    expect(onOpen).toHaveBeenLastCalledWith(day)
  })

  it("keeps floating source labels separate and external details reachable without edit affordances", () => {
    const onOpen = vi.fn()
    render(<CalendarTimeGrid days={projectCalendar([day], [], [], [external("Floating meeting", "floating", "2026-03-07T09:00:00", "2026-03-07T10:00:00")], [])} onOpen={onOpen} />)
    const source = within(screen.getByRole("region", { name: "Source-clock and interval details" }))
    expect(source.getByText(/2026-03-07 09:00:00 to 2026-03-07 10:00:00 \(floating local time\)/)).toBeTruthy()
    fireEvent.click(source.getByRole("button", { name: /Floating meeting, Imported event · read-only/ }))
    expect(onOpen).toHaveBeenCalledExactlyOnceWith(day)
    expect(screen.queryByRole("textbox")).toBeNull()
    expect(screen.queryByRole("button", { name: /Move/ })).toBeNull()
  })

  it("exposes short and midnight-spanning items through complete daily details", () => {
    const onOpen = vi.fn()
    const overnight = block("overnight", -1, 1)
    const short = { ...block("short", 9, 10), end_at: new Date(2026, 2, 7, 9, 1).toISOString() } as TimeBlock
    render(<CalendarTimeGrid days={projectCalendar([day], [task("Planning")], [overnight, short], [], [])} onOpen={onOpen} />)
    expect(screen.getByRole("button", { name: /continues from previous day/ })).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "3 items · Details" }))
    expect(onOpen).toHaveBeenCalledWith(day)
  })

  it("updates the current-time indicator and removes its timer on unmount", () => {
    const view = render(<CalendarTimeGrid days={[{ day, items: [] }]} onOpen={() => {}} />)
    expect(screen.getByRole("img", { name: /Current time/ })).toBeTruthy()
    const initial = screen.getByRole("img").getAttribute("aria-label")
    act(() => vi.advanceTimersByTime(60_000))
    expect(screen.getByRole("img").getAttribute("aria-label")).not.toBe(initial)
    expect(vi.getTimerCount()).toBe(1)
    view.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it("provides a keyboard-focusable scoped scroll region and discoverable empty-day creation", () => {
    const onOpen = vi.fn()
    render(<CalendarTimeGrid days={[{ day, items: [] }]} onOpen={onOpen} />)
    expect(screen.getByRole("status")).toBeTruthy()
    const scroller = screen.getByRole("region", { name: /Calendar time grid/ })
    scroller.focus()
    expect(document.activeElement).toBe(scroller)
    fireEvent.click(screen.getByRole("button", { name: "Add task on 2026-03-07" }))
    expect(onOpen).toHaveBeenCalledWith(day)
  })
})
