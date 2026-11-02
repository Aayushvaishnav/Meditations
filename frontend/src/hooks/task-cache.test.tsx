// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/api/client"
import type { Task } from "@/api/types"
import { deadlineFromLegacy } from "@/lib/task-deadlines"
import { qk, useCreateTask, useUpdateTask, useDeleteTask, useDeleteList, useCreateSession, useTasks } from "./api"

vi.mock("@/api/client", () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }, ApiError: class extends Error {} }))
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function task(id: string, patch: Partial<Task> = {}): Task {
  return { id, title: id, description: null, list_id: null, parent_id: null, priority: 0, status: "todo", due_date: null, deadline: deadlineFromLegacy(patch.due_date ?? null),
    estimated_minutes: null, actual_minutes: 0, recurrence_rule: null, recurrence_series_id: null, recurrence_occurrence: null,
    tags: [], order_index: 0, completed_at: null, created_at: "2026-10-01T00:00:00", updated_at: "2026-10-01T00:00:00", ...patch }
}
let client: QueryClient
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } })
  client.setQueryData(qk.tasks, [task("a"), task("b")])
})
afterEach(() => { cleanup(); client.clear(); vi.resetAllMocks() })
function wrapper({ children }: { children: ReactNode }) { return <QueryClientProvider client={client}>{children}</QueryClientProvider> }
function rows() { return client.getQueryData<Task[]>(qk.tasks)! }
function hooks() { return renderHook(() => ({ update: useUpdateTask(), create: useCreateTask(), remove: useDeleteTask(), removeList: useDeleteList() }), { wrapper }) }
async function start(action: () => Promise<unknown>) {
  let result!: Promise<unknown>
  await act(async () => { result = action().catch(() => undefined) })
  return { done: result }
}
async function finish(action: () => void, pending: { done: Promise<unknown> }) {
  await act(async () => { action(); await pending.done })
}

describe("task mutation concurrency", () => {
  it("does not erase a successful change on another task when an older request fails", async () => {
    const a = deferred<Task>(), b = deferred<Task>()
    vi.mocked(api.patch).mockImplementation((path) => path.endsWith("/a") ? a.promise : b.promise)
    const { result } = hooks()
    const first = await start(() => result.current.update.mutateAsync({ id: "a", patch: { title: "failed" } }))
    const second = await start(() => result.current.update.mutateAsync({ id: "b", patch: { title: "saved" } }))
    await finish(() => b.resolve(task("b", { title: "saved" })), second)
    await finish(() => a.reject(new Error("rejected")), first)
    expect(rows().map(t => t.title)).toEqual(["a", "saved"])
  })

  it.each([true, false])("rolls back overlapping same-field failures in either order (older first: %s)", async (olderFirst) => {
    const a = deferred<Task>(), b = deferred<Task>()
    vi.mocked(api.patch).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise)
    const { result } = hooks()
    const first = await start(() => result.current.update.mutateAsync({ id: "a", patch: { title: "one" } }))
    const second = await start(() => result.current.update.mutateAsync({ id: "a", patch: { title: "two" } }))
    if (olderFirst) {
      await finish(() => a.reject(new Error("one")), first)
      expect(rows()[0].title).toBe("two")
      await finish(() => b.reject(new Error("two")), second)
    } else {
      await finish(() => b.reject(new Error("two")), second)
      expect(rows()[0].title).toBe("one")
      await finish(() => a.reject(new Error("one")), first)
    }
    expect(rows()[0].title).toBe("a")
  })

  it("preserves a newer successful field while removing an older failed field on the same task", async () => {
    const a = deferred<Task>(), b = deferred<Task>()
    vi.mocked(api.patch).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise)
    const { result } = hooks()
    const first = await start(() => result.current.update.mutateAsync({ id: "a", patch: { title: "failed" } }))
    const second = await start(() => result.current.update.mutateAsync({ id: "a", patch: { priority: 3 } }))
    await finish(() => b.resolve(task("a", { priority: 3 })), second)
    await finish(() => a.reject(new Error("rejected")), first)
    expect(rows()[0]).toMatchObject({ title: "a", priority: 3 })
  })

  it("does not refetch over another pending optimistic update", async () => {
    const a = deferred<Task>(), b = deferred<Task>()
    vi.mocked(api.get).mockResolvedValue([task("a", { title: "saved" }), task("b")])
    vi.mocked(api.patch).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise)
    const { result } = renderHook(() => ({ tasks: useTasks(), update: useUpdateTask() }), { wrapper })
    const first = await start(() => result.current.update.mutateAsync({ id: "a", patch: { title: "saved" } }))
    const second = await start(() => result.current.update.mutateAsync({ id: "b", patch: { title: "pending" } }))
    await finish(() => a.resolve(task("a", { title: "saved" })), first)
    expect(rows()[1].title).toBe("pending")
    expect(api.get).not.toHaveBeenCalled()
    await finish(() => b.reject(new Error("rejected")), second)
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1))
    expect(rows().map(t => t.title)).toEqual(["saved", "b"])
  })

  it("removes only its own temporary row when creation fails in an initially empty cache", async () => {
    client.removeQueries({ queryKey: qk.tasks })
    const a = deferred<Task>(), b = deferred<Task>()
    vi.mocked(api.post).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise)
    const { result } = hooks()
    const first = await start(() => result.current.create.mutateAsync({ title: "failed" }))
    const second = await start(() => result.current.create.mutateAsync({ title: "saved", description: "details" }))
    expect(rows()[1].description).toBe("details")
    await finish(() => b.resolve(task("server-id", { title: "saved", description: "details" })), second)
    await finish(() => a.reject(new Error("rejected")), first)
    expect(rows()).toEqual([task("server-id", { title: "saved", description: "details" })])
  })

  it("restores deleted descendants without undoing unrelated edits", async () => {
    client.setQueryData(qk.tasks, [task("a"), task("child", { parent_id: "a" }), task("grandchild", { parent_id: "child" }), task("b")])
    const removal = deferred<void>(), update = deferred<Task>()
    vi.mocked(api.delete).mockReturnValue(removal.promise)
    vi.mocked(api.patch).mockReturnValue(update.promise)
    const { result } = hooks()
    const first = await start(() => result.current.remove.mutateAsync("a"))
    expect(rows().map(t => t.id)).toEqual(["b"])
    const second = await start(() => result.current.update.mutateAsync({ id: "b", patch: { title: "saved" } }))
    await finish(() => update.resolve(task("b", { title: "saved" })), second)
    await finish(() => removal.reject(new Error("rejected")), first)
    expect(rows().map(t => t.id)).toEqual(["a", "child", "grandchild", "b"])
    expect(rows()[3].title).toBe("saved")
  })

  it("does not resurrect a successfully deleted task when a concurrent update fails", async () => {
    const removal = deferred<void>(), update = deferred<Task>()
    vi.mocked(api.delete).mockReturnValue(removal.promise)
    vi.mocked(api.patch).mockReturnValue(update.promise)
    const { result } = hooks()
    const first = await start(() => result.current.update.mutateAsync({ id: "b", patch: { title: "failed" } }))
    const second = await start(() => result.current.remove.mutateAsync("a"))
    await finish(() => removal.resolve(), second)
    await finish(() => update.reject(new Error("rejected")), first)
    expect(rows()).toEqual([task("b")])
  })

  it("coordinates list-deletion rollback with task edits", async () => {
    client.setQueryData(qk.tasks, [task("a", { list_id: "list" })])
    const removal = deferred<void>(), update = deferred<Task>()
    vi.mocked(api.delete).mockReturnValue(removal.promise)
    vi.mocked(api.patch).mockReturnValue(update.promise)
    const { result } = hooks()
    const first = await start(() => result.current.removeList.mutateAsync("list"))
    const second = await start(() => result.current.update.mutateAsync({ id: "a", patch: { title: "saved" } }))
    await finish(() => update.resolve(task("a", { list_id: "list", title: "saved" })), second)
    await finish(() => removal.reject(new Error("rejected")), first)
    expect(rows()[0]).toMatchObject({ list_id: "list", title: "saved" })
  })

  it.each([
    { olderSucceeds: true, olderFirst: true },
    { olderSucceeds: true, olderFirst: false },
    { olderSucceeds: false, olderFirst: true },
    { olderSucceeds: false, olderFirst: false },
  ])("keeps the successful same-field edit across settlement orders: %j", async ({ olderSucceeds, olderFirst }) => {
    const a = deferred<Task>(), b = deferred<Task>()
    vi.mocked(api.patch).mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise)
    const olderHook = hooks(), newerHook = hooks()
    const first = await start(() => olderHook.result.current.update.mutateAsync({ id: "a", patch: { title: "one" } }))
    const second = await start(() => newerHook.result.current.update.mutateAsync({ id: "a", patch: { title: "two" } }))
    const settleA = () => olderSucceeds ? a.resolve(task("a", { title: "one" })) : a.reject(new Error("one"))
    const settleB = () => olderSucceeds ? b.reject(new Error("two")) : b.resolve(task("a", { title: "two" }))
    if (olderFirst) {
      await finish(settleA, first)
      expect(rows()[0].title).toBe("two")
      await finish(settleB, second)
    } else {
      await finish(settleB, second)
      expect(rows()[0].title).toBe(olderSucceeds ? "one" : "two")
      await finish(settleA, first)
    }
    expect(rows()[0].title).toBe(olderSucceeds ? "one" : "two")
  })

  it("removes a failed create from an absent cache and supports the next mutation batch", async () => {
    client.removeQueries({ queryKey: qk.tasks })
    vi.mocked(api.post).mockRejectedValueOnce(new Error("rejected")).mockResolvedValueOnce(task("saved"))
    const { result } = hooks()
    await act(async () => { await expect(result.current.create.mutateAsync({ title: "failed" })).rejects.toThrow("rejected") })
    expect(rows()).toEqual([])
    await act(async () => { await result.current.create.mutateAsync({ title: "saved" }) })
    expect(rows()).toEqual([task("saved")])
  })

  it("keeps pending edits through a refetch and preserves fresh unrelated server fields on rollback", async () => {
    const update = deferred<Task>()
    vi.mocked(api.patch).mockReturnValue(update.promise)
    vi.mocked(api.get).mockResolvedValue([task("a", { actual_minutes: 25 }), task("b"), task("from-capture")])
    const { result } = renderHook(() => ({ tasks: useTasks(), update: useUpdateTask() }), { wrapper })
    const pending = await start(() => result.current.update.mutateAsync({ id: "a", patch: { title: "pending" } }))
    await act(async () => { await result.current.tasks.refetch() })
    expect(rows()[0]).toMatchObject({ title: "pending", actual_minutes: 25 })
    expect(rows()[2].id).toBe("from-capture")
    await finish(() => update.reject(new Error("rejected")), pending)
    expect(rows()[0]).toMatchObject({ title: "a", actual_minutes: 25 })
  })

  it("preserves fresher server fields for a confirmed create during another pending mutation", async () => {
    const update = deferred<Task>()
    vi.mocked(api.patch).mockReturnValue(update.promise)
    vi.mocked(api.post).mockResolvedValue(task("created"))
    vi.mocked(api.get).mockResolvedValue([task("a"), task("b"), task("created", { actual_minutes: 25 })])
    const { result } = renderHook(() => ({ tasks: useTasks(), update: useUpdateTask(), create: useCreateTask() }), { wrapper })
    const pending = await start(() => result.current.update.mutateAsync({ id: "a", patch: { title: "pending" } }))
    await act(async () => { await result.current.create.mutateAsync({ title: "created" }) })
    await act(async () => { await result.current.tasks.refetch() })
    expect(rows().filter(task => task.id === "created")).toHaveLength(1)
    expect(rows().find(task => task.id === "created")?.actual_minutes).toBe(25)
    await finish(() => update.reject(new Error("rejected")), pending)
  })

  it("does not let a canceled useTasks request poison a later rollback snapshot", async () => {
    const query = deferred<Task[]>(), update = deferred<Task>()
    vi.mocked(api.get).mockReturnValue(query.promise)
    vi.mocked(api.patch).mockReturnValue(update.promise)
    const { result, unmount } = renderHook(() => ({ tasks: useTasks(), update: useUpdateTask() }), { wrapper })
    let refetch!: Promise<unknown>
    await act(async () => { refetch = result.current.tasks.refetch() })
    const pending = await start(() => result.current.update.mutateAsync({ id: "a", patch: { title: "pending" } }))
    await act(async () => { query.resolve([task("a", { title: "stale" })]); await refetch })
    expect(rows()[0].title).toBe("pending")
    unmount()
    await finish(() => update.reject(new Error("rejected")), pending)
    expect(rows()[0].title).toBe("a")
  })

  it("defers focus-triggered task refetch until an overlapping task edit settles", async () => {
    const update = deferred<Task>()
    vi.mocked(api.patch).mockReturnValue(update.promise)
    vi.mocked(api.post).mockResolvedValue({ duration_minutes: 25 })
    vi.mocked(api.get).mockResolvedValue([task("a", { actual_minutes: 25 }), task("b")])
    const { result } = renderHook(() => ({ tasks: useTasks(), update: useUpdateTask(), focus: useCreateSession() }), { wrapper })
    const pending = await start(() => result.current.update.mutateAsync({ id: "a", patch: { title: "pending" } }))
    await act(async () => { await result.current.focus.mutateAsync({ task_id: "a", duration_minutes: 25 }) })
    expect(rows()[0].title).toBe("pending")
    expect(api.get).not.toHaveBeenCalled()
    await finish(() => update.reject(new Error("rejected")), pending)
    expect(rows()[0]).toMatchObject({ title: "a", actual_minutes: 25 })
  })

  it("cancels an in-flight task fetch before applying the optimistic update", async () => {
    const query = deferred<Task[]>(), update = deferred<Task>()
    vi.mocked(api.get).mockReturnValue(query.promise)
    vi.mocked(api.patch).mockReturnValue(update.promise)
    const fetch = client.fetchQuery({ queryKey: qk.tasks, queryFn: () => api.get<Task[]>("/tasks"), staleTime: 0 }).catch(() => undefined)
    const { result } = hooks()
    const pending = await start(() => result.current.update.mutateAsync({ id: "a", patch: { title: "pending" } }))
    await act(async () => { query.resolve([task("a", { title: "stale" })]); await fetch })
    expect(rows()[0].title).toBe("pending")
    await finish(() => update.reject(new Error("rejected")), pending)
    expect(rows()[0].title).toBe("a")
  })
})

describe("optimistic deadline projections", () => {
  it("rolls back date-only edits together with the legacy timed projection", async () => {
    const original = task("a", { due_date: "2026-11-02T09:00:00" })
    client.setQueryData(qk.tasks, [original])
    const response = deferred<Task>()
    vi.mocked(api.patch).mockReturnValue(response.promise)
    const { result } = hooks()
    const pending = await start(() => result.current.update.mutateAsync({ id: "a", patch: { deadline: { kind: "date", date: "2026-11-03" } } }))
    expect(rows()[0]).toMatchObject({ due_date: null, deadline: { kind: "date", date: "2026-11-03" } })
    await finish(() => response.reject(new Error("save failed")), pending)
    expect(rows()).toEqual([original])
  })

  it("preserves a newer successful deadline when an older overlapping edit fails", async () => {
    const first = deferred<Task>(), second = deferred<Task>()
    vi.mocked(api.patch).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const { result } = hooks()
    const older = await start(() => result.current.update.mutateAsync({ id: "a", patch: { deadline: { kind: "date", date: "2026-11-03" } } }))
    const newer = await start(() => result.current.update.mutateAsync({ id: "a", patch: { deadline: { kind: "timed", at: "2026-11-04T09:00:00Z" } } }))
    const saved = task("a", { due_date: "2026-11-04T09:00:00Z" })
    await finish(() => second.resolve(saved), newer)
    await finish(() => first.reject(new Error("save failed")), older)
    expect(rows()[0]).toMatchObject({ due_date: saved.due_date, deadline: saved.deadline })
  })

  it("keeps legacy clearing and date-only creation explicit in the canonical cache", async () => {
    client.setQueryData(qk.tasks, [task("a", { deadline: { kind: "date", date: "2026-11-03" } })])
    const clear = deferred<Task>(), create = deferred<Task>()
    vi.mocked(api.patch).mockReturnValue(clear.promise)
    vi.mocked(api.post).mockReturnValue(create.promise)
    const { result } = hooks()
    const clearing = await start(() => result.current.update.mutateAsync({ id: "a", patch: { due_date: null } }))
    expect(rows()[0]).toMatchObject({ due_date: null, deadline: { kind: "none" } })
    const creating = await start(() => result.current.create.mutateAsync({ title: "New", deadline: { kind: "date", date: "2026-11-05" } }))
    expect(rows().find(row => row.title === "New")).toMatchObject({ due_date: null, deadline: { kind: "date", date: "2026-11-05" } })
    const saved = task("created", { title: "New", deadline: { kind: "date", date: "2026-11-05" } })
    await finish(() => create.resolve(saved), creating)
    await finish(() => clear.resolve(task("a")), clearing)
    expect(rows()).toEqual([task("a"), saved])
  })
})
