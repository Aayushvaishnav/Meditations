// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest"
import { useUi } from "./ui"

beforeEach(() => {
  localStorage.clear()
  useUi.setState({ calendarMode: "month", view: "list", scope: { kind: "smart", id: "all" } })
})

describe("calendar mode preferences", () => {
  it("defaults older preferences to Month without changing the task view or scope", async () => {
    localStorage.setItem("journal-ui", JSON.stringify({ state: { view: "calendar", scope: { kind: "list", id: "work" } }, version: 0 }))
    await useUi.persist.rehydrate()
    expect(useUi.getState().calendarMode).toBe("month")
    expect(useUi.getState().view).toBe("calendar")
    expect(useUi.getState().scope).toEqual({ kind: "list", id: "work" })
  })

  it("persists the mode separately from task navigation and restores it", async () => {
    useUi.getState().setCalendarMode("agenda")
    useUi.getState().setView("board")
    useUi.getState().setScope({ kind: "list", id: "work" })
    const saved = localStorage.getItem("journal-ui")!
    useUi.setState({ calendarMode: "month" })
    localStorage.setItem("journal-ui", saved)
    await useUi.persist.rehydrate()
    expect(useUi.getState().calendarMode).toBe("agenda")
    expect(useUi.getState().view).toBe("board")
    expect(useUi.getState().scope).toEqual({ kind: "list", id: "work" })
  })
})
