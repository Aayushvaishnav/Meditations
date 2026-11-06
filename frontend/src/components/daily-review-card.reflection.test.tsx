// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { DailyReviewCard } from "./daily-review-card"
import { useUi } from "@/stores/ui"

const state = vi.hoisted(() => ({
  score: {
    data: {
      final_score: 83.7, saved_review_score: 72.6, llm_nudge: 4.2, persisted: true,
      target_deep_work_hours: 4,
      metrics: { tasks_completed: 2, tasks_planned: 3, deep_work_hours: 1, habits_completed: 1, habits_scheduled: 2 },
      feedback: "You completed 2 important tasks.", insight: "Try 10 minutes outside.",
      suggested_action_for_tomorrow: "Plan a walk",
    },
    isError: false, refetch: vi.fn(),
  },
  rollup: { partial: null as null | { day: string; output: { feedback: string; key_insight: string; llm_nudge: number } }, pending: false, error: null as string | null, review: vi.fn() },
}))
vi.mock("@/hooks/api", () => ({ useDailyScore: () => state.score, useDailyRollupStream: () => state.rollup }))
vi.mock("@/components/recommendations/review-task-draft", () => ({ ReviewTaskDraft: ({ recommendation }: { recommendation: string }) => <button>{recommendation}</button> }))

beforeEach(() => {
  useUi.setState({ scoreDisplay: "reflection" })
  state.rollup.partial = null
  state.rollup.pending = false
  state.rollup.error = null
  state.score.isError = false
  vi.clearAllMocks()
})
afterEach(() => { cleanup(); useUi.setState({ scoreDisplay: "scored" }) })

it("hides structured scores while preserving activity, narrative numbers and saved actions", () => {
  const { container } = render(<DailyReviewCard day="2026-11-02" />)
  expect(screen.getByRole("heading", { name: "Day reflection" })).toBeTruthy()
  for (const text of ["83.7", "72.6", "+4.2", "live with AI nudge", "±10"]) expect(container.textContent).not.toContain(text)
  expect(screen.getByText("2/3 tasks")).toBeTruthy()
  expect(screen.getByText("1/2 habits")).toBeTruthy()
  expect(container.textContent).toContain("1h of 4h")
  expect(screen.getByText("You completed 2 important tasks.")).toBeTruthy()
  expect(screen.getByText("Try 10 minutes outside.")).toBeTruthy()
  expect(screen.getByRole("button", { name: "Plan a walk" })).toBeTruthy()
  expect(screen.getByRole("status")).toBeTruthy()
  fireEvent.click(screen.getByRole("button", { name: "Run AI review" }))
  expect(state.rollup.review).toHaveBeenCalledWith("2026-11-02")
  expect(container.textContent).toContain("entry for the selected day")
  expect(container.textContent).not.toContain("today's entry")
})

it("reacts to display changes without changing the review request", () => {
  const { container } = render(<DailyReviewCard day="2026-11-02" />)
  act(() => useUi.setState({ scoreDisplay: "scored" }))
  expect(screen.getByRole("heading", { name: "Day score" })).toBeTruthy()
  for (const text of ["83.7", "72.6", "+4.2", "current activity", "current focus target", "most recent saved AI nudge", "only when you rerun"]) expect(container.textContent).toContain(text)
  expect(state.rollup.review).not.toHaveBeenCalled()
})

it("retains streaming prose and review progress without exposing a streamed nudge", () => {
  state.rollup.partial = { day: "2026-11-02", output: { feedback: "Spent 30 minutes reading", key_insight: "Keep 2 priorities", llm_nudge: 8.9 } }
  state.rollup.pending = true
  const { container } = render(<DailyReviewCard day="2026-11-02" />)
  expect(screen.getByText("Spent 30 minutes reading")).toBeTruthy()
  expect(screen.getByText("Keep 2 priorities")).toBeTruthy()
  expect(container.textContent).not.toContain("8.9")
  expect(screen.getByRole("button", { name: "Reviewing…" }).hasAttribute("disabled")).toBe(true)
  expect(screen.getByRole("status")).toBeTruthy()
})

it("keeps failure details and retry controls available", () => {
  state.rollup.error = "Provider offline"
  state.score.isError = true
  render(<DailyReviewCard day="2026-11-02" />)
  expect(screen.getByText("AI review failed: Provider offline")).toBeTruthy()
  fireEvent.click(screen.getByRole("button", { name: "Retry review status" }))
  expect(state.score.refetch).toHaveBeenCalledOnce()
  fireEvent.click(screen.getByRole("button", { name: "Run AI review" }))
  expect(state.rollup.review).toHaveBeenCalledWith("2026-11-02")
})
