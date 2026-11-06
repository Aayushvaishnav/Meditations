import type { CalendarConnection, CalendarLinkView } from "@/api/types"
import type { InboundOverlay } from "@/api/calendar-inbound-types"

export type CalendarLinkProgress = "detached" | "conflict" | "error" | "removing" | "removed" | "syncing" | "queued" | "acknowledged"

export function calendarLinkProgress(link: CalendarLinkView): CalendarLinkProgress {
  if (link.selection_state === "detached") return "detached"
  if (link.state === "conflict") return "conflict"
  if (link.state === "error") return "error"
  const acknowledged = link.desired_action === link.acknowledged_action
    && link.local_revision === link.acknowledged_revision
  if (link.desired_action === "delete") return acknowledged ? "removed" : "removing"
  if (acknowledged) return "acknowledged"
  return link.state === "syncing" ? "syncing" : "queued"
}

const linkLabels: Record<CalendarLinkProgress, string> = {
  detached: "Detached; further sync stopped",
  conflict: "Remote conflict; action needed",
  error: "Remote sync failed; retry needed",
  removing: "Remote removal queued",
  removed: "Remote removal complete",
  syncing: "Sending local changes",
  queued: "Local changes queued",
  acknowledged: "Remote change acknowledged",
}

export function calendarLinkLabel(link: CalendarLinkView): string {
  return linkLabels[calendarLinkProgress(link)]
}

export function calendarSelectionLabel(link: CalendarLinkView | undefined, connectionId: string): string {
  if (!link) return "Not published"
  if (link.connection_id !== connectionId) return "Linked to another calendar"
  const progress = calendarLinkProgress(link)
  return progress === "removed" || progress === "removing"
    ? `${linkLabels[progress]}; select to publish again`
    : linkLabels[progress]
}

export type CalendarMirrorProgress = "never-checked" | "checking" | "current" | "stale"

export function calendarMirrorProgress(
  connection: Pick<CalendarConnection, "enabled" | "state">,
  reconciliation: InboundOverlay["reconciliation"] | undefined,
  request: { fetching: boolean; failed: boolean },
): CalendarMirrorProgress {
  if (!connection.enabled || connection.state === "authentication_required" || request.failed || reconciliation?.state === "error") return "stale"
  if (request.fetching) return "checking"
  if (reconciliation?.state === "current") return "current"
  return "never-checked"
}

export const calendarMirrorLabels: Record<CalendarMirrorProgress, string> = {
  "never-checked": "Mirror not checked yet",
  checking: "Checking mirrored appointments",
  current: "Mirror current as of last confirmed check",
  stale: "Mirrored appointments may be stale",
}
