// @vitest-environment jsdom
import { StrictMode } from "react"
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { FocusTimer } from "./focus-timer"
import { useFocusTimer } from "@/stores/timer"
const { mutate } = vi.hoisted(() => ({ mutate: vi.fn() }))
vi.mock("@/hooks/api", () => ({ useTasks: () => ({ data: [] }), useCreateSession: () => ({ mutate }) }))
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { success: vi.fn() }) }))
const timer = () => useFocusTimer.getState()
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(0); mutate.mockClear()
  timer().takeEvents(); timer().reset(); timer().setMode("pomodoro"); timer().setWorkMinutes(5); timer().setBreakMinutes(1)
  timer().setTask("linked-task"); useFocusTimer.setState({ open: true })
})
afterEach(() => { cleanup(); vi.useRealTimers() })
function mount() { return render(<StrictMode><FocusTimer /></StrictMode>) }
it("pause synchronizes completion and logs exactly once under StrictMode", () => {
  mount(); fireEvent.click(screen.getByRole("button", { name: "Start" }))
  vi.setSystemTime(300000)
  fireEvent.click(screen.getByRole("button", { name: "Pause" }))
  expect(mutate).toHaveBeenCalledTimes(1)
  expect(mutate).toHaveBeenCalledWith({ task_id: "linked-task", duration_minutes: 5, session_type: "pomodoro" })
  expect(timer().running).toBe(false); expect(timer().phase).toBe("break")
  act(() => { vi.advanceTimersByTime(5000) }); expect(mutate).toHaveBeenCalledTimes(1)
})
it("hidden timer catches up a delayed callback, finishes break, never logs another cycle", () => {
  mount(); fireEvent.click(screen.getByRole("button", { name: "Start" }))
  fireEvent.click(screen.getByRole("button", { name: "Hide timer" }))
  vi.setSystemTime(10000000)
  act(() => { vi.advanceTimersByTime(1000) })
  expect(mutate).toHaveBeenCalledTimes(1); expect(timer().running).toBe(false)
  act(() => { vi.advanceTimersByTime(1000000) }); expect(mutate).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole("button", { name: "Open focus timer" }))
  expect(screen.getByRole("button", { name: "Start" })).toBeTruthy()
})
it.each([[59999, 0, 0], [60000, 1, 1], [89999, 1, 1], [90000, 1, 2], [149999, 1, 2], [150000, 1, 3]])(
  "log stop synchronizes %i ms with threshold and rounded minutes", (ms, calls, minutes) => {
    mount(); fireEvent.click(screen.getByRole("button", { name: "Stopwatch" }))
    fireEvent.click(screen.getByRole("button", { name: "Start" }))
    vi.setSystemTime(ms)
    fireEvent.click(screen.getByRole("button", { name: "Log & stop" }))
    expect(mutate).toHaveBeenCalledTimes(calls)
    if (calls) expect(mutate).toHaveBeenCalledWith({ task_id: "linked-task", duration_minutes: minutes, session_type: "stopwatch" })
    expect(timer().running).toBe(false); expect(timer().elapsed).toBe(0)
  },
)
it("reset cancels an unfinished session without logging", () => {
  mount(); fireEvent.click(screen.getByRole("button", { name: "Start" }))
  vi.setSystemTime(10000); fireEvent.click(screen.getByRole("button", { name: "Reset timer" }))
  act(() => { vi.advanceTimersByTime(400000) })
  expect(mutate).not.toHaveBeenCalled(); expect(timer().secondsLeft).toBe(300)
})

it.each(["Reset timer", "Stopwatch"])("%s preserves completed work discovered after suspend", (action) => {
  mount()
  fireEvent.click(screen.getByRole("button", { name: "Start" }))
  vi.setSystemTime(600000)
  fireEvent.click(screen.getByRole("button", { name: action }))
  expect(mutate).toHaveBeenCalledTimes(1)
  expect(mutate).toHaveBeenCalledWith({ task_id: "linked-task", duration_minutes: 5, session_type: "pomodoro" })
  expect(timer().running).toBe(false)
  act(() => { vi.advanceTimersByTime(600000) })
  expect(mutate).toHaveBeenCalledTimes(1)
})
