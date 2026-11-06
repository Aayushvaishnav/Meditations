import { useEffect, useRef, useSyncExternalStore } from "react"
import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { api } from "@/api/client"
import { calendarSetupPending, subscribeCalendarSetup } from "@/lib/calendar-setup-operation"
import { calendarInboundKey } from "./calendar-inbound"
import { qk } from "./query-keys"
import { createBackup } from "@/lib/backup"
import { createCalendarExport } from "@/lib/calendar-export"
import { createDataExport } from "@/lib/data-export"
import { startBrowserDownload, type FileDownloadResult } from "@/lib/file-download"
import type { AppPrefs, SearchHit, SearchStatus, CalendarConnection, CalendarSyncStatus, CalendarLinkView } from "@/api/types"

export * from "./tasks"
export * from "./journal"
export * from "./ai"
export * from "./calendar-imports"
export * from "./query-keys"

export function useHealth() {
  return useQuery({
    queryKey: qk.health,
    queryFn: () => api.get<{ status: string }>("/health"),
    refetchInterval: 30_000,
    retry: 0,
  })
}
export function useSearch(query: string, enabled: boolean) {
  return useQuery({
    queryKey: ["search", query],
    queryFn: () => api.get<SearchHit[]>(`/search?q=${encodeURIComponent(query)}`),
    enabled: enabled && query.trim().length >= 2,
  })
}
export function useSearchStatus(enabled: boolean) {
  return useQuery({
    queryKey: ["search-status"],
    queryFn: () => api.get<SearchStatus>("/search/status"),
    enabled,
  })
}
export function useAppPrefs(enabled: boolean) {
  return useQuery({ queryKey: ["app-prefs"], queryFn: () => api.get<AppPrefs>("/settings/app"), enabled })
}
export function useSaveAppPrefs() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: { target_deep_work_hours?: number }) => api.put<AppPrefs>("/settings/app", input),
    onSuccess: (data) => {
      qc.setQueryData(["app-prefs"], data)
      return Promise.all([
        qc.invalidateQueries({ queryKey: ["app-prefs"] }),
        qc.invalidateQueries({ queryKey: ["scores-daily"] }),
      ])
    },
    onError: () => toast.error("Couldn't save preferences"),
  })
}
export function useBackup() {
  return useFileDownload(createBackup)
}
export function useDataExport() {
  return useFileDownload(createDataExport)
}
export function useCalendarExport() {
  return useFileDownload(createCalendarExport)
}
function useFileDownload<T = void>(create: (input: T) => Promise<FileDownloadResult>) {
  const active = useRef(false)
  const download = useRef<{ kind: "none" } | { kind: "active"; release: () => void }>({ kind: "none" })
  useEffect(() => {
    active.current = true
    return () => {
      active.current = false
      if (download.current.kind === "active") download.current.release()
      download.current = { kind: "none" }
    }
  }, [])
  return useMutation({
    mutationFn: async (input: T) => {
      const result = await create(input)
      if (result.kind !== "download") return result
      if (!active.current) return { kind: "left-view" } as const
      const release = startBrowserDownload(result.blob, result.filename)
      if (download.current.kind === "active") download.current.release()
      download.current = { kind: "active", release }
      return { kind: "download-started" } as const
    },
    retry: false,
    gcTime: 0,
  })
}
export function useReindex() {
  return useMutation({
    mutationFn: () => api.post<{ indexed: number; semantic: boolean }>("/search/reindex", {}),
    onSuccess: (data) =>
      toast.success(`Rebuilt index — ${data.indexed} documents`, {
        description: data.semantic ? "Semantic embeddings refreshed." : "Embedding model unavailable — keyword index only.",
      }),
    onError: () => toast.error("Couldn't rebuild the search index"),
  })
}
// Calendar control data never shares the canonical tasks cache
export const calendarKey = ["calendar-connections"] as const
const calendarMutationKey = ["calendar-control"] as const
export function useCalendarConnections() {
  return useQuery({ queryKey: calendarKey, queryFn: () => api.get<CalendarConnection[]>("/calendar/connections"), refetchInterval: 10_000 })
}
export function useCalendarStatus(id: string) {
  return useQuery({ queryKey: [...calendarKey, id, "status"], queryFn: () => api.get<CalendarSyncStatus>(`/calendar/connections/${id}/status`), refetchInterval: 10_000 })
}
export function useCalendarLinks(id: string) {
  return useQuery({ queryKey: [...calendarKey, id, "links"], queryFn: () => api.get<CalendarLinkView[]>(`/calendar/connections/${id}/links`), refetchInterval: 10_000 })
}
export function useCalendarControl() {
  const qc = useQueryClient()
  const pending = useIsMutating({ mutationKey: calendarMutationKey })
  const mutation = useMutation({
    mutationKey: calendarMutationKey,
    mutationFn: ({ path, method = "post", body = {} }: { path: string; method?: "post" | "patch"; body?: Record<string, unknown> }) => api[method](`/calendar/connections${path}`, body),
    onSettled: () => Promise.all([
      qc.invalidateQueries({ queryKey: calendarKey }),
      qc.invalidateQueries({ queryKey: calendarInboundKey }),
    ]),
  })
  return { ...mutation, isPending: pending > 0 }
}
export function useCalendarAllLinks() {
  return useQuery({
    queryKey: [...calendarKey, "all-links"],
    queryFn: async () => {
      const connections = await api.get<CalendarConnection[]>("/calendar/connections")
      return (await Promise.all(connections.map(connection =>
        api.get<CalendarLinkView[]>(`/calendar/connections/${connection.id}/links`),
      ))).flat()
    },
    refetchInterval: 10_000,
  })
}
export function useCalendarSetupPending() {
  return useSyncExternalStore(subscribeCalendarSetup, calendarSetupPending)
}


export { webhooksKey, useWebhooks, useWebhookDeliveries, useWebhookAction } from "./webhooks"

export { calendarInboundKey, useInboundOverlay, useCalendarResume, useResumeCalendarReconciliation } from "./calendar-inbound"
