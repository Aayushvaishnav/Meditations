import { useId, useState } from "react"
import { FileUp, LoaderCircle } from "lucide-react"
import type { CalendarImportTarget, ImportedCalendarEvent } from "@/api/calendar-import-types"
import {
  useCalendarImportPending,
  useImportedCalendars,
  useImportedCalendarEvents,
  useImportCalendar,
  useRemoveImportedCalendar,
} from "@/hooks/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

function EventInventory({ events }: { events: ImportedCalendarEvent[] }) {
  return <details className="min-w-0">
    <summary className="cursor-pointer rounded-sm py-2 text-sm font-medium focus-visible:outline-2 focus-visible:outline-ring">
      Stored appointments and series ({events.length})
    </summary>
    <ul className="mt-2 divide-y divide-border">
      {events.map(event => <li key={event.id} className="min-w-0 space-y-1 py-3 text-sm break-words">
        <p className="font-medium">{event.summary || "Untitled appointment"}</p>
        <p className="text-muted-foreground">
          {event.recurrence_kind !== "master" ? "Occurrence exception" : event.has_recurrence ? "Series master" : "Single appointment"}
          {event.status === "CANCELLED" && "; cancelled"}
        </p>
        {event.start_value && <p className="text-muted-foreground">Source start ({event.start_kind}): {event.start_value}{event.time_zone ? ` (${event.time_zone})` : ""}</p>}
        {event.end_value && <p className="text-muted-foreground">Source end: {event.end_value}</p>}
        {event.recurrence_kind !== "master" && <p className="text-muted-foreground">Original occurrence ({event.recurrence_kind}): {event.recurrence_id}{event.recurrence_time_zone ? ` (${event.recurrence_time_zone})` : ""}</p>}
        <p className="text-xs text-muted-foreground">UID: {event.uid}</p>
      </li>)}
    </ul>
    {events.length === 0 && <p className="text-sm text-muted-foreground">This imported calendar has no stored appointments.</p>}
  </details>
}

export function CalendarImportSettings() {
  const destinationId = useId()
  const sources = useImportedCalendars()
  const [target, setTarget] = useState<CalendarImportTarget>({ kind: "new", name: "" })
  const [selection, setSelection] = useState<{ kind: "none" } | { kind: "file"; file: File }>({ kind: "none" })
  const [fileVersion, setFileVersion] = useState(0)
  const [confirmRemoval, setConfirmRemoval] = useState(false)
  const [notice, setNotice] = useState("")
  const events = useImportedCalendarEvents(target)
  const upload = useImportCalendar()
  const remove = useRemoveImportedCalendar()
  const busy = useCalendarImportPending()
  const available = !sources.isPending && !sources.isError
  const selectedExists = target.kind === "new" || sources.data?.some(source => source.id === target.source_id)

  function clearFeedback() {
    upload.reset()
    remove.reset()
    setNotice("")
    setConfirmRemoval(false)
  }

  return <section className="glass min-w-0 rounded-2xl p-5" aria-labelledby="calendar-import-heading" aria-busy={busy}>
    <h2 id="calendar-import-heading" className="flex items-center gap-2 text-sm font-semibold">
      <FileUp className="size-4 text-primary" aria-hidden="true" />Import calendar files
    </h2>
    <div className="mt-4 space-y-4">
      <p className="text-sm text-muted-foreground">Keep a read-only copy of external appointments from a UTF-8 .ics file. Imports stay separate from tasks, work blocks and scores.</p>
      <p className="text-sm text-muted-foreground">Recurring series, exceptions and original time values are preserved for inspection here. Calendar occurrence display and reminders are unavailable.</p>
      {sources.isPending && <p role="status" className="text-sm">Loading imported calendars…</p>}
      {sources.isError && <div role="alert" className="space-y-2 text-sm text-destructive">
        <p>Could not load imported calendars. Retry before importing a file.</p>
        <Button variant="outline" className="min-h-11" onClick={() => void sources.refetch()}>Retry imported calendars</Button>
      </div>}
      <form onSubmit={event => {
        event.preventDefault()
        if (busy || !available || !selectedExists || selection.kind === "none" || (target.kind === "new" && !target.name.trim())) return
        setNotice("")
        upload.mutate({ target: { ...target }, file: selection.file }, { onSuccess: result => {
          setTarget({ kind: "existing", source_id: result.source_id })
          setSelection({ kind: "none" })
          setFileVersion(version => version + 1)
          setNotice(`Import saved: ${result.created} added, ${result.updated} updated, ${result.unchanged} unchanged.`)
        } })
      }}>
        <fieldset disabled={busy || !available} className="min-w-0 space-y-3">
          <legend className="sr-only">Import an iCalendar file</legend>
          <div className="text-sm">
            <label htmlFor={destinationId}>Import destination</label>
            <select id={destinationId} className="mt-1 min-h-11 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm" value={target.kind === "new" ? "new" : target.source_id} onChange={event => {
              clearFeedback()
              setTarget(event.target.value === "new" ? { kind: "new", name: "" } : { kind: "existing", source_id: event.target.value })
            }}>
              <option value="new">New imported calendar</option>
              {sources.data?.map(source => <option key={source.id} value={source.id}>{source.name} ({source.event_count})</option>)}
            </select>
          </div>
          {target.kind === "new" && <label className="block text-sm">Calendar name
            <Input className="mt-1 min-h-11" value={target.name} required onChange={event => { clearFeedback(); setTarget({ kind: "new", name: event.target.value }) }} placeholder="Personal appointments" />
          </label>}
          <label className="block text-sm">iCalendar file
            <input key={fileVersion} className="mt-1 block min-h-11 w-full min-w-0 rounded-md border border-input p-2 text-sm file:mr-3 file:rounded file:border-0 file:bg-secondary file:px-2 file:py-1 file:text-secondary-foreground focus-visible:outline-2 focus-visible:outline-ring" type="file" accept=".ics,text/calendar" required onChange={event => { clearFeedback(); setSelection(event.target.files?.[0] ? { kind: "file", file: event.target.files[0] } : { kind: "none" }) }} />
          </label>
          <p className="text-xs text-muted-foreground">Reimport into the same destination to update matching UIDs and original occurrence identities. Missing appointments stay stored; a new destination keeps an independent copy. The latest import wins, including older files.</p>
          <Button className="min-h-11" variant="outline" type="submit" disabled={busy || selection.kind === "none" || !selectedExists || (target.kind === "new" && !target.name.trim())}>
            {busy ? <LoaderCircle aria-hidden="true" className="size-4 motion-safe:animate-spin" /> : <FileUp aria-hidden="true" />}
            {upload.isPending ? "Importing calendar…" : "Import .ics file"}
          </Button>
        </fieldset>
      </form>
      {busy && <p role="status" className="text-sm text-muted-foreground">Saving calendar changes. You can leave this view; the operation will continue.</p>}
      {notice && <p role="status" className="text-sm text-muted-foreground">{notice}</p>}
      {(upload.isError || remove.isError) && <p role="alert" className="text-sm break-words text-destructive">{upload.error?.message || remove.error?.message} Check the file or destination and retry.</p>}
      {target.kind === "existing" && <div className="min-w-0 space-y-3 border-t border-border pt-3">
        {events.isPending && <p role="status" className="text-sm">Loading stored appointments…</p>}
        {events.isError && <div role="alert" className="text-sm text-destructive">Could not load appointments. <Button className="min-h-11" variant="outline" onClick={() => void events.refetch()}>Retry appointments</Button></div>}
        {events.data && <EventInventory events={events.data} />}
        {confirmRemoval ? <div className="space-y-2">
          <p className="text-sm">Remove this imported calendar and all its stored appointments? Original files, remote calendars and local tasks stay unchanged.</p>
          <div className="flex flex-wrap gap-2">
            <Button className="min-h-11" variant="destructive" disabled={busy} onClick={() => {
              if (busy) return
              remove.mutate(target.source_id, { onSuccess: () => {
                setTarget({ kind: "new", name: "" })
                setConfirmRemoval(false)
                setNotice("Imported calendar removed. Original files and local tasks are unchanged.")
              } })
            }}>Confirm removal</Button>
            <Button className="min-h-11" variant="outline" disabled={busy} onClick={() => setConfirmRemoval(false)}>Keep calendar</Button>
          </div>
        </div> : <Button className="min-h-11" variant="outline" disabled={busy} onClick={() => { clearFeedback(); setConfirmRemoval(true) }}>Remove imported calendar</Button>}
      </div>}
      <p className="text-xs text-muted-foreground">Files with unsupported components or invalid data are rejected as a whole. Imported content can be private; database backups include it, while portable ZIP exports exclude it.</p>
    </div>
  </section>
}
