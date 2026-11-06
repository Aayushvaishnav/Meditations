// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { InsightsView } from "./insights"
import { ScoreDisplayPreference, ScoreExplanation } from "./score-display"
import { useUi } from "@/stores/ui"

const state = vi.hoisted(() => ({ loading: false, error: false }))
const data = {
  series: [{ date: "2026-11-06", score: 87.6, deep_work_hours: 2, mood: 4 }],
  totals: { avg_score_7: 87.6, avg_score_prev_7: 72.3, completion_rate: 0.5, tasks_done: 3, total_focus_hours: 2, target_deep_work_hours: 4 },
  journaling_streak: 6, journaling_best: 12,
  habits: [{ id: "walk", name: "Walk outside", current_streak: 2, rate_30: 0.5 }],
  weekly: [{ week_start: "2026-11-02", avg_score: 81.2, trend: "rising" }],
  monthly: [{ month: "2026-10", avg_score: 76.4, trend: "declining" }],
}
vi.mock("@/hooks/api", () => ({ useInsights: () => ({ data, isLoading: state.loading, isError: state.error }) }))
beforeEach(() => { localStorage.clear(); useUi.setState(useUi.getInitialState()) })
afterEach(() => { cleanup(); state.loading = false; state.error = false; useUi.setState(useUi.getInitialState()); localStorage.clear() })

it("changes structured scoring visibility without changing activity, mood or incoming data", () => {
  const baseline = structuredClone(data)
  render(<><ScoreDisplayPreference /><InsightsView /></>)
  expect(screen.getByRole("img", { name: "Daily scores over 30 days" })).toBeTruthy()
  expect(screen.getByText("81.2")).toBeTruthy()
  fireEvent.change(screen.getByRole("combobox", { name: "Score display" }), { target: { value: "reflection" } })
  expect(screen.queryByRole("img", { name: /Daily scores/ })).toBeNull()
  expect(screen.queryByText("87.6")).toBeNull()
  expect(screen.queryByText("81.2")).toBeNull()
  expect(screen.queryByText("76.4")).toBeNull()
  expect(screen.queryByRole("heading", { name: /rollup trends/i })).toBeNull()
  expect(screen.getByRole("img", { name: "Daily mood over 30 days" })).toBeTruthy()
  expect(screen.getByRole("img", { name: "Daily focus hours over 30 days" })).toBeTruthy()
  expect(screen.getByText("50%")).toBeTruthy()
  expect(screen.getByText("Walk outside")).toBeTruthy()
  expect(screen.getByText("Journaling streak")).toBeTruthy()
  expect(data).toEqual(baseline)
  fireEvent.click(screen.getByRole("button", { name: "14d" }))
  expect(screen.getByRole("img", { name: "Daily mood over 14 days" })).toBeTruthy()
  expect(screen.queryByRole("img", { name: /Daily scores/ })).toBeNull()
  fireEvent.change(screen.getByRole("combobox", { name: "Score display" }), { target: { value: "scored" } })
  expect(screen.getByRole("img", { name: "Daily scores over 14 days" })).toBeTruthy()
  expect(screen.getByText("76.4")).toBeTruthy()
})

it("retains reflection-first through unmount, preference rehydration and navigation", async () => {
  useUi.getState().setScoreDisplay("reflection")
  const saved = localStorage.getItem("journal-ui")!
  const view = render(<InsightsView />)
  view.unmount()
  useUi.setState(useUi.getInitialState())
  localStorage.setItem("journal-ui", saved)
  await act(async () => { await useUi.persist.rehydrate() })
  useUi.getState().setSection("journal")
  useUi.getState().setSection("insights")
  render(<InsightsView />)
  expect(screen.queryByRole("img", { name: /Daily scores/ })).toBeNull()
  expect(screen.getByRole("img", { name: /Daily mood/ })).toBeTruthy()
})

it.each(["loading", "error"] as const)("keeps the preference across %s and recovery", (phase) => {
  useUi.getState().setScoreDisplay("reflection")
  state[phase] = true
  const view = render(<InsightsView />)
  expect(screen.queryByRole("img", { name: /Daily scores/ })).toBeNull()
  state[phase] = false
  view.rerender(<InsightsView />)
  expect(screen.queryByRole("img", { name: /Daily scores/ })).toBeNull()
  expect(screen.getByRole("img", { name: /Daily mood/ })).toBeTruthy()
})

it("explains the 90-point maximum separately from snapshots and live recalculation", () => {
  render(<InsightsView />)
  expect(screen.getByText(/Reviewed days use saved review snapshots/)).toBeTruthy()
  expect(screen.getByText(/Weekly and monthly review snapshots/)).toBeTruthy()
  fireEvent.click(screen.getByText("How scoring works"))
  expect(screen.getByText(/they total 90 points before the AI nudge/)).toBeTruthy()
  expect(screen.getByText(/Days without planned or completed tasks receive zero task points/)).toBeTruthy()
})

it("offers scoring details through a keyboard-focusable native disclosure", () => {
  render(<ScoreExplanation />)
  const summary = screen.getByText("How scoring works")
  summary.focus()
  expect(document.activeElement).toBe(summary)
  expect(summary.closest("details")?.open).toBe(false)
  fireEvent.click(summary)
  expect(summary.closest("details")?.open).toBe(true)
})
