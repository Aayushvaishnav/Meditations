import { useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import type { Task, TaskList, TaskStatus } from "@/api/types"
import { useUpdateTask } from "@/hooks/api"
import { BulkSelectionContext as Context, type BulkContext } from "@/hooks/bulk-selection"
import { Button } from "@/components/ui/button"
import { bulkTaskPatch, describeBulkAction, selectableTasks, type BulkTaskAction } from "@/lib/bulk-tasks"

type Failure = { id: string; title: string; message: string }
type Confirmation = { action: BulkTaskAction; ids: string[]; recurring: boolean }

export function BulkTasksProvider({ tasks, eligible, lists, children }: {
  tasks: Task[]; eligible: Task[]; lists: TaskList[]; children: ReactNode
}) {
  const [active, setActive] = useState(false)
  const [selected, setSelected] = useState(new Set<string>())
  const [pending, setPending] = useState(false)
  useEffect(() => {
    if (!active) return
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented && !pending) {
        setActive(false)
        setSelected(new Set())
      }
    }
    document.addEventListener("keydown", escape)
    return () => document.removeEventListener("keydown", escape)
  }, [active, pending])
  return <Context.Provider value={{ tasks, eligible, lists, active, setActive, selected, setSelected, pending, setPending }}>{children}</Context.Provider>
}

export function BulkTaskCheckbox({ task }: { task: Task }) {
  const context = useContext(Context)
  if (!context?.active || task.id.startsWith("temp-") || !context.eligible.some(item => item.id === task.id)) return null
  return <input type="checkbox" aria-label={`Select "${task.title}"`} checked={context.selected.has(task.id)} disabled={context.pending}
    className="size-4 shrink-0 accent-primary focus-visible:outline-2 focus-visible:outline-ring"
    onPointerDown={event => event.stopPropagation()} onMouseDown={event => event.stopPropagation()}
    onClick={event => event.stopPropagation()} onKeyDown={event => { if (event.key === " " || event.key === "Enter") event.stopPropagation() }}
    onChange={() => context.setSelected(previous => {
      const next = new Set(previous)
      if (next.has(task.id)) next.delete(task.id)
      else next.add(task.id)
      return next
    })} />
}

export function BulkTaskToolbar() {
  const context = useContext(Context)
  const trigger = useRef<HTMLButtonElement>(null)
  const wasActive = useRef(false)
  useLayoutEffect(() => {
    if (!context?.active && wasActive.current) trigger.current?.focus()
    wasActive.current = context?.active ?? false
  }, [context?.active])
  if (!context) return null
  if (!context.active) return <div className="px-3 sm:px-6 mb-4"><Button ref={trigger} variant="outline" size="sm" onClick={() => context.setActive(true)}>Select tasks</Button></div>
  return <ActiveToolbar context={context} />
}

const controlClass = "h-8 max-w-full rounded-lg border border-input bg-background px-2 text-sm text-foreground focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-50"

function ActiveToolbar({ context }: { context: BulkContext }) {
  const update = useUpdateTask()
  const queryClient = useQueryClient()
  const latest = useRef(context)
  useLayoutEffect(() => { latest.current = context }, [context])
  const running = useRef(false)
  const mounted = useRef(false)
  useLayoutEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      if (running.current) toast.info("Bulk changes stopped after navigation. Updates already sent may still finish.")
    }
  }, [])
  const [actionKind, setActionKind] = useState<BulkTaskAction["kind"]>("status")
  const [status, setStatus] = useState<TaskStatus>("todo")
  const [listId, setListId] = useState("no-list")
  const [tag, setTag] = useState("")
  const [confirmation, setConfirmation] = useState<Confirmation | undefined>()
  const [failures, setFailures] = useState<Failure[]>([])
  const [lastAction, setLastAction] = useState<BulkTaskAction | undefined>()
  const [successCount, setSuccessCount] = useState(0)
  const eligible = selectableTasks(context.eligible).filter(task => context.tasks.some(current => current.id === task.id))
  const eligibleIds = new Set(eligible.map(task => task.id))
  const selectedVisible = eligible.filter(task => context.selected.has(task.id))
  useEffect(() => {
    if (context.pending) return
    context.setSelected(previous => {
      const next = new Set([...previous].filter(id => eligibleIds.has(id)))
      return next.size === previous.size ? previous : next
    })
  })
  const confirmationValid = !confirmation || (
    confirmation.ids.length > 0 &&
    confirmation.ids.every(id => eligibleIds.has(id) && context.selected.has(id)) &&
    confirmation.ids.length === context.selected.size &&
    (confirmation.action.kind !== "list" || confirmation.action.listId === null || context.lists.some(list => confirmation.action.kind === "list" && list.id === confirmation.action.listId))
  )
  if (confirmation && !confirmationValid) setConfirmation(undefined)
  function prepare(action: BulkTaskAction, ids: string[]) {
    const targets = eligible.filter(task => ids.includes(task.id))
    context.setSelected(new Set(targets.map(task => task.id)))
    setConfirmation({ action: { ...action }, ids: targets.map(task => task.id), recurring: action.kind === "status" && action.status === "completed" && targets.some(task => Boolean(task.recurrence_rule)) })
  }
  async function execute(batch: Confirmation) {
    if (running.current || !confirmationValid) return
    running.current = true
    context.setPending(true)
    setConfirmation(undefined)
    setLastAction(batch.action)
    setFailures([])
    setSuccessCount(0)
    const errors: Failure[] = []
    let succeeded = 0
    try {
      for (const id of batch.ids) {
        if (!mounted.current) return
        const currentContext = latest.current
        const cache = queryClient.getQueryData<Task[]>(["tasks"]) ?? currentContext.tasks
        const task = cache.find(item => item.id === id)
        const title = task?.title ?? currentContext.tasks.find(item => item.id === id)?.title ?? id
        if (!task || !currentContext.eligible.some(item => item.id === id)) {
          errors.push({ id, title, message: "No longer available in this view; not updated." })
          continue
        }
        try {
          await update.mutateAsync({ id, patch: bulkTaskPatch(task, batch.action) })
          succeeded++
          if (mounted.current) context.setSelected(previous => { const next = new Set(previous); next.delete(id); return next })
        } catch (error) {
          errors.push({ id, title, message: error instanceof Error ? error.message : "Update failed" })
        }
      }
      if (mounted.current) {
        setSuccessCount(succeeded)
        setFailures(errors)
      }
    } finally {
      running.current = false
      if (mounted.current) context.setPending(false)
    }
  }
  function proposedAction(): BulkTaskAction {
    if (actionKind === "status") return { kind: "status", status }
    if (actionKind === "list") return { kind: "list", listId: listId === "no-list" ? null : listId, label: context.lists.find(list => list.id === listId)?.name ?? "No list" }
    return { kind: actionKind, tag: tag.trim() }
  }
  return <div className="px-3 sm:px-6 mb-4"><section aria-label="Bulk task actions" className="space-y-3 rounded-lg border border-border bg-muted/30 p-3">
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm tabular-nums" role="status">{context.selected.size} selected</span>
      <Button size="sm" variant="outline" disabled={context.pending} onClick={() => { setConfirmation(undefined); context.setSelected(new Set(eligibleIds)) }}>Select all visible</Button>
      <Button size="sm" variant="ghost" disabled={context.pending} onClick={() => { setConfirmation(undefined); context.setSelected(new Set()) }}>Clear selection</Button>
      <Button size="sm" variant="ghost" disabled={context.pending} onClick={() => { context.setSelected(new Set()); context.setActive(false) }}>Done selecting</Button>
    </div>
    <fieldset disabled={context.pending || Boolean(confirmation)} className="flex min-w-0 flex-wrap items-center gap-2">
      <select aria-label="Bulk action" className={controlClass} value={actionKind} onChange={event => setActionKind(event.target.value as BulkTaskAction["kind"])}>
        <option value="status">Change status</option><option value="list">Assign list</option><option value="add-tag">Add tag</option><option value="remove-tag">Remove tag</option>
      </select>
      {actionKind === "status" && <select aria-label="New status" className={controlClass} value={status} onChange={event => setStatus(event.target.value as TaskStatus)}>
        <option value="todo">To do</option><option value="in_progress">In progress</option><option value="completed">Completed</option><option value="canceled">Canceled</option>
      </select>}
      {actionKind === "list" && <select aria-label="Destination list" className={controlClass} value={listId} onChange={event => setListId(event.target.value)}>
        <option value="no-list">No list</option>{context.lists.map(list => <option key={list.id} value={list.id}>{list.name}</option>)}
      </select>}
      {(actionKind === "add-tag" || actionKind === "remove-tag") && <input aria-label="Tag" className={controlClass} value={tag} onChange={event => setTag(event.target.value)} />}
      <Button size="sm" disabled={!selectedVisible.length || ((actionKind === "add-tag" || actionKind === "remove-tag") && !tag.trim())} onClick={() => prepare(proposedAction(), selectedVisible.map(task => task.id))}>Review changes</Button>
    </fieldset>
    {confirmation && <div className="space-y-2 text-sm" aria-label="Confirm bulk changes">
      <p>{describeBulkAction(confirmation.action)} for {confirmation.ids.length} {confirmation.ids.length === 1 ? "task" : "tasks"}?</p>
      {confirmation.recurring && <p className="text-muted-foreground">Completing recurring tasks creates their next occurrences. This cannot be undone here.</p>}
      <div className="flex flex-wrap gap-2"><Button size="sm" disabled={context.pending || !confirmationValid} onClick={() => void execute(confirmation)}>Confirm changes</Button><Button size="sm" variant="outline" disabled={context.pending} onClick={() => setConfirmation(undefined)}>Cancel</Button></div>
    </div>}
    {context.pending && <p role="status" className="text-sm">Updating tasks…</p>}
    {!context.pending && successCount > 0 && <p role="status" className="text-sm">Updated {successCount} {successCount === 1 ? "task" : "tasks"}.</p>}
    {failures.length > 0 && <div className="space-y-2 text-sm" role="alert">
      <p>{failures.length} {failures.length === 1 ? "task was" : "tasks were"} not updated.</p>
      <ul className="space-y-1 break-words">{failures.map(failure => <li key={failure.id}><strong>{failure.title}</strong>: {failure.message}</li>)}</ul>
      <Button size="sm" variant="outline" disabled={context.pending || !lastAction || !failures.some(failure => eligibleIds.has(failure.id))} onClick={() => { if (lastAction) prepare(lastAction, failures.map(failure => failure.id)) }}>Retry failed only</Button>
    </div>}
  </section></div>
}
