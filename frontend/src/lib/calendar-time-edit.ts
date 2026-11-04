import { parseUTC } from "./date-values"

export type FoldChoice = "unselected" | "earlier" | "later"

export function localDateTimeValue(date: Date): string {
  const pad = (value: number, width = 2) => String(value).padStart(width, "0")
  return `${pad(date.getFullYear(), 4)}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`
}

export function localTimeCandidates(value: string): Date[] {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?$/.test(value)) return []
  const civil = new Date(`${value}Z`)
  if (!Number.isFinite(civil.getTime()) || civil.getUTCFullYear() < 1) return []
  const canonical = civil.toISOString().slice(0, -1)
  if (canonical.slice(0, value.length) !== value) return []
  const offsets = new Set<number>()
  // Date exposes no transition API; inspect the surrounding offset regimes, including half-hour folds
  for (let minute = -1440; minute <= 1440; minute++) {
    const instant = new Date(civil.getTime() + minute * 60_000)
    const localAsUTC = new Date(`${localDateTimeValue(instant)}Z`).getTime()
    offsets.add(localAsUTC - instant.getTime())
  }
  return [...offsets].map(offset => new Date(civil.getTime() - offset))
    .filter(date => localDateTimeValue(date) === canonical)
    .sort((a, b) => a.getTime() - b.getTime())
}

export function resolveLocalTime(value: string, original: string, choice: FoldChoice): Date {
  const candidates = localTimeCandidates(value)
  if (!candidates.length) throw new Error("Choose a valid local time; this time may not exist because the clocks change.")
  const previous = parseUTC(original)!
  if (choice === "unselected") {
    const unchanged = candidates.find(candidate => candidate.getTime() === previous.getTime())
    if (unchanged) return unchanged
    if (candidates.length > 1) throw new Error("This time occurs twice. Choose the earlier or later occurrence.")
  }
  const result = choice === "later" ? candidates[candidates.length - 1] : candidates[0]
  if (result.getUTCFullYear() < 1 || result.getUTCFullYear() > 9999) throw new Error("Choose a time within years 0001–9999.")
  return result
}
