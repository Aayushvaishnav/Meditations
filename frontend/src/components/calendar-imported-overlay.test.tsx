// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { useDraggable } from "@dnd-kit/core"
import { CalendarView } from "./calendar-view"
import { calendarImportsKey, useImportCalendar, useRemoveImportedCalendar } from "@/hooks/api"
import type { ImportedOverlay } from "@/api/calendar-overlay-types"

vi.mock("@dnd-kit/core", async importOriginal => {
  const original = await importOriginal<typeof import("@dnd-kit/core")>()
  return { ...original, useDraggable: vi.fn(original.useDraggable) }
})
const sources = [{ id: "a", name: "Personal" }, { id: "b", name: "Work" }]
function overlay(name = "Dentist"): ImportedOverlay {
  return { source_id: "a", items: [{ id: name, uid: name, source_id: "a", summary: name, status: "CONFIRMED", interval: { kind: "date", start: "2026-03-08", end: "2026-03-10" } }], unplaced: [] }
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
let client: QueryClient
let fetcher: ReturnType<typeof vi.fn>
let routes: Record<string, () => unknown>
function Operations() {
  const remove = useRemoveImportedCalendar()
  const reimport = useImportCalendar()
  return <><button onClick={() => remove.mutate("a")}>Remove source</button><button onClick={() => reimport.mutate({ target: { kind: "existing", source_id: "a" }, file: { arrayBuffer: async () => new TextEncoder().encode("BEGIN:VCALENDAR").buffer } as File })}>Reimport</button></>
}
function view(search = "", list = "all") {
  return <QueryClientProvider client={client}><Operations /><CalendarView tasks={[]} scope={list === "all" ? { kind: "smart", id: "all" } : { kind: "list", id: list }} search={search} /></QueryClientProvider>
}
async function select(id = "a") {
  await screen.findByRole("option", { name: "Personal" })
  fireEvent.change(screen.getByLabelText("Imported calendar"), { target: { value: id } })
}
function chip(name = "Dentist") { return screen.queryAllByRole("button").filter(button => button.textContent === `${name}Imported`) }
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] })
  vi.setSystemTime(new Date(2026, 2, 8, 12))
  vi.mocked(useDraggable).mockClear()
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  routes = { "/calendar/imports": () => sources, "/time-blocks": () => [], "/calendar/imports/a/overlay": () => overlay(), "/calendar/imports/b/overlay": () => overlay("Work meeting") }
  fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const path = new URL(url, "http://localhost").pathname.replace(/^\/api/, "")
    if (init?.method) return new Response(JSON.stringify({}), { status: 200 })
    if (!routes[path]) throw new Error(`Unexpected request ${path}`)
    const value = await routes[path]!()
    return value instanceof Response ? value : new Response(JSON.stringify(value), { status: 200 })
  })
  vi.stubGlobal("fetch", fetcher)
})
afterEach(() => { cleanup(); client.clear(); vi.unstubAllGlobals(); vi.useRealTimers() })

describe("imported calendar overlay with real query hooks", () => {
  it("starts explicitly hidden without fetching appointments; selection survives unrelated task filters", async () => {
    const rendered = render(view())
    await screen.findByRole("option", { name: "Personal" })
    expect((screen.getByLabelText("Imported calendar") as HTMLSelectElement).value).toBe("")
    expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("/overlay"))).toBe(false)
    await select()
    await waitFor(() => expect(chip()).toHaveLength(2))
    rendered.rerender(view("unrelated search", "other-list"))
    expect(chip()).toHaveLength(2)
    fireEvent.change(screen.getByLabelText("Imported calendar"), { target: { value: "" } })
    expect(chip()).toHaveLength(0)
  })
  it("hides stale appointments after either query fails on background refresh", async () => {
    render(view())
    await select()
    await waitFor(() => expect(chip()).toHaveLength(2))
    routes["/calendar/imports/a/overlay"] = () => new Response("failed", { status: 500 })
    await act(async () => { await client.invalidateQueries({ queryKey: [...calendarImportsKey, "overlay"] }) })
    await screen.findByRole("button", { name: "Retry appointments" })
    expect(chip()).toHaveLength(0)
    routes["/calendar/imports/a/overlay"] = () => overlay()
    fireEvent.click(screen.getByRole("button", { name: "Retry appointments" }))
    await waitFor(() => expect(chip()).toHaveLength(2))
    routes["/calendar/imports"] = () => new Response("failed", { status: 500 })
    await act(async () => { await client.invalidateQueries({ queryKey: calendarImportsKey, exact: true }) })
    await screen.findByRole("button", { name: "Retry calendars" })
    expect(chip()).toHaveLength(0)
  })
  it("resets selection to Hidden on remount even when the overlay remains cached", async () => {
    const rendered = render(view())
    await select()
    await waitFor(() => expect(chip()).toHaveLength(2))
    rendered.unmount()
    render(view())
    await screen.findByRole("option", { name: "Personal" })
    expect((screen.getByLabelText("Imported calendar") as HTMLSelectElement).value).toBe("")
    expect(chip()).toHaveLength(0)
  })
  it("opens all appointments from overflow without offering event mutations", async () => {
    const base = overlay().items[0]!
    routes["/calendar/imports/a/overlay"] = () => ({ source_id: "a", unplaced: [], items:
      ["First", "Second", "Third", "Fourth"].map(summary => ({ ...base, id: summary, summary,
        interval: { kind: "date", start: "2026-03-08", end: "2026-03-09" } })) })
    render(view())
    await select()
    const more = await screen.findByRole("button", { name: "+2 more" })
    expect(chip("First")).toHaveLength(1)
    expect(chip("Third")).toHaveLength(0)
    fireEvent.click(more)
    const dialog = await screen.findByRole("dialog")
    for (const name of ["First", "Second", "Third", "Fourth"]) {
      expect(within(dialog).getByText(name)).toBeTruthy()
    }
    expect(fetcher.mock.calls.filter(([, init]) => init?.method)).toHaveLength(0)
  })
  it("isolates a late response after switching sources", async () => {
    const pending = deferred<ImportedOverlay>()
    routes["/calendar/imports/a/overlay"] = () => pending.promise
    render(view())
    await select()
    expect(screen.getByText("Loading imported appointments…")).toBeTruthy()
    await select("b")
    await waitFor(() => expect(chip("Work meeting")).toHaveLength(2))
    await act(async () => pending.resolve(overlay()))
    expect(chip()).toHaveLength(0)
    expect(chip("Work meeting")).toHaveLength(2)
  })
  it("shows source loading, retries source errors, and explains an empty inventory", async () => {
    const pending = deferred<Response>()
    routes["/calendar/imports"] = () => pending.promise
    render(view())
    expect(screen.getByText("Loading imported calendars…")).toBeTruthy()
    await act(async () => pending.resolve(new Response("failed", { status: 500 })))
    await screen.findByRole("button", { name: "Retry calendars" })
    routes["/calendar/imports"] = () => []
    fireEvent.click(screen.getByRole("button", { name: "Retry calendars" }))
    await screen.findByText("Import an .ics file in Settings to add an overlay.")
    expect(fetcher.mock.calls.some(([url]) => String(url).endsWith("/overlay"))).toBe(false)
  })
  it("retries appointment errors and renders empty overlays with outside-grid reasons", async () => {
    routes["/calendar/imports/a/overlay"] = () => new Response("failed", { status: 500 })
    render(view())
    await select()
    await screen.findByRole("button", { name: "Retry appointments" })
    routes["/calendar/imports/a/overlay"] = () => ({ source_id: "a", items: [], unplaced: [{ id: "series", summary: "Recurring class", reason: "recurring_series" }, { id: "bad", summary: "Missing time", reason: "unsupported_time" }] })
    fireEvent.click(screen.getByRole("button", { name: "Retry appointments" }))
    await screen.findByText(/^0 standalone appointments/)
    fireEvent.click(screen.getByText("Outside the grid (2)"))
    expect(screen.getByText(/recurring series/)).toBeTruthy()
    expect(screen.getByText(/unsupported time/)).toBeTruthy()
    expect(chip()).toHaveLength(0)
  })
  it("opens read-only details without registering imported appointments as draggable or writing tasks", async () => {
    render(view())
    await select()
    await waitFor(() => expect(chip()).toHaveLength(2))
    fireEvent.click(chip()[0]!)
    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByText("Dentist")).toBeTruthy()
    expect(within(dialog).getByText(/Imported appointment · Read-only · confirmed/)).toBeTruthy()
    expect(within(dialog).getByText(/2026-03-10 \(end exclusive\)/)).toBeTruthy()
    expect(within(dialog).queryByRole("button", { name: /save|delete|move|clear deadline/i })).toBeNull()
    expect(useDraggable).not.toHaveBeenCalled()
    expect(fetcher.mock.calls.filter(([, init]) => init?.method)).toHaveLength(0)
  })
  it("places floating and timed points on their day without leaking exclusive ends", async () => {
    const base = overlay().items[0]!
    routes["/calendar/imports/a/overlay"] = () => ({ source_id: "a", unplaced: [], items: [
      { ...base, id: "floating", summary: "Floating gap", interval: { kind: "floating", start: "2026-03-08T02:15:00", end: "2026-03-09T00:00:00" } },
      { ...base, id: "point", summary: "Midnight point", interval: { kind: "timed", start: new Date(2026, 2, 9).toISOString(), end: new Date(2026, 2, 9).toISOString() } },
    ] })
    render(view())
    await select()
    await waitFor(() => expect(chip("Floating gap")).toHaveLength(1))
    expect(chip("Midnight point")).toHaveLength(1)
    const cell = (date: string) => within(screen.getByRole("button", { name: `Add task on ${date}` }).parentElement!.parentElement!)
    expect(cell("2026-03-08").getByText("Floating gap")).toBeTruthy()
    expect(cell("2026-03-08").queryByText("Midnight point")).toBeNull()
    expect(cell("2026-03-09").getByText("Midnight point")).toBeTruthy()
    expect(cell("2026-03-09").queryByText("Floating gap")).toBeNull()
  })
  it("invalidates selected overlay on reimport and hides it when a removed source disappears", async () => {
    render(view())
    await select()
    await waitFor(() => expect(chip()).toHaveLength(2))
    routes["/calendar/imports/a/overlay"] = () => overlay("Updated appointment")
    fireEvent.click(screen.getByRole("button", { name: "Reimport" }))
    await waitFor(() => expect(chip("Updated appointment")).toHaveLength(2))
    routes["/calendar/imports"] = () => [sources[1]]
    fireEvent.click(screen.getByRole("button", { name: "Remove source" }))
    await waitFor(() => expect((screen.getByLabelText("Imported calendar") as HTMLSelectElement).value).toBe(""))
    expect(chip("Updated appointment")).toHaveLength(0)
    expect(client.getQueryData(calendarImportsKey)).toEqual([sources[1]])
    expect(fetcher.mock.calls.filter(([url, init]) => String(url).includes("/tasks") && init?.method)).toHaveLength(0)
  })
})

it.each([2, 3])("counts only actually hidden appointments with two imports and %s mirrored events", async count => {
  const base = overlay().items[0]!
  const interval = { kind: "date", start: "2026-03-08", end: "2026-03-09" }
  routes["/calendar/connections"] = () => [{id: "c1", calendar_url: "https://dav.test/calendar", state: "connected", enabled: true}]
  routes["/calendar/imports/a/overlay"] = () => ({source_id: "a", unplaced: [], items: ["Imported one", "Imported two"].map(summary => ({...base, id: summary, summary, interval}))})
  routes["/calendar/connections/c1/inbound/overlay"] = () => ({connection_id: "c1", reconciliation: {state: "current", capability: "listing", last_synced_at: "2026-03-08T10:00:00", last_error: null}, unplaced: [], items: Array.from({length: count}, (_, i) => ({...base, connection_id: "c1", id: `live-${i}`, summary: `Live ${i}`, interval}))})
  render(view())
  await select()
  await screen.findByRole("option", {name: "https://dav.test/calendar"})
  fireEvent.change(screen.getByLabelText("Live calendar"), {target: {value: "c1"}})
  await waitFor(() => expect(screen.queryAllByRole("button").filter(button => button.textContent === "Live 0Mirrored")).toHaveLength(1))
  const day = within(screen.getByRole("button", {name: "Add task on 2026-03-08"}).parentElement!.parentElement!)
  if (count === 2) expect(day.queryByText(/\+\d+ more/)).toBeNull()
  else expect(day.getByText("+1 more")).toBeDefined()
})
