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
  items: InboundOverlayItem[]
  unplaced: InboundOverlayUnplaced[]
}
