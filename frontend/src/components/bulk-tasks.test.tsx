// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { Task, TaskList } from "@/api/types"
import { BulkTaskCheckbox, BulkTasksProvider, BulkTaskToolbar } from "./bulk-tasks"

const { mutateAsync } = vi.hoisted(() => ({ mutateAsync: vi.fn() }))
vi.mock("@/hooks/api", () => ({ useUpdateTask: () => ({ mutateAsync }) }))

const clients: QueryClient[] = []
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); mutateAsync.mockReset() })

function task(id: string, patch: Partial<Task> = {}): Task {
  return { id, title: id, tags: ["keep"], recurrence_rule: null, list_id: null,
    parent_id: null, description: null, priority: 0, importance: "unassigned", urgency: "unassigned",
    status: "todo", deadline: { kind: "none" }, due_date: null, estimated_minutes: null,
    actual_minutes: 0, recurrence_series_id: null, recurrence_occurrence: null,
    order_index: 0, completed_at: null, created_at: "2026-01-01", updated_at: "2026-01-01", ...patch }
}
const initial = [task("one", { title: "First", recurrence_rule: "FREQ=DAILY" }), task("two", { title: "Second" })]
function setup(tasks = initial, lists: TaskList[] = []) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  clients.push(client)
  client.setQueryData(["tasks"], tasks)
  function tree(current: Task[], eligible = current, destinations = lists) {
    return <QueryClientProvider client={client}><BulkTasksProvider tasks={current} eligible={eligible} lists={destinations}>
      <BulkTaskToolbar />{current.map(item => <BulkTaskCheckbox key={item.id} task={item} />)}
    </BulkTasksProvider></QueryClientProvider>
  }
  const view = render(tree(tasks))
  fireEvent.click(screen.getByText("Select tasks"))
  fireEvent.click(screen.getByText("Select all visible"))
  return { client, rerender: (current: Task[], eligible = current, destinations = lists) => view.rerender(tree(current, eligible, destinations)) }
}
function confirm() {
  fireEvent.click(screen.getByText("Review changes"))
  fireEvent.click(screen.getByText("Confirm changes"))
}

describe("bulk task actions", () => {
  it("confirms recurring completion and retries only failures with another confirmation", async () => {
    mutateAsync.mockReset().mockResolvedValueOnce({}).mockRejectedValueOnce(new Error("Offline")).mockResolvedValueOnce({})
    setup()
    fireEvent.change(screen.getByLabelText("New status"), { target: { value: "completed" } })
    fireEvent.click(screen.getByText("Review changes"))
    expect(mutateAsync).not.toHaveBeenCalled()
    expect(screen.getByText(/creates their next occurrences/)).toBeTruthy()
    fireEvent.click(screen.getByText("Confirm changes"))
    await waitFor(() => expect(screen.getByText(/Offline/)).toBeTruthy())
    expect((screen.getByLabelText('Select "First"') as HTMLInputElement).checked).toBe(false)
    expect((screen.getByLabelText('Select "Second"') as HTMLInputElement).checked).toBe(true)
    fireEvent.click(screen.getByLabelText('Select "First"'))
    expect(screen.getByText("2 selected")).toBeTruthy()
    fireEvent.click(screen.getByText("Retry failed only"))
    expect(screen.getByText("1 selected")).toBeTruthy()
    expect(mutateAsync).toHaveBeenCalledTimes(2)
    fireEvent.click(screen.getByText("Confirm changes"))
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(3))
    expect(mutateAsync.mock.calls.map(call => call[0].id)).toEqual(["one", "two", "two"])
  })
})


describe("bulk selection safety", () => {
  it("prunes hidden/deleted IDs while idle and never selects temporary tasks", () => {
    const view = setup([...initial, task("temp-new")])
    expect(screen.queryByLabelText('Select "temp-new"')).toBeNull()
    view.rerender(initial, [initial[1]])
    expect(screen.getByText("1 selected")).toBeTruthy()
    view.rerender([])
    expect(screen.getByText("0 selected")).toBeTruthy()
    fireEvent.keyDown(document, { key: "Escape" })
    expect(screen.getByText("Select tasks")).toBeTruthy()
  })
  it("invalidates confirmation when selection or destination changes", () => {
    const list: TaskList = { id: "work", name: "Work", color: "blue", icon: null, is_favorite: false, created_at: "2026-01-01" }
    const view = setup(initial, [list])
    fireEvent.click(screen.getByText("Review changes"))
    fireEvent.click(screen.getByLabelText('Select "First"'))
    expect(screen.queryByText("Confirm changes")).toBeNull()
    fireEvent.change(screen.getByLabelText("Bulk action"), { target: { value: "list" } })
    fireEvent.change(screen.getByLabelText("Destination list"), { target: { value: "work" } })
    fireEvent.click(screen.getByText("Review changes"))
    view.rerender(initial, initial, [])
    expect(screen.queryByText("Confirm changes")).toBeNull()
    expect(mutateAsync).not.toHaveBeenCalled()
  })
  it("reads tags from the current cache for each sequential target and locks pending selection", async () => {
    let release: () => void = () => { throw new Error("not started") }
    mutateAsync.mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve })).mockResolvedValueOnce({})
    const { client, rerender } = setup()
    fireEvent.change(screen.getByLabelText("Bulk action"), { target: { value: "add-tag" } })
    fireEvent.change(screen.getByLabelText("Tag"), { target: { value: "new" } })
    confirm()
    expect(screen.getByLabelText('Select "Second"')).toHaveProperty("disabled", true)
    fireEvent.keyDown(document, { key: "Escape" })
    expect(screen.queryByText("Select tasks")).toBeNull()
    rerender(initial, [initial[1]])
    expect(screen.getByText("2 selected")).toBeTruthy()
    client.setQueryData<Task[]>(["tasks"], [initial[0], { ...initial[1], tags: ["keep", "concurrent"] }])
    await act(async () => release())
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(2))
    expect(mutateAsync.mock.calls[1][0]).toEqual({ id: "two", patch: { tags: ["keep", "concurrent", "new"] } })
  })
  it("replaces old failures when a different action runs", async () => {
    mutateAsync.mockRejectedValueOnce(new Error("Old failure")).mockResolvedValueOnce({}).mockRejectedValueOnce(new Error("New failure")).mockResolvedValueOnce({})
    setup()
    confirm()
    await screen.findByText(/Old failure/)
    fireEvent.click(screen.getByText("Select all visible"))
    fireEvent.change(screen.getByLabelText("Bulk action"), { target: { value: "list" } })
    confirm()
    await screen.findByText(/New failure/)
    expect(screen.queryByText(/Old failure/)).toBeNull()
    expect(mutateAsync.mock.calls[2][0]).toEqual({ id: "one", patch: { list_id: null } })
  })
})

it("assigns a list and removes only the requested tag", async () => {
  mutateAsync.mockResolvedValue({})
  const list: TaskList = { id: "work", name: "Work", color: "blue", icon: null, is_favorite: false, created_at: "2026-01-01" }
  const { client } = setup(initial, [list])
  fireEvent.change(screen.getByLabelText("Bulk action"), { target: { value: "list" } })
  fireEvent.change(screen.getByLabelText("Destination list"), { target: { value: "work" } })
  confirm()
  await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(2))
  expect(mutateAsync.mock.calls.map(call => call[0].patch)).toEqual([{ list_id: "work" }, { list_id: "work" }])
  await waitFor(() => expect(screen.getByText("0 selected")).toBeTruthy())
  client.setQueryData<Task[]>(["tasks"], initial.map(item => ({ ...item, tags: ["keep", "remove", "unrelated"] })))
  fireEvent.click(screen.getByText("Select all visible"))
  fireEvent.change(screen.getByLabelText("Bulk action"), { target: { value: "remove-tag" } })
  fireEvent.change(screen.getByLabelText("Tag"), { target: { value: "remove" } })
  confirm()
  await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(4))
  expect(mutateAsync.mock.calls[3][0].patch).toEqual({ tags: ["keep", "unrelated"] })
})

it("invalidates hidden-target confirmation and checks eligibility again between awaited updates", async () => {
  let release: () => void = () => { throw new Error("not started") }
  mutateAsync.mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve }))
  const view = setup()
  fireEvent.click(screen.getByText("Review changes"))
  view.rerender(initial, [initial[0]])
  expect(screen.queryByText("Confirm changes")).toBeNull()
  view.rerender(initial)
  fireEvent.click(screen.getByText("Select all visible"))
  fireEvent.click(screen.getByText("Review changes"))
  const button = screen.getByText("Confirm changes")
  fireEvent.click(button)
  fireEvent.click(button)
  expect(mutateAsync).toHaveBeenCalledTimes(1)
  view.rerender([initial[0]])
  await act(async () => release())
  await screen.findByText(/No longer available in this view/)
  expect(mutateAsync).toHaveBeenCalledTimes(1)
})


it("exits selection with Escape from a focused checkbox", () => {
  setup()
  const checkbox = screen.getByLabelText('Select "First"')
  checkbox.focus()
  fireEvent.keyDown(checkbox, { key: "Escape" })
  expect(document.activeElement).toBe(screen.getByText("Select tasks"))
})
