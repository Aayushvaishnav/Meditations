import { CalendarSources } from "./calendar-sources"
import { useMemo, useState } from "react"
import {
  DndContext,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { useCreateTask, useUpdateTask, useTimeBlocks, useReplaceTimeBlock } from "@/hooks/api"
import { deadlineDayKey, localDayParam, moveDeadline } from "@/lib/task-deadlines"
import { toast } from "sonner"
import { blockOnDay, blockStartDay, moveTimeBlock, shiftBlockStart } from "@/lib/time-blocks"
import { importedEventOnDay } from "@/lib/calendar-overlay"
import { CalendarImportedOverlay, ImportedEventDetails } from "./calendar-imported-overlay"
import { CalendarLiveOverlay, LiveEventDetails } from "./calendar-live-overlay"
import { CalendarExport } from "./calendar-export"
import { TimeBlockDetails } from "./calendar-time-blocks"
import type { Task, TimeBlock } from "@/api/types"
import type { Scope } from "@/stores/ui"
import { selectScopedTasks } from "@/lib/task-filter"
import { cn } from "cn"

import { PRIORITY_DOT } from "./calendar/priority"
import { CalendarYear } from "./calendar/year"
import { CalendarMultiWeek } from "./calendar/multi-week"
import { CalendarMonth } from "./calendar/month"
import { DeadlineMove } from "./calendar/deadline-move"
import { CalendarAgenda } from "./calendar/agenda"
import { CalendarTimeGrid } from "./calendar/time-grid"
import { CalendarTimeEdit } from "./calendar/time-edit"
import { CalendarToolbar } from "./calendar/toolbar"
import { calendarRange, navigateCalendar } from "@/lib/calendar-range"
import { projectCalendar, calendarDaySummary } from "@/lib/calendar-projection"
import { useUi } from "@/stores/ui"

export function CalendarView({ tasks: allTasks, scope, search }: { tasks: Task[]; scope: Scope; search: string }) {
  const tasks = useMemo(() => selectScopedTasks(allTasks, scope, search), [allTasks, scope, search])
  const updateTask = useUpdateTask()
  const createTask = useCreateTask()
  const blocksQuery = useTimeBlocks()
  const replaceBlock = useReplaceTimeBlock()
  const taskById = useMemo(() => new Map(tasks.map(task => [task.id, task])), [tasks])
  const blocks = (blocksQuery.data ?? []).filter(block => taskById.has(block.task_id))
  const [cursor, setCursor] = useState(() => new Date())
  const mode = useUi(state => state.calendarMode)
  const [dayCount, setDayCount] = useState(3)
  const [weekCount, setWeekCount] = useState(2)
  const setMode = useUi(state => state.setCalendarMode)
  const range = useMemo(() => calendarRange(cursor, mode, dayCount, weekCount), [cursor, mode, dayCount, weekCount])
  const [openDay, setOpenDay] = useState<Date | null>(null)
  const [newTitle, setNewTitle] = useState("")
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))

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


  return (
    <CalendarImportedOverlay inlineControls={false}>{(imported, importedControls, importedSummary) =>
    <CalendarLiveOverlay inlineControls={false}>{(live, _unplacedCount, liveControls, liveSummary) =>
    <div className="px-6 pb-8">
      <CalendarToolbar anchor={cursor} mode={mode} onMode={setMode} dayCount={dayCount} onDayCount={setDayCount} weekCount={weekCount} onWeekCount={setWeekCount} onNavigate={direction => setCursor(navigateCalendar(cursor, mode, direction, dayCount, weekCount))} onToday={() => setCursor(new Date())} />
      <CalendarSources summary={`${importedSummary} · ${liveSummary}`}>{importedControls}{liveControls}</CalendarSources>
      <p className="mb-3 text-xs text-muted-foreground">Due labels mark deadlines. Shaded work blocks are separate plans. Times use your local timezone; moving a block keeps its displayed start time and duration.</p>
      {blocksQuery.isPending && <p role="status" className="mb-2 text-sm text-muted-foreground">Loading work blocks…</p>}
      {blocksQuery.isError && <div role="alert" className="mb-2 text-sm">Could not load work blocks. <Button variant="outline" size="sm" onClick={() => blocksQuery.refetch()}>Retry</Button></div>}
      <CalendarExport key={JSON.stringify([localDayParam(range.start), localDayParam(range.end), scope.kind, scope.id, search])}
        blocks={blocks.filter(block => range.days.some(day => day >= range.start && day < range.end && blockOnDay(block, day)))}
        taskById={taskById} unavailable={blocksQuery.isPending || blocksQuery.isError || replaceBlock.isPending} />
      {replaceBlock.isPending && <p role="status" className="mb-2 text-sm text-muted-foreground">Moving work block…</p>}
      <p className="mb-3 text-xs text-muted-foreground">Export includes local work blocks overlapping this displayed range; external events are not exported.</p>
      {!tasks.some(task => range.days.some(day => day >= range.start && day < range.end && deadlineDayKey(task.deadline) === localDayParam(day))) && <p className="mb-3 text-sm text-muted-foreground">No matching task deadlines in this range. Your current task scope and search still apply; try All tasks or clear your search.</p>}
      <DndContext sensors={sensors} onDragEnd={onDragEnd}>
        {mode === "year" ? <CalendarYear days={projectCalendar(range.days, tasks, blocks, imported, live)} anchor={cursor} onOpen={day => { setCursor(day); setOpenDay(day) }} onMonth={day => { setCursor(day); setMode("month") }} /> : mode === "multi-week" ? <CalendarMultiWeek days={projectCalendar(range.days, tasks, blocks, imported, live)} taskById={taskById} pending={replaceBlock.isPending} onOpen={setOpenDay} /> : mode === "month" ? <CalendarMonth days={projectCalendar(range.days, tasks, blocks, imported, live)} anchor={cursor} taskById={taskById} pending={replaceBlock.isPending} onOpen={setOpenDay} /> : mode === "agenda" ? <CalendarAgenda days={projectCalendar(range.days, tasks, blocks, imported, live)} onOpen={setOpenDay} onMove={moveBlock} pending={replaceBlock.isPending} /> : <CalendarTimeGrid days={projectCalendar(range.days, tasks, blocks, imported, live)} onOpen={setOpenDay} />}
      </DndContext>

      <Dialog open={openDay !== null} onOpenChange={(o) => !o && setOpenDay(null)}>
        <DialogContent className="flex max-h-[calc(100dvh-2rem)] w-[28rem] max-w-[calc(100vw-2rem)] flex-col">
          <DialogHeader>
            <DialogTitle>
              {openDay?.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" })}
            </DialogTitle>
          </DialogHeader>
          {openDay && <p className="text-sm text-muted-foreground">{calendarDaySummary(projectCalendar([openDay], tasks, blocks, imported, live)[0])}</p>}
          <label className="text-sm">New task deadline
          <Input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addOnDay()}
            placeholder="Add a task due this day…"
            className="mt-2"
          />
          </label>
          <div className="mt-2 min-h-0 flex-1 space-y-2 overflow-y-auto overflow-x-hidden">
            {openDay && imported.filter(event => importedEventOnDay(event, openDay)).map(event => <ImportedEventDetails key={event.id} event={event} />)}
            {openDay && live.filter(event => importedEventOnDay(event, openDay)).map(event => <LiveEventDetails key={event.id} event={event} />)}
            {openDay && blocks.filter(block => blockOnDay(block, openDay)).map(block => (
              <div key={`${block.id}:${block.updated_at}`}>
                <TimeBlockDetails block={block} task={taskById.get(block.task_id)!} onMove={moveBlock} pending={replaceBlock.isPending} />
                {block.kind === "timed" && <CalendarTimeEdit item={{ kind: "block", block }} pending={replaceBlock.isPending} onDeadline={() => {}} onBlock={input => replaceBlock.mutate({ id: block.id, input })} />}
              </div>
            ))}
            {openDay &&
              (byDayLocal(tasks).get(localDayParam(openDay)) ?? []).map((t) => (
                <div key={t.id} className="flex min-w-0 flex-wrap items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-accent/50">
                  <span className={cn("size-1.5 rounded-full", PRIORITY_DOT[t.priority])} />
                  <span className={cn("truncate", t.status === "completed" && "text-muted-foreground line-through")}>{t.title}</span>
                  <DeadlineMove key={`${t.id}:${deadlineDayKey(t.deadline)}`} task={t} pending={updateTask.isPending} onMove={target => {
                    try { updateTask.mutate({ id: t.id, patch: { deadline: moveDeadline(t.deadline, target) } }) }
                    catch (error) { toast.error(error instanceof Error ? error.message : "Could not move deadline.") }
                  }} />
                  {t.deadline.kind === "timed" && <CalendarTimeEdit key={`time:${t.id}:${t.updated_at}`} item={{ kind: "deadline", task: t }} pending={updateTask.isPending} onDeadline={deadline => updateTask.mutate({ id: t.id, patch: { deadline } })} onBlock={() => {}} />}
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
    </div>
    }</CalendarLiveOverlay>
    }</CalendarImportedOverlay>
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
