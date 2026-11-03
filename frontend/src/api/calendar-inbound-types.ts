import type { ImportedEventInterval } from "./calendar-overlay-types"

export interface InboundOverlayItem {
  connection_id: string
  id: string
  uid: string
  summary: string
  status: string
  interval: ImportedEventInterval
}

export interface InboundOverlayUnplaced {
  connection_id: string
  id: string
  uid: string
  summary: string
  reason: string
}

export interface InboundOverlay {
  connection_id: string
  reconciliation: {
    state: "never" | "current" | "error"
    capability: "unknown" | "sync_token" | "listing"
    last_synced_at: string | null
    last_error: string | null
  }
  items: InboundOverlayItem[]
  unplaced: InboundOverlayUnplaced[]
}
