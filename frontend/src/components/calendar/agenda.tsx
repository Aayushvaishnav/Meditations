import { useDroppable } from "@dnd-kit/core"
import type { CalendarDay, CalendarItem } from "@/lib/calendar-projection"
import { localDayParam } from "@/lib/task-deadlines"
import { Button } from "@/components/ui/button"
import { TaskChip } from "./day-grid"
import { TimeBlockDetails } from "../calendar-time-blocks"
import { ImportedEventDetails } from "../calendar-imported-overlay"
import { LiveEventDetails } from "../calendar-live-overlay"
import type { TimeBlock } from "@/api/types"
import { cn } from "cn"

function AgendaItem({ item, onMove, pending, onOpen }: { item: CalendarItem; onMove: (block: TimeBlock, target: string) => void; pending: boolean; onOpen: () => void }) {
  return <div className="min-w-0 space-y-1 py-2">
    <p className="text-xs font-medium text-muted-foreground">{item.kind === "deadline" ? "Task deadline" : item.kind === "block" ? "Work block" : item.kind === "imported" ? "Imported event · read-only" : "Live event · read-only"}</p>
    {item.kind === "deadline" ? <><TaskChip task={item.task} /><Button variant="ghost" size="sm" onClick={onOpen}>Deadline actions</Button></> : item.kind === "block" ? <TimeBlockDetails key={`${item.block.id}:${item.block.updated_at}`} block={item.block} task={item.task} onMove={onMove} pending={pending} /> : item.kind === "imported" ? <ImportedEventDetails event={item.event} /> : <LiveEventDetails event={item.event} />}
  </div>
}

function AgendaDay({ day, items, onOpen, onMove, pending }: CalendarDay & { onOpen: (day: Date) => void; onMove: (block: TimeBlock, target: string) => void; pending: boolean }) {
  const { setNodeRef, isOver } = useDroppable({ id: `day-${localDayParam(day)}`, data: { type: "day", date: day } })
  return <section ref={setNodeRef} className={cn("min-w-0 border-b border-border py-4", isOver && "bg-primary/10")} aria-label={localDayParam(day)}>
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">{day.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</h3><Button variant="ghost" size="sm" onClick={() => onOpen(day)}>Add task on {localDayParam(day)}</Button></div>
    {items.length === 0 && <p className="py-2 text-sm text-muted-foreground">No calendar items.</p>}
    {[true, false].map(allDay => {
      const group = items.filter(item => item.allDay === allDay)
      return group.length > 0 && <div key={String(allDay)} className="mt-3"><h4 className="text-xs font-semibold text-muted-foreground">{allDay ? "All day" : "Timed"}</h4>{group.map(item => <AgendaItem key={item.id} item={item} onMove={onMove} pending={pending} onOpen={() => onOpen(day)} />)}</div>
    })}
  </section>
}

export function CalendarAgenda({ days, ...props }: { days: CalendarDay[]; onOpen: (day: Date) => void; onMove: (block: TimeBlock, target: string) => void; pending: boolean }) {
  return <div>{days.every(day => day.items.length === 0) && <p role="status" className="py-4 text-sm text-muted-foreground">No calendar items in this 14-day range.</p>}{days.map(day => <AgendaDay key={localDayParam(day.day)} {...day} {...props} />)}</div>
}
