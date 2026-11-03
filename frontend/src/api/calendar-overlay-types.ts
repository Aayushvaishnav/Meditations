export type ImportedEventInterval = {
  kind: "date" | "timed" | "floating"
  start: string
  end: string
}

export interface ImportedOverlayItem {
  id: string
  source_id: string
  uid: string
  summary: string
  status: string
  interval: ImportedEventInterval
}

export interface ImportedOverlay {
  source_id: string
  items: ImportedOverlayItem[]
  unplaced: { id: string; summary: string; reason: string }[]
}
