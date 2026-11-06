// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, expect, it, vi } from "vitest"
import { api } from "@/api/client"
import { JournalProgress } from "./journal-progress"

vi.mock("@/api/client", () => ({ api: { get: vi.fn(), post: vi.fn() } }))
afterEach(() => { cleanup(); vi.resetAllMocks() })
const ready = { date: "2026-11-06", entry_exists: true, updated_at: "2026-11-06T10:00:00", keyword: "ready", semantic: "ready" }
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const content = (day: string, unsaved = false) => <QueryClientProvider client={client}><JournalProgress key={day} day={day} unsaved={unsaved} /></QueryClientProvider>
  const view = render(content(ready.date))
  return { client, ...view, changeDay: (day: string) => view.rerender(content(day)), unsaved: () => view.rerender(content(ready.date, true)) }
}
async function open() {
  fireEvent.click(screen.getByText("Save and search details"))
  await act(async () => { fireEvent(screen.getByText("Save and search details").closest("details")!, new Event("toggle")) })
}

it("fetches persisted receipts only on disclosure and retains a saved entry on indexing failure", async () => {
  vi.mocked(api.get).mockResolvedValue({ ...ready, semantic: "missing" })
  vi.mocked(api.post).mockRejectedValue(new Error("Offline"))
  const view = mount()
  expect(api.get).not.toHaveBeenCalled()
  await open()
  await screen.findByText("Semantic search index missing.")
  expect(screen.getByText("Keyword search ready.")).toBeTruthy()
  fireEvent.click(screen.getByRole("button", { name: "Retry indexing" }))
  await screen.findByRole("alert")
  expect(api.post).toHaveBeenCalledWith(`/journal/${ready.date}/reindex`, {})
  view.unsaved()
  expect(screen.getByText(/editor changes are still waiting/)).toBeTruthy()
  view.client.clear()
})

it("repairs indexing from a backend receipt rather than elapsed time", async () => {
  vi.mocked(api.get).mockResolvedValueOnce({ ...ready, keyword: "missing", semantic: "missing" }).mockResolvedValue(ready)
  vi.mocked(api.post).mockResolvedValue(ready)
  const { client } = mount()
  await open()
  fireEvent.click(await screen.findByRole("button", { name: "Retry indexing" }))
  await screen.findByText("Semantic search ready.")
  expect(screen.queryByRole("button", { name: "Retry indexing" })).toBeNull()
  client.clear()
})

it("offers status retry without implying local save failure and scopes disclosure to its day", async () => {
  vi.mocked(api.get).mockRejectedValueOnce(new Error("Offline")).mockResolvedValue(ready)
  const { client, changeDay } = mount()
  await open()
  fireEvent.click(await screen.findByRole("button", { name: "Retry status check" }))
  await screen.findByText("Keyword search ready.")
  changeDay("2026-11-07")
  expect(screen.queryByText("Keyword search ready.")).toBeNull()
  await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2))
  client.clear()
})
