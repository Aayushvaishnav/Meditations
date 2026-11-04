// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import type { Task } from "@/api/types"
import { MATRIX_ZONES } from "@/lib/eisenhower"
import { EisenhowerMatrix } from "./eisenhower-matrix"

const api = vi.hoisted(() => ({ update: vi.fn(), move: vi.fn(), create: vi.fn(), pending: false, error: false }))
vi.mock("@/hooks/api", () => ({
  useUpdateTask: () => ({ mutate: api.update, mutateAsync: api.move }),
  useCreateTask: () => ({ mutate: api.create, isPending: api.pending, isError: api.error }),
  useDeleteTask: () => ({ mutate: vi.fn() }),
  useDecomposeTask: () => ({ mutate: vi.fn(), isPending: false }),
}))
function task(id: string, patch: Partial<Task> = {}): Task {
  return { id, title: id, description: "Details", list_id: "work", parent_id: null,
    priority: 3, importance: "unassigned", urgency: "unassigned", status: "todo",
    deadline: { kind: "date", date: "2099-11-05" }, due_date: null,
    estimated_minutes: 25, actual_minutes: 0, recurrence_rule: "FREQ=DAILY",
    recurrence_series_id: "series", recurrence_occurrence: 1, tags: ["review"], order_index: 0,
    completed_at: null, created_at: "2026-11-01T00:00:00", updated_at: "2026-11-01T00:00:00", ...patch }
}
const all = { kind: "smart", id: "all" } as const
const lists = [{ id: "work", name: "Work", color: "blue", icon: null, is_favorite: false, created_at: "2026-11-01" }]
function view(tasks: Task[], scope: Parameters<typeof EisenhowerMatrix>[0]["scope"] = all, search = "") {
  return <EisenhowerMatrix tasks={tasks} lists={lists} scope={scope} search={search} />
}
function selector(title: string) { return screen.getByRole("combobox", { name: `Move "${title}" to quadrant` }) }
let resolveMove: () => void
let rejectMove: (error: Error) => void
beforeEach(() => {
  vi.clearAllMocks(); api.pending = false; api.error = false
  api.move.mockImplementation(() => new Promise<void>((resolve, reject) => { resolveMove = resolve; rejectMove = reject }))
})
afterEach(cleanup)

it("places tasks in all five regions and describes partial classifications", () => {
  render(view([...MATRIX_ZONES.map(z => task(z.id, { importance: z.importance, urgency: z.urgency })),
    task("partial importance", { importance: "important" }), task("partial urgency", { urgency: "urgent" })]))
  for (const zone of MATRIX_ZONES) {
    expect(within(screen.getByRole("region", { name: zone.label })).getByRole("article", { name: zone.id })).toBeTruthy()
  }
  expect(screen.getByText("Classification: important, urgency unassigned")).toBeTruthy()
  expect(screen.getByText("Classification: importance unassigned, urgent")).toBeTruthy()
})

it("filters scope and search while rendering a matching subtask exactly once without nesting", () => {
  render(view([task("parent", { tags: [] }), task("child", { title: "Review child", parent_id: "parent" }),
    task("other", { title: "Review other", list_id: "other" }), task("done", { title: "Review done", status: "completed" })],
  { kind: "list", id: "work" }, "review"))
  expect(screen.getAllByRole("article").map(a => a.getAttribute("aria-label"))).toEqual(["Review child"])
  expect(screen.getByText("Subtask of parent")).toBeTruthy()
  expect(screen.queryByRole("button", { name: "Expand subtasks" })).toBeNull()
})

it("completes through the real shared TaskCheckbox and retains the existing task options", () => {
  render(view([task("check")]))
  fireEvent.click(screen.getByRole("checkbox", { name: 'Complete "check"' }))
  expect(api.update).toHaveBeenCalledExactlyOnceWith({ id: "check", patch: { status: "completed" } })
  fireEvent.click(screen.getByRole("button", { name: 'Options for "check"' }))
  for (const name of ["Focus on this", "Break down with AI", "Rename", "Priority", "Deadline", "Move to list", "Delete"]) {
    expect(screen.getByRole("menuitem", { name })).toBeTruthy()
  }
})

it.each(MATRIX_ZONES.filter(z => z.id !== "unclassified"))("moves via the accessible selector to $id using only classification fields", async zone => {
  const original = task("move")
  const snapshot = structuredClone(original)
  render(view([original]))
  const select = selector("move") as HTMLSelectElement
  select.focus()
  expect(document.activeElement).toBe(select)
  expect(Array.from(select.options).map(o => o.value)).toEqual(MATRIX_ZONES.map(z => z.id))
  fireEvent.change(select, { target: { value: zone.id } })
  expect(api.move.mock.calls[0][0]).toEqual({ id: "move", patch: { importance: zone.importance, urgency: zone.urgency } })
  expect(original).toEqual(snapshot)
  expect(within(screen.getByRole("article", { name: "move" })).getByRole("status").textContent).toContain("Saving classification")
  expect(select.disabled).toBe(true)
  await act(async () => resolveMove())
  expect(select.disabled).toBe(false)
  expect(document.activeElement).toBe(select)
})

it.each([
  ["Importance", "important", { importance: "important", urgency: "urgent" }],
  ["Urgency", "not_urgent", { importance: "unassigned", urgency: "not_urgent" }],
] as const)("assigns %s independently and supports reset", async (label, value, patch) => {
  render(view([task("partial", { urgency: "urgent" })]))
  fireEvent.click(screen.getByText("Classification: importance unassigned, urgent"))
  fireEvent.change(screen.getByRole("combobox", { name: `${label} for "partial"` }), { target: { value } })
  expect(api.move.mock.calls[0][0]).toEqual({ id: "partial", patch })
  await act(async () => resolveMove())
  fireEvent.click(screen.getByRole("button", { name: "Reset classification" }))
  expect(api.move.mock.calls[1][0]).toEqual({ id: "partial", patch: { importance: "unassigned", urgency: "unassigned" } })
})

it("unlocks failed moves for retry and suppresses duplicate in-flight moves", async () => {
  render(view([task("retry")]))
  fireEvent.change(selector("retry"), { target: { value: "do" } })
  fireEvent.change(selector("retry"), { target: { value: "schedule" } })
  expect(api.move).toHaveBeenCalledTimes(1)
  await act(async () => rejectMove(new Error("failed")))
  expect(screen.getByRole("alert").textContent).toContain("Classification could not be saved")
  fireEvent.change(selector("retry"), { target: { value: "delegate" } })
  expect(api.move).toHaveBeenCalledTimes(2)
  expect(screen.queryByRole("alert")).toBeNull()
})

it.each(MATRIX_ZONES)("creates in $id with selected-list classification and clears only on success", zone => {
  render(view([], { kind: "list", id: "work" }))
  const region = within(screen.getByRole("region", { name: zone.label }))
  const input = region.getByRole("textbox") as HTMLInputElement
  fireEvent.change(input, { target: { value: "  New task  " } })
  fireEvent.click(region.getByRole("button", { name: "Add task" }))
  expect(api.create.mock.calls[0][0]).toEqual({ title: "New task", importance: zone.importance, urgency: zone.urgency, list_id: "work" })
  expect(input.value).toBe("  New task  ")
  act(() => api.create.mock.calls[0][1].onSuccess())
  expect(input.value).toBe("")
})

it("retains a different creation draft typed while the submitted task is pending", () => {
  const rendered = render(view([]))
  const region = within(screen.getByRole("region", { name: "Unclassified" }))
  const input = region.getByRole("textbox") as HTMLInputElement
  fireEvent.change(input, { target: { value: "Submitted task" } })
  fireEvent.click(region.getByRole("button", { name: "Add task" }))
  const onSuccess = api.create.mock.calls[0][1].onSuccess
  api.pending = true
  rendered.rerender(view([]))
  fireEvent.change(input, { target: { value: "Next task draft" } })
  expect(input.disabled).toBe(false)
  expect(api.create).toHaveBeenCalledTimes(1)
  api.pending = false
  rendered.rerender(view([]))
  act(() => onSuccess())
  expect(input.value).toBe("Next task draft")
  fireEvent.click(region.getByRole("button", { name: "Add task" }))
  expect(api.create.mock.calls[1][0].title).toBe("Next task draft")
})

it("keeps failed creation titles, blocks pending submission, and uses unclassified defaults without a selected list", () => {
  const rendered = render(view([]))
  const region = () => within(screen.getByRole("region", { name: "Unclassified" }))
  const input = region().getByRole("textbox") as HTMLInputElement
  expect((region().getByRole("button", { name: "Add task" }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.change(input, { target: { value: "Draft" } })
  fireEvent.click(region().getByRole("button", { name: "Add task" }))
  expect(api.create.mock.calls[0][0]).toEqual({ title: "Draft", importance: "unassigned", urgency: "unassigned" })
  api.pending = true
  rendered.rerender(view([]))
  expect((region().getByRole("button", { name: "Adding…" }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.submit(input.closest("form")!)
  expect(api.create).toHaveBeenCalledTimes(1)
  api.pending = false; api.error = true
  rendered.rerender(view([]))
  expect(region().getByRole("alert").textContent).toContain("Task could not be added")
  expect(input.value).toBe("Draft")
  fireEvent.click(region().getByRole("button", { name: "Add task" }))
  expect(api.create).toHaveBeenCalledTimes(2)
})

it("settles concurrent task moves independently even when the later move fails first", async () => {
  render(view([task("first"), task("second")]))
  fireEvent.change(selector("first"), { target: { value: "do" } })
  const firstResolve = resolveMove
  fireEvent.change(selector("second"), { target: { value: "schedule" } })
  expect(api.move).toHaveBeenCalledTimes(2)
  await act(async () => rejectMove(new Error("second failed")))
  const first = within(screen.getByRole("article", { name: "first" }))
  const second = within(screen.getByRole("article", { name: "second" }))
  expect(first.getByRole("status")).toBeTruthy()
  expect(second.getByRole("alert")).toBeTruthy()
  expect((selector("first") as HTMLSelectElement).disabled).toBe(true)
  expect((selector("second") as HTMLSelectElement).disabled).toBe(false)
  await act(async () => firstResolve())
  expect(first.queryByRole("status")).toBeNull()
  expect(second.getByRole("alert")).toBeTruthy()
  expect((selector("first") as HTMLSelectElement).disabled).toBe(false)
})
