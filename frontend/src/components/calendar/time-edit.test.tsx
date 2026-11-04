// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import type { CalendarItem } from "@/lib/calendar-projection"
import { localDateTimeValue } from "@/lib/calendar-time-edit"
import { CalendarTimeEdit } from "./time-edit"

const deadline = { id: "deadline:1", kind: "deadline", allDay: false, timing: { kind: "timed", clock: "12:00" }, task: { deadline: { kind: "timed", at: "2026-06-15T12:00:34.123" } } } as CalendarItem
const block = { ...deadline, id: "block:1", kind: "block", block: { kind: "timed", task_id: "task-1", timezone: "Asia/Kolkata", start_at: "2026-06-15T12:00:00", end_at: "2026-06-15T13:00:00" } } as CalendarItem
const props = () => ({ pending: false, onDeadline: vi.fn(), onBlock: vi.fn() })
afterEach(cleanup)
it("submits a deadline only explicitly and preserves subminute precision", () => {
  const callbacks = props()
  render(<CalendarTimeEdit item={deadline} {...callbacks} />)
  expect(callbacks.onDeadline).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button", { name: "Save time" }))
  expect(callbacks.onDeadline).toHaveBeenCalledExactlyOnceWith({ kind: "timed", at: "2026-06-15T12:00:34.123Z" })
  expect(callbacks.onBlock).not.toHaveBeenCalled()
})
it("uses the explicit block end and preserves task and timezone", () => {
  const callbacks = props()
  render(<CalendarTimeEdit item={block} {...callbacks} />)
  fireEvent.change(screen.getByLabelText("Block end"), { target: { value: localDateTimeValue(new Date("2026-06-15T14:30:00Z")) } })
  expect(callbacks.onBlock).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button"))
  expect(callbacks.onBlock).toHaveBeenCalledExactlyOnceWith({ kind: "timed", task_id: "task-1", timezone: "Asia/Kolkata", start_at: "2026-06-15T12:00:00.000Z", end_at: "2026-06-15T14:30:00.000Z" })
})
it("shows validation errors without dispatching inverted blocks", () => {
  const callbacks = props()
  render(<CalendarTimeEdit item={block} {...callbacks} />)
  fireEvent.change(screen.getByLabelText("Block end"), { target: { value: localDateTimeValue(new Date("2026-06-15T11:00:00Z")) } })
  fireEvent.click(screen.getByRole("button"))
  expect(screen.getByRole("alert")).toBeTruthy()
  expect(callbacks.onBlock).not.toHaveBeenCalled()
})
it("disables fields and guards programmatic submissions while pending", () => {
  const callbacks = props()
  render(<CalendarTimeEdit item={deadline} {...callbacks} pending />)
  const input = screen.getByLabelText("Deadline at") as HTMLInputElement
  expect(input.disabled).toBe(true)
  fireEvent.submit(input.closest("form")!)
  expect(callbacks.onDeadline).not.toHaveBeenCalled()
})
it.each(["imported", "live", "all-day"])("does not render controls for %s", kind => {
  const item = kind === "all-day" ? { ...deadline, allDay: true } : { ...deadline, kind }
  const { container } = render(<CalendarTimeEdit item={item as CalendarItem} {...props()} />)
  expect(container.childElementCount).toBe(0)
})
