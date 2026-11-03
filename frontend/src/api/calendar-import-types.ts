export interface ImportedCalendarSource {
  id: string
  name: string
  event_count: number
  updated_at: string
}

export type CalendarImportTarget =
  | { kind: "new"; name: string }
  | { kind: "existing"; source_id: string }

export interface CalendarImportResult {
  source_id: string
  created: number
  updated: number
  unchanged: number
}

export interface ImportedCalendarEvent {
  id: string
  uid: string
  summary: string
  recurrence_kind: "master" | "date" | "utc" | "local" | "floating"
  recurrence_id: string
  time_zone: string | null
  recurrence_time_zone: string | null
  start_kind: "date" | "utc" | "local" | "floating" | "unspecified"
  status: string
  has_recurrence: boolean
  start_value: string | null
  end_value: string | null
  representation: "opaque"
}
