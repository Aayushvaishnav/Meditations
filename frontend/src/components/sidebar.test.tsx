// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { Sidebar } from "./sidebar"
import { useUi } from "@/stores/ui"

const mocks = vi.hoisted(() => ({ create: vi.fn(), remove: vi.fn(), mediaChange: (_event: unknown) => {}, wide: false }))
vi.mock("@/hooks/api", () => ({
  useTasks: () => ({ data: [] }),
  useLists: () => ({ data: [{ id: "work", name: "Work", color: "#123456" }] }),
  useHealth: () => ({ isLoading: false, isError: false }),
  useCreateList: () => ({ mutate: mocks.create }),
  useDeleteList: () => ({ mutate: mocks.remove }),
}))
beforeEach(() => {
  useUi.setState(useUi.getInitialState())
  mocks.wide = false
  vi.stubGlobal("matchMedia", vi.fn(() => ({ get matches() { return mocks.wide }, addEventListener: (_name: string, handler: typeof mocks.mediaChange) => { mocks.mediaChange = handler }, removeEventListener: vi.fn() })))
  vi.clearAllMocks()
})
afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals() })
const desktop = () => within(screen.getByRole("complementary", { name: "Sidebar" }))

describe("sidebar navigation", () => {
  it("persists collapse without changing section, task scope, or search", async () => {
    useUi.setState({ section: "journal", scope: { kind: "list", id: "work" }, search: "draft" })
    render(<Sidebar />)
    fireEvent.click(desktop().getByRole("button", { name: "Collapse sidebar" }))
    expect(useUi.getState()).toMatchObject({ sidebar: "collapsed", section: "journal", scope: { kind: "list", id: "work" }, search: "draft" })
    expect(desktop().getByRole("button", { name: "Expand sidebar" }).getAttribute("aria-expanded")).toBe("false")
    expect(JSON.parse(localStorage.getItem("journal-ui")!).state.sidebar).toBe("collapsed")
    await act(async () => { await useUi.persist.rehydrate() })
    expect(useUi.getState().sidebar).toBe("collapsed")
    fireEvent.click(desktop().getByRole("button", { name: "Expand sidebar" }))
    expect(useUi.getState().sidebar).toBe("expanded")
  })
  it("loads old preferences expanded", async () => {
    localStorage.setItem("journal-ui", JSON.stringify({ state: { section: "insights", theme: "light" }, version: 0 }))
    await act(async () => { await useUi.persist.rehydrate() })
    expect(useUi.getState()).toMatchObject({ sidebar: "expanded", section: "insights" })
  })
  it("exposes all destinations and current selection in the rail, with Settings outside navigation scrolling", () => {
    useUi.setState({ sidebar: "collapsed" })
    render(<Sidebar />)
    for (const [label, section] of [["Journal", "journal"], ["Second brain", "second_brain"], ["Insights", "insights"], ["Settings", "settings"]]) {
      fireEvent.click(desktop().getByRole("button", { name: label }))
      expect(useUi.getState().section).toBe(section)
      expect(desktop().getByRole("button", { name: label }).getAttribute("aria-current")).toBe("page")
    }
    for (const [label, id] of [["Today", "today"], ["Overdue", "overdue"], ["Upcoming", "upcoming"], ["All tasks", "all"], ["Completed", "completed"]]) {
      fireEvent.click(desktop().getByRole("button", { name: label }))
      expect(useUi.getState().scope).toEqual({ kind: "smart", id })
    }
    const settings = desktop().getByRole("button", { name: "Settings" })
    expect(settings.closest("footer")).toBeTruthy()
    expect(settings.closest("nav")).toBeNull()
    expect(desktop().getByRole("status", { name: "API connected" })).toBeTruthy()
  })
  it("opens named lists, creates a list explicitly, and selects a scope", async () => {
    useUi.setState({ sidebar: "collapsed" })
    render(<Sidebar />)
    fireEvent.click(desktop().getByRole("button", { name: "Lists" }))
    const popup = await screen.findByRole("dialog", { name: "Lists" })
    fireEvent.click(within(popup).getByRole("button", { name: "New list" }))
    fireEvent.change(within(popup).getByRole("textbox", { name: "List name" }), { target: { value: "Personal" } })
    fireEvent.click(within(popup).getByRole("button", { name: "Create list" }))
    expect(mocks.create).toHaveBeenCalledWith({ name: "Personal" }, expect.any(Object))
    fireEvent.click(within(popup).getByRole("button", { name: "Work" }))
    expect(useUi.getState().scope).toEqual({ kind: "list", id: "work" })
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Lists" })).toBeNull())
  })
  it("requires a deliberate confirmation to delete a list", () => {
    render(<Sidebar />)
    fireEvent.click(desktop().getByRole("button", { name: 'Delete list "Work"' }))
    expect(mocks.remove).not.toHaveBeenCalled()
    fireEvent.click(desktop().getByRole("button", { name: "Delete list" }))
    expect(mocks.remove).toHaveBeenCalledWith("work")
  })
  it("closes the narrow drawer on navigation and restores focus without changing desktop preference", async () => {
    useUi.setState({ sidebar: "collapsed" })
    render(<Sidebar />)
    const trigger = screen.getByRole("button", { name: "Open navigation" })
    trigger.focus()
    fireEvent.click(trigger)
    const drawer = await screen.findByRole("dialog", { name: "Navigation" })
    fireEvent.click(within(drawer).getByRole("button", { name: "Journal" }))
    expect(useUi.getState()).toMatchObject({ section: "journal", sidebar: "collapsed" })
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Navigation" })).toBeNull())
    await waitFor(() => expect(document.activeElement).toBe(trigger))
  })
  it("moves focus to visible navigation controls across breakpoints", async () => {
    render(<Sidebar />)
    const desktopButton = desktop().getByRole("button", { name: "Collapse sidebar" })
    desktopButton.focus()
    act(() => { mocks.wide = false; mocks.mediaChange({ matches: false }) })
    const trigger = screen.getByRole("button", { name: "Open navigation" })
    expect(document.activeElement).toBe(trigger)
    fireEvent.click(trigger)
    await screen.findByRole("dialog", { name: "Navigation" })
    act(() => { mocks.wide = true; mocks.mediaChange({ matches: true }) })
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Navigation" })).toBeNull())
    await waitFor(() => expect(document.activeElement).toBe(desktopButton))
  })

})
