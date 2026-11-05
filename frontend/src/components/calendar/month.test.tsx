// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { CalendarMonth } from "./month"
import type { CalendarDay } from "@/lib/calendar-projection"

afterEach(cleanup)

describe("Month calendar access", () => {
  it("keeps its horizontal navigation region and day details reachable by keyboard", () => {
    const day = new Date(2026, 10, 5)
    const onOpen = vi.fn()
    const days: CalendarDay[] = [{ day, items: [{
      kind: "imported", id: "imported:source:appointment", editable: false,
      allDay: true, timing: { kind: "all-day" }, placement: "placed",
      event: { id: "appointment", source_id: "source", uid: "appointment", summary: "Dentist appointment", status: "CONFIRMED", interval: { kind: "date", start: "2026-11-05", end: "2026-11-06" } },
    }] }]
    render(<CalendarMonth days={days} anchor={day} taskById={new Map()} pending={false} onOpen={onOpen} />)
    const region = screen.getByRole("region", { name: "Month calendar; scroll horizontally to see more days" })
    region.focus()
    expect(document.activeElement).toBe(region)
    fireEvent.click(within(region).getByRole("button", { name: /Dentist appointment/ }))
    expect(onOpen).toHaveBeenCalledExactlyOnceWith(day)
    onOpen.mockClear()
    fireEvent.click(within(region).getByRole("button", { name: "Add task on 2026-11-05" }))
    expect(onOpen).toHaveBeenCalledExactlyOnceWith(day)
  })
})
