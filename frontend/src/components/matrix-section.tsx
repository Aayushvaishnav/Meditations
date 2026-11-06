import { BulkTasksProvider, BulkTaskToolbar } from "@/components/bulk-tasks"
import { selectMatrixTasks } from "@/lib/eisenhower"
import { useLists, useTasks } from "@/hooks/api"
import { useUi } from "@/stores/ui"
import { EisenhowerMatrix } from "@/components/eisenhower-matrix"
import { Header } from "@/components/header"
import { TaskQueryBoundary } from "@/components/task-query-boundary"

export function MatrixSection() {
  const search = useUi((s) => s.search)
  const lists = useLists()
  const query = useTasks()
  return (
    <main className="flex min-h-0 min-w-0 flex-1 flex-col">
      <Header />
      <div className="mt-3 min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
        <TaskQueryBoundary query={query}>
          {tasks => <BulkTasksProvider key={search} tasks={tasks} lists={lists.data ?? []}
            eligible={selectMatrixTasks(tasks, { kind: "smart", id: "all" }, search)}>
            <BulkTaskToolbar />
            <EisenhowerMatrix tasks={tasks} lists={lists.data ?? []} scope={{ kind: "smart", id: "all" }} search={search} />
          </BulkTasksProvider>}
        </TaskQueryBoundary>
      </div>
    </main>
  )
}
