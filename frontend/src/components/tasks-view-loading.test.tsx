// @vitest-environment jsdom
import { useState } from "react"
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import type { Task } from "@/api/types"
import type { Scope } from "@/stores/ui"
import { useUi } from "@/stores/ui"
import { TasksView } from "./tasks-view"

const modules = vi.hoisted(() => {
  function gate() {
    let resolve!: () => void
    const promise = new Promise<void>(done => { resolve = done })
    return { promise, resolve, requested: vi.fn() }
  }
  return { calendar: gate(), board: gate() }
})
const query = vi.hoisted(() => ({ data: [] as Task[], isLoading: false, isError: false, refetch: vi.fn() }))
vi.mock("@/hooks/api", () => ({ useTasks: () => query, useLists: () => ({ data: [] }) }))
function Header() {
  const [count, setCount] = useState(0)
  return <header><button onClick={() => setCount(count + 1)}>Header {count}</button><input aria-label="Search" value={useUi(s => s.search)} onChange={event => useUi.getState().setSearch(event.target.value)} /><button onClick={() => useUi.getState().setScope({ kind: "list", id: "work" })}>Work list</button></header>
}
vi.mock("@/components/header", () => ({ Header }))
vi.mock("@/components/quick-add", () => ({ QuickAdd: () => <input aria-label="Quick add" /> }))
vi.mock("@/components/briefing-card", () => ({ BriefingCard: () => null }))
vi.mock("@/components/task-sections", () => ({ TaskSections: () => <p>Task list</p> }))
vi.mock("@/components/skeletons", () => ({ KanbanSkeleton: () => <p role="status">Board loading</p>, TaskListSkeleton: () => <p role="status">Tasks loading</p> }))
type ViewProps = { tasks: Task[]; scope: Scope; search: string }
function LoadedView({ name, tasks, scope, search }: ViewProps & { name: string }) {
  return <section aria-label={name}>{JSON.stringify({ titles: tasks.map(task => task.title), scope, search })}</section>
}
vi.mock("@/components/calendar-view", async () => {
  modules.calendar.requested()
  await modules.calendar.promise
  return { CalendarView: (props: ViewProps) => <LoadedView {...props} name="Calendar" /> }
})
vi.mock("@/components/kanban-board", async () => {
  modules.board.requested()
  await modules.board.promise
  return { KanbanBoard: (props: ViewProps) => <LoadedView {...props} name="Board" /> }
})
afterEach(() => { cleanup(); useUi.setState(useUi.getInitialState()); localStorage.clear() })

it("defers heavy task views behind API state and keeps controls and latest context through pending navigation", async () => {
  useUi.setState({ view: "list", scope: { kind: "smart", id: "all" }, search: "" })
  const mounted = render(<TasksView />)
  expect(screen.getByText("Task list")).toBeTruthy()
  expect(modules.calendar.requested).not.toHaveBeenCalled()
  expect(modules.board.requested).not.toHaveBeenCalled()
  const header = screen.getByRole("button", { name: "Header 0" })
  const quickAdd = screen.getByRole("textbox", { name: "Quick add" })
  fireEvent.change(quickAdd, { target: { value: "Draft task" } })

  for (const view of ["calendar", "board"] as const) {
    query.isLoading = true
    act(() => useUi.getState().setView(view))
    expect(screen.getByRole("status").textContent).toBe(view === "board" ? "Board loading" : "Tasks loading")
    expect(modules[view].requested).not.toHaveBeenCalled()
    query.isLoading = false
    query.isError = true
    mounted.rerender(<TasksView />)
    expect(screen.getByText(/Can't reach the API/)).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(modules[view].requested).not.toHaveBeenCalled()
    query.isError = false
    await act(async () => { mounted.rerender(<TasksView />) })
    expect(modules[view].requested).toHaveBeenCalledTimes(1)
    expect(screen.getByRole("status").textContent).toBe(view === "board" ? "Board loading" : "Tasks loading")
    fireEvent.click(header)
    fireEvent.click(screen.getByRole("button", { name: "Work list" }))
    fireEvent.change(screen.getByRole("textbox", { name: "Search" }), { target: { value: `latest ${view}` } })
    query.data = [{
      id: `fresh-${view}`, title: `fresh ${view}`, description: null, list_id: "work", parent_id: null,
      priority: 0, importance: "unassigned", urgency: "unassigned", status: "todo",
      deadline: { kind: "none" }, due_date: null, estimated_minutes: null, actual_minutes: 0,
      recurrence_rule: null, recurrence_series_id: null, recurrence_occurrence: null,
      tags: [], order_index: 0, completed_at: null, created_at: "2026-11-05T00:00:00",
      updated_at: "2026-11-05T00:00:00",
    }]
    mounted.rerender(<TasksView />)
    act(() => useUi.getState().setView("list"))
    await act(async () => { modules[view].resolve(); await modules[view].promise })
    expect(screen.getByText("Task list")).toBeTruthy()
    expect(screen.queryByRole("region", { name: view === "board" ? "Board" : "Calendar" })).toBeNull()
    act(() => useUi.getState().setView(view))
    const content = screen.getByRole("region", { name: view === "board" ? "Board" : "Calendar" })
    expect(JSON.parse(content.textContent!)).toEqual({ titles: [`fresh ${view}`], scope: { kind: "list", id: "work" }, search: `latest ${view}` })
    expect(screen.getByRole("button", { name: `Header ${view === "calendar" ? 1 : 2}` })).toBe(header)
    expect(screen.getByRole("textbox", { name: "Quick add" })).toBe(quickAdd)
    expect((quickAdd as HTMLInputElement).value).toBe("Draft task")
  }
})
