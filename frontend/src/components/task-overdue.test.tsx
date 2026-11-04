// @vitest-environment jsdom
import { act, cleanup, render } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import type { Task } from "@/api/types"
import { localDayParam } from "@/lib/task-deadlines"
import { TaskItem } from "./task-item"
import { KanbanBoard } from "./kanban-board"
import { CalendarView } from "./calendar-view"

vi.mock("@/hooks/api", () => ({
  useCalendarConnections: () => ({ data: [], isSuccess: true }),
  useInboundOverlay: () => ({ data: undefined }),
  useImportedCalendars: () => ({ data: [], isSuccess: true }),
  useImportedCalendarOverlay: () => ({ data: undefined }),
  useCalendarExport: () => ({ mutate: vi.fn(), isPending: false, isSuccess: false, isError: false }),
  useTimeBlocks: () => ({ data: [], isPending: false, isError: false }),
  useReplaceTimeBlock: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateTask: () => ({ mutate: vi.fn() }),
  useCreateTask: () => ({ mutate: vi.fn() }),
  useDeleteTask: () => ({ mutate: vi.fn() }),
  useDecomposeTask: () => ({ mutate: vi.fn() }),
}))

function task(status: Task["status"] = "todo"): Task {
  return {
    id: "task", title: "Deadline task", description: null, list_id: null, parent_id: null,
    priority: 0, importance: "unassigned", urgency: "unassigned", status, due_date: new Date(Date.now() + 1000).toISOString(),
    deadline: { kind: "timed", at: new Date(Date.now() + 1000).toISOString() },
    estimated_minutes: null, actual_minutes: 0, recurrence_rule: null,
    recurrence_series_id: null, recurrence_occurrence: null, tags: [], order_index: 0,
    completed_at: null, created_at: "2026-11-01T00:00:00", updated_at: "2026-11-01T00:00:00",
  }
}
const views = {
  list: (t: Task) => <TaskItem task={t} subtasks={[]} lists={[]} />,
  board: (t: Task) => <KanbanBoard tasks={[t]} />,
  calendar: (t: Task) => <CalendarView tasks={[t]} scope={{ kind: "smart", id: "all" }} search="" />,
}
beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date("2026-11-02T12:00:00Z"))
})
afterEach(() => { cleanup(); vi.useRealTimers() })

it.each(Object.entries(views))("updates the %s overdue indicator while idle", (_name, view) => {
  const { container } = render(view(task()))
  expect(container.querySelector(".text-overdue, .bg-overdue")).toBeNull()
  act(() => vi.advanceTimersByTime(1001))
  expect(container.querySelector(".text-overdue, .bg-overdue")).not.toBeNull()
})

it.each(Object.entries(views))("does not mark completed tasks overdue in the %s view", (_name, view) => {
  const { container } = render(view(task("completed")))
  act(() => vi.advanceTimersByTime(1001))
  expect(container.querySelector(".text-overdue, .bg-overdue")).toBeNull()
})

it.each(Object.entries(views))("keeps date-only deadlines current through the entire local day in the %s view", (_name, view) => {
  vi.setSystemTime(new Date(2026, 10, 2, 23, 59, 59, 999))
  const t = { ...task(), due_date: null, deadline: { kind: "date" as const, date: localDayParam(new Date()) } }
  const { container } = render(view(t))
  expect(container.querySelector(".text-overdue, .bg-overdue")).toBeNull()
  act(() => vi.advanceTimersByTime(1))
  expect(container.querySelector(".text-overdue, .bg-overdue")).not.toBeNull()
})
