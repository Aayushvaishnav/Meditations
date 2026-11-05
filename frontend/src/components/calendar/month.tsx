import { CalendarDayGrid } from "./day-grid"

export function CalendarMonth(props: Parameters<typeof CalendarDayGrid>[0]) {
  return <section aria-label="Month calendar" className="min-w-0">
    <p className="mb-2 text-xs text-muted-foreground">Scroll sideways to see more days. Open a day for full item details.</p>
    <div role="region" aria-label="Month calendar; scroll horizontally to see more days" tabIndex={0} className="max-w-full overflow-x-auto pb-2 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset">
      <div className="min-w-[56rem]"><CalendarDayGrid {...props} /></div>
    </div>
  </section>
}
