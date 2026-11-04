import { ChevronLeft, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { CalendarMode } from "@/stores/ui"
import { addCalendarDays, calendarRange } from "@/lib/calendar-range"

export function CalendarToolbar({ anchor, mode, onMode, onNavigate, onToday, dayCount = 3, onDayCount, weekCount = 2, onWeekCount }: { anchor: Date; mode: CalendarMode; onMode: (mode: CalendarMode) => void; onNavigate: (direction: number) => void; onToday: () => void; dayCount?: number; onDayCount?: (count: number) => void; weekCount?: number; onWeekCount?: (count: number) => void }) {
  const range = calendarRange(anchor, mode, dayCount, weekCount)
  const label = mode === "year" ? String(anchor.getFullYear()) : mode === "month" ? anchor.toLocaleDateString(undefined, { month: "long", year: "numeric" }) : `${range.start.toLocaleDateString()} – ${addCalendarDays(range.end, -1).toLocaleDateString()}`
  const step = mode === "year" ? "year" : mode === "multi-week" ? `${weekCount} weeks` : mode === "month" ? "month" : mode === "week" ? "week" : mode === "multi-day" ? `${dayCount} days` : "14 days"
  return <div className="mb-2 flex flex-wrap items-center gap-2">
    <h2 className="text-base font-semibold">{label}</h2>
    <Button variant="ghost" size="icon-xs" onClick={() => onNavigate(-1)} aria-label={`Previous ${step}`}><ChevronLeft /></Button>
    <Button variant="ghost" size="sm" onClick={onToday}>Today</Button>
    <Button variant="ghost" size="icon-xs" onClick={() => onNavigate(1)} aria-label={`Next ${step}`}><ChevronRight /></Button>
    <select aria-label="Calendar mode" value={mode} onChange={event => onMode(event.target.value as CalendarMode)} className="rounded-md border border-input bg-background px-2 py-1 text-sm focus-visible:ring-2 focus-visible:ring-ring">
      <option value="month">Month</option><option value="agenda">Agenda</option>
      <option value="year">Year</option><option value="week">Week</option><option value="multi-day">Multi-Day</option><option value="multi-week">Multi-Week</option>
    </select>
    {mode === "multi-day" && <label className="flex items-center gap-2 text-sm">Days
      <select aria-label="Multi-Day day count" value={dayCount} onChange={event => onDayCount?.(Number(event.target.value))} className="rounded-md border border-input bg-background px-2 py-1 focus-visible:ring-2 focus-visible:ring-ring">
        {[2, 3, 4, 5, 6, 7].map(count => <option key={count} value={count}>{count}</option>)}
      </select>
    </label>}
    {mode === "multi-week" && <label className="flex items-center gap-2 text-sm">Weeks
      <select aria-label="Multi-Week week count" value={weekCount} onChange={event => onWeekCount?.(Number(event.target.value))} className="rounded-md border border-input bg-background px-2 py-1 focus-visible:ring-2 focus-visible:ring-ring">
        {[2, 3, 4, 5, 6].map(count => <option key={count} value={count}>{count}</option>)}
      </select>
    </label>}
    <span className="ml-auto text-xs text-muted-foreground">{mode === "year" ? "Select a day for details or a month to drill down" : mode === "month" || mode === "multi-week" ? "Drag a deadline or work block to move it" : mode === "agenda" ? "Use deadline actions or Move block to reschedule" : "Open day details to reschedule"}</span>
  </div>
}
