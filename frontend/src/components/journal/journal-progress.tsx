import { useState } from "react"
import { Button } from "@/components/ui/button"
import { useJournalStatus, useReindexJournal } from "@/hooks/journal-status"
import { indexProgress } from "@/lib/progress-state"
import { parseUTC } from "@/lib/dates"

/** Search receipts describe persisted text, independently from editor save feedback. */
export function JournalProgress({ day, unsaved }: { day: string; unsaved: boolean }) {
  const [open, setOpen] = useState(false)
  const status = useJournalStatus(day, open)
  const reindex = useReindexJournal()
  const data = status.data
  const needsIndex = data?.keyword === "missing" || data?.semantic === "missing"
  return (
    <details className="mt-3 text-xs text-muted-foreground" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
      <summary className="w-fit cursor-pointer rounded-sm focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2">Save and search details</summary>
      {open && <div className="mt-2 space-y-2">
        <p>Journal entries stay on this device. AI review and calendar publication have separate progress.</p>
        {unsaved && <p>Search status describes the last persisted entry; editor changes are still waiting to save.</p>}
        {status.isFetching && <p role="status">Checking search indexes…</p>}
        {status.isError ? <div role="alert">
          <p>Could not check search status. This does not change your saved entry.</p>
          <Button variant="outline" size="xs" onClick={() => void status.refetch()}>Retry status check</Button>
        </div> : data && <>
          {data.updated_at && <p>Last local save: {parseUTC(data.updated_at)?.toLocaleString()}</p>}
          <ul className="space-y-1" aria-label="Search indexing status">
            {(["keyword", "semantic"] as const).map(kind => {
              const progress = indexProgress(kind, data[kind])
              return <li key={kind}><span className="font-medium text-foreground">{progress.label}.</span> {progress.detail}</li>
            })}
          </ul>
          {needsIndex && <Button variant="outline" size="xs" disabled={reindex.isPending} onClick={() => reindex.mutate(day)}>
            {reindex.isPending ? "Indexing saved text…" : "Retry indexing"}
          </Button>}
        </>}
        {reindex.isError && <p role="alert" className="text-destructive">Could not rebuild search. Your saved entry is unchanged; retry when the local backend is reachable.</p>}
      </div>}
    </details>
  )
}
