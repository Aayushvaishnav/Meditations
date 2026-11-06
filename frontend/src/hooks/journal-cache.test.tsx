// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { afterEach, expect, it, vi } from "vitest"
import { api } from "@/api/client"
import { useJournalEntry, useSaveJournal, type JournalDocument } from "./api"

vi.mock("@/api/client", () => ({ api: { get: vi.fn(), put: vi.fn() }, ApiError: class extends Error {} }))
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }))
afterEach(() => { cleanup(); vi.resetAllMocks() })

const day = "2026-10-20"
const key = ["journal", day]
const document: JournalDocument = { date: day, raw_markdown: "Entry", mood: null, energy: null }
function setup(previous: JournalDocument | null | undefined) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (previous !== undefined) client.setQueryData(key, previous)
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  const hook = renderHook(() => useSaveJournal(), { wrapper })
  return { client, ...hook }
}

it.each([null, undefined, document])("restores the exact snapshot after a failed write from %j", async (previous) => {
  let reject!: (error: Error) => void
  vi.mocked(api.put).mockImplementation(() => new Promise((_resolve, fail) => { reject = fail }))
  const { client, result } = setup(previous)
  let pending!: Promise<unknown>
  act(() => { pending = result.current.mutateAsync({ day, raw_markdown: "New entry" }).catch(() => undefined) })
  await waitFor(() => expect(client.getQueryData(key)).toEqual({ ...document, raw_markdown: "New entry" }))
  await act(async () => { reject(new Error("Write failed")); await pending })
  expect(client.getQueryData(key)).toEqual(previous)
  if (previous === undefined) expect(client.getQueryState(key)).toBeUndefined()
  client.clear()
})

it.each([
  { raw_markdown: "", mood: 3, energy: null },
  { raw_markdown: "", mood: null, energy: 4 },
  { raw_markdown: "", mood: null, energy: null },
  { raw_markdown: " \n ", mood: null, energy: null },
])("optimistically represents rating-only and empty saves: %j", async (input) => {
  vi.mocked(api.put).mockResolvedValue({ saved: false })
  const { client, result } = setup(document)
  await act(async () => { await result.current.mutateAsync({ day, ...input }) })
  expect(client.getQueryData(key)).toEqual(input.mood !== null || input.energy !== null ? { date: day, ...input } : null)
  client.clear()
})

it("preserves real server metadata from a GET", async () => {
  const serverEntry = { ...document, tasks_done: 9, updated_at: "server timestamp" }
  vi.mocked(api.get).mockResolvedValue(serverEntry)
  const client = new QueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  const { result } = renderHook(() => useJournalEntry(day), { wrapper })
  await waitFor(() => expect(result.current.data).toEqual(serverEntry))
  expect(client.getQueryData(key)).toEqual(serverEntry)
  client.clear()
})
