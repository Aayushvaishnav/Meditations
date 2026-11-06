// @vitest-environment jsdom
import type { ReactNode } from "react"
import { act, cleanup, renderHook } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, expect, it, vi } from "vitest"
import { useDailyRollupStream } from "./ai"
import { sseEvents } from "@/lib/stream"
import { toast } from "sonner"

vi.mock("@/lib/stream", () => ({ sseEvents: vi.fn() }))
vi.mock("sonner", () => ({ toast: { success: vi.fn() } }))
afterEach(() => { cleanup(); vi.resetAllMocks() })
function mount() {
  const client = new QueryClient()
  const invalidate = vi.spyOn(client, "invalidateQueries")
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  return { client, invalidate, ...renderHook(() => useDailyRollupStream(), { wrapper }) }
}

it("requires a final completion event before reporting a saved review", async () => {
  vi.mocked(sseEvents).mockImplementation(async function* () { yield { event: "partial", data: { feedback: "Preview" } } })
  const { result, client, invalidate } = mount()
  await act(async () => { await result.current.review("2026-11-06") })
  expect(result.current.error).toContain("before completion")
  expect(result.current.partial).toBeNull()
  expect(result.current.pending).toBe(false)
  expect(toast.success).not.toHaveBeenCalled()
  expect(invalidate).not.toHaveBeenCalled()
  client.clear()
})

it("preserves the error and supports a confirmed retry", async () => {
  vi.mocked(sseEvents).mockImplementationOnce(async function* () { yield { event: "error", data: { message: "Provider offline" } } })
    .mockImplementationOnce(async function* () { yield { event: "done", data: { final_score: 90 } } })
  const { result, client, invalidate } = mount()
  await act(async () => { await result.current.review("2026-11-06") })
  expect(result.current.error).toBe("Provider offline")
  await act(async () => { await result.current.review("2026-11-06") })
  expect(result.current.error).toBeNull()
  expect(toast.success).toHaveBeenCalledOnce()
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["scores-daily", "2026-11-06"] })
  client.clear()
})
