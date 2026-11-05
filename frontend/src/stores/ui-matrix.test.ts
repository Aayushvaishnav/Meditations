// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it } from "vitest"
import { useUi } from "./ui"

beforeEach(() => { localStorage.clear(); useUi.setState(useUi.getInitialState()) })
afterEach(() => { localStorage.clear(); useUi.setState(useUi.getInitialState()); localStorage.clear() })

async function restore(state: Record<string, unknown>) {
  localStorage.setItem("journal-ui", JSON.stringify({ state, version: 0 }))
  await useUi.persist.rehydrate()
}

it("migrates legacy task Matrix preferences to the Matrix section and List task view", async () => {
  const scope = { kind: "list", id: "work" }
  await restore({ section: "tasks", view: "matrix", scope, sidebar: "collapsed", theme: "light" })
  expect(useUi.getState()).toMatchObject({ section: "matrix", view: "list", scope, sidebar: "collapsed", theme: "light" })
  expect(typeof useUi.getState().setSection).toBe("function")
})

it.each(["journal", "second_brain", "insights", "settings"])("preserves the %s section while migrating a legacy Matrix view", async (section) => {
  const scope = { kind: "smart", id: "completed" }
  await restore({ section, view: "matrix", scope })
  expect(useUi.getState()).toMatchObject({ section, view: "list", scope })
})

it.each(["list", "board", "calendar"] as const)("rehydrates a saved Matrix section with its %s task view", async (view) => {
  const scope = { kind: "list", id: "work" }
  await restore({ section: "matrix", view, scope })
  expect(useUi.getState()).toMatchObject({ section: "matrix", view, scope })
})

it.each(["board", "calendar"] as const)("persists %s through a Matrix roundtrip", async (view) => {
  useUi.setState({ section: "tasks", view, scope: { kind: "smart", id: "all" } })
  useUi.getState().setSection("matrix")
  const saved = localStorage.getItem("journal-ui")!
  useUi.setState(useUi.getInitialState())
  localStorage.setItem("journal-ui", saved)
  await useUi.persist.rehydrate()
  expect(useUi.getState()).toMatchObject({ section: "matrix", view, scope: { kind: "smart", id: "all" } })
  useUi.getState().setScope({ kind: "smart", id: "today" })
  expect(useUi.getState()).toMatchObject({ section: "tasks", view, scope: { kind: "smart", id: "today" } })
})
