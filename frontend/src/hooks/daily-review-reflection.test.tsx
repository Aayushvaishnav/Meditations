// @vitest-environment jsdom
import type { ReactNode } from "react"
import { act, cleanup, renderHook } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { useDailyRollupStream } from "./ai"
import { sseEvents } from "@/lib/stream"
import { useUi } from "@/stores/ui"
import { toast } from "sonner"

vi.mock("@/lib/stream", () => ({ sseEvents: vi.fn() }))
vi.mock("sonner", () => ({ toast: { success: vi.fn() } }))
beforeEach(() => { localStorage.clear(); useUi.setState(useUi.getInitialState()) })
afterEach(() => { cleanup(); vi.resetAllMocks(); useUi.setState(useUi.getInitialState()); localStorage.clear() })

it.each(["scored", "reflection"] as const)("uses the current %s preference when an in-flight review completes", async (scoreDisplay) => {
  vi.mocked(sseEvents).mockImplementation(async function* () {
    useUi.getState().setScoreDisplay(scoreDisplay)
    yield { event: "done", data: { final_score: 87.6 } }
  })
  useUi.getState().setScoreDisplay(scoreDisplay === "scored" ? "reflection" : "scored")
  const client = new QueryClient()
  const invalidate = vi.spyOn(client, "invalidateQueries")
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  const { result } = renderHook(() => useDailyRollupStream(), { wrapper })
  await act(async () => { await result.current.review("2026-11-06") })
  expect(result.current.error).toBeNull()
  expect(toast.success).toHaveBeenCalledOnce()
  const message = vi.mocked(toast.success).mock.calls[0][0]
  expect(message).toContain("saved locally")
  if (scoreDisplay === "reflection") expect(message).not.toMatch(/score|87\.6/)
  else expect(message).toContain("87.6")
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["scores-daily", "2026-11-06"] })
  expect(sseEvents).toHaveBeenCalledWith("/agents/rollup/daily/stream?day=2026-11-06", {})
  client.clear()
})
