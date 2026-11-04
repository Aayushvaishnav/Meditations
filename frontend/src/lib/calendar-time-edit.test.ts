import { describe, expect, it } from "vitest"
import { localDateTimeValue, localTimeCandidates, resolveLocalTime } from "./calendar-time-edit"

it("roundtrips unchanged instants including seconds and milliseconds", () => {
  const original = "2026-06-15T14:12:34.567Z"
  expect(resolveLocalTime(localDateTimeValue(new Date(original)), original, "unselected").toISOString()).toBe(original)
})
it.each(["", "2026-02-30T12:00", "2026-13-01T12:00", "0000-01-01T12:00", "2026-01-01T24:00", "not a time"])("rejects invalid civil time %s", value => {
  expect(() => resolveLocalTime(value, "2026-01-01T00:00:00Z", "unselected")).toThrow()
})
it("accepts leap days and minute precision", () => {
  expect(localTimeCandidates("2028-02-29T12:30")).toHaveLength(1)
})
const zone = Intl.DateTimeFormat().resolvedOptions().timeZone
const cases = zone === "America/New_York" ? { gap: "2026-03-08T02:30", fold: "2026-11-01T01:30", minutes: 60 }
  : zone === "Australia/Lord_Howe" ? { gap: "2026-10-04T02:15", fold: "2026-04-05T01:45", minutes: 30 } : undefined
describe.skipIf(!cases)(`DST in ${zone}`, () => {
  it("rejects gaps rather than normalizing", () => {
    expect(localTimeCandidates(cases!.gap)).toEqual([])
  })
  it("requires a fold choice for edits and preserves either original occurrence", () => {
    const candidates = localTimeCandidates(cases!.fold)
    expect(candidates).toHaveLength(2)
    expect(candidates[1].getTime() - candidates[0].getTime()).toBe(cases!.minutes * 60_000)
    expect(() => resolveLocalTime(cases!.fold, "2026-01-01T00:00:00Z", "unselected")).toThrow(/occurs twice/)
    for (const original of candidates) expect(resolveLocalTime(cases!.fold, original.toISOString(), "unselected")).toEqual(original)
    expect(resolveLocalTime(cases!.fold, candidates[1].toISOString(), "earlier")).toEqual(candidates[0])
    expect(resolveLocalTime(cases!.fold, candidates[0].toISOString(), "later")).toEqual(candidates[1])
  })
})
