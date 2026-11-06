import { overlayWindowQuery, type CalendarOverlayWindow } from "@/lib/calendar-overlay-window"
import { useEffect } from "react"
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { InboundOverlay } from "@/api/calendar-inbound-types"

// Reconciled CalDAV caches are independent of imports and task telemetry
export const calendarInboundKey = ["calendar-inbound"] as const
export type LiveSelection = { kind: "none" } | { kind: "connection"; id: string }

export function useInboundOverlay(selection: LiveSelection, window?: CalendarOverlayWindow) {
  return useQuery({
    queryKey: [...calendarInboundKey, "overlay", selection, window ?? { kind: "inventory" }],
    enabled: selection.kind === "connection",
    refetchInterval: 10_000,
    queryFn: () => {
      if (selection.kind !== "connection") throw new Error("Choose a connected calendar first")
      return api.get<InboundOverlay>(`/calendar/connections/${encodeURIComponent(selection.id)}/inbound/overlay${overlayWindowQuery(window)}`)
    },
  })
}

const activePasses = new WeakMap<QueryClient, Promise<void>>()
function reconcile(client: QueryClient): Promise<void> {
  const active = activePasses.get(client)
  if (active) return active
  const pass = api.post<void>("/calendar/connections/resume", {}).finally(async () => {
    try {
      await Promise.all([
        client.invalidateQueries({ queryKey: calendarInboundKey }),
        client.invalidateQueries({ queryKey: ["calendar-connections"] }),
      ])
    } finally {
      activePasses.delete(client)
    }
  })
  activePasses.set(client, pass)
  return pass
}

export function useCalendarResume() {
  const client = useQueryClient()
  return useMutation({
    mutationKey: [...calendarInboundKey, "resume"],
    mutationFn: () => reconcile(client),
  })
}

export function useResumeCalendarReconciliation() {
  const client = useQueryClient()
  useEffect(() => {
    const signal = () => {
      if (document.visibilityState === "visible") void reconcile(client).catch(() => {
        // Status queries expose reconciliation failures; resume has no separate UI
      })
    }
    window.addEventListener("focus", signal)
    document.addEventListener("visibilitychange", signal)
    return () => {
      window.removeEventListener("focus", signal)
      document.removeEventListener("visibilitychange", signal)
    }
  }, [client])
}
