// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import type { DragEndEvent } from "@dnd-kit/core"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { Task } from "@/api/types"
import { useUi } from "@/stores/ui"
import App from "@/App"

const mocks = vi.hoisted(() => ({ tasks: [] as Task[], create: vi.fn(), update: vi.fn(), dragEnd: (_event: DragEndEvent) => {} }))
vi.mock("@/hooks/api", () => ({
  useTasks: () => ({ data: mocks.tasks }), useLists: () => ({ data: [] }),
  useCreateTask: () => ({ mutate: mocks.create }), useUpdateTask: () => ({ mutate: mocks.update }),
}))
vi.mock("@dnd-kit/core", () => ({
  DndContext: ({ children, onDragEnd }: { children: ReactNode; onDragEnd: typeof mocks.dragEnd }) => { mocks.dragEnd = onDragEnd; return children },
  PointerSensor: class {}, useSensor: vi.fn(), useSensors: vi.fn(),
  useDraggable: () => ({ attributes: {}, listeners: {}, setNodeRef: vi.fn(), isDragging: false }),
  useDroppable: () => ({ setNodeRef: vi.fn(), isOver: false }),
}))
vi.mock("@/components/focus-timer", () => ({ FocusTimer: () => null }))
vi.mock("@/components/header", () => ({ Header: () => null }))
vi.mock("@/components/journal-editor", () => ({ JournalView: () => null }))
vi.mock("@/components/briefing-card", () => ({ BriefingCard: () => null }))
vi.mock("@/components/command-palette", () => ({ CommandPalette: () => null }))
vi.mock("@/components/kanban-board", () => ({ KanbanBoard: () => null }))
vi.mock("@/components/quick-add", () => ({ QuickAdd: () => null }))
vi.mock("@/components/insights", () => ({ InsightsView: () => null }))
vi.mock("@/components/second-brain", () => ({ SecondBrain: () => null }))
vi.mock("@/components/settings", () => ({ SettingsView: () => null }))
vi.mock("@/components/sidebar", () => ({ Sidebar: () => null }))
vi.mock("@/components/task-sections", () => ({ TaskSections: () => null }))
vi.mock("@/components/skeletons", () => ({ KanbanSkeleton: () => null, TaskListSkeleton: () => null }))

function task(id: string, patch: Partial<Task> = {}): Task {
  return { id, title: id, description: null, list_id: null, parent_id: null, priority: 0, status: "todo", due_date: new Date(2026, 2, 8, 9).toISOString(),
    estimated_minutes: null, actual_minutes: 0, recurrence_rule: null, recurrence_series_id: null, recurrence_occurrence: null,
    tags: [], order_index: 0, completed_at: null, created_at: "2026-03-01T00:00:00", updated_at: "2026-03-01T00:00:00", ...patch }
}
function cell(day: string) {
  return within(screen.getByRole("button", { name: `Add task on ${day}` }).parentElement!.parentElement!)
}
function drop(id: string, target: Date | undefined, type = "day") {
  act(() => mocks.dragEnd({ active: { id }, over: target ? { data: { current: { type, date: target } } } : null } as DragEndEvent))
}
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] })
  vi.setSystemTime(new Date(2026, 2, 7, 12))
  useUi.setState({ section: "tasks", view: "calendar", scope: { kind: "smart", id: "all" }, search: "" })
  mocks.tasks = []
  vi.clearAllMocks()
})
afterEach(() => { cleanup(); vi.useRealTimers() })

describe("calendar task context", () => {
  it("follows selected list and title/tag search through the application", () => {
    mocks.tasks = [task("Planning", { list_id: "work" }), task("Other", { list_id: "home" }), task("Review", { list_id: "work", tags: ["PLAN"] })]
    useUi.setState({ scope: { kind: "list", id: "work" }, search: "plan" })
    render(<App />)
    expect(screen.getByRole("button", { name: "Planning" })).toBeTruthy()
    expect(screen.getByRole("button", { name: "Review" })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Other" })).toBeNull()
    act(() => useUi.getState().setSearch("other"))
    expect(screen.queryByRole("button", { name: "Planning" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Other" })).toBeNull()
  })

  it.each([
    { scope: "today", visible: ["overdue", "today"] },
    { scope: "overdue", visible: ["overdue"] },
    { scope: "upcoming", visible: ["tomorrow", "future"] },
    { scope: "all", visible: ["overdue", "today", "tomorrow", "future"] },
    { scope: "completed", visible: ["done"] },
  ] as const)("matches $scope smart scope and excludes canceled tasks", ({ scope, visible }) => {
    mocks.tasks = [
      task("overdue", { due_date: new Date(2026, 2, 6, 23, 59).toISOString() }),
      task("today", { due_date: new Date(2026, 2, 7, 0).toISOString() }),
      task("tomorrow"), task("future", { due_date: new Date(2026, 2, 12, 9).toISOString() }),
      task("done", { status: "completed" }), task("canceled", { status: "canceled" }), task("undated", { due_date: null }),
    ]
    useUi.setState({ scope: { kind: "smart", id: scope } })
    render(<App />)
    for (const id of ["overdue", "today", "tomorrow", "future", "done", "canceled", "undated"]) {
      expect(screen.queryByRole("button", { name: new RegExp(`^${id}`) }) !== null, id).toBe((visible as readonly string[]).includes(id))
    }
  })

  it("creates on the selected local date in the selected list", () => {
    useUi.setState({ scope: { kind: "list", id: "work" } })
    render(<App />)
    fireEvent.click(screen.getByRole("button", { name: "Add task on 2026-03-08" }))
    const input = screen.getByRole("textbox")
    fireEvent.change(input, { target: { value: "  New task  " } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(mocks.create).toHaveBeenCalledWith({ title: "New task", list_id: "work", due_date: new Date(2026, 2, 8, 9).toISOString() })
    expect((input as HTMLInputElement).value).toBe("")
  })

  it("creates an unassigned task from a smart scope and ignores blank titles", () => {
    render(<App />)
    fireEvent.click(screen.getByRole("button", { name: "Add task on 2026-03-08" }))
    const input = screen.getByRole("textbox")
    fireEvent.change(input, { target: { value: "  " } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(mocks.create).not.toHaveBeenCalled()
    fireEvent.change(input, { target: { value: "New task" } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(mocks.create).toHaveBeenCalledWith({ title: "New task", list_id: null, due_date: new Date(2026, 2, 8, 9).toISOString() })
  })
})

describe("calendar dates and rescheduling", () => {
  it("groups naive UTC instants by local date and sorts by time", () => {
    mocks.tasks = [task("Late", { due_date: new Date(2026, 2, 8, 23, 59).toISOString().slice(0, -1) }),
      task("Early", { due_date: new Date(2026, 2, 8, 0, 1).toISOString().slice(0, -1) }),
      task("Next day", { due_date: new Date(2026, 2, 9, 0).toISOString().slice(0, -1) }), task("Invalid", { due_date: "invalid" })]
    render(<App />)
    expect(cell("2026-03-08").getAllByRole("button").slice(1).map(button => button.textContent)).toEqual([
      expect.stringContaining("Early"), expect.stringContaining("Late"),
    ])
    expect(cell("2026-03-09").getByRole("button", { name: /^Next day/ })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Invalid" })).toBeNull()
  })

  it.each([
    { month: 2, from: 7, to: 8, hour: 9, minute: 15 },
    { month: 9, from: 31, to: 1, hour: 9, minute: 15 },
    { month: 9, from: 31, to: 1, hour: 1, minute: 30 },
    { month: 2, from: 7, to: 8, hour: 2, minute: 30 },
  ])("preserves local clock intent across calendar moves: %j", ({ month, from, to, hour, minute }) => {
    const source = new Date(2026, month, from, hour, minute, 42, 123)
    const target = new Date(2026, to === 1 ? month + 1 : month, to)
    mocks.tasks = [task("Move", { due_date: source.toISOString() })]
    render(<App />)
    drop("Move", target)
    const expected = new Date(target.getFullYear(), target.getMonth(), target.getDate(), hour, minute, 42, 123)
    expect(mocks.update).toHaveBeenCalledWith({ id: "Move", patch: { due_date: expected.toISOString() } })
  })

  it("ignores canceled drops, other targets, unknown tasks, unscheduled tasks and same-day moves", () => {
    mocks.tasks = [task("Move"), task("Undated", { due_date: null })]
    render(<App />)
    drop("Move", undefined)
    drop("Move", new Date(2026, 2, 10), "other")
    drop("missing", new Date(2026, 2, 10))
    drop("Undated", new Date(2026, 2, 10))
    drop("Move", new Date(2026, 2, 8))
    expect(mocks.update).not.toHaveBeenCalled()
  })

  it("removes a task date from the selected day's dialog", () => {
    mocks.tasks = [task("Scheduled")]
    render(<App />)
    fireEvent.click(screen.getByRole("button", { name: "Add task on 2026-03-08" }))
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "remove date" }))
    expect(mocks.update).toHaveBeenCalledWith({ id: "Scheduled", patch: { due_date: null } })
  })

  it("navigates year boundaries and returns to today's month", () => {
    vi.setSystemTime(new Date(2026, 11, 31, 12))
    render(<App />)
    fireEvent.click(screen.getByRole("button", { name: "Next month" }))
    expect(screen.getByRole("button", { name: "Add task on 2027-01-31" })).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Previous month" }))
    expect(screen.getByRole("button", { name: "Add task on 2026-12-01" })).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Previous month" }))
    fireEvent.click(screen.getByRole("button", { name: "Today" }))
    expect(screen.getByRole("button", { name: "Add task on 2026-12-31" })).toBeTruthy()
  })
})
