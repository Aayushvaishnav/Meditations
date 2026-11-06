// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import type { Scope } from "@/stores/ui"
import { useUi } from "@/stores/ui"
import { TasksView } from "./tasks-view"

const modules = vi.hoisted(() => {
  function gate() {
    let resolve!: () => void
    const promise = new Promise<void>(done => { resolve = done })
    return { promise, resolve }
  }
  return { calendar: gate(), board: gate() }
})
vi.mock("@/hooks/api", () => ({
  useTasks: () => ({ data: [], isLoading: false, isError: false }),
  useLists: () => ({ data: [] }),
}))
vi.mock("@/components/header", () => ({ Header: () => <input aria-label="Filter" /> }))
vi.mock("@/components/quick-add", () => ({ QuickAdd: () => null }))
vi.mock("@/components/briefing-card", () => ({ BriefingCard: () => null }))
vi.mock("@/components/task-sections", () => ({ TaskSections: () => null }))
function Content({ scope, search }: { scope: Scope; search: string }) {
  return <section aria-label="Loaded view">{JSON.stringify({ scope, search })}</section>
}
vi.mock("@/components/calendar-view", async () => {
  await modules.calendar.promise
  return { CalendarView: Content }
})
vi.mock("@/components/kanban-board", async () => {
  await modules.board.promise
  return { KanbanBoard: Content }
})
afterEach(() => { cleanup(); useUi.setState(useUi.getInitialState()); localStorage.clear() })

it("replaces each selected view's fallback with current context without another navigation", async () => {
  useUi.setState({ view: "calendar", scope: { kind: "smart", id: "all" }, search: "initial" })
  render(<TasksView />)
  const filter = screen.getByRole("textbox", { name: "Filter" })
  for (const view of ["calendar", "board"] as const) {
    act(() => useUi.getState().setView(view))
    expect(screen.getByLabelText(view === "board" ? "Loading board" : "Loading tasks")).toBeTruthy()
    const scope = { kind: "list", id: `latest-${view}` } as const
    act(() => useUi.setState({ scope, search: `changed-${view}` }))
    await act(async () => {
      modules[view].resolve()
      await modules[view].promise
      if (view === "calendar") await import("./calendar-view")
      else await import("./kanban-board")
    })
    expect(JSON.parse(screen.getByRole("region", { name: "Loaded view" }).textContent!)).toEqual({ scope, search: `changed-${view}` })
    expect(useUi.getState().view).toBe(view)
    expect(screen.getByRole("textbox", { name: "Filter" })).toBe(filter)
    expect(screen.queryByLabelText(view === "board" ? "Loading board" : "Loading tasks")).toBeNull()
  }
})
