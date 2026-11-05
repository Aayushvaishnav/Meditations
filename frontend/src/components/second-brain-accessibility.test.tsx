// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { SecondBrain } from "./second-brain"
import { useUi } from "@/stores/ui"

const fixtures = vi.hoisted(() => ({
  sources: [
    { n: 1, doc_id: "day", kind: "journal", date: "2026-11-05", title: "Journal source" },
    { n: 2, doc_id: "week", kind: "weekly", date: "2026-11-02", title: "Weekly source" },
    { n: 3, doc_id: "month", kind: "monthly", date: "2026-11-01", title: "Monthly source" },
  ],
}))
vi.mock("@/hooks/api", () => ({
  useSearch: () => ({ data: fixtures.sources.map(source => ({ ...source, excerpt: "Matching reflection", sources: ["fts"] })), isPending: false, isError: false }),
  useSearchStatus: () => ({ data: { semantic: true } }),
  useSecondBrainChat: () => ({ messages: [{ role: "assistant", content: "A reflection [1] [2] [3]", sources: fixtures.sources }], pending: false, send: vi.fn(), reset: vi.fn() }),
}))
const scrollIntoView = Element.prototype.scrollIntoView
beforeEach(() => {
  vi.useFakeTimers()
  Element.prototype.scrollIntoView = vi.fn()
  useUi.setState({ section: "second_brain", journalDay: null })
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  Element.prototype.scrollIntoView = scrollIntoView
  useUi.setState({ section: "tasks", journalDay: null })
})

it("keeps journal citations actionable and describes rollup citations without inert buttons", () => {
  render(<SecondBrain />)
  expect(screen.queryAllByRole("button", { name: /Weekly source|Monthly source/ })).toHaveLength(0)
  expect(screen.getByText("Citation 2: Weekly source (Week)")).toBeTruthy()
  expect(screen.getByText("Citation 3: Monthly source (Month)")).toBeTruthy()
  fireEvent.click(screen.getByRole("button", { name: "Open citation 1: Journal source (Journal)" }))
  expect(useUi.getState().section).toBe("journal")
  expect(useUi.getState().journalDay).toBe("2026-11-05")
})

it("names both input modes and offers navigation only for journal search hits", () => {
  render(<SecondBrain />)
  expect(screen.getByRole("textbox", { name: "Ask your journals" })).toBeTruthy()
  fireEvent.click(screen.getByRole("button", { name: "Search" }))
  const input = screen.getByRole("textbox", { name: "Search your journals" })
  fireEvent.change(input, { target: { value: "review" } })
  act(() => { vi.advanceTimersByTime(300) })
  expect(screen.queryAllByRole("button", { name: /Weekly source|Monthly source/ })).toHaveLength(0)
  expect(screen.getByText("Weekly source")).toBeTruthy()
  expect(screen.getByText("Monthly source")).toBeTruthy()
  fireEvent.click(screen.getByRole("button", { name: /Journal source/ }))
  expect(useUi.getState().section).toBe("journal")
  expect(useUi.getState().journalDay).toBe("2026-11-05")
})
