// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { useDeadlinePassed } from "./use-deadline-passed"

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date("2026-11-02T12:00:00Z"))
})
afterEach(() => { cleanup(); vi.useRealTimers() })

it("changes only after the strict deadline without another render", () => {
  const { result } = renderHook(() => useDeadlinePassed(Date.parse("2026-11-02T12:00:01Z")))
  expect(result.current).toBe(false)
  act(() => vi.advanceTimersByTime(1000))
  expect(result.current).toBe(false)
  act(() => vi.advanceTimersByTime(1))
  expect(result.current).toBe(true)
  expect(vi.getTimerCount()).toBe(0)
})

it("handles absent and already-past deadlines without timers", () => {
  const { result, rerender } = renderHook(({ deadline }) => useDeadlinePassed(deadline), {
    initialProps: { deadline: null as number | null },
  })
  expect(result.current).toBe(false)
  expect(vi.getTimerCount()).toBe(0)
  rerender({ deadline: Date.now() - 1 })
  expect(result.current).toBe(true)
  expect(vi.getTimerCount()).toBe(0)
})

it("replaces obsolete timers on reschedule and cancels on unmount", () => {
  const now = Date.now()
  const { result, rerender, unmount } = renderHook(({ deadline }) => useDeadlinePassed(deadline), {
    initialProps: { deadline: now + 1000 as number | null },
  })
  rerender({ deadline: now + 2000 })
  act(() => vi.advanceTimersByTime(1001))
  expect(result.current).toBe(false)
  expect(vi.getTimerCount()).toBe(1)
  rerender({ deadline: null })
  expect(vi.getTimerCount()).toBe(0)
  rerender({ deadline: now + 5000 })
  unmount()
  expect(vi.getTimerCount()).toBe(0)
  act(() => window.dispatchEvent(new Event("focus")))
  expect(vi.getTimerCount()).toBe(0)
})

it.each(["focus", "visibilitychange"])("refreshes after suspended timers on %s and handles backward clock changes", (event) => {
  const now = Date.now()
  const { result } = renderHook(() => useDeadlinePassed(now + 1000))
  vi.setSystemTime(now + 5000)
  act(() => (event === "focus" ? window : document).dispatchEvent(new Event(event)))
  expect(result.current).toBe(true)
  vi.setSystemTime(now)
  act(() => (event === "focus" ? window : document).dispatchEvent(new Event(event)))
  expect(result.current).toBe(false)
  act(() => vi.advanceTimersByTime(1001))
  expect(result.current).toBe(true)
})

it("tracks independent deadlines and releases every subscription", () => {
  const now = Date.now()
  const first = renderHook(() => useDeadlinePassed(now + 1000))
  const second = renderHook(() => useDeadlinePassed(now + 2000))
  act(() => vi.advanceTimersByTime(1001))
  expect(first.result.current).toBe(true)
  expect(second.result.current).toBe(false)
  first.unmount()
  act(() => vi.advanceTimersByTime(1000))
  expect(second.result.current).toBe(true)
  second.unmount()
  expect(vi.getTimerCount()).toBe(0)
})

it("re-arms distant deadlines without overflowing browser timer delays", () => {
  const maxDelay = 2 ** 31 - 1
  const deadline = Date.now() + maxDelay + 1000
  const { result } = renderHook(() => useDeadlinePassed(deadline))
  act(() => vi.advanceTimersByTime(maxDelay))
  expect(result.current).toBe(false)
  expect(vi.getTimerCount()).toBe(1)
  act(() => vi.advanceTimersByTime(1001))
  expect(result.current).toBe(true)
})
