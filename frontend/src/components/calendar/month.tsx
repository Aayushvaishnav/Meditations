import { CalendarDayGrid } from "./day-grid"

export function CalendarMonth(props: Parameters<typeof CalendarDayGrid>[0]) {
  return <CalendarDayGrid {...props} />
}
