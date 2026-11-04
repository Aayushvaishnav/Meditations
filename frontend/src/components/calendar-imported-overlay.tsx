import { useId, useState, type ReactNode } from "react"
import { CalendarDays } from "lucide-react"
import type { ImportedOverlayItem } from "@/api/calendar-overlay-types"
import { useImportedCalendars, useImportedCalendarOverlay, type OverlaySelection } from "@/hooks/api"
import { Button } from "./ui/button"
import { importedEventLabel } from "@/lib/calendar-overlay"

export function CalendarImportedOverlay({ children, inlineControls = true }: { inlineControls?: boolean; children: (items: ImportedOverlayItem[], controls: ReactNode, summary: string) => ReactNode }) {
  const id = useId()
  const sources = useImportedCalendars()
  const [selection, setSelection] = useState<OverlaySelection>({ kind: "none" })
  const selected = selection.kind === "source" ? sources.data?.find(source => source.id === selection.id) : undefined
  const effective: OverlaySelection = selected ? { kind: "source", id: selected.id } : { kind: "none" }
  const overlay = useImportedCalendarOverlay(effective)
  const items = selected && !sources.isError && !overlay.isError ? overlay.data?.items ?? [] : []
  const controls = <section aria-label="Imported calendar overlay" className="mb-4 space-y-2 border-b border-border pb-4">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={id} className="text-sm font-medium">Imported calendar</label>
        <select id={id} value={selected?.id ?? ""} onChange={event => setSelection(event.target.value ? { kind: "source", id: event.target.value } : { kind: "none" })}
          className="min-h-9 min-w-0 max-w-full rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-2 focus-visible:outline-ring">
          <option value="">Hidden</option>
          {(sources.data ?? []).map(source => <option key={source.id} value={source.id}>{source.name}</option>)}
        </select>
      </div>
      <p className="max-w-prose text-xs text-muted-foreground">Read-only appointments from imported files. Independent of task filters, deadlines, work blocks and scores. Manage files in Settings.</p>
      {sources.isPending && <p role="status" className="text-sm text-muted-foreground">Loading imported calendars…</p>}
      {sources.isError && <p role="alert" className="text-sm">Could not load imported calendars. <Button variant="outline" size="sm" onClick={() => sources.refetch()}>Retry calendars</Button></p>}
      {sources.isSuccess && sources.data.length === 0 && <p className="text-xs text-muted-foreground">Import an .ics file in Settings to add an overlay.</p>}
      {selected && overlay.isPending && <p role="status" className="text-sm text-muted-foreground">Loading imported appointments…</p>}
      {selected && overlay.isError && <p role="alert" className="text-sm">Could not load imported appointments. <Button variant="outline" size="sm" onClick={() => overlay.refetch()}>Retry appointments</Button></p>}
      {selected && overlay.isSuccess && <>
        <p className="text-xs text-muted-foreground">{items.length} standalone appointments available. Series remain in the source inventory without occurrence expansion. Floating times keep their source clock labels.</p>
        {overlay.data.unplaced.length > 0 && <details>
          <summary className="cursor-pointer rounded-sm py-1 text-xs focus-visible:outline-2 focus-visible:outline-ring">Outside the grid ({overlay.data.unplaced.length})</summary>
          <ul className="max-h-48 space-y-2 overflow-y-auto py-2 text-xs">
            {overlay.data.unplaced.map(item => <li key={item.id} className="break-words"><span className="font-medium">{item.summary || "Untitled appointment"}</span>: {item.reason.replaceAll("_", " ")}</li>)}
          </ul>
        </details>}
      </>}
    </section>
  const summary = [selected ? `Imported: ${selected.name}` : "Imported hidden", sources.isError || (selected && overlay.isError) ? "error; open sources to retry" : ""].filter(Boolean).join(" · ")
  return <>{inlineControls && controls}{children(items, controls, summary)}</>
}

export function ImportedEventChip({ event, onOpen }: { event: ImportedOverlayItem; onOpen: () => void }) {
  return <button type="button" onClick={onOpen} title={`${event.summary || "Untitled appointment"}: ${importedEventLabel(event)}`}
    className="flex w-full min-w-0 items-center gap-1 rounded border border-dashed border-border px-1.5 py-1 text-left text-[11px] hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring">
    <CalendarDays className="size-3 shrink-0" aria-hidden="true" />
    <span className="truncate">{event.summary || "Untitled appointment"}</span>
    <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">Imported</span>
  </button>
}

export function ImportedEventDetails({ event }: { event: ImportedOverlayItem }) {
  return <div className="space-y-1 rounded-md border border-dashed border-border p-2 text-sm break-words">
    <p className="font-medium">{event.summary || "Untitled appointment"}</p>
    <p className="text-xs text-muted-foreground">{importedEventLabel(event)}</p>
    <p className="text-xs text-muted-foreground">Imported appointment · Read-only{event.status ? ` · ${event.status.toLowerCase()}` : ""}</p>
  </div>
}
