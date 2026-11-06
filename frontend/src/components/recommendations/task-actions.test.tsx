// @vitest-environment jsdom
import { useState } from "react"
import { useCapture } from "@/hooks/ai"
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api/client"
import type { Task } from "@/api/types"
import { qk } from "@/hooks/query-keys"
import { useFocusTimer } from "@/stores/timer"
import { useUi } from "@/stores/ui"
import { RecommendationTaskActions } from "./task-actions"
import { DailyReviewCard } from "@/components/daily-review-card"

vi.mock("@/api/client", () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }, ApiError: class extends Error {} }))
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }))
function task(id: string, patch: Partial<Task> = {}): Task {
  return { id, title: "Duplicate", description: null, list_id: "outside", parent_id: null,
    priority: 0, importance: "unassigned", urgency: "unassigned", status: "todo",
    due_date: null, deadline: { kind: "date", date: "2027-02-10" }, estimated_minutes: 25,
    actual_minutes: 0, recurrence_rule: null, recurrence_series_id: null, recurrence_occurrence: null,
    tags: [], order_index: 0, completed_at: null, created_at: "2026-01-01T00:00:00", updated_at: "2026-01-01T00:00:00", ...patch }
}
let client: QueryClient
let server: Task[]
beforeEach(() => {
  vi.resetAllMocks()
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } })
  server = [task("other"), task("linked")]
  vi.mocked(api.get).mockImplementation(async path => path === "/tasks" ? server : [])
  vi.mocked(api.post).mockImplementation(async (_path, input) => ({ id: "saved", ...input as object }))
  useFocusTimer.setState({ clock: { status: "paused" }, running: false, phase: "work", mode: "pomodoro", elapsed: 0, secondsLeft: 1500, workMinutes: 25, remainderMs: 0, taskId: null, open: false, events: [] })
  useUi.setState({ section: "journal", search: "unrelated search", scope: { kind: "list", id: "different-list" } })
})
afterEach(() => { cleanup(); client.clear() })
function mount(review = false) {
  render(<QueryClientProvider client={client}><RecommendationTaskActions taskId="linked" />{review && <DailyReviewCard day="2027-02-10" />}</QueryClientProvider>)
}
async function ready() { await screen.findByRole("button", { name: "Open task" }) }
function click(name: string) { fireEvent.click(screen.getByRole("button", { name })) }
function change(label: string, value: string) { fireEvent.change(screen.getByLabelText(label), { target: { value } }) }
async function schedule() { await ready(); click("Schedule") }
function submit() { fireEvent.submit(screen.getByRole("form", { name: "Schedule work block" })) }

describe("recommendation actions with canonical task queries", () => {
  it("opens by stable ID despite duplicate titles, follows renames, and completes through TaskItem without changing UI scope", async () => {
    mount(); await ready()
    const ui = useUi.getState()
    click("Open task")
    expect(useUi.getState()).toBe(ui)
    server = [server[0], task("linked", { title: "Renamed linked task" })]
    await act(async () => { client.setQueryData(qk.tasks, server) })
    vi.mocked(api.patch).mockImplementation(async (_path, patch) => {
      server = [server[0], { ...server[1], ...patch as Partial<Task> }]
      return server[1]
    })
    fireEvent.click(await screen.findByRole("checkbox", { name: 'Complete "Renamed linked task"' }))
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith("/tasks/linked", { status: "completed" }))
    await waitFor(() => expect((screen.getByRole("button", { name: "Schedule" }) as HTMLButtonElement).disabled).toBe(true))
    expect(server[0].status).toBe("todo")
  })
  it("keeps a deleted recommendation as reference without actions", async () => {
    server = []; mount()
    await screen.findByText(/linked task is no longer available/)
    expect(screen.queryByRole("button", { name: "Open task" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Schedule" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Start focus" })).toBeNull()
  })
  it.each(["completed", "canceled"] as const)("disables scheduling and focus for %s tasks", async status => {
    server = [task("linked", { status })]; mount(); await ready()
    for (const name of ["Schedule", "Start focus"]) expect((screen.getByRole("button", { name }) as HTMLButtonElement).disabled).toBe(true)
  })
  it("retries a failed task fetch", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new Error("offline"))
    mount(); await screen.findByRole("alert"); click("Retry tasks"); await ready()
  })
  it("attaches the linked ID and starts focus", async () => {
    mount(); await ready(); click("Start focus")
    expect(useFocusTimer.getState()).toMatchObject({ taskId: "linked", running: true, open: true, phase: "work" })
  })
  it.each([
    { taskId: "other", running: true },
    { taskId: "other", running: false, secondsLeft: 1400 },
    { taskId: "linked", running: false, phase: "break" as const, secondsLeft: 300 },
  ])("does not overwrite an existing focus session: %j", async state => {
    useFocusTimer.setState(state); const before = useFocusTimer.getState()
    mount(); await ready(); click("Start focus")
    expect(useFocusTimer.getState()).toBe(before)
  })
  it("requires explicit schedule confirmation and sends exclusive all-day end without changing deadline", async () => {
    mount(); await schedule(); change("Block date", "2028-02-29")
    expect(api.post).not.toHaveBeenCalled()
    click("Save work block")
    await screen.findByText(/Work block saved/)
    expect(api.post).toHaveBeenCalledWith("/time-blocks", { kind: "all_day", task_id: "linked", start_date: "2028-02-29", end_date: "2028-03-01" })
    expect(api.patch).not.toHaveBeenCalled()
    expect(client.getQueryData<Task[]>(qk.tasks)?.find(t => t.id === "linked")?.deadline).toEqual({ kind: "date", date: "2027-02-10" })
  })
  it("validates local candidates and time order before saving timed blocks", async () => {
    mount(); await schedule(); change("Block type", "timed")
    submit(); await screen.findByRole("alert"); expect(api.post).not.toHaveBeenCalled()
    change("Block start", "2027-02-10T12:00"); change("Block end", "2027-02-10T11:00")
    submit(); await screen.findByText(/End must be after start/); expect(api.post).not.toHaveBeenCalled()
    change("Block end", "2027-02-10T13:00"); submit()
    await screen.findByText(/Work block saved/)
    expect(api.post).toHaveBeenCalledWith("/time-blocks", { kind: "timed", task_id: "linked", start_at: new Date("2027-02-10T12:00").toISOString(), end_at: new Date("2027-02-10T13:00").toISOString(), timezone: Intl.DateTimeFormat().resolvedOptions().timeZone })
  })
  it("retains hidden drafts and failed saves for an explicit retry", async () => {
    vi.mocked(api.post).mockRejectedValueOnce(new Error("offline"))
    mount(); await schedule(); change("Block date", "2027-07-19")
    click("Schedule"); expect(screen.queryByRole("form", { name: "Schedule work block" })).toBeNull()
    click("Schedule"); expect((screen.getByLabelText("Block date") as HTMLInputElement).value).toBe("2027-07-19")
    click("Save work block"); await screen.findByRole("alert")
    expect((screen.getByLabelText("Block date") as HTMLInputElement).value).toBe("2027-07-19")
    click("Save work block"); await screen.findByText(/Work block saved/)
    expect(api.post).toHaveBeenCalledTimes(2)
    expect(vi.mocked(api.post).mock.calls[0]).toEqual(vi.mocked(api.post).mock.calls[1])
  })
  it("keeps the schedule draft while task cancellation disables the open form", async () => {
    mount(); await schedule(); change("Block date", "2027-08-12")
    await act(async () => { client.setQueryData(qk.tasks, [task("linked", { status: "canceled" })]) })
    await waitFor(() => expect(screen.getByRole("button", { name: "Save work block" }).matches(":disabled")).toBe(true))
    submit(); expect(api.post).not.toHaveBeenCalled()
    await act(async () => { client.setQueryData(qk.tasks, [task("linked")]) })
    await waitFor(() => expect(screen.getByRole("button", { name: "Save work block" }).matches(":disabled")).toBe(false))
    expect((screen.getByLabelText("Block date") as HTMLInputElement).value).toBe("2027-08-12")
  })
  it("composes capture, planning, focus and an edited saved-review follow-up", async () => {
    server = []
    function CaptureFlow() {
      const capture = useCapture()
      const [reference, setReference] = useState<{ kind: "empty" } | { kind: "task"; id: string }>({ kind: "empty" })
      return <>
        <button onClick={async () => {
          const result = await capture.mutateAsync("Capture a manageable project step")
          setReference({ kind: "task", id: result.tasks[0].id })
        }}>Capture a step</button>
        {reference.kind === "task" && <RecommendationTaskActions taskId={reference.id} />}
        <DailyReviewCard day="2027-02-10" />
      </>
    }
    const savedScore = {
      persisted: true, final_score: 90, llm_nudge: 0,
      suggested_action_for_tomorrow: "Review progress on the linked task",
    }
    client.setQueryData(["scores-daily", "2027-02-10"], savedScore)
    vi.mocked(api.get).mockImplementation(async path => path === "/tasks" ? server : path.startsWith("/scores/daily/") ? savedScore : [])
    vi.mocked(api.post).mockImplementation(async (path, input) => {
      if (path === "/agents/capture") {
        server = [task("linked")]
        return { tasks: server, journal_snippet: "Captured a small step" }
      }
      if (path === "/tasks") {
        const created = task("followup", input as Partial<Task>)
        server = [...server, created]
        return created
      }
      return { id: "block", ...input as object }
    })
    render(<QueryClientProvider client={client}><CaptureFlow /></QueryClientProvider>)
    click("Capture a step"); await ready(); click("Open task")
    expect(api.post).toHaveBeenCalledWith("/agents/capture", { text: "Capture a manageable project step" })
    expect(screen.getByRole("checkbox", { name: 'Complete "Duplicate"' })).toBeTruthy()
    click("Schedule"); change("Block date", "2027-02-10"); click("Save work block")
    await screen.findByText(/Work block saved/)
    click("Start focus"); expect(useFocusTimer.getState().taskId).toBe("linked")
    click("Draft task"); change("Task title", "Confirm progress with a short review")
    expect(vi.mocked(api.post).mock.calls.filter(([path]) => path === "/tasks")).toHaveLength(0)
    click("Create task"); await screen.findByText("Task created")
    expect(api.post).toHaveBeenCalledWith("/tasks", {
      title: "Confirm progress with a short review",
      description: "Follow-up from daily review 2027-02-10\n\nReview progress on the linked task",
      deadline: { kind: "none" },
    })
    await waitFor(() => expect(client.getQueryData<Task[]>(qk.tasks)?.some(t => t.id === "followup")).toBe(true))
  })

  it.skipIf(Intl.DateTimeFormat().resolvedOptions().timeZone !== "America/New_York")("rejects spring gaps and requires explicit fall-fold occurrences", async () => {
    mount(); await schedule(); change("Block type", "timed")
    change("Block start", "2026-03-08T02:30"); change("Block end", "2026-03-08T04:00")
    submit(); await screen.findByText(/may not exist because the clocks change/)
    expect(api.post).not.toHaveBeenCalled()
    change("Block start", "2026-11-01T01:30"); change("Block end", "2026-11-01T02:30")
    submit(); await screen.findByText(/This time occurs twice/)
    expect(api.post).not.toHaveBeenCalled()
    change("Block start occurrence", "later"); submit()
    await screen.findByText(/Work block saved/)
    expect(api.post).toHaveBeenCalledWith("/time-blocks", {
      kind: "timed", task_id: "linked", start_at: "2026-11-01T06:30:00.000Z", end_at: "2026-11-01T07:30:00.000Z", timezone: "America/New_York",
    })
  })

  it("submits one work block while confirmation is in flight", async () => {
    let resolve!: (value: unknown) => void
    vi.mocked(api.post).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    mount(); await schedule()
    submit(); submit()
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1))
    await act(async () => resolve({ id: "block" }))
    await screen.findByText(/Work block saved/)
  })

})
