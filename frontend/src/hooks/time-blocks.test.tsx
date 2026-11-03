// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { toast } from "sonner"
import { api } from "@/api/client"
import type { TimeBlock, TimeBlockInput } from "@/api/types"
import { qk, useDeleteList, useDeleteTask, useReplaceTimeBlock, useTasks, useTimeBlocks } from "./api"

vi.mock("@/api/client", () => ({ api: { get: vi.fn(), put: vi.fn(), delete: vi.fn() }, ApiError: class extends Error {} }))
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }))

const input: TimeBlockInput = { kind: "all_day", task_id: "task", start_date: "2026-11-02", end_date: "2026-11-04" }
const block: TimeBlock = { ...input, id: "block", timezone: null, start_at: null, end_at: null, created_at: "2026-11-01T00:00:00", updated_at: "2026-11-01T00:00:00" }
let client: QueryClient
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } })
})
afterEach(() => { cleanup(); client.clear(); vi.resetAllMocks() })

describe("time block hooks", () => {
  it("fetches all blocks independently of the tasks cache", async () => {
    vi.mocked(api.get).mockImplementation(async path => path === "/time-blocks" ? [block] : [])
    const { result } = renderHook(() => ({ blocks: useTimeBlocks(), tasks: useTasks() }), { wrapper })
    await waitFor(() => expect(result.current.blocks.isSuccess && result.current.tasks.isSuccess).toBe(true))
    expect(api.get).toHaveBeenCalledWith("/time-blocks")
    expect(client.getQueryData(qk.timeBlocks)).toEqual([block])
    expect(client.getQueryData(qk.tasks)).toEqual([])
    await act(async () => { await client.invalidateQueries({ queryKey: qk.tasks }) })
    expect(vi.mocked(api.get).mock.calls.filter(([path]) => path === "/time-blocks")).toHaveLength(1)
  })

  it.each([true, false])("waits for server confirmation and refetches on settlement (success: %s)", async success => {
    client.setQueryData(qk.timeBlocks, [block])
    for (const key of [qk.tasks, ["journal-activity"], ["scores-daily"], ["insights"]]) client.setQueryData(key, [])
    let resolve!: (value: TimeBlock) => void
    let reject!: (error: Error) => void
    vi.mocked(api.put).mockReturnValue(new Promise<TimeBlock>((yes, no) => { resolve = yes; reject = no }))
    const confirmed: TimeBlock = { id: block.id, task_id: "task", kind: "timed", start_at: "2026-11-02T10:00:00", end_at: "2026-11-02T11:00:00", timezone: "UTC", start_date: null, end_date: null, created_at: block.created_at, updated_at: block.updated_at }
    const replacement: TimeBlockInput = { kind: "timed", task_id: confirmed.task_id, start_at: confirmed.start_at, end_at: confirmed.end_at, timezone: confirmed.timezone }
    vi.mocked(api.get).mockResolvedValue(success ? [confirmed] : [block])
    const { result } = renderHook(() => ({ blocks: useTimeBlocks(), replace: useReplaceTimeBlock() }), { wrapper })
    let pending!: Promise<unknown>
    await act(async () => { pending = result.current.replace.mutateAsync({ id: block.id, input: replacement }).catch(() => undefined) })
    expect(client.getQueryData(qk.timeBlocks)).toEqual([block])
    expect(api.put).toHaveBeenCalledWith("/time-blocks/block", replacement)
    await act(async () => {
      if (success) resolve(confirmed)
      else reject(new Error("failed"))
      await pending
    })
    await waitFor(() => expect(result.current.blocks.data).toEqual(success ? [confirmed] : [block]))
    expect(api.get).toHaveBeenCalledWith("/time-blocks")
    expect(toast.error).toHaveBeenCalledTimes(success ? 0 : 1)
    for (const key of [qk.tasks, ["journal-activity"], ["scores-daily"], ["insights"]]) expect(client.getQueryState(key)?.isInvalidated).toBe(false)
  })

  it("keeps pending state across observers and remounts until settlement", async () => {
    let resolve!: (value: TimeBlock) => void
    vi.mocked(api.put).mockReturnValue(new Promise<TimeBlock>(yes => { resolve = yes }))
    const first = renderHook(() => useReplaceTimeBlock(), { wrapper })
    act(() => { first.result.current.mutate({ id: block.id, input }) })
    await waitFor(() => expect(first.result.current.isPending).toBe(true))
    first.unmount()
    const second = renderHook(() => useReplaceTimeBlock(), { wrapper })
    expect(second.result.current.isPending).toBe(true)
    await act(async () => { resolve(block) })
    await waitFor(() => expect(second.result.current.isPending).toBe(false))
  })

  it("retains the confirmed response when the settlement refetch fails", async () => {
    client.setQueryData(qk.timeBlocks, [block])
    const confirmed = { ...block, end_date: "2026-11-05" }
    vi.mocked(api.put).mockResolvedValue(confirmed)
    vi.mocked(api.get).mockRejectedValue(new Error("refetch failed"))
    const { result } = renderHook(() => ({ blocks: useTimeBlocks(), replace: useReplaceTimeBlock() }), { wrapper })
    await act(async () => { await result.current.replace.mutateAsync({ id: block.id, input }) })
    await waitFor(() => expect(result.current.blocks.isRefetchError).toBe(true))
    expect(result.current.blocks.data).toEqual([confirmed])
    expect(api.get).toHaveBeenCalledWith("/time-blocks")
  })

  it.each([false, true])("does not reintroduce a block removed during replacement (cache exists: %s)", async cacheExists => {
    client.setQueryData(qk.timeBlocks, [block])
    let resolve!: (value: TimeBlock) => void
    vi.mocked(api.put).mockReturnValue(new Promise<TimeBlock>(yes => { resolve = yes }))
    const { result } = renderHook(() => useReplaceTimeBlock(), { wrapper })
    let pending!: Promise<TimeBlock>
    act(() => { pending = result.current.mutateAsync({ id: block.id, input }) })
    if (cacheExists) client.setQueryData(qk.timeBlocks, [])
    else client.removeQueries({ queryKey: qk.timeBlocks })
    await act(async () => { resolve(block); await pending })
    expect(client.getQueryData(qk.timeBlocks)).toEqual(cacheExists ? [] : undefined)
  })

  it.each(["task", "list"] as const)("invalidates blocks after %s deletion", async resource => {
    client.setQueryData(qk.tasks, [])
    client.setQueryData(qk.lists, [])
    client.setQueryData(qk.timeBlocks, [block])
    vi.mocked(api.delete).mockResolvedValue(undefined)
    const { result } = renderHook(() => ({ task: useDeleteTask(), list: useDeleteList() }), { wrapper })
    await act(async () => { await result.current[resource].mutateAsync("id") })
    expect(api.delete).toHaveBeenCalledWith(resource === "task" ? "/tasks/id" : "/lists/id")
    expect(client.getQueryState(qk.timeBlocks)?.isInvalidated).toBe(true)
  })
})
