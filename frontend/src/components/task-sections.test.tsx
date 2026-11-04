// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import type { Task } from "@/api/types"
import { deadlineFromLegacy } from "@/lib/task-deadlines"
import { TaskSections } from "./task-sections"

vi.mock("@/components/task-item", () => ({
  TaskItem: ({ task, subtasks }: { task: Task; subtasks: Task[] }) => <div>{task.title}{subtasks.map(child => <span key={child.id}>{child.title}</span>)}</div>,
}))
function task(id: string, patch: Partial<Task> = {}): Task {
  return { id, title: id, description: null, list_id: "work", parent_id: null, priority: 0, importance: "unassigned", urgency: "unassigned", status: "todo", due_date: null, deadline: deadlineFromLegacy(patch.due_date ?? null),
    estimated_minutes: null, actual_minutes: 0, recurrence_rule: null, recurrence_series_id: null, recurrence_occurrence: null,
    tags: [], order_index: 0, completed_at: null, created_at: "2026-03-01T00:00:00", updated_at: "2026-03-01T00:00:00", ...patch }
}
beforeEach(() => { vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date(2026, 2, 7, 12)) })
afterEach(() => { cleanup(); vi.useRealTimers() })
it("applies list and terminal-status filtering to nested subtasks", () => {
  const tasks = [task("Parent"), task("Active", { parent_id: "Parent" }), task("Canceled", { parent_id: "Parent", status: "canceled" }),
    task("Finished", { parent_id: "Parent", status: "completed" }), task("Home", { parent_id: "Parent", list_id: "home" })]
  render(<TaskSections tasks={tasks} scope={{ kind: "list", id: "work" }} search="" lists={[]} />)
  expect(screen.getByText("Active")).toBeTruthy()
  for (const title of ["Canceled", "Finished", "Home"]) expect(screen.queryByText(title)).toBeNull()
})
it("shows a matching child when its parent is outside the active filter", () => {
  const tasks = [task("Parent"), task("Matching child", { parent_id: "Parent" })]
  render(<TaskSections tasks={tasks} scope={{ kind: "list", id: "work" }} search="matching" lists={[]} />)
  expect(screen.getByText("Matching child")).toBeTruthy()
  expect(screen.queryByText("Parent")).toBeNull()
})
