import { BulkTasksProvider, BulkTaskToolbar } from "@/components/bulk-tasks"
import { taskSections } from "@/lib/task-sections"
import { boardColumns, selectBoardTasks } from "@/lib/board"
import { lazy, Suspense } from "react"
import { useLists, useTasks } from "@/hooks/api"
import { useUi } from "@/stores/ui"
import { BriefingCard } from "@/components/briefing-card"
import { Header } from "@/components/header"
import { QuickAdd } from "@/components/quick-add"
import { KanbanSkeleton, TaskListSkeleton } from "@/components/skeletons"
import { TaskQueryBoundary } from "@/components/task-query-boundary"
import { TaskSections } from "@/components/task-sections"

const CalendarView = lazy(() => import("@/components/calendar-view").then((m) => ({ default: m.CalendarView })))
const KanbanBoard = lazy(() => import("@/components/kanban-board").then((m) => ({ default: m.KanbanBoard })))

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
      <div className="mt-3 min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
        {view === "list" && !query.isError && scope.kind === "smart" && scope.id === "today" && <BriefingCard />}
        <TaskQueryBoundary query={query} loading={view === "board" ? <KanbanSkeleton /> : <TaskListSkeleton />}>
          {tasks => (
            <BulkTasksProvider key={JSON.stringify([view, scope, search])} tasks={tasks} lists={lists.data ?? []}
              eligible={view === "calendar" ? [] : view === "board"
                ? boardColumns(selectBoardTasks(tasks, scope, search)).flatMap(column => column.tasks)
                : taskSections(tasks, scope, search).selectable}>
              {view !== "calendar" && <BulkTaskToolbar />}
              <Suspense key={view} fallback={view === "board" ? <KanbanSkeleton /> : <TaskListSkeleton />}>
                {view === "calendar"
                  ? <CalendarView tasks={tasks} scope={scope} search={search} />
                  : view === "board"
                    ? <KanbanBoard tasks={tasks} scope={scope} search={search} />
                    : <TaskSections tasks={tasks} scope={scope} search={search} lists={lists.data ?? []} />}
              </Suspense>
            </BulkTasksProvider>
          )}
        </TaskQueryBoundary>
      </div>
    </main>
  )
}
