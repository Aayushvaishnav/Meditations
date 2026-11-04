import { useDraggable, useDroppable } from "@dnd-kit/core"
import { Plus } from "lucide-react"
import type { Task, TimeBlock } from "@/api/types"
import type { ImportedOverlayItem } from "@/api/calendar-overlay-types"
import type { InboundOverlayItem } from "@/api/calendar-inbound-types"
import { deadlineCalendarDate, deadlineCutoff, localDayParam } from "@/lib/task-deadlines"
import { useDeadlinePassed } from "@/hooks/use-deadline-passed"
import { TimeBlockChip } from "../calendar-time-blocks"
import { ImportedEventChip } from "../calendar-imported-overlay"
import { LiveEventChip } from "../calendar-live-overlay"
import { cn } from "cn"
import { sortTasks } from "@/lib/dates"
import type { CalendarDay } from "@/lib/calendar-projection"
import { PRIORITY_DOT } from "./priority"

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

export function TaskChip({ task }: { task: Task }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: task.id,
    data: { type: "calendar-task" },
  })
  const due = deadlineCalendarDate(task.deadline)
  const overdue = useDeadlinePassed(task.status === "completed" ? null : deadlineCutoff(task.deadline))
  return (
    <button
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={cn(
        "flex w-full touch-none items-center gap-1.5 rounded-md px-1.5 py-0.5 text-left text-[11px] leading-tight transition-colors hover:bg-accent/70",
        isDragging && "opacity-30",
        task.status === "completed" && "text-muted-foreground line-through opacity-60",
      )}
    >
      <span className={cn("size-1.5 shrink-0 rounded-full", PRIORITY_DOT[task.priority])} />
      <span className="truncate">{task.title}</span>
      <span className="shrink-0 text-[10px] text-muted-foreground">Due</span>
      {task.deadline.kind === "timed" && due && (
        <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
          {due.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}
        </span>
      )}
      {overdue && <span className="size-1.5 shrink-0 rounded-full bg-overdue" />}
    </button>
  )
}

export function DayCell({
  day,
  inMonth,
  tasks,
  onOpen,
  blocks,
  taskById,
  pending,
  imported,
  live,
  showMonth,
}: {
  day: Date
  showMonth: boolean
  inMonth: boolean
  tasks: Task[]
  imported: ImportedOverlayItem[]
  live: InboundOverlayItem[]
  blocks: TimeBlock[]
  taskById: Map<string, Task>
  pending: boolean
  onOpen: (day: Date) => void
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `day-${localDayParam(day)}`, data: { type: "day", date: day } })
  const isToday = localDayParam(day) === localDayParam(new Date())

  return (
    <div
      ref={setNodeRef}
      className={cn(
        "group flex min-h-24 min-w-0 flex-col gap-0.5 rounded-lg border p-1.5 transition-colors",
        inMonth ? "border-[var(--glass-border)] bg-[var(--glass-bg)]" : "border-transparent opacity-50",
        isOver && "border-primary/60 bg-primary/10",
      )}
    >
      <div className="flex items-center justify-between px-0.5">
        <span
          className={cn(
            "text-xs",
            isToday ? "flex size-5 items-center justify-center rounded-full bg-primary font-semibold text-primary-foreground" : inMonth ? "text-foreground" : "text-muted-foreground",
          )}
        >
          {day.getDate()}
        </span>
        {showMonth && <span className="truncate text-[10px] text-muted-foreground">{day.toLocaleDateString(undefined, { month: "short" })}</span>}
        <button
          onClick={() => onOpen(day)}
          aria-label={`Add task on ${localDayParam(day)}`}
          className="rounded p-0.5 text-muted-foreground transition-opacity hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Plus className="size-3" />
        </button>
      </div>
      {blocks.slice(0, 3).map(block => (
        <TimeBlockChip key={block.id} block={block} day={localDayParam(day)} task={taskById.get(block.task_id)!} onOpen={() => onOpen(day)} disabled={pending} />
      ))}
      {imported.slice(0, 2).map(event => <ImportedEventChip key={event.id} event={event} onOpen={() => onOpen(day)} />)}
      {live.slice(0, 2).map(event => <LiveEventChip key={event.id} event={event} onOpen={() => onOpen(day)} />)}
      {tasks.slice(0, 4).map((t) => (
        <TaskChip key={t.id} task={t} />
      ))}
      {(tasks.length > 4 || blocks.length > 3 || imported.length > 2 || live.length > 2) && (
        <button onClick={() => onOpen(day)} className="px-1 text-left text-[10px] text-muted-foreground hover:text-foreground">
          +{Math.max(0, tasks.length - 4) + Math.max(0, blocks.length - 3) + Math.max(0, imported.length - 2) + Math.max(0, live.length - 2)} more
        </button>
      )}
    </div>
  )
}

export function CalendarDayGrid({ days, anchor, taskById, pending, onOpen }: { days: CalendarDay[]; anchor?: Date; taskById: Map<string, Task>; pending: boolean; onOpen: (day: Date) => void }) {
  return <>
    <div className="grid grid-cols-7 gap-1 px-1 pb-1">{WEEKDAYS.map(day => <div key={day} className="px-1 text-[10px] font-semibold tracking-wide text-muted-foreground uppercase">{day}</div>)}</div>
    <div className="group/grid grid grid-cols-7 gap-1">{days.map(({ day, items }) => <DayCell key={localDayParam(day)} day={day} showMonth={!anchor} inMonth={!anchor || (day.getMonth() === anchor.getMonth() && day.getFullYear() === anchor.getFullYear())} tasks={items.flatMap(item => item.kind === "deadline" ? [item.task] : []).sort(sortTasks)} blocks={items.flatMap(item => item.kind === "block" ? [item.block] : [])} imported={items.flatMap(item => item.kind === "imported" ? [item.event] : [])} live={items.flatMap(item => item.kind === "live" ? [item.event] : [])} taskById={taskById} pending={pending} onOpen={onOpen} />)}</div>
  </>
}
