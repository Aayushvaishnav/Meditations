// @vitest-environment jsdom
import { useEffect, useState } from "react"
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import App from "./App"
import { useUi, type Section } from "@/stores/ui"

const lazyModules = vi.hoisted(() => {
  function gate() {
    let resolve!: () => void
    const promise = new Promise<void>((done) => { resolve = done })
    return { promise, resolve, requested: vi.fn() }
  }
  return { journal: gate(), insights: gate(), second_brain: gate(), settings: gate() }
})
const mounts = vi.hoisted(() => ({ sidebar: 0, timer: 0, palette: 0 }))

function ShellControl({ name }: { name: keyof typeof mounts }) {
  const [count, setCount] = useState(0)
  useEffect(() => { mounts[name] += 1 }, [name])
  return <button onClick={() => setCount((value) => value + 1)}>{name}: {count}</button>
}

vi.mock("@/components/sidebar", () => ({ Sidebar: () => <ShellControl name="sidebar" /> }))
vi.mock("@/components/focus-timer", () => ({ FocusTimer: () => <ShellControl name="timer" /> }))
vi.mock("@/components/command-palette", () => ({ CommandPalette: () => <ShellControl name="palette" /> }))
vi.mock("@/components/header", () => ({ Header: () => <h1>Tasks</h1> }))
vi.mock("@/components/quick-add", () => ({ QuickAdd: () => null }))
vi.mock("@/components/briefing-card", () => ({ BriefingCard: () => null }))
vi.mock("@/components/calendar-view", () => ({ CalendarView: () => null }))
vi.mock("@/components/kanban-board", () => ({ KanbanBoard: () => null }))
vi.mock("@/components/task-sections", () => ({ TaskSections: () => <p>Task list</p> }))
vi.mock("@/components/skeletons", () => ({ KanbanSkeleton: () => null, TaskListSkeleton: () => null }))
vi.mock("@/hooks/api", () => ({
  useTasks: () => ({ data: [], isLoading: false, isError: false }),
  useLists: () => ({ data: [] }),
  useResumeCalendarReconciliation: () => {},
}))
vi.mock("@/components/journal-editor", async () => {
  lazyModules.journal.requested()
  await lazyModules.journal.promise
  return { JournalView: () => <main><h1>Journal content</h1></main> }
})
vi.mock("@/components/insights", async () => {
  lazyModules.insights.requested()
  await lazyModules.insights.promise
  return { InsightsView: () => <main><h1>Insights content</h1></main> }
})
vi.mock("@/components/second-brain", async () => {
  lazyModules.second_brain.requested()
  await lazyModules.second_brain.promise
  return { SecondBrain: () => <main><h1>Brain content</h1></main> }
})
vi.mock("@/components/settings", async () => {
  lazyModules.settings.requested()
  await lazyModules.settings.promise
  return { SettingsView: () => <main><h1>Settings content</h1></main> }
})

function navigate(section: Section) {
  act(() => useUi.getState().setSection(section))
}
function expectLoading(label: string) {
  const main = screen.getByRole("main")
  expect(main.getAttribute("aria-busy")).toBe("true")
  expect(within(main).getByRole("status").textContent).toContain(label)
}
async function resolveSection(section: keyof typeof lazyModules) {
  await act(async () => {
    lazyModules[section].resolve()
    await lazyModules[section].promise
  })
}

afterEach(() => {
  cleanup()
  useUi.setState(useUi.getInitialState())
  localStorage.clear()
})

// One navigation lifecycle keeps each lazy module's first load independent of test order.
it("loads sections on demand while preserving the shell and current navigation", async () => {
  render(<App />)
  expect(screen.getByRole("heading", { name: "Tasks" })).toBeTruthy()
  expect(screen.getByText("Task list")).toBeTruthy()
  for (const gate of Object.values(lazyModules)) expect(gate.requested).not.toHaveBeenCalled()

  const initialMounts = { ...mounts }
  for (const name of Object.keys(mounts)) fireEvent.click(screen.getByRole("button", { name: `${name}: 0` }))
  function expectShellPreserved() {
    for (const name of Object.keys(mounts)) expect(screen.getByRole("button", { name: `${name}: 1` })).toBeTruthy()
    expect(mounts).toEqual(initialMounts)
  }

  navigate("journal")
  expectLoading("journal")
  expectShellPreserved()
  await resolveSection("journal")
  expect(screen.getByRole("heading", { name: "Journal content" })).toBeTruthy()
  expect(screen.queryByRole("status")).toBeNull()
  expect(lazyModules.journal.requested).toHaveBeenCalledTimes(1)
  expect(lazyModules.insights.requested).not.toHaveBeenCalled()
  expect(lazyModules.second_brain.requested).not.toHaveBeenCalled()
  expect(lazyModules.settings.requested).not.toHaveBeenCalled()

  navigate("insights")
  expectLoading("insights")
  expectShellPreserved()
  navigate("tasks")
  await resolveSection("insights")
  expect(screen.getByRole("heading", { name: "Tasks" })).toBeTruthy()
  expect(screen.queryByRole("heading", { name: "Insights content" })).toBeNull()
  navigate("insights")
  expect(screen.getByRole("heading", { name: "Insights content" })).toBeTruthy()
  expect(screen.queryByRole("status")).toBeNull()

  navigate("second_brain")
  expectLoading("Second Brain")
  expectShellPreserved()
  await resolveSection("second_brain")
  expect(screen.getByRole("heading", { name: "Brain content" })).toBeTruthy()
  expect(screen.queryByRole("status")).toBeNull()

  navigate("journal")
  expect(screen.getByRole("heading", { name: "Journal content" })).toBeTruthy()
  expect(screen.queryByRole("status")).toBeNull()
  expectShellPreserved()
  expect(lazyModules.insights.requested).toHaveBeenCalledTimes(1)
  expect(lazyModules.second_brain.requested).toHaveBeenCalledTimes(1)
  expect(lazyModules.settings.requested).not.toHaveBeenCalled()

  cleanup()
  localStorage.setItem("journal-ui", JSON.stringify({ state: { section: "settings" }, version: 0 }))
  await act(async () => { await useUi.persist.rehydrate() })
  render(<App />)
  expectLoading("settings")
  for (const name of Object.keys(mounts)) expect(screen.getByRole("button", { name: `${name}: 0` })).toBeTruthy()
  await resolveSection("settings")
  expect(screen.getByRole("heading", { name: "Settings content" })).toBeTruthy()
  expect(screen.queryByRole("status")).toBeNull()
  navigate("tasks")
  navigate("settings")
  expect(screen.getByRole("heading", { name: "Settings content" })).toBeTruthy()
  expect(screen.queryByRole("status")).toBeNull()
  expect(lazyModules.settings.requested).toHaveBeenCalledTimes(1)
})
