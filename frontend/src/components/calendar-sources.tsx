import { useId, useState, type ReactNode } from "react"
import { ChevronDown } from "lucide-react"
import { useUi } from "@/stores/ui"
import { Button } from "./ui/button"

export function CalendarSources({ summary, children }: { summary: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const setSection = useUi(state => state.setSection)
  return <div className="mb-3 min-w-0">
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
      <Button variant="outline" size="sm" aria-expanded={open} aria-controls={id} onClick={() => setOpen(value => !value)}>
        Calendar sources <ChevronDown aria-hidden="true" className={open ? "rotate-180" : ""} />
      </Button>
      <p aria-live="polite" className="min-w-0 break-all text-xs text-muted-foreground">{summary}</p>
    </div>
    <div id={id} hidden={!open} className="mt-3">
      {children}
      <Button variant="link" size="sm" onClick={() => setSection("settings")}>Manage calendars in Settings</Button>
    </div>
  </div>
}
