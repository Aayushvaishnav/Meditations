// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { Task } from "@/api/types"
import { useUi, type Scope } from "@/stores/ui"
import { TasksView } from "./tasks-view"

const state = vi.hoisted(() => ({ tasks: [] as Task[], mutate: vi.fn() }))
vi.mock("@/hooks/api", () => ({
  useTasks: () => ({ data: state.tasks, isLoading: false, isError: false }),
  useLists: () => ({ data: [] }),
  useUpdateTask: () => ({ mutate: state.mutate }),
}))
vi.mock("@/components/header", () => ({ Header: () => null }))
vi.mock("@/components/quick-add", () => ({ QuickAdd: () => null }))
vi.mock("@/components/briefing-card", () => ({ BriefingCard: () => null }))
vi.mock("@/components/calendar-view", () => ({ CalendarView: () => null }))
vi.mock("@/components/task-sections", () => ({ TaskSections: () => null }))

function task(id: string, patch: Partial<Task> = {}): Task {
  return { id, title: id, description: null, list_id: "work", parent_id: null,
    priority: 0, importance: "unassigned", urgency: "unassigned", status: "todo",
    deadline: { kind: "none" }, due_date: null, estimated_minutes: null, actual_minutes: 0,
    recurrence_rule: null, recurrence_series_id: null, recurrence_occurrence: null,
    tags: [], order_index: 0, completed_at: null, created_at: "2026-11-01T00:00:00",
    updated_at: "2026-11-01T00:00:00", ...patch }
}
const rows = [
  task("overdue", { deadline: { kind: "date", date: "2026-11-01" } }),
  task("today", { deadline: { kind: "date", date: "2026-11-02" } }),
  task("tomorrow", { deadline: { kind: "date", date: "2026-11-03" } }),
  task("future", { deadline: { kind: "date", date: "2026-11-10" }, status: "in_progress" }),
  task("undated"), task("done", { status: "completed" }),
  task("home", { list_id: "home" }), task("home done", { list_id: "home", status: "completed" }),
  task("canceled", { status: "canceled" }), task("child", { parent_id: "undated" }),
  task("done child", { parent_id: "undated", status: "completed" }),
]
function titles() { return screen.queryAllByRole("checkbox").map(button => button.getAttribute("aria-label")!.split('"')[1]).sort() }
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(new Date(2026, 10, 2, 12))
  state.tasks = rows; state.mutate.mockClear()
  useUi.setState({ view: "board", scope: { kind: "list", id: "work" }, search: "" })
})
afterEach(() => { cleanup(); vi.useRealTimers(); useUi.setState(useUi.getInitialState()); localStorage.clear() })

describe("Board scope integration", () => {
  it("switches lists while mounted and keeps only each list's top-level active and Done cards", async () => {
    await act(async () => { render(<TasksView />); await import("@/components/kanban-board") })
    expect(titles()).toEqual(["done", "future", "overdue", "today", "tomorrow", "undated"])
    act(() => useUi.getState().setScope({ kind: "list", id: "home" }))
    expect(titles()).toEqual(["home", "home done"])
    fireEvent.click(screen.getByRole("checkbox", { name: 'Complete "home"' }))
    expect(state.mutate).toHaveBeenCalledWith({ id: "home", patch: { status: "completed" } })
  })
  it.each([
    ["today", ["overdue", "today"]], ["overdue", ["overdue"]],
    ["upcoming", ["future", "tomorrow"]], ["completed", ["done", "home done"]],
    ["all", ["done", "future", "home", "home done", "overdue", "today", "tomorrow", "undated"]],
  ] as const)("respects the %s smart scope", async (id, expected) => {
    useUi.setState({ scope: { kind: "smart", id } as Scope })
    await act(async () => { render(<TasksView />); await import("@/components/kanban-board") })
    expect(titles()).toEqual(expected)
  })
  it("intersects title and tag search with scope, and clears an empty search result", async () => {
    state.tasks = [...rows, task("tagged", { tags: ["review"] }), task("foreign review", { list_id: "home" })]
    useUi.setState({ search: "review" })
    await act(async () => { render(<TasksView />); await import("@/components/kanban-board") })
    expect(titles()).toEqual(["tagged"])
    act(() => useUi.setState({ search: "absent" }))
    expect(titles()).toEqual([])
    fireEvent.click(screen.getByRole("button", { name: "Clear filter" }))
    expect(useUi.getState().search).toBe("")
    expect(titles()).toContain("tagged")
  })
  it("applies the Done cap after scope and search selection", async () => {
    state.tasks = [...Array.from({ length: 35 }, (_, i) => task(`done ${i}`, { status: "completed" })), task("foreign done", { list_id: "home", status: "completed" })]
    await act(async () => { render(<TasksView />); await import("@/components/kanban-board") })
    expect(titles()).toHaveLength(30)
    expect(screen.queryByText("foreign done")).toBeNull()
    expect(screen.getByText(/\+5 older completed/)).toBeTruthy()
    act(() => useUi.setState({ search: "done 34" }))
    expect(titles()).toEqual(["done 34"])
  })
})
