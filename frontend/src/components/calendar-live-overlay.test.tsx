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
  useInboundOverlay: (id: string | null) => (id === null ? { data: undefined } : { data: overlays.get(id), isSuccess: overlays.has(id) }),
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
