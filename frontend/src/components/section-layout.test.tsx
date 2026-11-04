// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { SectionLayout } from "./section-layout"
import { SectionLoading } from "./section-loading"
import { InsightsView } from "./insights"
import { SecondBrain } from "./second-brain"

const state = vi.hoisted(() => ({
  insights: { isError: false, isLoading: false } as Record<string, unknown>,
  messages: [] as Array<{ role: "assistant"; content: string }>,
  pending: false,
}))
vi.mock("@/hooks/api", () => ({
  useInsights: () => state.insights,
  useSearch: () => ({ data: [], isPending: false }),
  useSearchStatus: () => ({ data: { semantic: true } }),
  useSecondBrainChat: () => ({ messages: state.messages, pending: state.pending, send: vi.fn(), reset: vi.fn() }),
}))
afterEach(() => {
  cleanup()
  state.insights = { isError: false, isLoading: false }
  state.messages = []
  state.pending = false
})

describe("section layout", () => {
  it.each(["workspace", "reading"] as const)("preserves landmarks, accessibility and controls in the %s variant", (width) => {
    const action = vi.fn()
    render(<SectionLayout width={width} aria-label="Example section" aria-busy="true"><button onClick={action}>Continue</button></SectionLayout>)
    const main = screen.getByRole("main", { name: "Example section" })
    expect(main.getAttribute("aria-busy")).toBe("true")
    expect(main.contains(screen.getByRole("button"))).toBe(true)
    fireEvent.click(screen.getByRole("button"))
    expect(action).toHaveBeenCalledOnce()
  })
  it.each(["journal", "insights", "second_brain", "settings"] as const)("announces lazy loading for %s in one section landmark", (section) => {
    render(<SectionLoading section={section} />)
    expect(screen.getAllByRole("main")).toHaveLength(1)
    expect(screen.getByRole("main").getAttribute("aria-busy")).toBe("true")
    expect(screen.getByRole("status").textContent).toContain("Loading")
  })
  it.each(["loading", "error", "empty"])("keeps Insights %s in the section landmark", (stateName) => {
    state.insights = { isLoading: stateName === "loading", isError: stateName === "error" }
    render(<InsightsView />)
    expect(screen.getAllByRole("main")).toHaveLength(1)
    if (stateName === "error") expect(screen.getByText(/Couldn't load insights/)).toBeTruthy()
    else expect(screen.getByRole("heading", { name: "Insights" })).toBeTruthy()
    if (stateName === "empty") expect(screen.getByText("No daily habits configured yet.")).toBeTruthy()
  })
  it("keeps a partial answer and its controls available while streaming", () => {
    Element.prototype.scrollIntoView = vi.fn()
    state.messages = [{ role: "assistant", content: "A partial answer with a verylongunbrokenreference" }]
    state.pending = true
    render(<SecondBrain />)
    expect(screen.getByRole("main").contains(screen.getByText(/A partial answer/))).toBe(true)
    expect(screen.getByRole("button", { name: "New conversation" })).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Search" }))
    expect(screen.getByText("Search across your journals, weekly rollups and monthly reviews.")).toBeTruthy()
  })
})
