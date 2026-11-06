// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { InboundOverlay, InboundOverlayItem } from "@/api/calendar-inbound-types"

const overlays = new Map<string, InboundOverlay>()
const connections = { data: [
  { id: "c1", server_url: "https://dav.test/", calendar_url: "https://dav.test/cal/", state: "connected", enabled: true, credential_state: "present" },
  { id: "c2", server_url: "https://dav.test/", calendar_url: "https://dav.test/other/", state: "disconnected", enabled: false, credential_state: "absent" },
], isSuccess: true }

vi.mock("@/hooks/api", () => ({
  useCalendarConnections: () => connections,
  useInboundOverlay: (selection: {kind: string; id?: string}) => (selection.kind === "none" ? { data: undefined } : { data: overlays.get(selection.id!), isSuccess: overlays.has(selection.id!) }),
}))

import { CalendarLiveOverlay, LiveEventChip, LiveEventDetails } from "./calendar-live-overlay"

afterEach(cleanup)

const dentist: InboundOverlayItem = { connection_id: "c1", id: "e1", uid: "u1", summary: "Dentist", status: "CONFIRMED", interval: { kind: "timed", start: "2026-01-15T09:00:00Z", end: "2026-01-15T10:00:00Z" } }

describe("live calendar overlay", () => {
  it("lists only connected calendars as options and starts hidden", () => {
    overlays.clear()
    render(<CalendarLiveOverlay>{() => null}</CalendarLiveOverlay>)
    const select = screen.getByLabelText("Live calendar") as HTMLSelectElement
    expect(Array.from(select.options).map(option => option.value)).toEqual(["", "c1"])
    expect(select.value).toBe("")
  })

  it("renders mirrored items and an unplaced count after selection", async () => {
    overlays.set("c1", {
      connection_id: "c1",
      reconciliation: {state: "current", capability: "listing", last_synced_at: "2026-01-15T10:00:00", last_error: null},
      items: [dentist],
      unplaced: [{ connection_id: "c1", id: "e2", uid: "u2", summary: "Series", reason: "recurrence" }],
    })
    let rendered: { count: number; unplaced: number } | null = null
    render(<CalendarLiveOverlay>{(items, unplaced) => { rendered = { count: items.length, unplaced }; return null }}</CalendarLiveOverlay>)
    fireEvent.change(screen.getByLabelText("Live calendar"), { target: { value: "c1" } })
    await waitFor(() => expect(rendered).toEqual({ count: 1, unplaced: 1 }))
    expect(screen.getByText(/1 mirrored appointments/i)).toBeDefined()
    expect(screen.getByText(/1 cannot be placed/i)).toBeDefined()
  })

  it("labels chips and details read-only", () => {
    render(<div><LiveEventChip event={dentist} onOpen={() => {}} /><LiveEventDetails event={dentist} /></div>)
    expect(screen.getByText("Mirrored")).toBeDefined()
    expect(screen.getByText(/Mirrored from the connected calendar · Read-only · confirmed/i)).toBeDefined()
  })
})

it("reports stale selected live data outside the closed controls without unmounting events", async () => {
  const { CalendarSources } = await import("./calendar-sources")
  overlays.set("c1", {
    connection_id: "c1",
    reconciliation: { state: "error", capability: "listing", last_synced_at: "2026-01-15T10:00:00", last_error: "Server unavailable" },
    items: [dentist], unplaced: [],
  })
  render(<CalendarLiveOverlay inlineControls={false}>{(items, _count, controls, summary) => <>
    <CalendarSources summary={summary}>{controls}</CalendarSources>
    {items.map(item => <LiveEventChip key={item.id} event={item} onOpen={() => {}} />)}
  </>}</CalendarLiveOverlay>)
  const trigger = screen.getByRole("button", { name: "Calendar sources" })
  fireEvent.click(trigger)
  fireEvent.change(screen.getByLabelText("Live calendar"), { target: { value: "c1" } })
  expect(screen.getByText(/Last successful check:/)).toBeDefined()
  fireEvent.click(trigger)
  expect(screen.getByText(/Live:.*stale appointments/)).toBeDefined()
  expect(screen.getByRole("button", { name: /Dentist/ })).toBeDefined()
  expect(screen.queryByRole("combobox", { name: "Live calendar" })).toBeNull()
})

it("reports confirmed mirror checks in the compact sources summary", () => {
  overlays.set("c1", { connection_id: "c1", reconciliation: { state: "current", capability: "listing", last_synced_at: "2020-01-01T00:00:00", last_error: null }, items: [], unplaced: [] })
  render(<CalendarLiveOverlay inlineControls={false}>{(_items, _count, _controls, summary) => <p>{summary}</p>}</CalendarLiveOverlay>)
  // Selection remains explicit; hidden sources do not claim a current mirror
  expect(screen.getByText("Live hidden")).toBeTruthy()
  cleanup()
  render(<CalendarLiveOverlay>{(_items, _count, _controls, summary) => <p>{summary}</p>}</CalendarLiveOverlay>)
  fireEvent.change(screen.getByLabelText("Live calendar"), { target: { value: "c1" } })
  expect(screen.getByText(/Live:.*Mirror current as of last confirmed check/)).toBeTruthy()
  expect(screen.getByText(/Last successful check:/)).toBeTruthy()
})
