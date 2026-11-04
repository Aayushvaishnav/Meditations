import { useState } from "react"
import type { Task } from "@/api/types"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { deadlineDayKey } from "@/lib/task-deadlines"

export function DeadlineMove({ task, pending, onMove }: { task: Task; pending: boolean; onMove: (target: Date) => void }) {
  const [target, setTarget] = useState(() => deadlineDayKey(task.deadline) ?? "")
  return <form className="flex min-w-0 flex-wrap items-end gap-2" onSubmit={event => {
    event.preventDefault()
    if (!event.currentTarget.checkValidity()) return
    const date = new Date(`${target}T00:00:00`)
    if (Number.isFinite(date.getTime())) onMove(date)
  }}>
    <label className="min-w-0 flex-1 text-xs text-muted-foreground">Move deadline for {task.title}
      <Input type="date" min="0001-01-01" max="9999-12-31" aria-label={`Move deadline for ${task.title}`} value={target} required disabled={pending} onChange={event => setTarget(event.target.value)} className="mt-1 w-full min-w-0" />
    </label>
    <Button type="submit" variant="outline" size="sm" disabled={pending || !target}>Move deadline</Button>
  </form>
}
