import { useLists, useTasks } from "@/hooks/api"
import { useUi } from "@/stores/ui"
import { BriefingCard } from "@/components/briefing-card"
import { CalendarView } from "@/components/calendar-view"
import { Header } from "@/components/header"
import { KanbanBoard } from "@/components/kanban-board"
import { QuickAdd } from "@/components/quick-add"
import { KanbanSkeleton, TaskListSkeleton } from "@/components/skeletons"
import { TaskQueryBoundary } from "@/components/task-query-boundary"
import { TaskSections } from "@/components/task-sections"

export function TasksView() {
  const view = useUi((s) => s.view)
  const scope = useUi((s) => s.scope)
  const search = useUi((s) => s.search)
  const lists = useLists()
  const query = useTasks()
  return (
    <main className="flex min-h-0 min-w-0 flex-1 flex-col">
      <Header />
      <QuickAdd />
      {view === "list" && !query.isError && scope.kind === "smart" && scope.id === "today" && <BriefingCard />}
      <div className="mt-3 min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
        <TaskQueryBoundary query={query} loading={view === "board" ? <KanbanSkeleton /> : <TaskListSkeleton />}>
          {tasks => view === "calendar"
            ? <CalendarView tasks={tasks} scope={scope} search={search} />
            : view === "board"
              ? <KanbanBoard tasks={tasks} scope={scope} search={search} />
              : <TaskSections tasks={tasks} scope={scope} search={search} lists={lists.data ?? []} />}
        </TaskQueryBoundary>
      </div>
    </main>
  )
}
