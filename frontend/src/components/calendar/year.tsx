import { useRef, useState } from "react"
import { cn } from "cn"
import { calendarDaySummary, type CalendarDay } from "@/lib/calendar-projection"
import { addCalendarDays, calendarMonthDays } from "@/lib/calendar-range"
import { localDayParam } from "@/lib/task-deadlines"

export function CalendarYear({ days, anchor, onOpen, onMonth }: { days: CalendarDay[]; anchor: Date; onOpen: (day: Date) => void; onMonth: (day: Date) => void }) {
  const root = useRef<HTMLDivElement>(null)
  const [focusedDays, setFocusedDays] = useState<Record<number, string>>({})
  const byDate = new Map(days.map(day => [localDayParam(day.day), day]))
  const today = localDayParam(new Date())
  const selected = localDayParam(anchor)
  return <section aria-label={`${anchor.getFullYear()} year overview`}>
    <p className="mb-3 text-xs text-muted-foreground">Shading shows visible item density: 1 item, 2–3 items, or 4+ items. Counts include each day of a spanning event. Use arrow keys within a month; Enter opens day details.</p>
    <div ref={root} className="grid min-w-0 grid-cols-1 gap-x-6 gap-y-5 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
      {Array.from({ length: 12 }, (_, month) => {
        const start = new Date(anchor.getFullYear(), month, 1)
        const label = start.toLocaleDateString(undefined, { month: "long" })
        const monthDays = calendarMonthDays(start)
        const defaultTabDay = anchor.getMonth() === month ? selected : today.startsWith(`${anchor.getFullYear()}-${String(month + 1).padStart(2, "0")}-`) ? today : localDayParam(start)
        const tabDay = focusedDays[month]?.startsWith(`${anchor.getFullYear()}-`) ? focusedDays[month] : defaultTabDay
        return <section key={month} aria-label={`${label} ${anchor.getFullYear()}`} className="min-w-0">
          <button onClick={() => onMonth(anchor.getMonth() === month ? anchor : start)} aria-label={`Open ${label} ${anchor.getFullYear()} in Month`} className="mb-2 rounded px-1 py-1 text-sm font-semibold hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring">{label}</button>
          <div className="grid grid-cols-7 gap-1 text-center">
            {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map(day => <span key={day} className="py-1 text-[10px] text-muted-foreground" aria-hidden="true">{day}</span>)}
            {monthDays.map(day => {
              const key = localDayParam(day)
              if (day.getMonth() !== month) return <span key={key} />
              const projection = byDate.get(key) ?? { day, items: [] }
              const count = projection.items.length
              return <button key={key} data-year-day={key} tabIndex={key === tabDay ? 0 : -1}
                aria-label={`${key}, ${calendarDaySummary(projection)}`}
                aria-current={key === today ? "date" : undefined} aria-pressed={key === selected}
                onFocus={() => setFocusedDays(current => ({ ...current, [month]: key }))}
                onClick={() => onOpen(day)}
                onKeyDown={event => {
                  const offset = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[event.key]
                  if (offset === undefined) return
                  event.preventDefault()
                  const target = addCalendarDays(day, offset)
                  if (target.getFullYear() !== day.getFullYear() || target.getMonth() !== month) return
                  const next = root.current?.querySelector<HTMLButtonElement>(`[data-year-day="${localDayParam(target)}"]`)
                  if (next) {
                    next.focus()
                  }
                }}
                className={cn("relative min-h-11 min-w-0 rounded text-xs tabular-nums hover:underline focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2", count === 0 ? "hover:bg-accent" : count === 1 ? "bg-primary/10" : count < 4 ? "bg-primary/20" : "bg-primary/35", key === selected && "ring-1 ring-foreground", key === today && "font-bold underline underline-offset-4")}
              >{day.getDate()}</button>
            })}
          </div>
        </section>
      })}
    </div>
  </section>
}
