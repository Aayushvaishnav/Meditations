// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { CalendarView } from "./calendar-view"
import { calendarInboundKey } from "@/hooks/calendar-inbound"
import type { InboundOverlay } from "@/api/calendar-inbound-types"

const overlayPath = "/calendar/connections/c1/inbound/overlay"
const connection = { id: "c1", calendar_url: "https://dav.test/personal", state: "connected", enabled: true }
function overlay(summary = "Live appointment"): InboundOverlay {
  return {
    connection_id: "c1",
    reconciliation: { state: "current", capability: "listing", last_synced_at: "2026-03-08T10:00:00", last_error: null },
    items: [{ connection_id: "c1", id: "event", uid: "event", summary, status: "CONFIRMED", interval: { kind: "date", start: "2026-03-08", end: "2026-03-09" } }],
    unplaced: [],
  }
}
let client: QueryClient
let routes: Record<string, () => unknown>
let fetcher: ReturnType<typeof vi.fn>
const disclosure = () => screen.getByRole("button", { name: "Calendar sources" })
const chips = (summary = "Live appointment") => screen.queryAllByRole("button").filter(button => button.textContent === `${summary}Mirrored`)

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] })
  vi.setSystemTime(new Date(2026, 2, 8, 12))
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  routes = { "/calendar/imports": () => [], "/time-blocks": () => [], "/calendar/connections": () => [connection], [overlayPath]: () => overlay() }
  fetcher = vi.fn(async (url: string) => {
    const path = new URL(url, "http://localhost").pathname.replace(/^\/api/, "")
    if (!routes[path]) throw new Error(`Unexpected request ${path}`)
    const result = await routes[path]!()
    return result instanceof Response ? result : new Response(JSON.stringify(result), { status: 200 })
  })
  vi.stubGlobal("fetch", fetcher)
})
afterEach(() => { cleanup(); client.clear(); vi.unstubAllGlobals(); vi.useRealTimers() })

async function selectLiveCalendar() {
  render(<QueryClientProvider client={client}><CalendarView tasks={[]} scope={{ kind: "smart", id: "all" }} search="" /></QueryClientProvider>)
  expect(disclosure().getAttribute("aria-expanded")).toBe("false")
  fireEvent.click(disclosure())
  await screen.findByRole("option", { name: connection.calendar_url })
  fireEvent.change(screen.getByLabelText("Live calendar"), { target: { value: "c1" } })
  await waitFor(() => expect(chips()).toHaveLength(1))
  fireEvent.click(disclosure())
  expect(screen.queryByRole("combobox", { name: "Live calendar" })).toBeNull()
}

describe("live calendar sources disclosure with real query hooks", () => {
  it("keeps its query owner and polling active while controls are closed", async () => {
    // Enable interval timers before mounting so React Query schedules a controllable poll
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] })
    await selectLiveCalendar()
    expect(chips()).toHaveLength(1)
    const query = client.getQueryCache().find({ queryKey: [...calendarInboundKey, "overlay", { kind: "connection", id: "c1" }], exact: true })!
    expect(query.getObserversCount()).toBe(1)
    const before = fetcher.mock.calls.filter(([url]) => String(url).includes(overlayPath)).length
    routes[overlayPath] = () => overlay("Polled appointment")
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
    await waitFor(() => expect(chips("Polled appointment")).toHaveLength(1))
    expect(chips()).toHaveLength(0)
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes(overlayPath)).length).toBeGreaterThan(before)
    expect(query.getObserversCount()).toBe(1)
    expect(disclosure().getAttribute("aria-expanded")).toBe("false")
  })

  it.each(["disconnect", "remove"] as const)("removes mirrored events when the selected connection is %s while closed", async operation => {
    await selectLiveCalendar()
    routes["/calendar/connections"] = () => operation === "disconnect" ? [{ ...connection, state: "disconnected" }] : []
    await act(async () => { await client.invalidateQueries({ queryKey: ["calendar-connections"] }) })
    await waitFor(() => expect(chips()).toHaveLength(0))
    expect(screen.getByText(/Live hidden/)).toBeTruthy()
    expect(disclosure().getAttribute("aria-expanded")).toBe("false")
    fireEvent.click(disclosure())
    expect((screen.getByLabelText("Live calendar") as HTMLSelectElement).value).toBe("")
    expect(screen.queryByRole("option", { name: connection.calendar_url })).toBeNull()
  })

  it.each(["appointments", "connections"] as const)("exposes closed %s errors and allows retry after opening", async resource => {
    await selectLiveCalendar()
    const path = resource === "appointments" ? overlayPath : "/calendar/connections"
    const key = resource === "appointments" ? calendarInboundKey : ["calendar-connections"]
    routes[path] = () => new Response("failed", { status: 500 })
    await act(async () => { await client.invalidateQueries({ queryKey: key }) })
    await waitFor(() => expect(chips()).toHaveLength(0))
    expect(screen.getByText(/Live:.*error; open sources to retry/)).toBeTruthy()
    expect(screen.queryByRole("button", { name: `Retry ${resource}` })).toBeNull()
    fireEvent.click(disclosure())
    routes[path] = () => resource === "appointments" ? overlay() : [connection]
    fireEvent.click(screen.getByRole("button", { name: `Retry ${resource}` }))
    await waitFor(() => expect(chips()).toHaveLength(1))
    fireEvent.click(disclosure())
    expect(screen.queryByText(/error; open sources to retry/)).toBeNull()
    expect(chips()).toHaveLength(1)
  })
})
