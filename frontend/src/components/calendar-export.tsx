import { useId, useState } from "react"
import { Download, LoaderCircle } from "lucide-react"
import type { Task, TimeBlock } from "@/api/types"
import { Button } from "@/components/ui/button"
import { useCalendarExport } from "@/hooks/api"
import { parseUTC } from "@/lib/date-values"
import { blockTimeLabel } from "@/lib/time-blocks"

export function CalendarExport({ blocks, taskById, unavailable }: {
  blocks: TimeBlock[]; taskById: Map<string, Task>; unavailable: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const panelId = useId()
  const exportCalendar = useCalendarExport()
  const selectedIds = blocks.filter(block => selected.has(block.id)).map(block => block.id)

  return (
    <div className="mb-4">
      <Button variant="outline" size="sm" className="min-h-11" aria-expanded={expanded} aria-controls={panelId}
        onClick={() => setExpanded(value => !value)}>
        <Download aria-hidden="true" /> Export work blocks
      </Button>
      {expanded && <section id={panelId} aria-label="Calendar export" className="mt-3 space-y-3 rounded-lg border p-4">
        <p className="max-w-prose text-sm text-muted-foreground">
          Choose work blocks overlapping the displayed range, using your current scope and search filters. Each selected block exports its full interval. Deadlines and external events stay separate.
        </p>
        <p className="max-w-prose text-sm text-muted-foreground">
          The .ics file contains task titles and block dates or times. It is a snapshot, instead of live sync. Recurring tasks export only their selected blocks, as individual events.
        </p>
        {blocks.length === 0 && <p className="text-sm text-muted-foreground">No work blocks match this range and these filters. Add blocks through the API or choose another range or filter.</p>}
        <fieldset disabled={unavailable || exportCalendar.isPending} className="min-w-0">
          <legend className="sr-only">Work blocks to export</legend>
          <div className="max-h-64 overflow-y-auto">
            {blocks.map(block => <label key={block.id} className="flex min-h-11 cursor-pointer items-start gap-3 rounded-md px-2 py-2 hover:bg-accent/50">
              <input type="checkbox" className="mt-1 size-4 shrink-0 accent-primary focus-visible:ring-2 focus-visible:ring-ring" checked={selected.has(block.id)}
                onChange={event => {
                  const checked = event.target.checked
                  setSelected(previous => {
                    const next = new Set(previous)
                    if (checked) next.add(block.id)
                    else next.delete(block.id)
                    return next
                  })
                }} />
              <span className="min-w-0 break-words text-sm">
                <span className="block font-medium">{taskById.get(block.task_id)?.title}</span>
                <span className="block text-xs text-muted-foreground">{block.kind === "all_day"
                  ? `${block.start_date} to ${block.end_date} (exclusive end) · All day`
                  : `${parseUTC(block.start_at)!.toLocaleDateString()} · ${blockTimeLabel(block)} · Saved zone: ${block.timezone}`}</span>
              </span>
            </label>)}
          </div>
        </fieldset>
        <div className="flex flex-wrap items-center gap-3">
          <Button className="min-h-11" disabled={unavailable || exportCalendar.isPending || selectedIds.length === 0}
            onClick={() => exportCalendar.mutate(selectedIds)}>
            {exportCalendar.isPending ? <LoaderCircle className="motion-safe:animate-spin" aria-hidden="true" /> : <Download aria-hidden="true" />}
            {exportCalendar.isPending ? "Preparing calendar…" : "Download .ics"}
          </Button>
          <span className="text-sm text-muted-foreground">{selectedIds.length} selected</span>
        </div>
        <div role="status" className="text-sm text-muted-foreground">
          {exportCalendar.isPending && "Preparing selected blocks. Keep this view open."}
          {exportCalendar.isSuccess && exportCalendar.data.kind === "download-started" && "Download started. Check your browser downloads for the .ics file."}
          {exportCalendar.isSuccess && exportCalendar.data.kind === "saved" && "Calendar saved to the selected file."}
          {exportCalendar.isSuccess && exportCalendar.data.kind === "cancelled" && "Export cancelled. No file was created."}
        </div>
        {exportCalendar.isError && <p role="alert" className="text-sm text-destructive">{exportCalendar.error.message} Check the blocks and try downloading again.</p>}
        <p className="text-xs text-muted-foreground">Finish saving edits before exporting. Import and update behavior varies by calendar app; repeated imports may create duplicates.</p>
      </section>}
    </div>
  )
}
