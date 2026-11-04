// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api/client"
import type { Task } from "@/api/types"
import { qk, useTasks, useUpdateTask } from "@/hooks/api"
import { EisenhowerMatrix } from "./eisenhower-matrix"

vi.mock("@/api/client", () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }, ApiError: class extends Error {} }))
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function task(id: string, patch: Partial<Task> = {}): Task {
  return {
    id, title: id, description: "Keep details", list_id: null, parent_id: null,
    priority: 3, importance: "unassigned", urgency: "unassigned", status: "todo",
    due_date: null, deadline: { kind: "date", date: "2027-01-10" },
    estimated_minutes: 25, actual_minutes: 0, recurrence_rule: null,
    recurrence_series_id: null, recurrence_occurrence: null, tags: ["keep"], order_index: 0,
    completed_at: null, created_at: "2026-10-01T00:00:00", updated_at: "2026-10-01T00:00:00", ...patch,
  }
}
let client: QueryClient
let server: Task[]
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } })
  server = [task("a"), task("b")]
  client.setQueryData(qk.tasks, server)
  vi.mocked(api.get).mockImplementation(async () => server)
})
afterEach(() => { cleanup(); client.clear(); vi.resetAllMocks() })
function Harness() {
  const { data = [] } = useTasks()
  const update = useUpdateTask()
  return <>
    <button onClick={() => update.mutate({ id: "a", patch: { title: "Edited a", priority: 1 } })}>Edit task independently</button>
    <EisenhowerMatrix tasks={data} lists={[]} scope={{ kind: "smart", id: "all" }} />
  </>
}
function mount() { render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>) }
function rows() { return client.getQueryData<Task[]>(qk.tasks)! }
function card(title: string) { return screen.getByRole("article", { name: title }) }
function zone(label: string) { return screen.getByRole("region", { name: label }) }
function move(title: string, value: string) {
  fireEvent.change(screen.getByRole("combobox", { name: `Move "${title}" to quadrant` }), { target: { value } })
}
async function placement(title: string, label: string) {
  await waitFor(() => expect(within(zone(label)).getByRole("article", { name: title })).toBeTruthy())
}

describe("matrix with canonical task cache and real mutation hooks", () => {
  it.each(["resolve", "reject"] as const)("keeps creation input focus when a pending cross-zone move settles: %s", async outcome => {
    const request = deferred<Task>()
    vi.mocked(api.patch).mockReturnValue(request.promise)
    mount()
    const originalSelector = screen.getByRole("combobox", { name: 'Move "a" to quadrant' })
    originalSelector.focus()
    move("a", "schedule")
    await placement("a", "Not urgent & important")
    expect(originalSelector.isConnected).toBe(false)
    expect(card("a").getAttribute("aria-busy")).toBe("true")
    const input = screen.getByRole("textbox", { name: "New task in Urgent & important" })
    input.focus()
    fireEvent.change(input, { target: { value: "Continue this draft" } })
    expect(document.activeElement).toBe(input)
    if (outcome === "resolve") {
      server = [task("a", { importance: "important", urgency: "not_urgent" }), server[1]]
      await act(async () => { request.resolve(server[0]) })
    } else {
      await act(async () => { request.reject(new Error("classification rejected")) })
    }
    await waitFor(() => expect(card("a").getAttribute("aria-busy")).toBe("false"))
    await placement("a", outcome === "resolve" ? "Not urgent & important" : "Unclassified")
    expect(document.activeElement).toBe(input)
    expect((input as HTMLInputElement).value).toBe("Continue this draft")
  })

  it.each(["resolve", "reject"] as const)("restores the move selector after actual cross-zone remount: %s", async outcome => {
    const request = deferred<Task>()
    vi.mocked(api.patch).mockReturnValue(request.promise)
    mount()
    const originalSelector = screen.getByRole("combobox", { name: 'Move "a" to quadrant' })
    originalSelector.focus()
    move("a", "schedule")
    await placement("a", "Not urgent & important")
    expect(originalSelector.isConnected).toBe(false)
    expect(document.activeElement).toBe(document.body)
    if (outcome === "resolve") {
      server = [task("a", { importance: "important", urgency: "not_urgent" }), server[1]]
      await act(async () => { request.resolve(server[0]) })
    } else {
      await act(async () => { request.reject(new Error("classification rejected")) })
    }
    await waitFor(() => expect(card("a").getAttribute("aria-busy")).toBe("false"))
    await placement("a", outcome === "resolve" ? "Not urgent & important" : "Unclassified")
    const restoredSelector = screen.getByRole("combobox", { name: 'Move "a" to quadrant' })
    expect(restoredSelector).not.toBe(originalSelector)
    await waitFor(() => expect(document.activeElement === restoredSelector).toBe(true))
    expect((restoredSelector as HTMLSelectElement).disabled).toBe(false)
  })

  it("moves optimistically and sends only classification, preserving every other task field", async () => {
    const request = deferred<Task>()
    vi.mocked(api.patch).mockReturnValue(request.promise)
    const original = server[0]
    mount()
    move("a", "schedule")
    await placement("a", "Not urgent & important")
    expect(rows()[0]).toEqual({ ...original, importance: "important", urgency: "not_urgent" })
    expect(api.patch).toHaveBeenCalledExactlyOnceWith("/tasks/a", { importance: "important", urgency: "not_urgent" })
    expect(card("a").getAttribute("aria-busy")).toBe("true")
    server = [{ ...original, importance: "important", urgency: "not_urgent" }, server[1]]
    await act(async () => { request.resolve(server[0]) })
    await waitFor(() => expect(card("a").getAttribute("aria-busy")).toBe("false"))
    await placement("a", "Not urgent & important")
  })

  it.each([true, false])("restores failed placement without reverting concurrent title/priority edits (move settles first: %s)", async (moveFirst) => {
    const classification = deferred<Task>(), edit = deferred<Task>()
    vi.mocked(api.patch).mockReturnValueOnce(classification.promise).mockReturnValueOnce(edit.promise)
    mount()
    move("a", "do")
    await placement("a", "Urgent & important")
    fireEvent.click(screen.getByRole("button", { name: "Edit task independently" }))
    await placement("Edited a", "Urgent & important")
    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(2))
    server = [task("a", { title: "Edited a", priority: 1 }), server[1]]
    if (moveFirst) {
      await act(async () => { classification.reject(new Error("classification rejected")) })
      await placement("Edited a", "Unclassified")
      expect(rows()[0].priority).toBe(1)
      expect(api.get).not.toHaveBeenCalled()
      await act(async () => { edit.resolve(server[0]) })
    } else {
      await act(async () => { edit.resolve(server[0]) })
      await waitFor(() => expect(client.isMutating()).toBe(1))
      await placement("Edited a", "Urgent & important")
      expect(api.get).not.toHaveBeenCalled()
      await act(async () => { classification.reject(new Error("classification rejected")) })
    }
    await placement("Edited a", "Unclassified")
    expect(rows()[0]).toEqual(server[0])
    expect(within(card("Edited a")).getByRole("alert")).toBeTruthy()
    expect(screen.getByRole("combobox", { name: 'Move "Edited a" to quadrant' }).hasAttribute("disabled")).toBe(false)
  })

  it.each([true, false])("settles different-task moves independently (failure first: %s)", async (failureFirst) => {
    const a = deferred<Task>(), b = deferred<Task>()
    vi.mocked(api.patch).mockImplementation(path => path === "/tasks/a" ? a.promise : b.promise)
    mount()
    move("a", "do")
    await placement("a", "Urgent & important")
    move("b", "delegate")
    await placement("b", "Urgent & not important")
    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(2))
    server = [task("a"), task("b", { importance: "not_important", urgency: "urgent" })]
    if (failureFirst) {
      await act(async () => { a.reject(new Error("rejected")) })
      await placement("a", "Unclassified")
      await placement("b", "Urgent & not important")
      expect(card("b").getAttribute("aria-busy")).toBe("true")
      expect(api.get).not.toHaveBeenCalled()
      await act(async () => { b.resolve(server[1]) })
    } else {
      await act(async () => { b.resolve(server[1]) })
      await waitFor(() => expect(card("b").getAttribute("aria-busy")).toBe("false"))
      await placement("a", "Urgent & important")
      expect(card("a").getAttribute("aria-busy")).toBe("true")
      expect(api.get).not.toHaveBeenCalled()
      await act(async () => { a.reject(new Error("rejected")) })
    }
    await placement("a", "Unclassified")
    await placement("b", "Urgent & not important")
    expect(rows()).toEqual(server)
    expect(within(card("a")).getByRole("alert")).toBeTruthy()
    expect(within(card("b")).queryByRole("alert")).toBeNull()
  })
})
