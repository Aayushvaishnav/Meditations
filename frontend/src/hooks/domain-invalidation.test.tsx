// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api/client"
import type { Task } from "@/api/types"
import {
  useCapture, useCreateSession, useCreateTask, useDailyScore, useDecomposeTask,
  useDeleteList, useDeleteTask, useInsights, useJournalActivity, useJournalDays,
  useTasks, useUpdateTask,
} from "./api"

vi.mock("@/api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  ApiError: class extends Error {},
}))
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const day = "2026-10-30"
const end = "2026-10-31"
const task: Task = {
  id: "task-1", list_id: "list-1", parent_id: null, title: "Planned task",
  description: null, priority: 0, importance: "unassigned", urgency: "unassigned", status: "todo", due_date: `${day}T09:00:00`, deadline: { kind: "timed", at: `${day}T09:00:00` },
  estimated_minutes: null, actual_minutes: 0, recurrence_rule: null,
  recurrence_series_id: null, recurrence_occurrence: null, tags: [], order_index: 0,
  completed_at: null, created_at: `${day}T08:00:00`, updated_at: `${day}T08:00:00`,
}
const keys = {
  tasks: ["tasks"], activity: ["journal-activity", day], score: ["scores-daily", day],
  insights: ["insights", 30], days: ["journal-days", day, end], focus: ["focus-summary", day],
} as const
const paths = {
  tasks: "/tasks", activity: `/journal/${day}/activity`, score: `/scores/daily/${day}`,
  insights: "/insights?days=30", days: `/journal/days?from=${day}&to=${end}`,
  focus: `/focus/summary?on_date=${day}`,
} as const
type Domain = keyof typeof keys
const domains = Object.keys(keys) as Domain[]

function useDomains() {
  return {
    tasks: useTasks(), activity: useJournalActivity(day), score: useDailyScore(day, true),
    insights: useInsights(30, true), days: useJournalDays(day, end, true),
    // No exported focus-summary hook; observe the actual cache namespace with useQuery.
    focus: useQuery({ queryKey: keys.focus, queryFn: () => api.get(paths.focus) }),
  }
}

function useMutations() {
  const create = useCreateTask()
  const update = useUpdateTask()
  const remove = useDeleteTask()
  const focus = useCreateSession()
  const capture = useCapture()
  const decompose = useDecomposeTask()
  const deleteList = useDeleteList()
  return {
    create: () => create.mutateAsync({ title: task.title, due_date: task.due_date }),
    update: () => update.mutateAsync({ id: task.id, patch: { status: "completed" } }),
    remove: () => remove.mutateAsync(task.id),
    focus: () => focus.mutateAsync({ task_id: task.id, duration_minutes: 25 }),
    capture: () => capture.mutateAsync("Do planned task today; remember this day"),
    decompose: () => decompose.mutateAsync(task.id),
    deleteList: () => deleteList.mutateAsync("list-1"),
  }
}

// Telemetry counts due/completed tasks and sessions; journal-days contains entry metadata only.
// Decomposition creates undated open subtasks; list deletion only clears list_id (SET NULL).
const cases: { name: keyof ReturnType<typeof useMutations>; changed: Domain[] }[] = [
  { name: "create", changed: ["tasks", "activity", "score", "insights"] },
  { name: "update", changed: ["tasks", "activity", "score", "insights"] },
  { name: "remove", changed: ["tasks", "activity", "score", "insights"] },
  { name: "focus", changed: ["tasks", "activity", "score", "insights", "focus"] },
  { name: "capture", changed: ["tasks", "activity", "score", "insights", "days"] },
  { name: "decompose", changed: ["tasks"] },
  { name: "deleteList", changed: ["tasks"] },
]

const clients: QueryClient[] = []
afterEach(() => {
  cleanup()
  clients.splice(0).forEach((client) => client.clear())
  vi.resetAllMocks()
})

function setup(changed: Domain[]) {
  const client = new QueryClient({ defaultOptions: {
    queries: { retry: false, staleTime: Infinity }, mutations: { retry: false },
  } })
  clients.push(client)
  let mutated = false
  const data = (domain: Domain, updated: boolean): unknown => {
    if (domain === "tasks") return updated ? [{ ...task, title: "Server task after mutation" }] : [task]
    if (domain === "activity") return { date: day, tasks_done: [], tasks_planned: updated ? 2 : 1, focus_minutes: updated && changed.includes("focus") ? 25 : 0, focus_sessions: updated && changed.includes("focus") ? 1 : 0, habits: [] }
    if (domain === "score") return { date: day, final_score: updated ? 75 : 50 }
    if (domain === "insights") return { days: 30, series: [], totals: { tasks_done: updated ? 1 : 0, total_focus_hours: updated && changed.includes("focus") ? 25 / 60 : 0 } }
    if (domain === "days") return updated ? [{ date: day, mood: null, energy: null }] : []
    return { date: day, total_minutes: updated ? 25 : 0, sessions: updated ? 1 : 0 }
  }
  vi.mocked(api.get).mockImplementation(async (path) => {
    const domain = domains.find((domain) => paths[domain] === path)
    if (!domain) throw new Error(`Unexpected GET ${path}`)
    return data(domain, mutated && changed.includes(domain))
  })
  const mutate = async (path: string) => {
    mutated = true
    if (path === "/agents/capture") return { tasks: [task], journal_snippet: "Remember this day" }
    if (path === "/agents/decompose") return { subtasks: [{ ...task, parent_id: task.id, due_date: null, deadline: { kind: "none" } }], advice: "" }
    return task
  }
  vi.mocked(api.post).mockImplementation(mutate)
  vi.mocked(api.patch).mockImplementation(mutate)
  vi.mocked(api.delete).mockImplementation(async () => { mutated = true })
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  return { client, wrapper, data }
}

describe("QA-03 domain cache refresh", () => {
  it.each(cases)("$name refreshes observed affected domains", async ({ name, changed }) => {
    const { client, wrapper, data } = setup(changed)
    const observer = renderHook(useDomains, { wrapper })
    const mutation = renderHook(useMutations, { wrapper })
    await waitFor(() => expect(domains.every((domain) => observer.result.current[domain].isSuccess)).toBe(true))
    await act(async () => { await mutation.result.current[name]() })
    await waitFor(() => expect(client.isFetching()).toBe(0))
    for (const domain of domains) {
      expect.soft(client.getQueryData(keys[domain]), `${name}: observed ${domain}`).toEqual(data(domain, changed.includes(domain)))
    }
  })

  it.each(cases)("$name invalidates inactive affected domains and refreshes on return", async ({ name, changed }) => {
    const { client, wrapper, data } = setup(changed)
    const observer = renderHook(useDomains, { wrapper })
    const mutation = renderHook(useMutations, { wrapper })
    await waitFor(() => expect(domains.every((domain) => observer.result.current[domain].isSuccess)).toBe(true))
    observer.unmount()
    vi.mocked(api.get).mockClear()
    await act(async () => { await mutation.result.current[name]() })
    expect(api.get).not.toHaveBeenCalled()
    for (const domain of changed) {
      expect.soft(client.getQueryState(keys[domain])?.isInvalidated, `${name}: inactive ${domain} marked stale`).toBe(true)
    }
    renderHook(useDomains, { wrapper })
    await act(async () => { await Promise.resolve() })
    await waitFor(() => expect(client.isFetching()).toBe(0))
    for (const domain of domains) {
      expect.soft(client.getQueryData(keys[domain]), `${name}: returning to ${domain}`).toEqual(data(domain, changed.includes(domain)))
    }
  })
})
