// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import type { Task } from "@/api/types"
import App from "./App"
import { useUi } from "@/stores/ui"

const query = vi.hoisted(() => ({ isLoading: true, isError: false, data: [] as Task[], refetch: vi.fn() }))
vi.mock("@/hooks/api", () => ({
  useTasks: () => query,
  useLists: () => ({ data: [] }),
  useResumeCalendarReconciliation: () => {},
  useUpdateTask: () => ({ mutateAsync: vi.fn() }),
  useCreateTask: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
}))
vi.mock("@/components/task-item", () => ({ TaskItem: ({ task }: { task: Task }) => <span>{task.title}</span> }))
vi.mock("@/components/sidebar", () => ({ Sidebar: () => null }))
vi.mock("@/components/focus-timer", () => ({ FocusTimer: () => null }))
vi.mock("@/components/command-palette", () => ({ CommandPalette: () => null }))
vi.mock("@/components/header", () => ({ Header: () => <h1>Tasks</h1> }))
vi.mock("@/components/quick-add", () => ({ QuickAdd: () => null }))
vi.mock("@/components/briefing-card", () => ({ BriefingCard: () => null }))
vi.mock("@/components/calendar-view", () => ({ CalendarView: () => null }))
vi.mock("@/components/kanban-board", () => ({ KanbanBoard: () => null }))
vi.mock("@/components/task-sections", () => ({ TaskSections: () => null }))
afterEach(() => { cleanup(); useUi.setState(useUi.getInitialState()); localStorage.clear() })

it.each(["list", "board", "calendar"] as const)("loads Matrix independently of the %s task view with retry support", async (view) => {
  useUi.setState({ section: "matrix", view, scope: { kind: "smart", id: "completed" } })
  query.refetch.mockClear()
  query.data = []
  query.isLoading = true; query.isError = false
  let mounted!: ReturnType<typeof render>
  await act(async () => { mounted = render(<App />); await import("@/components/matrix-section") })
  expect(screen.getByLabelText("Loading tasks").getAttribute("aria-busy")).toBe("true")
  expect(screen.queryByRole("region", { name: "Unclassified" })).toBeNull()
  query.isLoading = false; query.isError = true
  mounted.rerender(<App />)
  fireEvent.click(screen.getByRole("button", { name: "Retry" }))
  expect(query.refetch).toHaveBeenCalledOnce()
  expect(screen.queryByRole("region", { name: "Unclassified" })).toBeNull()
  query.isError = false
  mounted.rerender(<App />)
  expect(screen.getAllByRole("region")).toHaveLength(5)
  expect(screen.getByRole("region", { name: "Unclassified" })).toBeTruthy()
})

function task(id: string, patch: Partial<Task> = {}): Task {
  return { id, title: id, description: null, list_id: "other", parent_id: null,
    priority: 0, importance: "unassigned", urgency: "unassigned", status: "todo",
    deadline: { kind: "none" }, due_date: null, estimated_minutes: null, actual_minutes: 0,
    recurrence_rule: null, recurrence_series_id: null, recurrence_occurrence: null,
    tags: [], order_index: 0, completed_at: null, created_at: "2026-11-01T00:00:00",
    updated_at: "2026-11-01T00:00:00", ...patch }
}

it.each([
  { kind: "smart", id: "today" },
  { kind: "smart", id: "completed" },
  { kind: "list", id: "work" },
] as const)("shows all active tasks regardless of saved scope $kind/$id, while applying search", async (scope) => {
  useUi.setState({ section: "matrix", view: "calendar", scope, search: "review" })
  query.isLoading = false; query.isError = false
  query.data = [task("review other list"), task("review in progress", { status: "in_progress" }),
    task("review child", { parent_id: "parent" }), task("review completed", { status: "completed" }),
    task("review canceled", { status: "canceled" }), task("unrelated")]
  await act(async () => { render(<App />); await import("@/components/matrix-section") })
  expect(screen.getAllByRole("article").map(card => card.getAttribute("aria-label"))).toEqual(
    expect.arrayContaining(["review other list", "review in progress", "review child"]),
  )
  expect(screen.getAllByRole("article")).toHaveLength(3)
  expect(useUi.getState()).toMatchObject({ section: "matrix", view: "calendar", scope, search: "review" })
})
