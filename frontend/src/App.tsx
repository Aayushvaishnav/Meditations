import { AlertCircle } from "lucide-react"
import { MotionConfig } from "framer-motion"
import { FocusTimer } from "@/components/focus-timer"
import { Header } from "@/components/header"
import { BriefingCard } from "@/components/briefing-card"
import { CalendarView } from "@/components/calendar-view"
import { CommandPalette } from "@/components/command-palette"
import { EisenhowerMatrix } from "@/components/eisenhower-matrix"
import { KanbanBoard } from "@/components/kanban-board"
import { QuickAdd } from "@/components/quick-add"
import { Sidebar } from "@/components/sidebar"
import { TaskSections } from "@/components/task-sections"
import { KanbanSkeleton, TaskListSkeleton } from "@/components/skeletons"
import { useLists, useTasks, useResumeCalendarReconciliation } from "@/hooks/api"
import { THEMES, useUi } from "@/stores/ui"
import { lazy, Suspense, useEffect } from "react"
import { SectionLoading } from "@/components/section-loading"
import { Button } from "@/components/ui/button"

const JournalView = lazy(() => import("@/components/journal-editor").then((m) => ({ default: m.JournalView })))
const InsightsView = lazy(() => import("@/components/insights").then((m) => ({ default: m.InsightsView })))
const SecondBrain = lazy(() => import("@/components/second-brain").then((m) => ({ default: m.SecondBrain })))
const SettingsView = lazy(() => import("@/components/settings").then((m) => ({ default: m.SettingsView })))

function TasksErrorBanner({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 pt-24 text-center text-muted-foreground">
      <AlertCircle className="size-8 text-destructive" />
      <p className="text-sm">Can't reach the API. Is the backend running on port 8000?</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        Retry
      </Button>
    </div>
  )
}

export default function App() {
  const theme = useUi((s) => s.theme)
  useEffect(() => {
    const root = document.documentElement
    const meta = THEMES.find((t) => t.id === theme)
    root.classList.toggle("dark", meta?.dark ?? true)
    root.classList.toggle("light", theme === "light")
    for (const t of THEMES) {
      root.classList.toggle(`theme-${t.id}`, theme === t.id)
    }
  }, [theme])

  const section = useUi((s) => s.section)
  const view = useUi((s) => s.view)
  const scope = useUi((s) => s.scope)
  const search = useUi((s) => s.search)
  const tasks = useTasks()
  const lists = useLists()
  useResumeCalendarReconciliation() // app resume triggers one calendar reconciliation pass

  return (
    <MotionConfig reducedMotion="user">
      <div className="flex h-dvh flex-col overflow-hidden text-foreground md:flex-row">
        <Sidebar />
        <Suspense key={section} fallback={<SectionLoading section={section} />}>
          {section === "journal" ? (
            <JournalView />
          ) : section === "second_brain" ? (
            <SecondBrain />
          ) : section === "insights" ? (
            <InsightsView />
          ) : section === "settings" ? (
            <SettingsView />
          ) : (
            <main className="flex min-h-0 min-w-0 flex-1 flex-col">
              <Header />
              <QuickAdd />
              {view === "list" && !tasks.isError && scope.kind === "smart" && scope.id === "today" && <BriefingCard />}
              <div className="mt-3 min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
                {tasks.isError ? (
                  <TasksErrorBanner onRetry={() => void tasks.refetch()} />
                ) : tasks.isLoading ? (
                  view === "board" ? (
                    <KanbanSkeleton />
                  ) : (
                    <TaskListSkeleton />
                  )
                ) : view === "calendar" ? (
                  <CalendarView tasks={tasks.data ?? []} scope={scope} search={search} />
                ) : view === "matrix" ? (
                  <EisenhowerMatrix tasks={tasks.data ?? []} lists={lists.data ?? []} scope={scope} search={search} />
                ) : view === "board" ? (
                  <KanbanBoard tasks={tasks.data ?? []} search={search} />
                ) : (
                  <TaskSections tasks={tasks.data ?? []} scope={scope} search={search} lists={lists.data ?? []} />
                )}
              </div>
            </main>
          )}
        </Suspense>
        <FocusTimer />
        <CommandPalette />
      </div>
    </MotionConfig>
  )
}
