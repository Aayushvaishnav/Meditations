import { useEffect } from "react"
import { useFocusTimer } from "@/stores/timer"
import { useCreateSession } from "@/hooks/api"
import { toast } from "sonner"

/** Keep completion delivery independent of the callback that synchronized time. */
export function useFocusTimerController() {
  const running = useFocusTimer((s) => s.running)
  const events = useFocusTimer((s) => s.events)
  const { mutate } = useCreateSession()

  useEffect(() => {
    if (!running) return
    const id = window.setInterval(() => useFocusTimer.getState().tick(), 1000)
    return () => window.clearInterval(id)
  }, [running])

  useEffect(() => {
    // Drain before side effects; effect replay cannot deliver the same event twice.
    for (const event of useFocusTimer.getState().takeEvents()) {
      if (event.type === "work-done") {
        mutate({ task_id: event.taskId, duration_minutes: event.workMinutes, session_type: "pomodoro" })
        toast.success(`Pomodoro complete — ${event.workMinutes}m logged`)
      } else {
        toast("Break over — ready for the next one")
      }
    }
  }, [events, mutate])
}
