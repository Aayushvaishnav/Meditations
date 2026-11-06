// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { api } from "@/api/client"
import type { Task } from "@/api/types"
import { qk } from "@/hooks/api"
import { useUi, type MainView, type Scope } from "@/stores/ui"
import { TasksView } from "./tasks-view"
import { Sidebar } from "./sidebar"
import { MatrixSection } from "./matrix-section"
import { TooltipProvider } from "./ui/tooltip"

vi.mock("@/api/client", () => ({ api: { get: vi.fn(), patch: vi.fn() }, ApiError: class extends Error {} }))
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }))
vi.mock("@/components/quick-add", () => ({ QuickAdd: () => null }))
vi.mock("@/components/briefing-card", () => ({ BriefingCard: () => null }))

function task(id: string, patch: Partial<Task> = {}): Task {
  return { id, title: id, description: null, list_id: "work", parent_id: null,
    priority: 2, importance: "unassigned", urgency: "unassigned", status: "todo",
    deadline: { kind: "date", date: "2026-11-02" }, due_date: null,
    estimated_minutes: null, actual_minutes: 0, recurrence_rule: null,
    recurrence_series_id: null, recurrence_occurrence: null, tags: ["contract"], order_index: 0,
    completed_at: null, created_at: "2026-11-01T00:00:00", updated_at: "2026-11-01T00:00:00", ...patch }
}
let client: QueryClient
let server: Task[]
function Harness() {
  const section = useUi(state => state.section)
  return <><Sidebar />{section === "matrix" ? <MatrixSection /> : <TasksView />}</>
}
function mount() {
  render(<QueryClientProvider client={client}><TooltipProvider><Harness /></TooltipProvider></QueryClientProvider>)
}
async function navigate(view: MainView | "matrix") {
  const sidebar = within(screen.getByRole("complementary", { name: "Sidebar" }))
  if (view === "matrix") {
    fireEvent.click(sidebar.getByRole("button", { name: "Eisenhower Matrix" }))
    return
  }
  if (useUi.getState().section === "matrix") {
    const scope = useUi.getState().scope
    const label = scope.kind === "list" ? "Work" : { all: "All tasks", today: "Today", upcoming: "Upcoming", overdue: "Overdue", completed: "Completed" }[scope.id]
    fireEvent.click(sidebar.getByRole("button", { name: label }))
  }
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: `${view === "list" ? "List" : view === "board" ? "Board" : "Calendar"} view` }))
    if (view === "board") await import("./kanban-board")
    if (view === "calendar") await import("./calendar-view")
  })
}
function visible(title: string, expected: boolean) {
  expect(screen.queryAllByText(title, { exact: true }).length > 0).toBe(expected)
}
beforeEach(() => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
  vi.useFakeTimers({ toFake: ["Date"] })
  vi.setSystemTime(new Date(2026, 10, 2, 12))
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } })
  server = [task("Work today"), task("Home today", { list_id: "home" }),
    task("Work tomorrow", { deadline: { kind: "date", date: "2026-11-03" } }),
    task("Work done", { status: "completed", completed_at: "2026-11-02T09:00:00" }),
    task("Work canceled", { status: "canceled" }), task("No match", { tags: [] })]
  client.setQueryData(qk.tasks, server)
  client.setQueryData(qk.lists, [{ id: "work", name: "Work", color: "#123456", order_index: 0, is_favorite: false, icon: null }])
  client.setQueryData(qk.health, { status: "ok" })
  vi.mocked(api.get).mockImplementation(async (path) => {
    if (path === "/tasks") return server
    if (["/lists", "/time-blocks", "/calendar/imports", "/calendar/connections"].includes(path)) return []
    throw new Error(`Unexpected GET ${path}`)
  })
  useUi.setState({ section: "tasks", view: "list", scope: { kind: "smart", id: "all" }, search: "contract", calendarMode: "agenda" })
})
afterEach(() => {
  cleanup(); client.clear(); vi.resetAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers()
  useUi.setState(useUi.getInitialState()); localStorage.clear()
})

it.each([
  [{ kind: "list", id: "work" }, ["Work today", "Work tomorrow"]],
  [{ kind: "smart", id: "today" }, ["Work today", "Home today"]],
  [{ kind: "smart", id: "upcoming" }, ["Work tomorrow"]],
  [{ kind: "smart", id: "completed" }, ["Work done"]],
] satisfies [Scope, string[]][])("retains scope/search across List, Board and Calendar, with explicit Matrix independence: %j", async (scope, expected) => {
  useUi.setState({ scope })
  mount()
  for (const view of ["list", "board", "calendar"] as const) {
    await navigate(view)
    for (const row of server) {
      const boardDone = view === "board" && scope.kind === "list" && row.id === "Work done"
      visible(row.title, expected.includes(row.id) || boardDone)
    }
    expect(useUi.getState()).toMatchObject({ scope, search: "contract" })
  }
  // Matrix is an independent section; it uses All plus search, not the previous task scope
  await navigate("matrix")
  for (const row of server) visible(row.title, row.status === "todo" && row.tags.includes("contract"))
  await navigate("list")
  for (const row of server) visible(row.title, expected.includes(row.id))
})

it("carries a Matrix edit through Calendar and completion through Board back into the shared cache", async () => {
  vi.mocked(api.patch).mockImplementation(async (path, patch) => {
    const id = path.split("/").at(-1)
    server = server.map(row => row.id === id ? { ...row, ...patch as Partial<Task> } : row)
    return server.find(row => row.id === id)!
  })
  mount()
  await navigate("matrix")
  fireEvent.change(screen.getByRole("combobox", { name: 'Move "Work today" to quadrant' }), { target: { value: "schedule" } })
  await waitFor(() => expect(client.isMutating()).toBe(0))
  expect(api.patch).toHaveBeenCalledWith("/tasks/Work today", { importance: "important", urgency: "not_urgent" })
  await navigate("calendar")
  visible("Work today", true)
  await navigate("board")
  fireEvent.click(screen.getByRole("checkbox", { name: 'Complete "Work today"' }))
  await waitFor(() => expect(client.getQueryData<Task[]>(qk.tasks)?.find(row => row.id === "Work today")?.status).toBe("completed"))
  await waitFor(() => expect(client.isMutating()).toBe(0))
  await navigate("calendar")
  visible("Work today", false)
  await navigate("matrix")
  visible("Work today", false)
  fireEvent.click(within(screen.getByRole("complementary", { name: "Sidebar" })).getByRole("button", { name: "Completed" }))
  await navigate("list")
  visible("Work today", true)
  expect(client.getQueryData<Task[]>(qk.tasks)?.find(row => row.id === "Work today")).toMatchObject({
    importance: "important", urgency: "not_urgent", priority: 2, deadline: { kind: "date", date: "2026-11-02" },
  })
  expect(api.patch).toHaveBeenCalledTimes(2)
})

it("restores Calendar placement after a failed Board completion settles off-screen, then permits retry", async () => {
  let reject!: (error: Error) => void
  vi.mocked(api.patch).mockImplementationOnce(() => new Promise((_resolve, no) => { reject = no }))
  mount()
  await navigate("board")
  fireEvent.click(screen.getByRole("checkbox", { name: 'Complete "Work today"' }))
  await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1))
  await navigate("calendar")
  visible("Work today", false)
  let finishRefetch!: (rows: Task[]) => void
  vi.mocked(api.get).mockImplementationOnce(() => new Promise(resolve => { finishRefetch = resolve }))
  await act(async () => { reject(new Error("Offline")) })
  await waitFor(() => visible("Work today", true))
  expect(client.getQueryData<Task[]>(qk.tasks)?.find(row => row.id === "Work today")?.status).toBe("todo")
  await waitFor(() => expect(finishRefetch).toBeTypeOf("function"))
  expect(client.isFetching({ queryKey: qk.tasks })).toBe(1)
  await act(async () => { finishRefetch(server) })
  await navigate("matrix")
  visible("Work today", true)
  vi.mocked(api.patch).mockImplementationOnce(async () => {
    server = server.map(row => row.id === "Work today" ? { ...row, status: "completed" } : row)
    return server[0]
  })
  await navigate("board")
  fireEvent.click(screen.getByRole("checkbox", { name: 'Complete "Work today"' }))
  await waitFor(() => expect(client.isMutating()).toBe(0))
  await navigate("calendar")
  visible("Work today", false)
  expect(api.patch).toHaveBeenCalledTimes(2)
})
