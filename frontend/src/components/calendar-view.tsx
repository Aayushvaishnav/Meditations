import { useMemo, useState } from "react"
import {
  DndContext,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core"
import { ChevronLeft, ChevronRight, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { useCreateTask, useUpdateTask, useTimeBlocks, useReplaceTimeBlock } from "@/hooks/api"
import { sortTasks } from "@/lib/dates"
import { deadlineCalendarDate, deadlineCutoff, deadlineDayKey, localDayParam, moveDeadline } from "@/lib/task-deadlines"
import { toast } from "sonner"
import { blockOnDay, blockStartDay, moveTimeBlock, shiftBlockStart } from "@/lib/time-blocks"
import type { ImportedOverlayItem } from "@/api/calendar-overlay-types"
import type { InboundOverlayItem } from "@/api/calendar-inbound-types"
import { importedEventOnDay } from "@/lib/calendar-overlay"
import { CalendarImportedOverlay, ImportedEventChip, ImportedEventDetails } from "./calendar-imported-overlay"
import { CalendarLiveOverlay, LiveEventChip, LiveEventDetails } from "./calendar-live-overlay"
import { CalendarExport } from "./calendar-export"
import { TimeBlockChip, TimeBlockDetails } from "./calendar-time-blocks"
import type { Task, TimeBlock } from "@/api/types"
import type { Scope } from "@/stores/ui"
import { selectScopedTasks } from "@/lib/task-filter"
import { useDeadlinePassed } from "@/hooks/use-deadline-passed"
import { cn } from "cn"

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

const PRIORITY_DOT: Record<number, string> = {
  3: "bg-high",
  2: "bg-medium",
  1: "bg-low",
  0: "bg-muted-foreground/40",
}

function TaskChip({ task }: { task: Task }) {
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

function DayCell({
  day,
  inMonth,
  tasks,
  onOpen,
  blocks,
  taskById,
  pending,
  imported,
  live,
}: {
  day: Date
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

export function CalendarView({ tasks: allTasks, scope, search }: { tasks: Task[]; scope: Scope; search: string }) {
  const tasks = useMemo(() => selectScopedTasks(allTasks, scope, search), [allTasks, scope, search])
  const updateTask = useUpdateTask()
  const createTask = useCreateTask()
  const blocksQuery = useTimeBlocks()
  const replaceBlock = useReplaceTimeBlock()
  const taskById = useMemo(() => new Map(tasks.map(task => [task.id, task])), [tasks])
  const blocks = (blocksQuery.data ?? []).filter(block => taskById.has(block.task_id))
  const [cursor, setCursor] = useState(() => {
    const d = new Date()
    d.setDate(1)
    d.setHours(0, 0, 0, 0)
    return d
  })
  const [openDay, setOpenDay] = useState<Date | null>(null)
  const [newTitle, setNewTitle] = useState("")
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))

  const weeks = useMemo(() => {
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1)
    const gridStart = new Date(first)
    gridStart.setDate(first.getDate() - ((first.getDay() + 6) % 7)) // back to Monday
    const byDay = new Map<string, Task[]>()
    for (const t of tasks) {
      const key = deadlineDayKey(t.deadline)
      if (!key) continue
      const bucket = byDay.get(key) ?? []
      bucket.push(t)
      byDay.set(key, bucket)
    }
    for (const bucket of byDay.values()) {
      bucket.sort(sortTasks)
    }
    return Array.from({ length: 6 }, (_, w) =>
      Array.from({ length: 7 }, (_, d) => {
        const day = new Date(gridStart)
        day.setDate(gridStart.getDate() + w * 7 + d)
        return { day, inMonth: day.getMonth() === cursor.getMonth(), tasks: byDay.get(localDayParam(day)) ?? [] }
      }),
    )
  }, [cursor, tasks])

  function moveBlock(block: TimeBlock, target: string) {
    if (replaceBlock.isPending || target === blockStartDay(block)) return
    try {
      replaceBlock.mutate({ id: block.id, input: moveTimeBlock(block, target) })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not move the work block.")
    }
  }

  function onDragEnd(event: DragEndEvent) {
    const overData = event.over?.data.current as { type?: string; date?: Date } | undefined
    if (event.active.data?.current?.type === "calendar-block") {
      const block = blocks.find(value => value.id === event.active.data.current?.blockId)
      if (block && overData?.type === "day" && overData.date) {
        try {
          const source = event.active.data.current?.day as string | undefined
          moveBlock(block, shiftBlockStart(block, source ?? blockStartDay(block), localDayParam(overData.date)))
        } catch (error) {
          toast.error(error instanceof Error ? error.message : "Could not move the work block.")
        }
      }
      return
    }
    const task = tasks.find((t) => t.id === event.active.id)
    if (!overData || overData.type !== "day" || !overData.date || !task) return
    const sourceDay = deadlineDayKey(task.deadline)
    if (sourceDay === null) return
    const target = overData.date
    if (sourceDay === localDayParam(target)) return
    updateTask.mutate({ id: task.id, patch: { deadline: moveDeadline(task.deadline, target) } })
  }

  function addOnDay() {
    if (!openDay || !newTitle.trim()) return
    createTask.mutate({ title: newTitle.trim(), list_id: scope.kind === "list" ? scope.id : null, deadline: { kind: "date", date: localDayParam(openDay) } })
    setNewTitle("")
  }

  const monthLabel = cursor.toLocaleDateString(undefined, { month: "long", year: "numeric" })

  return (
    <div className="px-6 pb-8">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold">{monthLabel}</h2>
        <Button variant="ghost" size="icon-xs" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))} aria-label="Previous month">
          <ChevronLeft />
        </Button>
        <Button variant="ghost" size="icon-xs" onClick={() => setCursor(new Date(new Date().getFullYear(), new Date().getMonth(), 1))} aria-label="Today">
          <span className="text-xs">Today</span>
        </Button>
        <Button variant="ghost" size="icon-xs" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))} aria-label="Next month">
          <ChevronRight />
        </Button>
        <span className="ml-auto text-xs text-muted-foreground">Drag a deadline or work block to move it</span>
      </div>

      <p className="mb-3 text-xs text-muted-foreground">Due labels mark deadlines. Shaded work blocks are separate plans. Times use your local timezone; moving a block keeps its displayed start time and duration.</p>
      {blocksQuery.isPending && <p role="status" className="mb-2 text-sm text-muted-foreground">Loading work blocks…</p>}
      {blocksQuery.isError && <div role="alert" className="mb-2 text-sm">Could not load work blocks. <Button variant="outline" size="sm" onClick={() => blocksQuery.refetch()}>Retry</Button></div>}
      <CalendarImportedOverlay>{imported => <>
      <CalendarLiveOverlay>{(live) => <>
      <CalendarExport key={JSON.stringify([cursor.getFullYear(), cursor.getMonth(), scope.kind, scope.id, search])}
        blocks={blocks.filter(block => weeks.flat().some(({ day, inMonth }) => inMonth && blockOnDay(block, day)))}
        taskById={taskById} unavailable={blocksQuery.isPending || blocksQuery.isError || replaceBlock.isPending} />
      {replaceBlock.isPending && <p role="status" className="mb-2 text-sm text-muted-foreground">Moving work block…</p>}
      <DndContext sensors={sensors} onDragEnd={onDragEnd}>
        <div className="grid grid-cols-7 gap-1 px-1 pb-1">
          {WEEKDAYS.map((w) => (
            <div key={w} className="px-1 text-[10px] font-semibold tracking-wide text-muted-foreground uppercase">
              {w}
            </div>
          ))}
        </div>
        <div className="group/grid grid grid-cols-7 gap-1">
          {weeks.flat().map(({ day, inMonth, tasks: dayTasks }, i) => (
            <DayCell key={i} imported={imported.filter(event => importedEventOnDay(event, day))} live={live.filter(event => importedEventOnDay(event, day))} day={day} inMonth={inMonth} tasks={dayTasks} blocks={blocks.filter(block => blockOnDay(block, day))} taskById={taskById} pending={replaceBlock.isPending} onOpen={setOpenDay} />
          ))}
        </div>
      </DndContext>

      <Dialog open={openDay !== null} onOpenChange={(o) => !o && setOpenDay(null)}>
        <DialogContent className="w-[28rem] max-w-[calc(100vw-2rem)]">
          <DialogHeader>
            <DialogTitle>
              {openDay?.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}
            </DialogTitle>
          </DialogHeader>
          <label className="text-sm">New task deadline
          <Input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addOnDay()}
            placeholder="Add a task due this day…"
            className="mt-2"
          />
          </label>
          <div className="mt-2 max-h-80 space-y-2 overflow-y-auto">
            {openDay && imported.filter(event => importedEventOnDay(event, openDay)).map(event => <ImportedEventDetails key={event.id} event={event} />)}
            {openDay && live.filter(event => importedEventOnDay(event, openDay)).map(event => <LiveEventDetails key={event.id} event={event} />)}
            {openDay && blocks.filter(block => blockOnDay(block, openDay)).map(block => (
              <TimeBlockDetails key={`${block.id}:${block.updated_at}`} block={block} task={taskById.get(block.task_id)!} onMove={moveBlock} pending={replaceBlock.isPending} />
            ))}
            {openDay &&
              (byDayLocal(tasks).get(localDayParam(openDay)) ?? []).map((t) => (
                <div key={t.id} className="flex items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-accent/50">
                  <span className={cn("size-1.5 rounded-full", PRIORITY_DOT[t.priority])} />
                  <span className={cn("truncate", t.status === "completed" && "text-muted-foreground line-through")}>{t.title}</span>
                  <button
                    className="ml-auto text-xs text-muted-foreground hover:text-foreground"
                    onClick={() => updateTask.mutate({ id: t.id, patch: { deadline: { kind: "none" } } })}
                  >
                    clear deadline
                  </button>
                </div>
              ))}
            {openDay && (byDayLocal(tasks).get(localDayParam(openDay)) ?? []).length === 0 && (
              <p className="py-4 text-center text-sm text-muted-foreground">No task deadlines.</p>
            )}
          </div>
        </DialogContent>
      </Dialog>
      </>}</CalendarLiveOverlay>
      </>}</CalendarImportedOverlay>
    </div>
  )
}

function byDayLocal(tasks: Task[]): Map<string, Task[]> {
  const map = new Map<string, Task[]>()
  for (const t of tasks) {
    const key = deadlineDayKey(t.deadline)
    if (!key) continue
    const bucket = map.get(key) ?? []
    bucket.push(t)
    map.set(key, bucket)
  }
  return map
}
