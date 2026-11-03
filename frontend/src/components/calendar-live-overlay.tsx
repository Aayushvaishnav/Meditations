import { useId, useState, type ReactNode } from "react"
import { Cloud } from "lucide-react"
import type { InboundOverlayItem } from "@/api/calendar-inbound-types"
import { useCalendarConnections, useInboundOverlay } from "@/hooks/api"
import { Button } from "./ui/button"
import { importedEventLabel } from "@/lib/calendar-overlay"

export type LiveSelection = { kind: "none" } | { kind: "connection"; id: string }

export function CalendarLiveOverlay({ children }: { children: (items: InboundOverlayItem[], unplacedCount: number) => ReactNode }) {
  const id = useId()
  const connections = useCalendarConnections()
  const connected = (connections.data ?? []).filter(connection => connection.state === "connected")
  const [selection, setSelection] = useState<LiveSelection>({ kind: "none" })
  const selected = selection.kind === "connection" ? connected.find(connection => connection.id === selection.id) : undefined
  const overlay = useInboundOverlay(selected?.id ?? null)
  const items = selected && !connections.isError && !overlay.isError ? overlay.data?.items ?? [] : []
  const unplacedCount = selected ? overlay.data?.unplaced.length ?? 0 : 0
  return <>
    <section aria-label="Live calendar overlay" className="mb-4 space-y-2 border-b border-border pb-4">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={id} className="text-sm font-medium">Live calendar</label>
        <select id={id} value={selected?.id ?? ""} onChange={event => setSelection(event.target.value ? { kind: "connection", id: event.target.value } : { kind: "none" })}
          className="min-h-9 min-w-0 max-w-full rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-2 focus-visible:outline-ring">
          <option value="">Hidden</option>
          {connected.map(connection => <option key={connection.id} value={connection.id}>{connection.calendar_url}</option>)}
        </select>
      </div>
      <p className="max-w-prose text-xs text-muted-foreground">Read-only appointments mirrored from the connected CalDAV calendar while the app runs. They never affect tasks, deadlines, focus or scores.</p>
      {connections.isPending && <p role="status" className="text-sm text-muted-foreground">Loading calendar connections…</p>}
      {connections.isError && <p role="alert" className="text-sm">Could not load connections. <Button variant="outline" size="sm" onClick={() => connections.refetch()}>Retry connections</Button></p>}
      {connections.isSuccess && connected.length === 0 && <p className="text-xs text-muted-foreground inline-flex items-center gap-1"><Cloud className="size-3" aria-hidden="true" /> Connect a calendar in Settings to mirror its events here.</p>}
      {selected && overlay.isPending && <p role="status" className="text-sm text-muted-foreground">Loading mirrored appointments…</p>}
      {selected && overlay.isError && <p role="alert" className="text-sm">Could not load mirrored appointments. <Button variant="outline" size="sm" onClick={() => overlay.refetch()}>Retry appointments</Button></p>}
      {selected && overlay.isSuccess && <p className="text-xs text-muted-foreground">{items.length} mirrored appointments. Events outside the grid are listed separately.{unplacedCount > 0 ? ` ${unplacedCount} cannot be placed (series, cancelled or unparsable).` : ""}</p>}
    </section>
    {children(items, unplacedCount)}
  </>
}

export function LiveEventChip({ event, onOpen }: { event: InboundOverlayItem; onOpen: () => void }) {
  return <button type="button" onClick={onOpen} title={`${event.summary || "Untitled appointment"}: ${importedEventLabel(event)}`}
    className="flex w-full min-w-0 items-center gap-1 rounded border border-dashed border-border px-1.5 py-1 text-left text-[11px] hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring">
    <Cloud className="size-3 shrink-0" aria-hidden="true" />
    <span className="truncate">{event.summary || "Untitled appointment"}</span>
    <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">Mirrored</span>
  </button>
}

export function LiveEventDetails({ event }: { event: InboundOverlayItem }) {
  return <div className="space-y-1 rounded-md border border-dashed border-border p-2 text-sm break-words">
    <p className="font-medium">{event.summary || "Untitled appointment"}</p>
    <p className="text-xs text-muted-foreground">{importedEventLabel(event)}</p>
    <p className="text-xs text-muted-foreground">Mirrored from the connected calendar · Read-only{event.status ? ` · ${event.status.toLowerCase()}` : ""}</p>
  </div>
}
