import { describe, expect, it } from "vitest"
import type { CalendarLinkView } from "@/api/types"
import { calendarLinkProgress, calendarMirrorProgress } from "./calendar-progress"

const link: CalendarLinkView = { id: "link", connection_id: "calendar", local_block_id: "block", selection_state: "opted_in", state: "synced", desired_action: "upsert", acknowledged_action: "upsert", local_revision: 2, acknowledged_revision: 2, last_error: null }

describe("calendar publication acknowledgement", () => {
  it("requires both revision and action equality, instead of a synced label", () => {
    expect(calendarLinkProgress(link)).toBe("acknowledged")
    expect(calendarLinkProgress({ ...link, acknowledged_revision: 1 })).toBe("queued")
    expect(calendarLinkProgress({ ...link, acknowledged_action: "unknown" })).toBe("queued")
    expect(calendarLinkProgress({ ...link, state: "pending" })).toBe("acknowledged")
  })
  it("distinguishes deletion acknowledgement from deliberate detachment", () => {
    const removed = { ...link, state: "detached" as const, selection_state: "opted_out" as const, desired_action: "delete" as const, acknowledged_action: "delete" as const }
    expect(calendarLinkProgress(removed)).toBe("removed")
    expect(calendarLinkProgress({ ...removed, acknowledged_revision: 1 })).toBe("removing")
    expect(calendarLinkProgress({ ...removed, selection_state: "detached" })).toBe("detached")
  })
})

describe("calendar mirror checks", () => {
  const connection = { enabled: true, state: "connected" as const }
  const reconciliation = { state: "current" as const, capability: "listing" as const, last_synced_at: "2020-01-01", last_error: null }
  it("uses confirmed checks rather than age heuristics", () => {
    expect(calendarMirrorProgress(connection, reconciliation, { fetching: false, failed: false })).toBe("current")
    expect(calendarMirrorProgress(connection, undefined, { fetching: false, failed: false })).toBe("never-checked")
    expect(calendarMirrorProgress(connection, reconciliation, { fetching: true, failed: false })).toBe("checking")
  })
  it("keeps failed or paused mirrors stale even with cached confirmation", () => {
    expect(calendarMirrorProgress(connection, reconciliation, { fetching: false, failed: true })).toBe("stale")
    expect(calendarMirrorProgress({ ...connection, enabled: false }, reconciliation, { fetching: true, failed: false })).toBe("stale")
  })
})
