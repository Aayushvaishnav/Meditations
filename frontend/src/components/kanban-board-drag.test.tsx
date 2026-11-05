// @vitest-environment jsdom
import { act, cleanup, render } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import type { ReactNode } from "react"
import type { DragEndEvent } from "@dnd-kit/core"
import type { Task } from "@/api/types"
import { KanbanBoard } from "./kanban-board"

const drag = vi.hoisted(() => ({ end: (_event: DragEndEvent) => {}, mutate: vi.fn() }))
vi.mock("@/hooks/api", () => ({ useUpdateTask: () => ({ mutate: drag.mutate }) }))
vi.mock("@/components/task-item", () => ({ TaskCheckbox: () => null }))
vi.mock("@dnd-kit/core", () => ({
  DndContext: ({ children, onDragEnd }: { children: ReactNode; onDragEnd: typeof drag.end }) => { drag.end = onDragEnd; return children },
  DragOverlay: () => null, KeyboardSensor: class {}, PointerSensor: class {},
  useDroppable: () => ({}), useSensor: () => ({}), useSensors: () => [],
}))
vi.mock("@dnd-kit/sortable", () => ({
  SortableContext: ({ children }: { children: ReactNode }) => children,
  useSortable: () => ({}), sortableKeyboardCoordinates: () => {}, verticalListSortingStrategy: () => {},
}))
function task(id: string, patch: Partial<Task> = {}): Task {
  return { id, title: id, description: null, list_id: "work", parent_id: null,
    priority: 0, importance: "unassigned", urgency: "unassigned", status: "todo",
    deadline: { kind: "none" }, due_date: null, estimated_minutes: null, actual_minutes: 0,
    recurrence_rule: null, recurrence_series_id: null, recurrence_occurrence: null,
    tags: [], order_index: 0, completed_at: null, created_at: "2026-11-01T00:00:00",
    updated_at: "2026-11-01T00:00:00", ...patch }
}
function drop(id: string, target: string, status?: Task["status"]) {
  act(() => drag.end({
    activatorEvent: new Event("pointerup"), collisions: [], delta: { x: 0, y: 0 },
    active: { id, data: { current: {} }, rect: { current: { initial: null, translated: null } } },
    over: {
      id: target, disabled: false,
      rect: { top: 0, left: 0, bottom: 100, right: 100, width: 100, height: 100 },
      data: { current: status ? { type: "column", status } : { type: "task" } },
    },
  }))
}
afterEach(() => { cleanup(); drag.mutate.mockClear() })
const scope = { kind: "list", id: "work" } as const

it("moves to an empty status column without changing list membership or deadline", () => {
  const rows = [task("move"), task("foreign", { list_id: "home", status: "in_progress", order_index: 5000 })]
  render(<KanbanBoard tasks={rows} scope={scope} />)
  drop("move", "col-in_progress", "in_progress")
  expect(drag.mutate).toHaveBeenCalledExactlyOnceWith({ id: "move", patch: { status: "in_progress", order_index: 1000 } })
  expect(rows[0]).toMatchObject({ list_id: "work", deadline: { kind: "none" }, status: "todo" })
})
it("orders only against scope/search-visible neighbors", () => {
  render(<KanbanBoard tasks={[
    task("match move"), task("match prev", { order_index: 100 }), task("match next", { order_index: 300 }),
    task("hidden", { order_index: 290 }), task("match foreign", { list_id: "home", order_index: 299 }),
  ]} scope={scope} search="match" />)
  drop("match move", "match next")
  expect(drag.mutate).toHaveBeenCalledExactlyOnceWith({ id: "match move", patch: { order_index: 200 } })
})
it("inserts after the displayed Done cards instead of hidden overflow", () => {
  render(<KanbanBoard tasks={[task("move"), ...Array.from({ length: 35 }, (_, i) => task(`done-${i}`, { status: "completed", order_index: i * 1000 }))]} scope={scope} />)
  drop("move", "col-completed", "completed")
  expect(drag.mutate).toHaveBeenCalledExactlyOnceWith({ id: "move", patch: { status: "completed", order_index: 30000 } })
})
it("does not mutate a source excluded by a scope or search change during drag", () => {
  const rows = [task("move"), task("target", { status: "in_progress" })]
  const mounted = render(<KanbanBoard tasks={rows} scope={scope} />)
  mounted.rerender(<KanbanBoard tasks={rows} scope={{ kind: "list", id: "home" }} />)
  drop("move", "col-completed", "completed")
  mounted.rerender(<KanbanBoard tasks={rows} scope={scope} search="target" />)
  drop("move", "col-completed", "completed")
  expect(drag.mutate).not.toHaveBeenCalled()
})
it("does not use a card target excluded by scope", () => {
  render(<KanbanBoard tasks={[task("move"), task("foreign", { list_id: "home" })]} scope={scope} />)
  drop("move", "foreign")
  expect(drag.mutate).not.toHaveBeenCalled()
})
