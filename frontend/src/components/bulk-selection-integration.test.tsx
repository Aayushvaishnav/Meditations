// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import type { Task } from "@/api/types"
import { useUi } from "@/stores/ui"
import { TasksView } from "./tasks-view"
import { MatrixSection } from "./matrix-section"

const state = vi.hoisted(() => ({ tasks: [] as Task[], mutate: vi.fn(), mutateAsync: vi.fn() }))
vi.mock("@/hooks/api", () => ({
  useTasks: () => ({ data: state.tasks, isLoading: false, isError: false }),
  useLists: () => ({ data: [] }),
  useUpdateTask: () => ({ mutate: state.mutate, mutateAsync: state.mutateAsync }),
  useCreateTask: () => ({ mutate: vi.fn(), isPending: false }),
  useDecomposeTask: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteTask: () => ({ mutate: vi.fn(), isPending: false }),
}))
vi.mock("@/components/header", () => ({ Header: () => null }))
vi.mock("@/components/quick-add", () => ({ QuickAdd: () => null }))
vi.mock("@/components/briefing-card", () => ({ BriefingCard: () => null }))
vi.mock("@/components/calendar-view", () => ({ CalendarView: () => <div>Calendar content</div> }))

function task(id: string, patch: Partial<Task> = {}): Task {
  return { id, title: id, description: null, list_id: "work", parent_id: null,
    priority: 0, importance: "unassigned", urgency: "unassigned", status: "todo",
    deadline: { kind: "none" }, due_date: null, estimated_minutes: null, actual_minutes: 0,
    recurrence_rule: null, recurrence_series_id: null, recurrence_occurrence: null,
    tags: [], order_index: 0, completed_at: null, created_at: "2026-11-01T00:00:00",
    updated_at: "2026-11-01T00:00:00", ...patch }
}
async function mount(matrix = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  let view!: ReturnType<typeof render>
  await act(async () => {
    view = render(<QueryClientProvider client={client}>{matrix ? <MatrixSection /> : <TasksView />}</QueryClientProvider>)
    await import("@/components/kanban-board")
  })
  return view
}
function startSelection() { fireEvent.click(screen.getByRole("button", { name: "Select tasks" })) }
function selection(title: string) { return screen.getByRole("checkbox", { name: `Select "${title}"` }) as HTMLInputElement }
function selectableTitles() {
  return screen.queryAllByRole("checkbox", { name: /^Select "/ }).map(input => input.getAttribute("aria-label")!.slice(8, -1)).sort()
}
beforeEach(() => {
  state.tasks = [task("Parent"), task("Child", { parent_id: "Parent" })]
  state.mutate.mockReset()
  state.mutateAsync.mockReset().mockResolvedValue(undefined)
  useUi.setState({ view: "list", scope: { kind: "list", id: "work" }, search: "" })
})
afterEach(() => { cleanup(); useUi.setState(useUi.getInitialState()); localStorage.clear() })

it("expands immediate list subtasks for independent selection without completing either task", async () => {
  await mount()
  expect(screen.queryByRole("checkbox", { name: 'Select "Child"' })).toBeNull()
  startSelection()
  expect(selectableTitles()).toEqual(["Child", "Parent"])
  fireEvent.click(selection("Parent"))
  expect(selection("Parent").checked).toBe(true)
  expect(selection("Child").checked).toBe(false)
  fireEvent.click(selection("Child"))
  expect(selection("Child").checked).toBe(true)
  expect(state.mutate).not.toHaveBeenCalled()
  expect(state.mutateAsync).not.toHaveBeenCalled()
})

it("selects only rendered Board cards, excluding subtasks and completed cards beyond the Done cap", async () => {
  useUi.setState({ view: "board" })
  state.tasks = [task("Parent"), task("Child", { parent_id: "Parent" }),
    ...Array.from({ length: 35 }, (_, i) => task(`Done ${i}`, { status: "completed" })),
    task("Canceled", { status: "canceled" })]
  await mount()
  startSelection()
  expect(selectableTitles()).toHaveLength(31)
  expect(selectableTitles()).toContain("Parent")
  expect(selectableTitles()).not.toContain("Child")
  expect(selectableTitles()).not.toContain("Canceled")
  fireEvent.click(screen.getByRole("button", { name: "Select all visible" }))
  expect(screen.getAllByRole("checkbox", { name: /^Select "/ }).every(input => (input as HTMLInputElement).checked)).toBe(true)
  expect(screen.getByText("31 selected")).toBeTruthy()
})

it.each(["scope", "search", "view"] as const)("clears selection on %s navigation", async change => {
  await mount()
  startSelection()
  fireEvent.click(selection("Parent"))
  act(() => {
    if (change === "scope") useUi.setState({ scope: { kind: "smart", id: "all" } })
    if (change === "search") useUi.setState({ search: "Parent" })
    if (change === "view") useUi.setState({ view: "board" })
  })
  expect(screen.queryByRole("region", { name: "Bulk task actions" })).toBeNull()
  startSelection()
  expect(screen.getByText("0 selected")).toBeTruthy()
  expect(selection("Parent").checked).toBe(false)
})

it("uses the same independent selection controls in Matrix and only selects active tasks", async () => {
  state.tasks = [task("Parent"), task("Child", { parent_id: "Parent" }),
    task("In progress", { status: "in_progress", list_id: "home" }),
    task("Completed", { status: "completed" }), task("Canceled", { status: "canceled" })]
  await mount(true)
  startSelection()
  expect(selectableTitles()).toEqual(["Child", "In progress", "Parent"])
  fireEvent.click(selection("Parent"))
  expect(selection("Child").checked).toBe(false)
  expect(selection("In progress").checked).toBe(false)
  fireEvent.click(screen.getByRole("button", { name: "Select all visible" }))
  expect(screen.getByText("3 selected")).toBeTruthy()
  act(() => useUi.setState({ search: "Parent" }))
  startSelection()
  expect(screen.getByText("0 selected")).toBeTruthy()
  expect(selectableTitles()).toEqual(["Parent"])
})

it("does not offer bulk selection in Calendar", async () => {
  useUi.setState({ view: "calendar" })
  await mount()
  expect(await screen.findByText("Calendar content")).toBeTruthy()
  expect(screen.queryByRole("button", { name: "Select tasks" })).toBeNull()
  expect(selectableTitles()).toEqual([])
})

it.each(["scope", "search", "view", "section"] as const)("stops unsent bulk edits after pending %s navigation", async change => {
  let resolve!: () => void
  state.mutateAsync.mockImplementationOnce(() => new Promise<void>(done => { resolve = done }))
  const view = await mount()
  startSelection()
  fireEvent.click(screen.getByRole("button", { name: "Select all visible" }))
  fireEvent.change(screen.getByLabelText("New status"), { target: { value: "in_progress" } })
  fireEvent.click(screen.getByRole("button", { name: "Review changes" }))
  fireEvent.click(screen.getByRole("button", { name: "Confirm changes" }))
  expect(state.mutateAsync).toHaveBeenCalledTimes(1)
  act(() => {
    if (change === "scope") useUi.setState({ scope: { kind: "smart", id: "all" } })
    if (change === "search") useUi.setState({ search: "Parent" })
    if (change === "view") useUi.setState({ view: "board" })
    if (change === "section") view.unmount()
  })
  await act(async () => resolve())
  expect(state.mutateAsync).toHaveBeenCalledTimes(1)
})
