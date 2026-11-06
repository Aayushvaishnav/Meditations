// @vitest-environment jsdom
import type { ReactNode } from "react"
import { act, cleanup, renderHook, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, expect, it, vi } from "vitest"
import { api } from "@/api/client"
import { useJournalStatus } from "./journal-status"
import { useSaveJournal } from "./journal"
import { useCapture } from "./ai"

vi.mock("@/api/client", () => ({ api: { get: vi.fn(), put: vi.fn(), post: vi.fn() }, ApiError: class extends Error {} }))
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
afterEach(() => { cleanup(); vi.resetAllMocks() })

it.each(["save", "capture"])("refreshes an open persisted index receipt after %s", async (operation) => {
  const day = "2026-11-06"
  let persisted = false
  vi.mocked(api.get).mockImplementation(async () => ({ date: day, entry_exists: persisted, updated_at: null, keyword: persisted ? "ready" : "not_applicable", semantic: persisted ? "missing" : "not_applicable" }))
  vi.mocked(api.put).mockImplementation(async () => { persisted = true; return { saved: true } })
  vi.mocked(api.post).mockImplementation(async () => { persisted = true; return { tasks: [], journal_snippet: "A new memory" } })
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  const { result } = renderHook(() => ({ status: useJournalStatus(day, true), save: useSaveJournal(), capture: useCapture() }), { wrapper })
  await waitFor(() => expect(result.current.status.data?.keyword).toBe("not_applicable"))
  await act(async () => {
    if (operation === "save") await result.current.save.mutateAsync({ day, raw_markdown: "A new memory" })
    else await result.current.capture.mutateAsync("Remember this")
  })
  await waitFor(() => expect(result.current.status.data?.keyword).toBe("ready"))
  expect(result.current.status.data?.semantic).toBe("missing")
  client.clear()
})
