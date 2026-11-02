// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { afterEach, expect, it, vi } from "vitest"
import { api } from "@/api/client"
import { useDailyScore, useSaveAppPrefs } from "./api"

vi.mock("@/api/client", () => ({ api: { get: vi.fn(), put: vi.fn() }, ApiError: class extends Error {} }))
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }))

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

it("refreshes live daily scores when the focus target changes", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  let target = 4
  vi.mocked(api.get).mockImplementation(async () => ({ target_deep_work_hours: target, final_score: target === 4 ? 32.5 : 50 }))
  vi.mocked(api.put).mockImplementation(async () => {
    target = 2
    return { target_deep_work_hours: target }
  })
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  const { result } = renderHook(() => ({ score: useDailyScore("2026-09-14", true), save: useSaveAppPrefs() }), { wrapper })
  await waitFor(() => expect(result.current.score.data?.final_score).toBe(32.5))
  await act(async () => { await result.current.save.mutateAsync({ target_deep_work_hours: 2 }) })
  await waitFor(() => expect(result.current.score.data?.final_score).toBe(50))
  client.clear()
})
