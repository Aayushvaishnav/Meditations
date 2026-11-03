import { useState } from "react"
import { useDraggable } from "@dnd-kit/core"
import { CalendarDays, Clock } from "lucide-react"
import type { Task, TimeBlock } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { blockStartDay, blockTimeLabel } from "@/lib/time-blocks"
import { cn } from "cn"

export function TimeBlockChip({ block, task, onOpen, disabled, day }: { day: string; block: TimeBlock; task: Task; onOpen: () => void; disabled: boolean }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `block:${block.id}:${day}`, data: { type: "calendar-block", blockId: block.id, day }, disabled,
  })
  const Icon = block.kind === "all_day" ? CalendarDays : Clock
  return (
    <button ref={setNodeRef} {...attributes} {...listeners} onClick={onOpen} disabled={disabled}
      aria-label={`${task.title}, work block, ${blockTimeLabel(block)}`}
      className={cn("flex w-full touch-none items-start gap-1 rounded-md bg-primary/10 px-1.5 py-1 text-left text-[11px] hover:bg-primary/20 focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50", isDragging && "opacity-30")}>
      <Icon className="mt-0.5 size-3 shrink-0" aria-hidden="true" />
      <span className="min-w-0"><span className="block truncate">{task.title}</span><span className="block text-[10px]">{blockTimeLabel(block)}</span></span>
    </button>
  )
}

export function TimeBlockDetails({ block, task, onMove, pending }: {
  block: TimeBlock; task: Task; onMove: (block: TimeBlock, day: string) => void; pending: boolean
}) {
  const [target, setTarget] = useState(blockStartDay(block))
  return (
    <div className="space-y-2 rounded-md border p-2">
      <p className="text-sm font-medium">{task.title}</p>
      <p className="text-xs text-muted-foreground">Work block · {blockTimeLabel(block)}{block.kind === "timed" ? ` · Saved zone: ${block.timezone}` : ""}</p>
      {block.kind === "all_day" && <p className="text-xs text-muted-foreground">{block.start_date} to {block.end_date} (exclusive end)</p>}
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-0 flex-1 text-xs">Move block start to
          <Input aria-label={`New start date for ${task.title} block ${block.id}`} type="date" min="0001-01-01" max="9999-12-31" value={target} onChange={event => setTarget(event.target.value)} />
        </label>
        <Button size="sm" disabled={pending || !target || target === blockStartDay(block)} onClick={() => onMove(block, target)}>Move block</Button>
      </div>
    </div>
  )
}
