// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import { Header } from "./header"
import { TooltipProvider } from "./ui/tooltip"
import { useUi } from "@/stores/ui"
vi.mock("@/hooks/api", () => ({ useLists: () => ({ data: [] }) }))
afterEach(() => { cleanup(); useUi.setState(useUi.getInitialState()); localStorage.clear() })

it("offers only List, Board, and Calendar in the tasks header", () => {
  useUi.setState({ section: "tasks", view: "list", scope: { kind: "smart", id: "all" } })
  render(<TooltipProvider><Header /></TooltipProvider>)
  expect(screen.getByRole("heading", { name: "All tasks" })).toBeTruthy()
  expect(screen.queryByRole("button", { name: "Matrix view" })).toBeNull()
  for (const [view, name] of [["list", "List view"], ["board", "Board view"], ["calendar", "Calendar view"]] as const) {
    fireEvent.click(screen.getByRole("button", { name }))
    expect(useUi.getState().view).toBe(view)
    expect(screen.getByRole("button", { name }).getAttribute("aria-pressed")).toBe("true")
  }
})

it.each(["board", "calendar"] as const)("keeps filtering but hides task views in Matrix, then restores %s", (view) => {
  useUi.setState({ section: "matrix", view, scope: { kind: "smart", id: "today" }, search: "draft" })
  render(<TooltipProvider><Header /></TooltipProvider>)
  expect(screen.getByRole("heading", { name: "Eisenhower Matrix" })).toBeTruthy()
  for (const name of ["List view", "Board view", "Calendar view", "Matrix view"]) {
    expect(screen.queryByRole("button", { name })).toBeNull()
  }
  const filter = screen.getByRole("textbox", { name: "Filter tasks" })
  expect((filter as HTMLInputElement).value).toBe("draft")
  fireEvent.change(filter, { target: { value: "review" } })
  expect(useUi.getState()).toMatchObject({ section: "matrix", view, search: "review", scope: { kind: "smart", id: "today" } })
  act(() => useUi.getState().setScope({ kind: "smart", id: "all" }))
  expect(screen.getByRole("heading", { name: "All tasks" })).toBeTruthy()
  expect(screen.getByRole("button", { name: view === "board" ? "Board view" : "Calendar view" }).getAttribute("aria-pressed")).toBe("true")
})

it.each(["Board view", "Calendar view"])("preserves a task view selected through %s across Matrix navigation", (name) => {
  useUi.setState({ section: "tasks", view: "list", scope: { kind: "smart", id: "all" } })
  render(<TooltipProvider><Header /></TooltipProvider>)
  fireEvent.click(screen.getByRole("button", { name }))
  const selectedView = useUi.getState().view
  act(() => useUi.getState().setSection("matrix"))
  expect(screen.getByRole("heading", { name: "Eisenhower Matrix" })).toBeTruthy()
  expect(useUi.getState().view).toBe(selectedView)
  act(() => useUi.getState().setScope({ kind: "smart", id: "today" }))
  expect(screen.getByRole("button", { name }).getAttribute("aria-pressed")).toBe("true")
  expect(useUi.getState()).toMatchObject({ section: "tasks", view: selectedView })
})
