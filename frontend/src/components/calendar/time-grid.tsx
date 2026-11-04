import { useEffect, useState } from "react"
import { CalendarDays, Clock, Flag } from "lucide-react"
import type { CalendarDay, CalendarItem } from "@/lib/calendar-projection"
import { dayTimeLayout } from "@/lib/calendar-time-grid"
import { localDayParam } from "@/lib/task-deadlines"
import { blockTimeLabel } from "@/lib/time-blocks"
import { importedEventLabel } from "@/lib/calendar-overlay"
import { cn } from "cn"

const HOUR_HEIGHT = 72
const DAY_HEIGHT = HOUR_HEIGHT * 24

function title(item: CalendarItem) {
  return item.kind === "deadline" || item.kind === "block" ? item.task.title : item.event.summary
}
function kindLabel(item: CalendarItem) {
  return item.kind === "deadline" ? "Task deadline" : item.kind === "block" ? "Work block" : item.kind === "imported" ? "Imported event · read-only" : "Live event · read-only"
}
function timeLabel(item: CalendarItem) {
  return item.kind === "block" ? blockTimeLabel(item.block) : item.kind === "deadline" ? item.timing.kind === "timed" ? `Due ${item.timing.clock.slice(0, 5)}` : "All day" : importedEventLabel(item.event)
}
function ItemButton({ item, onOpen }: { item: CalendarItem; onOpen: () => void }) {
  return <button type="button" onClick={onOpen} aria-label={`${title(item)}, ${kindLabel(item)}, ${timeLabel(item)}`} title={`${title(item)} · ${kindLabel(item)} · ${timeLabel(item)}`}
    className="flex w-full min-w-0 items-start gap-1 rounded px-1 py-1 text-left text-xs hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset">
    {item.kind === "deadline" ? <Flag aria-hidden="true" className="size-3 shrink-0" /> : <CalendarDays aria-hidden="true" className="size-3 shrink-0" />}
    <span className="min-w-0 truncate">{title(item)}<span className="block text-muted-foreground">{kindLabel(item)}</span></span>
  </button>
}

function TimeGridDay({ day, now, onOpen }: { day: CalendarDay; now: Date; onOpen: (day: Date) => void }) {
  const layout = dayTimeLayout(day)
  const key = localDayParam(day.day)
  const isToday = key === localDayParam(now)
  const markers = new Map<number, CalendarItem[]>()
  for (const marker of layout.markers) markers.set(marker.minute, [...(markers.get(marker.minute) ?? []), marker.item])
  return <section className="min-w-0 border-r border-border last:border-r-0" aria-label={key}>
    <div className="min-h-20 border-b border-border p-2">
      <h3 className={cn("text-sm font-semibold", isToday && "text-primary")}>
        <button type="button" onClick={() => onOpen(day.day)} aria-label={`Add task on ${key}`} aria-current={isToday ? "date" : undefined} className="rounded text-left hover:underline focus-visible:ring-2 focus-visible:ring-ring">
          {day.day.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}
        </button>
      </h3>
      <button type="button" onClick={() => onOpen(day.day)} className="mt-1 rounded text-xs text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">{day.items.length} {day.items.length === 1 ? "item" : "items"} · Details</button>
    </div>
    <div className="relative" style={{ height: DAY_HEIGHT }} aria-label={`Timed items on ${key}`}>
      {Array.from({ length: 24 }, (_, hour) => <div key={hour} aria-hidden="true" className="pointer-events-none absolute inset-x-0 border-t border-border/60" style={{ top: hour * HOUR_HEIGHT }} />)}
      {layout.intervals.map(interval => <button key={interval.item.id} type="button" onClick={() => onOpen(day.day)}
        aria-label={`${title(interval.item)}, ${kindLabel(interval.item)}, ${timeLabel(interval.item)}${interval.continuesBefore ? ", continues from previous day" : ""}${interval.continuesAfter ? ", continues next day" : ""}`}
        title={`${title(interval.item)} · ${timeLabel(interval.item)}`}
        className={cn("absolute overflow-hidden rounded border px-1 py-0.5 text-left text-xs hover:bg-accent focus-visible:z-20 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset", interval.item.kind === "block" ? "border-primary/30 bg-primary/10" : "border-dashed border-border bg-muted")}
        style={{ top: interval.startMinute / 60 * HOUR_HEIGHT, height: (interval.endMinute - interval.startMinute) / 60 * HOUR_HEIGHT, left: `${interval.column / interval.columns * (markers.size ? 62 : 100)}%`, width: `calc(${(markers.size ? 62 : 100) / interval.columns}% - 2px)` }}>
        <span className="block truncate font-medium">{title(interval.item)}</span>
        <span className="block truncate">{timeLabel(interval.item)}</span>
        <span className="block truncate text-muted-foreground">{kindLabel(interval.item)}</span>
        {(interval.continuesBefore || interval.continuesAfter) && <span className="block truncate">Continues {interval.continuesBefore ? "from previous day" : "next day"}</span>}
      </button>)}
      {[...markers].map(([minute, items]) => <button type="button" key={minute} onClick={() => onOpen(day.day)}
        aria-label={items.map(item => `${title(item)}, ${kindLabel(item)}, ${timeLabel(item)}`).join("; ")}
        title={items.map(item => `${title(item)} · ${timeLabel(item)}`).join("; ")}
        className="absolute right-0 z-10 flex w-[38%] items-start gap-0.5 border-t border-primary bg-background px-1 text-left text-xs hover:bg-accent focus-visible:z-20 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
        style={{ top: minute / 60 * HOUR_HEIGHT, transform: minute > 1410 ? "translateY(-100%)" : undefined }}>
        <Flag aria-hidden="true" className="mt-0.5 size-3 shrink-0" /><span className="min-w-0 truncate">{items[0].kind === "deadline" ? "Due" : "At"} {String(Math.floor(minute / 60)).padStart(2, "0")}:{String(Math.floor(minute % 60)).padStart(2, "0")}<span className="block truncate">{items.length > 1 ? `${items.length} items` : title(items[0])}</span></span>
      </button>)}
      {isToday && <div role="img" aria-label={`Current time ${now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`} className="pointer-events-none absolute inset-x-0 z-10 border-t border-primary" style={{ top: (now.getHours() + now.getMinutes() / 60) * HOUR_HEIGHT }}><span className="absolute -top-1 left-0 size-2 rounded-full bg-primary" /></div>}
    </div>
  </section>
}

export function CalendarTimeGrid({ days, onOpen }: { days: CalendarDay[]; onOpen: (day: Date) => void }) {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 60_000)
    return () => window.clearInterval(timer)
  }, [])
  const sourceDays = days.map(day => ({ ...day, sourceClock: dayTimeLayout(day).sourceClock })).filter(day => day.sourceClock.length)
  return <div className="min-w-0 space-y-4">
    <p className="text-xs text-muted-foreground">Due flags mark deadlines. Open a date for details and edits. Scroll sideways to see more days.</p>
    {days.every(day => day.items.length === 0) && <p role="status" className="text-sm text-muted-foreground">No calendar items in this range. Open a date to add a task deadline.</p>}
    <section aria-label="All-day items" className="rounded-lg border border-border p-3">
      <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold"><CalendarDays aria-hidden="true" className="size-4" />All day</h3>
      {days.every(day => day.items.every(item => !item.allDay)) ? <p className="text-xs text-muted-foreground">No all-day items.</p> : <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{days.filter(day => day.items.some(item => item.allDay)).map(day => <div key={localDayParam(day.day)} className="min-w-0"><h4 className="text-xs font-medium">{day.day.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}</h4>{day.items.filter(item => item.allDay).map(item => <ItemButton key={item.id} item={item} onOpen={() => onOpen(day.day)} />)}</div>)}</div>}
    </section>
    {sourceDays.length > 0 && <section aria-label="Source-clock and interval details" className="rounded-lg border border-border p-3">
      <h3 className="mb-1 flex items-center gap-2 text-sm font-semibold"><Clock aria-hidden="true" className="size-4" />Source-clock and interval details</h3>
      <p className="mb-2 text-xs text-muted-foreground">Floating times and intervals without a safe grid position retain their source labels here.</p>
      {sourceDays.map(day => <div key={localDayParam(day.day)} className="mb-2 min-w-0"><h4 className="text-xs font-medium">{localDayParam(day.day)}</h4>{day.sourceClock.map(item => <div key={item.id} className="min-w-0"><ItemButton item={item} onOpen={() => onOpen(day.day)} /><p className="break-words px-1 text-xs text-muted-foreground">{timeLabel(item)}</p></div>)}</div>)}
    </section>}
    <div role="region" aria-label="Calendar time grid; scroll horizontally to see more days" tabIndex={0} className="max-w-full overflow-x-auto rounded-lg border border-border focus-visible:ring-2 focus-visible:ring-ring">
      <div className="grid" style={{ gridTemplateColumns: `3.5rem repeat(${days.length}, minmax(10rem, 1fr))`, minWidth: `calc(3.5rem + ${days.length * 10}rem)` }}>
        <div aria-hidden="true" className="sticky left-0 z-20 bg-background"><div className="min-h-20 border-b border-border" /><div className="relative" style={{ height: DAY_HEIGHT }}>{Array.from({ length: 24 }, (_, hour) => <span key={hour} className="absolute right-2 text-xs tabular-nums text-muted-foreground" style={{ top: hour * HOUR_HEIGHT + 2 }}>{String(hour).padStart(2, "0")}:00</span>)}</div></div>
        {days.map(day => <TimeGridDay key={localDayParam(day.day)} day={day} now={now} onOpen={onOpen} />)}
      </div>
    </div>
  </div>
}
