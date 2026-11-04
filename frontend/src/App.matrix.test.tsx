// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import App from "./App"
import { useUi } from "@/stores/ui"

const query = vi.hoisted(() => ({ isLoading: true, isError: false, data: [], refetch: vi.fn() }))
vi.mock("@/hooks/api", () => ({
  useTasks: () => query,
  useLists: () => ({ data: [] }),
  useResumeCalendarReconciliation: () => {},
  useUpdateTask: () => ({ mutateAsync: vi.fn() }),
  useCreateTask: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
}))
vi.mock("@/components/sidebar", () => ({ Sidebar: () => null }))
vi.mock("@/components/focus-timer", () => ({ FocusTimer: () => null }))
vi.mock("@/components/command-palette", () => ({ CommandPalette: () => null }))
vi.mock("@/components/header", () => ({ Header: () => <h1>Tasks</h1> }))
vi.mock("@/components/quick-add", () => ({ QuickAdd: () => null }))
vi.mock("@/components/briefing-card", () => ({ BriefingCard: () => null }))
vi.mock("@/components/calendar-view", () => ({ CalendarView: () => null }))
vi.mock("@/components/kanban-board", () => ({ KanbanBoard: () => null }))
vi.mock("@/components/task-sections", () => ({ TaskSections: () => null }))
afterEach(() => { cleanup(); useUi.setState(useUi.getInitialState()); localStorage.clear() })

it("keeps Matrix behind task loading and retry, then renders all zones from the canonical query", () => {
  useUi.setState({ section: "tasks", view: "matrix", scope: { kind: "smart", id: "all" } })
  query.isLoading = true; query.isError = false
  const mounted = render(<App />)
  expect(screen.getByLabelText("Loading tasks").getAttribute("aria-busy")).toBe("true")
  expect(screen.queryByRole("region", { name: "Unclassified" })).toBeNull()
  query.isLoading = false; query.isError = true
  mounted.rerender(<App />)
  fireEvent.click(screen.getByRole("button", { name: "Retry" }))
  expect(query.refetch).toHaveBeenCalledOnce()
  expect(screen.queryByRole("region", { name: "Unclassified" })).toBeNull()
  query.isError = false
  mounted.rerender(<App />)
  expect(screen.getAllByRole("region")).toHaveLength(5)
  expect(screen.getByRole("region", { name: "Unclassified" })).toBeTruthy()
})
