import { CalendarDayGrid } from "./day-grid"

export function CalendarMultiWeek(props: Omit<Parameters<typeof CalendarDayGrid>[0], "anchor">) {
  return <section aria-label="Multi-Week calendar" className="min-w-0">
    <p className="mb-2 text-xs text-muted-foreground">Week rows run Monday to Sunday. Open a day for its full date and details.</p>
    <div className="overflow-x-auto pb-2" role="region" aria-label="Calendar weeks; scroll horizontally to see more days" tabIndex={0}>
      <div className="min-w-[42rem]"><CalendarDayGrid {...props} /></div>
    </div>
  </section>
}
