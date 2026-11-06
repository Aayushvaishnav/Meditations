// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, expect, it, vi } from "vitest"
import type { Task } from "@/api/types"
import { api } from "@/api/client"
import { useUpdateTask } from "@/hooks/tasks"
import { BulkTaskCheckbox, BulkTasksProvider, BulkTaskToolbar } from "./bulk-tasks"

vi.mock("@/api/client", () => ({ api: { patch: vi.fn() } }))
vi.mock("sonner", () => ({ toast: { error: vi.fn(), info: vi.fn() } }))
afterEach(() => { cleanup(); vi.restoreAllMocks() })

function task(id: string): Task {
  return { id, title: id, tags: [], recurrence_rule: null, list_id: null,
    parent_id: null, description: null, priority: 0, importance: "unassigned", urgency: "unassigned",
    status: "todo", deadline: { kind: "none" }, due_date: null, estimated_minutes: null,
    actual_minutes: 0, recurrence_series_id: null, recurrence_occurrence: null,
    order_index: 0, completed_at: null, created_at: "2026-01-01", updated_at: "2026-01-01" }
}
function ConcurrentEdit() {
  const update = useUpdateTask()
  return <button onClick={() => update.mutate({ id: "two", patch: { title: "Unrelated edit" } })}>Edit title</button>
}
it("real task mutations retain successful bulk changes and simultaneous title edits when one bulk target fails", async () => {
  const tasks = [task("one"), task("two")]
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  client.setQueryData(["tasks"], tasks)
  let rejectBulk: (error: Error) => void = () => { throw new Error("bulk not started") }
  vi.mocked(api.patch).mockImplementation(async (path, patch) => {
    if (path === "/tasks/two" && typeof patch === "object" && patch !== null && "status" in patch) {
      return new Promise<never>((_resolve, reject) => { rejectBulk = reject })
    }
    return undefined
  })
  render(<QueryClientProvider client={client}><BulkTasksProvider tasks={tasks} eligible={tasks} lists={[]}>
    <BulkTaskToolbar />{tasks.map(item => <BulkTaskCheckbox key={item.id} task={item} />)}<ConcurrentEdit />
  </BulkTasksProvider></QueryClientProvider>)
  fireEvent.click(screen.getByText("Select tasks"))
  fireEvent.click(screen.getByText("Select all visible"))
  fireEvent.change(screen.getByLabelText("New status"), { target: { value: "in_progress" } })
  fireEvent.click(screen.getByText("Review changes"))
  fireEvent.click(screen.getByText("Confirm changes"))
  await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(2))
  fireEvent.click(screen.getByText("Edit title"))
  await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(3))
  await act(async () => rejectBulk(new Error("Offline")))
  await screen.findByText(/Offline/)
  expect(client.getQueryData<Task[]>(["tasks"])?.map(({ id, title, status }) => ({ id, title, status }))).toEqual([
    { id: "one", title: "one", status: "in_progress" },
    { id: "two", title: "Unrelated edit", status: "todo" },
  ])
  client.clear()
})
