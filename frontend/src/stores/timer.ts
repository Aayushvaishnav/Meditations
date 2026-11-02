import { create } from "zustand"
import { persist } from "zustand/middleware"

export type TimerMode = "pomodoro" | "stopwatch"
export type TimerPhase = "work" | "break"

type Clock = { status: "paused" } | { status: "running"; at: number }
type TimerEvent = { type: "work-done"; workMinutes: number; taskId: string | null } | { type: "break-done" }

interface FocusTimerState {
  clock: Clock
  remainderMs: number
  events: TimerEvent[]
  takeEvents: () => TimerEvent[]
  mode: TimerMode
  phase: TimerPhase
  running: boolean
  secondsLeft: number // pomodoro countdown
  elapsed: number // stopwatch seconds
  workMinutes: number
  breakMinutes: number
  taskId: string | null
  open: boolean
  setMode: (mode: TimerMode) => void
  setTask: (taskId: string | null) => void
  setWorkMinutes: (n: number) => void
  setBreakMinutes: (n: number) => void
  start: () => void
  pause: () => void
  reset: () => void
  toggleOpen: () => void
  /** Synchronize wall-clock elapsed time; queue completion events for the controller. */
  tick: () => "work-done" | "break-done" | null
}

export const useFocusTimer = create<FocusTimerState>()(
  persist(
    (set, get) => ({
      clock: { status: "paused" },
      remainderMs: 0,
      events: [],
      takeEvents: () => {
        const events = get().events
        if (events.length) set({ events: [] })
        return events
      },
      mode: "pomodoro",
      phase: "work",
      running: false,
      secondsLeft: 25 * 60,
      elapsed: 0,
      workMinutes: 25,
      breakMinutes: 5,
      taskId: null,
      open: true,
      setMode: (mode) => {
        if (mode === get().mode) return
        get().reset()
        set({ mode })
      },
      setTask: (taskId) => set({ taskId }),
      setWorkMinutes: (n) => {
        const clamped = Math.max(5, Math.min(90, n))
        set((s) => ({
          workMinutes: clamped,
          secondsLeft: s.phase === "work" && !s.running ? clamped * 60 : s.secondsLeft,
          remainderMs: s.phase === "work" && !s.running ? 0 : s.remainderMs,
        }))
      },
      setBreakMinutes: (n) => {
        const clamped = Math.max(1, Math.min(30, n))
        set((s) => ({
          breakMinutes: clamped,
          secondsLeft: s.phase === "break" && !s.running ? clamped * 60 : s.secondsLeft,
          remainderMs: s.phase === "break" && !s.running ? 0 : s.remainderMs,
        }))
      },
      start: () => {
        if (!get().running) set({ running: true, clock: { status: "running", at: Date.now() } })
      },
      pause: () => {
        get().tick()
        set({ running: false, clock: { status: "paused" } })
      },
      reset: () => {
        get().tick()
        set((s) => ({
          clock: { status: "paused" },
          remainderMs: 0,
          running: false,
          elapsed: 0,
          phase: "work",
          secondsLeft: s.workMinutes * 60,
        }))
      },
      toggleOpen: () => set((s) => ({ open: !s.open })),
      tick: () => {
        const s = get()
        if (!s.running || s.clock.status !== "running") return null
        const now = Date.now()
        const milliseconds = Math.max(0, now - s.clock.at) + s.remainderMs
        const seconds = Math.floor(milliseconds / 1000)
        const clock: Clock = { status: "running", at: now }
        const remainderMs = milliseconds % 1000
        if (s.mode === "stopwatch") {
          set({ elapsed: s.elapsed + seconds, clock, remainderMs })
          return null
        }
        if (seconds < s.secondsLeft) {
          set({ secondsLeft: s.secondsLeft - seconds, clock, remainderMs })
          return null
        }
        const events: TimerEvent[] = []
        const overflow = seconds - s.secondsLeft
        if (s.phase === "work") {
          events.push({ type: "work-done", workMinutes: s.workMinutes, taskId: s.taskId })
          if (overflow < s.breakMinutes * 60) {
            set({
              phase: "break",
              secondsLeft: s.breakMinutes * 60 - overflow,
              clock,
              remainderMs,
              events: [...s.events, ...events],
            })
            return "work-done"
          }
        }
        events.push({ type: "break-done" })
        set({
          phase: "work",
          secondsLeft: s.workMinutes * 60,
          running: false,
          clock: { status: "paused" },
          remainderMs: 0,
          events: [...s.events, ...events],
        })
        return s.phase === "work" ? "work-done" : "break-done"
      },
    }),
    {
      name: "journal-focus-timer",
      partialize: (s) => ({
        mode: s.mode,
        workMinutes: s.workMinutes,
        breakMinutes: s.breakMinutes,
        taskId: s.taskId,
        open: s.open,
      }),
      // a fresh page load starts paused; persisted countdowns are re-seeded
      onRehydrateStorage: () => (state) => {
        if (state) state.reset()
      },
    },
  ),
)
