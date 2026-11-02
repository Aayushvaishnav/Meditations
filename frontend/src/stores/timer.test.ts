// @vitest-environment jsdom
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest"
import { useFocusTimer } from "./timer"
const timer = () => useFocusTimer.getState()
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(0)
  timer().takeEvents(); timer().reset(); timer().setMode("pomodoro"); timer().setWorkMinutes(5); timer().setBreakMinutes(1)
})
afterEach(() => vi.useRealTimers())
describe("wall clock timer", () => {
  it("catches up delayed callbacks and preserves fractional seconds", () => {
    timer().start(); vi.setSystemTime(12500); timer().tick()
    expect(timer().secondsLeft).toBe(288)
    vi.setSystemTime(13000); timer().tick(); expect(timer().secondsLeft).toBe(287)
  })
  it("excludes paused time and synchronizes pause", () => {
    timer().start(); vi.setSystemTime(12500); timer().pause()
    expect(timer().secondsLeft).toBe(288)
    vi.setSystemTime(100000); timer().start(); vi.setSystemTime(100500); timer().tick()
    expect(timer().secondsLeft).toBe(287)
  })
  it("enters break at the exact boundary", () => {
    timer().start(); vi.setSystemTime(300000)
    expect(timer().tick()).toBe("work-done")
    expect(timer().phase).toBe("break"); expect(timer().secondsLeft).toBe(60)
  })
  it("consumes break overflow without synthesizing more work", () => {
    timer().start(); vi.setSystemTime(315000); timer().tick()
    expect(timer().phase).toBe("break"); expect(timer().secondsLeft).toBe(45)
    vi.setSystemTime(999999999); timer().tick()
    expect(timer().running).toBe(false); expect(timer().phase).toBe("work")
    expect(timer().secondsLeft).toBe(300)
  })
  it("stops after a huge delay while reporting the completed work", () => {
    timer().start(); vi.setSystemTime(999999999)
    expect(timer().tick()).toBe("work-done"); expect(timer().running).toBe(false)
    expect(timer().tick()).toBe(null)
  })
  it("stopwatch syncs elapsed time on pause", () => {
    timer().setMode("stopwatch"); timer().start(); vi.setSystemTime(90500); timer().pause()
    expect(timer().elapsed).toBe(90)
    timer().reset(); expect(timer().elapsed).toBe(0)
  })
  it("mode changes reset, same mode does not, and configuration clamps", () => {
    timer().start(); timer().setMode("pomodoro"); expect(timer().running).toBe(true)
    timer().setMode("stopwatch"); expect(timer().running).toBe(false)
    timer().setWorkMinutes(200); timer().setBreakMinutes(-5)
    expect(timer().workMinutes).toBe(90); expect(timer().breakMinutes).toBe(1)
  })
  it("stops at the exact break boundary and emits each completion once", () => {
    timer().start(); vi.setSystemTime(300000); timer().tick()
    vi.setSystemTime(360000); expect(timer().tick()).toBe("break-done")
    expect(timer().running).toBe(false)
    expect(timer().takeEvents().map((event) => event.type)).toEqual(["work-done", "break-done"])
    expect(timer().takeEvents()).toEqual([])
    expect(timer().tick()).toBe(null)
  })
  it("repeated start does not discard elapsed time and reset clears fractional progress", () => {
    timer().start(); vi.setSystemTime(12500); timer().start(); timer().pause()
    expect(timer().secondsLeft).toBe(288)
    timer().reset(); timer().start(); vi.setSystemTime(13000); timer().tick()
    expect(timer().secondsLeft).toBe(300)
  })
  it("duration changes seed a complete duration while paused", () => {
    timer().start(); vi.setSystemTime(12500); timer().pause(); timer().setWorkMinutes(10)
    timer().start(); vi.setSystemTime(13000); timer().tick()
    expect(timer().secondsLeft).toBe(600)
  })
  it("completion payload survives reset and later configuration changes", () => {
    timer().setTask("completed-task"); timer().start(); vi.setSystemTime(300000); timer().pause()
    timer().reset(); timer().setTask("another-task"); timer().setWorkMinutes(10)
    expect(timer().takeEvents()).toEqual([{ type: "work-done", taskId: "completed-task", workMinutes: 5 }])
  })
  it("rehydrates settings but not running progress", async () => {
    timer().setMode("stopwatch"); timer().setTask("task"); timer().start()
    vi.setSystemTime(90000); timer().tick()
    const persisted = JSON.parse(localStorage.getItem("journal-focus-timer")!).state
    expect(Object.keys(persisted).sort()).toEqual(["breakMinutes", "mode", "open", "taskId", "workMinutes"])
    await useFocusTimer.persist.rehydrate()
    expect(timer().running).toBe(false); expect(timer().elapsed).toBe(0)
    expect(timer().mode).toBe("stopwatch"); expect(timer().taskId).toBe("task")
  })
})
