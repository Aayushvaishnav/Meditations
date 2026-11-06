// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, expect, it, vi } from "vitest"
import { api } from "@/api/client"
import { useUi } from "@/stores/ui"
import { CalendarView } from "./calendar-view"
import { calendarRange } from "@/lib/calendar-range"
import { calendarOverlayWindow } from "@/lib/calendar-overlay-window"

vi.mock("@/hooks/api", async importOriginal => ({
  ...await importOriginal<typeof import("@/hooks/api")>(),
  useTimeBlocks: () => ({ data: [], isPending: false, isError: false }),
  useUpdateTask: () => ({ mutate: vi.fn() }),
  useCreateTask: () => ({ mutate: vi.fn() }),
  useReplaceTimeBlock: () => ({ mutate: vi.fn(), isPending: false }),
  useCalendarExport: () => ({ mutate: vi.fn(), isPending: false }),
}))

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers() })

it("retains explicit source authority and requests the visible window through all six modes and navigation", async () => {
  vi.useFakeTimers({ toFake: ["Date"] })
  vi.setSystemTime(new Date(2026, 2, 7, 12))
  useUi.setState({ calendarMode: "month" })
  const get = vi.spyOn(api, "get").mockImplementation(async path => {
    if (path === "/calendar/imports") return [{ id: "import", name: "Personal" }]
    if (path === "/calendar/connections") return [{ id: "live", calendar_url: "https://dav.test/work", state: "connected", enabled: true }]
    if (path.includes("/overlay?")) {
      const source = path.includes("/imports/") ? "import" : "live"
      return { source_id: source, connection_id: source, reconciliation: { state: "current", capability: "sync_token", last_synced_at: null, last_error: null }, items: [0, 1].map(index => ({ id: `${source}:series:2026030${7 + index}`, uid: "shared-series", source_id: source, connection_id: source, summary: `${source} occurrence ${index}`, status: "CONFIRMED", interval: { kind: "date", start: `2026-03-0${7 + index}`, end: `2026-03-0${8 + index}` } })), unplaced: [] }
    }
    throw new Error(`Unexpected path ${path}`)
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  client.setQueryData(["tasks"], [{ id: "local-authority" }])
  render(<QueryClientProvider client={client}><CalendarView tasks={[]} scope={{ kind: "smart", id: "all" }} search="" /></QueryClientProvider>)
  fireEvent.click(screen.getByRole("button", { name: "Calendar sources" }))
  await screen.findByRole("option", { name: "Personal" })
  await screen.findByRole("option", { name: "https://dav.test/work" })
  expect(get.mock.calls.some(([path]) => path.includes("/overlay"))).toBe(false)
  fireEvent.change(screen.getByLabelText("Imported calendar"), { target: { value: "import" } })
  fireEvent.change(screen.getByLabelText("Live calendar"), { target: { value: "live" } })
  for (const mode of ["month", "agenda", "week", "multi-day", "multi-week", "year"] as const) {
    fireEvent.change(screen.getByRole("combobox", { name: "Calendar mode" }), { target: { value: mode } })
    const window = calendarOverlayWindow(calendarRange(new Date(2026, 2, 7), mode).days)
    for (const base of ["/calendar/imports/import/overlay", "/calendar/connections/live/inbound/overlay"]) {
      await waitFor(() => expect(get).toHaveBeenCalledWith(`${base}?start=${window.start}&end=${window.end}`))
    }
    expect((screen.getByLabelText("Imported calendar") as HTMLSelectElement).value).toBe("import")
    expect((screen.getByLabelText("Live calendar") as HTMLSelectElement).value).toBe("live")
    if (mode !== "year") {
      await waitFor(() => expect(screen.getAllByText("import occurrence 0").length).toBeGreaterThan(0))
      expect(screen.getAllByText("live occurrence 0").length).toBeGreaterThan(0)
    }
  }
  fireEvent.click(screen.getByRole("button", { name: "Next year" }))
  await waitFor(() => expect(get.mock.calls.some(([path]) => path.includes("start=2026-12-31&end=2028-01-02"))).toBe(true))
  expect((screen.getByLabelText("Imported calendar") as HTMLSelectElement).value).toBe("import")
  expect(client.getQueryData(["tasks"])).toEqual([{ id: "local-authority" }])
  const overlays = client.getQueryCache().findAll({ predicate: query => query.queryKey.includes("overlay") && query.state.status === "success" })
  for (const query of overlays) {
    const data = query.state.data as { items: { id: string; uid: string }[] }
    expect(new Set(data.items.map(item => item.id)).size).toBe(2)
    expect(new Set(data.items.map(item => item.uid)).size).toBe(1)
  }
  client.clear()
}, 20_000)
