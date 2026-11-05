import type { ReactNode } from "react"
import { AlertCircle } from "lucide-react"
import type { Task } from "@/api/types"
import type { useTasks } from "@/hooks/api"
import { TaskListSkeleton } from "@/components/skeletons"
import { Button } from "@/components/ui/button"

export function TaskQueryBoundary({ query: tasks, children, loading = <TaskListSkeleton /> }: {
  query: ReturnType<typeof useTasks>
  children: (tasks: Task[]) => ReactNode
  loading?: ReactNode
}) {
  if (tasks.isError) return (
    <div className="flex flex-col items-center gap-3 pt-24 text-center text-muted-foreground">
      <AlertCircle className="size-8 text-destructive" />
      <p className="text-sm">Can't reach the API. Is the backend running on port 8000?</p>
      <Button variant="outline" size="sm" onClick={() => void tasks.refetch()}>Retry</Button>
    </div>
  )
  if (tasks.isLoading) return loading
  return children(tasks.data ?? [])
}
