// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it } from "vitest"
import { useUi } from "./ui"

beforeEach(() => { localStorage.clear(); useUi.setState(useUi.getInitialState()) })
afterEach(() => { useUi.setState(useUi.getInitialState()); localStorage.clear() })

it.each([{}, { scoreDisplay: null }, { scoreDisplay: "unknown" }])("defaults older or invalid preferences to scores: %j", async (state) => {
  localStorage.setItem("journal-ui", JSON.stringify({ state, version: 0 }))
  await useUi.persist.rehydrate()
  expect(useUi.getState().scoreDisplay).toBe("scored")
})

it.each(["scored", "reflection"] as const)("persists %s across navigation and reload without changing other preferences", async (scoreDisplay) => {
  useUi.setState({ theme: "light", sidebar: "collapsed", view: "calendar" })
  useUi.getState().setScoreDisplay(scoreDisplay)
  useUi.getState().setSection("journal")
  useUi.getState().setSection("insights")
  const saved = localStorage.getItem("journal-ui")!
  useUi.setState(useUi.getInitialState())
  localStorage.setItem("journal-ui", saved)
  await useUi.persist.rehydrate()
  expect(useUi.getState()).toMatchObject({ scoreDisplay, theme: "light", sidebar: "collapsed", view: "calendar", section: "insights" })
})

it("preserves reflection-first when migrating a legacy Matrix preference", async () => {
  localStorage.setItem("journal-ui", JSON.stringify({ state: { scoreDisplay: "reflection", section: "tasks", view: "matrix" }, version: 0 }))
  await useUi.persist.rehydrate()
  expect(useUi.getState()).toMatchObject({ scoreDisplay: "reflection", section: "matrix", view: "list" })
})
