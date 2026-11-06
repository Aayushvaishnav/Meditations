import { useState } from "react"
import { CalendarDays, Timer } from "lucide-react"
import { Button } from "@/components/ui/button"
import { TaskItem } from "@/components/task-item"
import { useTasks, useLists } from "@/hooks/tasks"
import { useFocusTimer } from "@/stores/timer"
import { ScheduleRecommendation } from "./schedule-recommendation"

export function RecommendationTaskActions({ taskId }: { taskId: string }) {
  const tasks = useTasks()
  const lists = useLists()
  const timer = useFocusTimer()
  const [details, setDetails] = useState(false)
  const [schedule, setSchedule] = useState(false)
  const task = tasks.data?.find(item => item.id === taskId)
  const active = task?.status === "todo" || task?.status === "in_progress"
  const timerBusy = timer.running || timer.elapsed > 0 || timer.phase === "break" || timer.secondsLeft !== timer.workMinutes * 60 || timer.remainderMs > 0
  const differentSession = timerBusy && (timer.taskId !== taskId || timer.phase !== "work")

  if (tasks.isError) return <p role="alert" className="mt-1 text-sm text-destructive">Tasks could not be loaded. <Button variant="link" size="sm" onClick={() => void tasks.refetch()}>Retry tasks</Button></p>
  if (tasks.isPending) return <p role="status" className="mt-1 text-xs text-muted-foreground">Loading linked task…</p>
  if (!task) return <p className="mt-1 text-xs text-muted-foreground">The linked task is no longer available. The recommendation is kept for reference.</p>

  return <div className="mt-2 min-w-0 space-y-2">
    <p className="text-xs text-muted-foreground break-words">Linked task: {task.title}{!active && ` · ${task.status}`}</p>
    <div className="flex flex-wrap gap-2">
      <Button variant="outline" size="sm" aria-expanded={details} onClick={() => setDetails(value => !value)}>{details ? "Close task" : "Open task"}</Button>
      <Button variant="outline" size="sm" aria-expanded={schedule} disabled={!active} onClick={() => setSchedule(value => !value)}><CalendarDays aria-hidden="true" />Schedule</Button>
      <Button variant="outline" size="sm" disabled={!active || differentSession} onClick={() => {
        const current = useFocusTimer.getState()
        useFocusTimer.setState({ taskId, open: true })
        current.start()
      }}><Timer aria-hidden="true" />Start focus</Button>
    </div>
    {differentSession && active && <p className="text-xs text-muted-foreground">Finish or reset the current timer before starting focus for this task.</p>}
    {details && <TaskItem task={task} subtasks={(tasks.data ?? []).filter(item => item.parent_id === task.id)} lists={lists.data ?? []} showList actionsVisible showCompletedDeadline />}
    <div hidden={!schedule}><ScheduleRecommendation taskId={taskId} disabled={!active} /></div>
  </div>
}
