import { overlayWindowQuery, type CalendarOverlayWindow } from "@/lib/calendar-overlay-window"
import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { ImportedOverlay } from "@/api/calendar-overlay-types"
import type { CalendarImportTarget, CalendarImportResult, ImportedCalendarSource, ImportedCalendarEvent } from "@/api/calendar-import-types"

// Imported calendars have their own cache; uploads never change task telemetry
export const calendarImportsKey = ["calendar-imports"] as const
const calendarImportMutationKey = ["calendar-import-operation"] as const
export function useImportedCalendars() {
  return useQuery({
    queryKey: calendarImportsKey,
    queryFn: () => api.get<ImportedCalendarSource[]>("/calendar/imports"),
  })
}
export function useImportedCalendarEvents(target: CalendarImportTarget) {
  return useQuery({
    queryKey: [...calendarImportsKey, "events", target.kind === "existing" ? target.source_id : { kind: "new" }],
    enabled: target.kind === "existing",
    queryFn: () => {
      if (target.kind !== "existing") throw new Error("Choose an imported calendar first")
      return api.get<ImportedCalendarEvent[]>(`/calendar/imports/${encodeURIComponent(target.source_id)}/events`)
    },
  })
}
export function useCalendarImportPending() {
  return useIsMutating({ mutationKey: calendarImportMutationKey }) > 0
}
export function useImportCalendar() {
  const qc = useQueryClient()
  return useMutation({
    mutationKey: calendarImportMutationKey,
    mutationFn: async ({ target, file }: { target: CalendarImportTarget; file: File }) => {
      let content: string
      try {
        content = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(await file.arrayBuffer())
      } catch {
        throw new Error("Could not read this file as UTF-8. Choose a UTF-8 iCalendar file and retry.")
      }
      return api.post<CalendarImportResult>("/calendar/imports", { target, content })
    },
    onSettled: () => qc.invalidateQueries({ queryKey: calendarImportsKey }),
  })
}
export function useRemoveImportedCalendar() {
  const qc = useQueryClient()
  return useMutation({
    mutationKey: calendarImportMutationKey,
    mutationFn: (sourceId: string) => api.delete<void>(`/calendar/imports/${encodeURIComponent(sourceId)}`),
    onSettled: () => qc.invalidateQueries({ queryKey: calendarImportsKey }),
  })
}
export type OverlaySelection = { kind: "none" } | { kind: "source"; id: string }
export function useImportedCalendarOverlay(selection: OverlaySelection, window?: CalendarOverlayWindow) {
  return useQuery({
    queryKey: ["calendar-imports", "overlay", selection, window ?? { kind: "inventory" }],
    enabled: selection.kind === "source",
    queryFn: () => {
      if (selection.kind !== "source") throw new Error("Choose an imported calendar first")
      return api.get<ImportedOverlay>(`/calendar/imports/${encodeURIComponent(selection.id)}/overlay${overlayWindowQuery(window)}`)
    },
  })
}
