import { MotionConfig } from "framer-motion"
import { FocusTimer } from "@/components/focus-timer"
import { CommandPalette } from "@/components/command-palette"
import { Sidebar } from "@/components/sidebar"
import { useResumeCalendarReconciliation } from "@/hooks/api"
import { THEMES, useUi } from "@/stores/ui"
import { lazy, Suspense, useEffect } from "react"
import { SectionLoading } from "@/components/section-loading"
import { TasksView } from "@/components/tasks-view"
import { MatrixSection } from "@/components/matrix-section"

const JournalView = lazy(() => import("@/components/journal-editor").then((m) => ({ default: m.JournalView })))
const InsightsView = lazy(() => import("@/components/insights").then((m) => ({ default: m.InsightsView })))
const SecondBrain = lazy(() => import("@/components/second-brain").then((m) => ({ default: m.SecondBrain })))
const SettingsView = lazy(() => import("@/components/settings").then((m) => ({ default: m.SettingsView })))

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
          ) : section === "matrix" ? (
            <MatrixSection />
          ) : (
            <TasksView />
          )}
        </Suspense>
        <FocusTimer />
        <CommandPalette />
      </div>
    </MotionConfig>
  )
}
