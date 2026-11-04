import { useRef, useState, useLayoutEffect } from "react"
import { DndContext, DragOverlay, PointerSensor, pointerWithin, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core"
import { GripVertical } from "lucide-react"
import { cn } from "cn"
import type { Task, TaskList } from "@/api/types"
import type { Scope } from "@/stores/ui"
import { useCreateTask, useUpdateTask } from "@/hooks/api"
import { MATRIX_ZONES, classificationForZone, matrixZoneOf, selectMatrixTasks, type MatrixZoneId } from "@/lib/eisenhower"
import { TaskItem } from "@/components/task-item"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

const SELECT_STYLE = "min-h-9 max-w-full rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50"
const ACCENTS = ["border-t-overdue", "border-t-primary", "border-t-chart-3", "border-t-muted-foreground", "border-t-border"]
type MoveState = "pending" | "failed"
type FocusRequest = { id: string; zone: MatrixZoneId }

function MatrixCard({ task, tasks, lists, state, move, focusedTask, consumeFocus }: {
  task: Task; tasks: Task[]; lists: TaskList[]; state?: MoveState
  move: (task: Task, patch: Pick<Task, "importance" | "urgency">, focus: boolean) => void
  focusedTask: FocusRequest | undefined
  consumeFocus: () => void
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: task.id, disabled: state === "pending" || task.id.startsWith("temp-") })
  const selectRef = useRef<HTMLSelectElement>(null)
  useLayoutEffect(() => {
    if (focusedTask?.id !== task.id || focusedTask.zone !== matrixZoneOf(task) || state === "pending") return
    const active = document.activeElement
    if (active === document.body || active === selectRef.current) selectRef.current?.focus()
    consumeFocus()
  }, [focusedTask, task, state, consumeFocus])
  const parent = tasks.find(candidate => candidate.id === task.parent_id)
  const zone = matrixZoneOf(task)
  return (
    <article ref={setNodeRef} aria-label={task.title} aria-busy={state === "pending"} className={cn("min-w-0 rounded-xl border border-border bg-background/60 p-2", isDragging && "opacity-40")}>
      <TaskItem task={task} subtasks={[]} lists={lists} showList actionsVisible showCompletedDeadline />
      {task.parent_id !== null && <p className="px-3 pb-2 text-xs text-muted-foreground break-words">Subtask of {parent?.title ?? "another task"}</p>}
      <div className="flex flex-wrap items-center gap-2 px-3 pb-1">
        <button {...attributes} {...listeners} aria-label={`Drag "${task.title}" to a quadrant`} aria-describedby="matrix-drag-help" className="flex size-9 touch-none items-center justify-center rounded-md text-muted-foreground hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring" disabled={state === "pending" || task.id.startsWith("temp-")}>
          <GripVertical className="size-4" />
        </button>
        <label className="min-w-0 flex-1 text-xs text-muted-foreground">
          Move to quadrant
          <select ref={selectRef} aria-label={`Move "${task.title}" to quadrant`} className={cn(SELECT_STYLE, "mt-1 block w-full text-foreground")} value={zone} disabled={state === "pending" || task.id.startsWith("temp-")} onChange={event => move(task, classificationForZone(event.target.value as MatrixZoneId), true)}>
            {MATRIX_ZONES.map(zone => <option key={zone.id} value={zone.id}>{zone.label}</option>)}
          </select>
        </label>
      </div>
      {zone === "unclassified" && (
        <details className="px-3 pt-2 text-xs">
          <summary className="cursor-pointer rounded-sm text-muted-foreground focus-visible:outline-2 focus-visible:outline-ring">Classification: {task.importance === "unassigned" ? "importance unassigned" : task.importance === "important" ? "important" : "not important"}, {task.urgency === "unassigned" ? "urgency unassigned" : task.urgency === "urgent" ? "urgent" : "not urgent"}</summary>
          <div className="mt-2 flex flex-wrap gap-2">
            <label className="min-w-0">Importance<select aria-label={`Importance for "${task.title}"`} className={cn(SELECT_STYLE, "mt-1 block w-full")} value={task.importance} disabled={state === "pending"} onChange={event => move(task, { importance: event.target.value as Task["importance"], urgency: task.urgency }, true)}>
              <option value="unassigned">Unassigned</option><option value="important">Important</option><option value="not_important">Not important</option>
            </select></label>
            <label className="min-w-0">Urgency<select aria-label={`Urgency for "${task.title}"`} className={cn(SELECT_STYLE, "mt-1 block w-full")} value={task.urgency} disabled={state === "pending"} onChange={event => move(task, { importance: task.importance, urgency: event.target.value as Task["urgency"] }, true)}>
              <option value="unassigned">Unassigned</option><option value="urgent">Urgent</option><option value="not_urgent">Not urgent</option>
            </select></label>
            <Button variant="ghost" size="sm" disabled={state === "pending"} onClick={() => move(task, classificationForZone("unclassified"), true)}>Reset classification</Button>
          </div>
        </details>
      )}
      {state === "pending" && <p role="status" className="px-3 pt-2 text-xs text-muted-foreground">Saving classification…</p>}
      {state === "failed" && <p role="alert" className="px-3 pt-2 text-xs text-destructive">Classification could not be saved. Choose a quadrant to try again.</p>}
    </article>
  )
}

function MatrixZone({ zone, index, tasks, scope, children }: { zone: typeof MATRIX_ZONES[number]; index: number; tasks: Task[]; scope: Scope; children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: zone.id })
  const [title, setTitle] = useState("")
  const create = useCreateTask()
  return (
    <section ref={setNodeRef} aria-label={zone.label} className={cn("min-w-0 rounded-xl border border-border border-t-2 bg-muted/20 p-3 sm:p-4", ACCENTS[index], isOver && "bg-primary/10 ring-2 ring-primary", zone.id === "unclassified" && "lg:col-span-2")}>
      <div className="mb-3 flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{zone.label}</h2><span className="text-xs tabular-nums text-muted-foreground" aria-label={`${tasks.length} tasks`}>{tasks.length}</span></div>
      <div className="space-y-2">{children}{tasks.length === 0 && <p className="py-5 text-sm text-muted-foreground">{zone.id === "unclassified" ? "All visible tasks are classified." : "No matching tasks in this quadrant."}</p>}</div>
      <form className="mt-3 flex min-w-0 flex-wrap gap-2" onSubmit={event => {
        event.preventDefault()
        if (!title.trim() || create.isPending) return
        const submittedTitle = title.trim()
        create.mutate({ title: submittedTitle, ...classificationForZone(zone.id), ...(scope.kind === "list" ? { list_id: scope.id } : {}) }, {
          onSuccess: () => setTitle(current => current.trim() === submittedTitle ? "" : current),
        })
      }}>
        <Input aria-label={`New task in ${zone.label}`} placeholder="Task title" value={title} onChange={event => setTitle(event.target.value)} className="min-w-0 flex-1 basis-40" />
        <Button type="submit" variant="outline" size="sm" disabled={!title.trim() || create.isPending}>{create.isPending ? "Adding…" : "Add task"}</Button>
      </form>
      {create.isError && <p role="alert" className="mt-2 text-xs text-destructive">Task could not be added. Your title is kept; try again.</p>}
    </section>
  )
}

export function EisenhowerMatrix({ tasks, lists, scope, search = "" }: { tasks: Task[]; lists: TaskList[]; scope: Scope; search?: string }) {
  const visible = selectMatrixTasks(tasks, scope, search)
  const update = useUpdateTask()
  const [states, setStates] = useState<Record<string, MoveState>>({})
  const [focusedTask, setFocusedTask] = useState<FocusRequest>()
  const [draggedTask, setDraggedTask] = useState<Task>()
  const inFlight = useRef(new Set<string>())
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))
  function move(task: Task, patch: Pick<Task, "importance" | "urgency">, focus: boolean) {
    if (inFlight.current.has(task.id) || task.id.startsWith("temp-") || (task.importance === patch.importance && task.urgency === patch.urgency)) return
    inFlight.current.add(task.id)
    setFocusedTask(focus ? { id: task.id, zone: matrixZoneOf(patch) } : undefined)
    setStates(previous => ({ ...previous, [task.id]: "pending" }))
    void update.mutateAsync({ id: task.id, patch }).then(
      () => setStates(previous => { const next = { ...previous }; delete next[task.id]; return next }),
      () => {
        setFocusedTask(current => current?.id === task.id ? { id: task.id, zone: matrixZoneOf(task) } : current)
        setStates(previous => ({ ...previous, [task.id]: "failed" }))
      },
    ).finally(() => { inFlight.current.delete(task.id) })
  }
  function onDragEnd({ active, over }: DragEndEvent) {
    setDraggedTask(undefined)
    const task = visible.find(task => task.id === active.id)
    const zone = MATRIX_ZONES.find(zone => zone.id === over?.id)
    if (task && zone) move(task, classificationForZone(zone.id), false)
  }
  return (
    <div className="mx-auto max-w-[100rem] px-3 pb-24 sm:px-6">
      <p className="mb-4 max-w-prose text-sm text-muted-foreground">Organize by importance and urgency. Moving a task preserves its priority and deadline.</p>
      {visible.length === 0 && <p role="status" className="mb-4 text-sm text-muted-foreground">No tasks match this scope{search ? " and filter" : ""}. New tasks appear here when they match the current scope and filter.</p>}
      <p id="matrix-drag-help" className="sr-only">Drag to a quadrant, or use the Move to quadrant selector.</p>
      <DndContext collisionDetection={pointerWithin} sensors={sensors} onDragStart={({ active }) => setDraggedTask(visible.find(task => task.id === active.id))} onDragCancel={() => setDraggedTask(undefined)} onDragEnd={onDragEnd}>
        <div className="grid min-w-0 grid-cols-1 items-start gap-4 lg:grid-cols-2">
          {MATRIX_ZONES.map((zone, index) => {
            const bucket = visible.filter(task => matrixZoneOf(task) === zone.id)
            return <MatrixZone key={zone.id} zone={zone} index={index} tasks={bucket} scope={scope}>
              {bucket.map(task => <MatrixCard key={task.id} task={task} tasks={tasks} lists={lists} state={states[task.id]} move={move} focusedTask={focusedTask} consumeFocus={() => setFocusedTask(undefined)} />)}
            </MatrixZone>
          })}
        </div>
        <DragOverlay>{draggedTask && <div className="max-w-sm rounded-xl border border-primary bg-background p-3 text-sm shadow-lg break-words">{draggedTask.title}</div>}</DragOverlay>
      </DndContext>
    </div>
  )
}
