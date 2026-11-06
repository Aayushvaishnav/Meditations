import { useId, useMemo, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useCreateTimeBlock } from "@/hooks/time-blocks"
import { localDayParam } from "@/lib/task-deadlines"
import { localTimeCandidates, type FoldChoice } from "@/lib/calendar-time-edit"
import type { TimeBlockInput } from "@/api/types"

function LocalTimeField({ label, value, onChange, choice, onChoice, disabled }: {
  label: string; value: string; onChange: (value: string) => void
  choice: FoldChoice; onChoice: (choice: FoldChoice) => void; disabled: boolean
}) {
  const candidates = useMemo(() => localTimeCandidates(value), [value])
  return <div className="min-w-0 space-y-1">
    <label className="block text-sm">{label}
      <Input type="datetime-local" required disabled={disabled} value={value} onChange={event => { onChange(event.target.value); onChoice("unselected") }} />
    </label>
    {candidates.length > 1 && <label className="block text-sm">{label} occurrence
      <select className="mt-1 w-full rounded-md border border-input bg-background p-2" disabled={disabled} value={choice} onChange={event => onChoice(event.target.value as FoldChoice)}>
        <option value="unselected">Choose an occurrence</option>
        <option value="earlier">Earlier occurrence</option>
        <option value="later">Later occurrence</option>
      </select>
    </label>}
  </div>
}

function selectedTime(value: string, choice: FoldChoice): Date {
  const candidates = localTimeCandidates(value)
  if (!candidates.length) throw new Error("Choose a valid local time; this time may not exist because the clocks change.")
  if (candidates.length > 1 && choice === "unselected") throw new Error("This time occurs twice. Choose the earlier or later occurrence.")
  const result = choice === "later" ? candidates[candidates.length - 1] : candidates[0]
  if (result.getUTCFullYear() < 1 || result.getUTCFullYear() > 9999) throw new Error("Choose a time within years 0001–9999.")
  return result
}

export function ScheduleRecommendation({ taskId, disabled }: { taskId: string; disabled: boolean }) {
  const create = useCreateTimeBlock()
  const submitting = useRef(false)
  const [kind, setKind] = useState<"all_day" | "timed">("all_day")
  const [day, setDay] = useState(() => localDayParam(new Date()))
  const [start, setStart] = useState("")
  const [end, setEnd] = useState("")
  const [startChoice, setStartChoice] = useState<FoldChoice>("unselected")
  const [endChoice, setEndChoice] = useState<FoldChoice>("unselected")
  const [result, setResult] = useState<{ kind: "editing" } | { kind: "saved" } | { kind: "error"; message: string }>({ kind: "editing" })
  const errorId = useId()
  const pending = create.isPending
  if (result.kind === "saved") return <p role="status" className="text-sm text-muted-foreground">Work block saved. Your task deadline is unchanged.</p>
  return <form className="mt-2 max-w-lg space-y-3" aria-label="Schedule work block" aria-describedby={result.kind === "error" ? errorId : undefined} onSubmit={async event => {
    event.preventDefault()
    if (submitting.current || pending || disabled) return
    submitting.current = true
    try {
      let input: TimeBlockInput
      if (kind === "all_day") {
        const date = new Date(`${day}T00:00:00Z`)
        if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== day || day < "0001-01-01") throw new Error("Choose a valid calendar date.")
        date.setUTCDate(date.getUTCDate() + 1)
        if (date.getUTCFullYear() > 9999) throw new Error("The block would end outside the supported date range.")
        input = { kind, task_id: taskId, start_date: day, end_date: date.toISOString().slice(0, 10) }
      } else {
        const from = selectedTime(start, startChoice)
        const until = selectedTime(end, endChoice)
        if (until <= from) throw new Error("End must be after start.")
        input = { kind, task_id: taskId, start_at: from.toISOString(), end_at: until.toISOString(), timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }
      }
      await create.mutateAsync(input)
      setResult({ kind: "saved" })
    } catch (cause) {
      setResult({ kind: "error", message: cause instanceof Error ? cause.message : "Could not save the work block. Try again." })
    } finally {
      submitting.current = false
    }
  }}>
    <p className="text-xs text-muted-foreground">Create a local work block without changing the task deadline.</p>
    <fieldset disabled={pending || disabled} className="min-w-0 space-y-3">
      <legend className="sr-only">Work block details</legend>
      <label className="block text-sm">Block type
        <select className="mt-1 w-full rounded-md border border-input bg-background p-2" value={kind} onChange={event => setKind(event.target.value as typeof kind)}>
          <option value="all_day">All day</option><option value="timed">Timed</option>
        </select>
      </label>
      {kind === "all_day" ? <label className="block text-sm">Block date
        <Input type="date" required min="0001-01-01" max="9999-12-30" value={day} onChange={event => setDay(event.target.value)} />
      </label> : <>
        <LocalTimeField label="Block start" value={start} onChange={setStart} choice={startChoice} onChoice={setStartChoice} disabled={pending} />
        <LocalTimeField label="Block end" value={end} onChange={setEnd} choice={endChoice} onChoice={setEndChoice} disabled={pending} />
        <p className="text-xs text-muted-foreground">Times use {Intl.DateTimeFormat().resolvedOptions().timeZone}.</p>
      </>}
      <Button type="submit" size="sm">{pending ? "Saving…" : "Save work block"}</Button>
    </fieldset>
    {result.kind === "error" && <p id={errorId} role="alert" className="text-sm text-destructive">{result.message} Your draft is kept; you can retry.</p>}
  </form>
}
