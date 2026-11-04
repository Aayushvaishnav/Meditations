import { useId, useMemo, useState } from "react"
import type { Task, TimeBlock, TaskDeadline, TimeBlockInput } from "@/api/types"
import type { CalendarItem } from "@/lib/calendar-projection"
import { localDateTimeValue, localTimeCandidates, resolveLocalTime, type FoldChoice } from "@/lib/calendar-time-edit"
import { parseUTC } from "@/lib/date-values"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"

type TimeEditItem = CalendarItem | { kind: "deadline"; task: Task } | { kind: "block"; block: TimeBlock }
type Props = { item: TimeEditItem; pending: boolean; onDeadline: (deadline: TaskDeadline) => void; onBlock: (input: TimeBlockInput) => void }

export function CalendarTimeEdit(props: Props) {
  const { item } = props
  if ("allDay" in item && item.allDay) return null
  if (item.kind === "deadline" && item.task.deadline.kind === "timed") {
    return <TimeEditForm key={`${item.task.id}:${item.task.deadline.at}`} {...props} start={item.task.deadline.at} />
  }
  if (item.kind === "block" && item.block.kind === "timed") {
    return <TimeEditForm key={`${item.block.id}:${item.block.start_at}:${item.block.end_at}`} {...props} start={item.block.start_at} end={item.block.end_at} />
  }
  return null
}

function TimeField({ label, original, pending, value, onChange, choice, onChoice }: {
  label: string; original: string; pending: boolean; value: string; onChange: (value: string) => void; choice: FoldChoice; onChoice: (choice: FoldChoice) => void
}) {
  const candidates = useMemo(() => localTimeCandidates(value), [value])
  const unchanged = candidates.some(date => date.getTime() === parseUTC(original)!.getTime())
  return <div className="w-full min-w-0 basis-full space-y-1">
    <label className="block text-xs text-muted-foreground">{label}
      <Input className="mt-1 w-full min-w-0" type="datetime-local" step="0.001" min="0001-01-01T00:00" max="9999-12-31T23:59:59.999" required disabled={pending} value={value} onChange={event => onChange(event.target.value)} />
    </label>
    {candidates.length > 1 && <label className="block text-xs text-muted-foreground">{label} occurrence
      <select className="mt-1 block w-full rounded-md border border-input bg-background p-2 text-foreground" disabled={pending} value={choice} onChange={event => onChoice(event.target.value as FoldChoice)}>
        <option value="unselected">{unchanged ? "Keep original occurrence" : "Choose an occurrence"}</option>
        <option value="earlier">Earlier occurrence</option>
        <option value="later">Later occurrence</option>
      </select>
    </label>}
  </div>
}

function TimeEditForm({ item, pending, onDeadline, onBlock, start, end }: Props & { start: string; end?: string }) {
  const [at, setAt] = useState(() => localDateTimeValue(parseUTC(start)!))
  const [until, setUntil] = useState(() => end === undefined ? "" : localDateTimeValue(parseUTC(end)!))
  const [startChoice, setStartChoice] = useState<FoldChoice>("unselected")
  const [endChoice, setEndChoice] = useState<FoldChoice>("unselected")
  const [error, setError] = useState<string>()
  const errorId = useId()
  return <form noValidate aria-describedby={error ? errorId : undefined} className="flex w-full min-w-0 flex-wrap items-end gap-2 py-2" onSubmit={event => {
    event.preventDefault()
    if (pending) return
    setError(undefined)
    try {
      const startDate = resolveLocalTime(at, start, startChoice)
      if (item.kind === "deadline") onDeadline({ kind: "timed", at: startDate.toISOString() })
      else if (item.kind === "block" && item.block.kind === "timed" && end !== undefined) {
        const endDate = resolveLocalTime(until, end, endChoice)
        if (endDate.getTime() <= startDate.getTime()) throw new Error("End must be after start.")
        onBlock({ kind: "timed", task_id: item.block.task_id, timezone: item.block.timezone, start_at: startDate.toISOString(), end_at: endDate.toISOString() })
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Choose valid times.")
    }
  }}>
    <TimeField label={end === undefined ? "Deadline at" : "Block start"} original={start} pending={pending} value={at} onChange={value => { setAt(value); setStartChoice("unselected") }} choice={startChoice} onChoice={setStartChoice} />
    {end !== undefined && <TimeField label="Block end" original={end} pending={pending} value={until} onChange={value => { setUntil(value); setEndChoice("unselected") }} choice={endChoice} onChoice={setEndChoice} />}
    <Button type="submit" variant="outline" size="sm" disabled={pending}>Save time</Button>
    {error && <p id={errorId} role="alert" className="w-full text-xs text-destructive">{error}</p>}
  </form>
}
