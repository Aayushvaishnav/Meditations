// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { Task, TimeBlock } from "@/api/types"
import { useUi } from "@/stores/ui"
import { CalendarView } from "./calendar-view"

const mocks = vi.hoisted(() => ({ blocks: [] as TimeBlock[], update: vi.fn(), create: vi.fn(), replace: vi.fn(), exportCalendar: vi.fn() }))
const imported = { source_id: "import", items: [{ id: "imported", uid: "imported", source_id: "import", summary: "Dentist", status: "CONFIRMED", interval: { kind: "date", start: "2026-03-08", end: "2026-03-09" } }], unplaced: [] }
const live = { connection_id: "live", reconciliation: { state: "current", capability: "sync_token", last_synced_at: "2026-03-07T09:00:00", last_error: null }, items: [{ connection_id: "live", id: "live-event", uid: "live-event", summary: "Remote meeting", status: "CONFIRMED", interval: { kind: "date", start: "2026-03-08", end: "2026-03-09" } }], unplaced: [] }
vi.mock("@/hooks/api", () => ({
  useTimeBlocks: () => ({ data: mocks.blocks, isPending: false, isError: false }),
  useUpdateTask: () => ({ mutate: mocks.update }),
  useCreateTask: () => ({ mutate: mocks.create }),
  useReplaceTimeBlock: () => ({ mutate: mocks.replace, isPending: false }),
  useCalendarExport: () => ({ mutate: mocks.exportCalendar, isPending: false, isSuccess: false, isError: false }),
  useImportedCalendars: () => ({ data: [{ id: "import", name: "Personal" }], isSuccess: true }),
  useImportedCalendarOverlay: (selection: { kind: string }) => ({ data: selection.kind === "source" ? imported : undefined, isSuccess: true }),
  useCalendarConnections: () => ({ data: [{ id: "live", calendar_url: "https://calendar.test/work", state: "connected", enabled: true }], isSuccess: true }),
  useInboundOverlay: (selection: { kind: string }) => ({ data: selection.kind === "connection" ? live : undefined, isSuccess: true }),
  useResumeCalendarReconciliation: () => {},
}))

function task(id: string, patch: Partial<Task> = {}): Task {
  return { id, title: id, description: null, list_id: "work", parent_id: null, priority: 2, importance: "unassigned", urgency: "unassigned", status: "todo", due_date: null,
    deadline: { kind: "date", date: "2026-03-08" }, estimated_minutes: null, actual_minutes: 0, recurrence_rule: null,
    recurrence_series_id: null, recurrence_occurrence: null, tags: [], order_index: 0, completed_at: null,
    created_at: "2026-03-01T00:00:00", updated_at: "2026-03-01T00:00:00", ...patch }
}
function block(id: string, owner: string, start: string, end: string): TimeBlock {
  return { id, task_id: owner, kind: "all_day", start_date: start, end_date: end, start_at: null, end_at: null, timezone: null,
    created_at: "2026-03-01T00:00:00", updated_at: "2026-03-01T00:00:00" }
}
function mode(value: "month" | "agenda" | "week" | "multi-day" | "year" | "multi-week") { fireEvent.change(screen.getByLabelText("Calendar mode"), { target: { value } }) }
function view(tasks: Task[] = []) { return <CalendarView tasks={tasks} scope={useUi.getState().scope} search={useUi.getState().search} /> }
function days() { return screen.getAllByRole("button", { name: /^Add task on / }).map(button => button.getAttribute("aria-label") ?? button.textContent) }
function sources() { fireEvent.click(screen.getByText("Calendar sources", { selector: "button" })) }
function selectSources() {
  sources()
  fireEvent.change(screen.getByLabelText("Imported calendar"), { target: { value: "import" } })
  fireEvent.change(screen.getByLabelText("Live calendar"), { target: { value: "live" } })
  sources()
}
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] })
  vi.setSystemTime(new Date(2026, 2, 7, 12))
  useUi.setState({ calendarMode: "month", scope: { kind: "smart", id: "all" }, search: "" })
  mocks.blocks = []
  vi.clearAllMocks()
})
afterEach(() => { cleanup(); vi.useRealTimers() })

describe("CAL-02 calendar modes", () => {
  it("requires fresh source opt-in after remount while retaining the chosen calendar mode", () => {
    const first = render(view())
    sources()
    for (const name of ["Imported calendar", "Live calendar"]) {
      expect((screen.getByLabelText(name) as HTMLSelectElement).value).toBe("")
    }
    sources()
    selectSources()
    mode("agenda")
    expect(screen.getByText("Dentist")).toBeTruthy()
    expect(screen.getByText("Remote meeting")).toBeTruthy()

    first.unmount()
    render(view())
    expect(useUi.getState().calendarMode).toBe("agenda")
    expect(screen.queryByText("Dentist")).toBeNull()
    expect(screen.queryByText("Remote meeting")).toBeNull()
    sources()
    for (const name of ["Imported calendar", "Live calendar"]) {
      expect((screen.getByLabelText(name) as HTMLSelectElement).value).toBe("")
    }
  })

  it("offers all six implemented modes and switches from a six-week month to fourteen days anchored on today", () => {
    render(view())
    expect(days()).toHaveLength(42)
    const selector = screen.getByRole("combobox", { name: "Calendar mode" })
    expect(within(selector).getByRole("option", { name: "Month" }).getAttribute("disabled")).toBeNull()
    expect(within(selector).getByRole("option", { name: "Agenda" }).getAttribute("disabled")).toBeNull()
    expect(within(selector).getAllByRole("option")).toHaveLength(6)
    for (const option of within(selector).getAllByRole("option")) expect((option as HTMLOptionElement).disabled).toBe(false)
    mode("agenda")
    expect(useUi.getState().calendarMode).toBe("agenda")
    expect(days()).toHaveLength(14)
    expect(days()[0]).toBe("Add task on 2026-03-07")
    expect(days().at(-1)).toBe("Add task on 2026-03-20")
  })

  it("moves Agenda by fourteen days across month boundaries and Today resets the shared anchor", () => {
    render(view())
    mode("agenda")
    fireEvent.click(screen.getByRole("button", { name: "Next 14 days" }))
    expect(days()[0]).toBe("Add task on 2026-03-21")
    expect(days().at(-1)).toBe("Add task on 2026-04-03")
    mode("month")
    mode("agenda")
    expect(days()[0]).toBe("Add task on 2026-03-21")
    fireEvent.click(screen.getByRole("button", { name: "Previous 14 days" }))
    expect(days()[0]).toBe("Add task on 2026-03-07")
    fireEvent.click(screen.getByRole("button", { name: "Previous 14 days" }))
    expect(days()[0]).toBe("Add task on 2026-02-21")
    fireEvent.click(screen.getByRole("button", { name: "Today" }))
    expect(days()[0]).toBe("Add task on 2026-03-07")
  })

  it("retains list/search context and selected source overlays through closed controls and mode changes", () => {
    useUi.setState({ scope: { kind: "list", id: "work" }, search: "plan" })
    const tasks = [task("Planning"), task("Tagged", { tags: ["PLAN"] }), task("Home plan", { list_id: "home" }), task("Unrelated")]
    render(view(tasks))
    selectSources()
    for (const target of ["agenda", "month", "week", "multi-day"] as const) {
      mode(target)
      expect(screen.getByRole("button", { name: /^Planning/ })).toBeTruthy()
      expect(screen.getByRole("button", { name: /^Tagged/ })).toBeTruthy()
      expect(screen.queryByRole("button", { name: /^Home plan/ })).toBeNull()
      expect(screen.queryByRole("button", { name: /^Unrelated/ })).toBeNull()
      expect(screen.getByText("Dentist")).toBeTruthy()
      expect(screen.getByText("Remote meeting")).toBeTruthy()
      expect(screen.queryByRole("combobox", { name: "Imported calendar" })).toBeNull()
      sources()
      expect((screen.getByLabelText("Imported calendar") as HTMLSelectElement).value).toBe("import")
      expect((screen.getByLabelText("Live calendar") as HTMLSelectElement).value).toBe("live")
      sources()
    }
    expect(useUi.getState().scope).toEqual({ kind: "list", id: "work" })
    expect(useUi.getState().search).toBe("plan")
  })

  it("labels each Agenda item by its actual kind and keeps external appointments read-only", () => {
    mocks.blocks = [block("planned", "Planning", "2026-03-08", "2026-03-09")]
    render(view([task("Planning")]))
    selectSources()
    mode("agenda")
    const day = within(screen.getByRole("region", { name: "2026-03-08" }))
    for (const label of ["Task deadline", "Work block", "Imported event · read-only", "Live event · read-only"]) {
      expect(day.getByText(label)).toBeTruthy()
    }
    for (const title of ["Dentist", "Remote meeting"]) {
      const details = within(day.getByText(title).parentElement!)
      expect(details.getByText(/Read-only/)).toBeTruthy()
      expect(details.queryAllByRole("button")).toHaveLength(0)
      expect(details.queryAllByRole("textbox")).toHaveLength(0)
    }
    expect(mocks.update).not.toHaveBeenCalled()
    expect(mocks.replace).not.toHaveBeenCalled()
  })

  it.each(["month", "agenda", "week", "multi-day"] as const)("provides a focusable native date action in %s without editing task priority", target => {
    render(view([task("Planning")]))
    mode(target)
    const trigger = target === "agenda"
      ? screen.getByRole("button", { name: "Deadline actions" })
      : screen.getByRole("button", { name: "Add task on 2026-03-08" })
    trigger.focus()
    expect(document.activeElement).toBe(trigger)
    fireEvent.click(trigger)
    const dialog = within(screen.getByRole("dialog"))
    const input = dialog.getByLabelText("Move deadline for Planning") as HTMLInputElement
    expect(input.type).toBe("date")
    input.focus()
    expect(document.activeElement).toBe(input)
    fireEvent.change(input, { target: { value: "2026-03-12" } })
    expect(mocks.update).not.toHaveBeenCalled()
    const submit = dialog.getByRole("button", { name: "Move deadline" })
    submit.focus()
    expect(document.activeElement).toBe(submit)
    fireEvent.submit(input.closest("form")!)
    expect(mocks.update).toHaveBeenCalledExactlyOnceWith({ id: "Planning", patch: { deadline: { kind: "date", date: "2026-03-12" } } })
    expect(dialog.queryByRole("combobox", { name: /priority/i })).toBeNull()
    expect(mocks.replace).not.toHaveBeenCalled()
  })

  it("refreshes surviving multi-day block move drafts after updated data arrives", () => {
    const tasks = [task("Planning")]
    mocks.blocks = [block("spanning", "Planning", "2026-03-07", "2026-03-10")]
    const rendered = render(view(tasks))
    mode("agenda")
    const occurrence = () => within(screen.getByRole("region", { name: "2026-03-08" }))
    fireEvent.change(occurrence().getByLabelText("New start date for Planning block spanning"), { target: { value: "2026-03-15" } })
    mocks.blocks = [{ ...block("spanning", "Planning", "2026-03-08", "2026-03-11"), updated_at: "2026-03-07T12:00:00" }]
    rendered.rerender(view(tasks))
    expect((occurrence().getByLabelText("New start date for Planning block spanning") as HTMLInputElement).value).toBe("2026-03-08")
  })

  it("exports only filtered work blocks overlapping the Agenda range, never deadlines or external appointments", () => {
    useUi.setState({ scope: { kind: "list", id: "work" }, search: "plan" })
    const tasks = [task("Planning"), task("Other plan", { list_id: "home" }), task("Unrelated")]
    mocks.blocks = [block("overlap", "Planning", "2026-03-06", "2026-03-08"), block("last", "Planning", "2026-03-20", "2026-03-21"),
      block("before", "Planning", "2026-03-05", "2026-03-07"), block("after", "Planning", "2026-03-21", "2026-03-22"),
      block("other-list", "Other plan", "2026-03-08", "2026-03-09"), block("other-search", "Unrelated", "2026-03-08", "2026-03-09")]
    render(view(tasks))
    selectSources()
    mode("agenda")
    fireEvent.click(screen.getByText("Export work blocks", { selector: "button" }))
    const panel = within(screen.getByRole("region", { name: "Calendar export" }))
    expect(panel.getAllByRole("checkbox")).toHaveLength(2)
    for (const checkbox of panel.getAllByRole("checkbox")) fireEvent.click(checkbox)
    expect(panel.queryByText("Dentist")).toBeNull()
    expect(panel.queryByText("Remote meeting")).toBeNull()
    fireEvent.click(panel.getByRole("button", { name: "Download .ics" }))
    expect(mocks.exportCalendar).toHaveBeenCalledWith(["overlap", "last"])
  })
})


describe("CAL-03 time-grid integration", () => {
  it("navigates Monday-start weeks and configurable Multi-Day windows without resetting the anchor", () => {
    render(view())
    mode("week")
    expect(days()).toHaveLength(7)
    expect(days()[0]).toBe("Add task on 2026-03-02")
    fireEvent.click(screen.getByRole("button", { name: "Next week" }))
    expect(days()[0]).toBe("Add task on 2026-03-09")
    mode("multi-day")
    expect(days()[0]).toBe("Add task on 2026-03-14")
    expect(days()).toHaveLength(3)
    fireEvent.change(screen.getByLabelText("Multi-Day day count"), { target: { value: "5" } })
    expect(days()).toHaveLength(5)
    fireEvent.click(screen.getByRole("button", { name: "Next 5 days" }))
    expect(days()[0]).toBe("Add task on 2026-03-19")
    mode("week")
    mode("multi-day")
    expect(days()).toHaveLength(5)
    expect(days()[0]).toBe("Add task on 2026-03-19")
    fireEvent.click(screen.getByRole("button", { name: "Today" }))
    expect(days()[0]).toBe("Add task on 2026-03-07")
  })

  it.each(["week", "multi-day"] as const)("moves a block in %s through the date form without changing its task deadline", target => {
    mocks.blocks = [block("planned", "Planning", "2026-03-08", "2026-03-10")]
    render(view([task("Planning")]))
    mode(target)
    fireEvent.click(screen.getByRole("button", { name: "Add task on 2026-03-08" }))
    const dialog = within(screen.getByRole("dialog"))
    fireEvent.change(dialog.getByLabelText("New start date for Planning block planned"), { target: { value: "2026-03-15" } })
    fireEvent.click(dialog.getByRole("button", { name: "Move block" }))
    expect(mocks.replace).toHaveBeenCalledExactlyOnceWith({ id: "planned", input: { kind: "all_day", task_id: "Planning", start_date: "2026-03-15", end_date: "2026-03-17" } })
    expect(mocks.update).not.toHaveBeenCalled()
  })

  it("exports only scoped local blocks overlapping the configurable range", () => {
    mocks.blocks = [block("before", "Planning", "2026-03-06", "2026-03-07"), block("overlap", "Planning", "2026-03-06", "2026-03-08"), block("last", "Planning", "2026-03-09", "2026-03-10"), block("after", "Planning", "2026-03-10", "2026-03-11")]
    render(view([task("Planning")]))
    selectSources()
    mode("multi-day")
    fireEvent.click(screen.getByText("Export work blocks", { selector: "button" }))
    const panel = within(screen.getByRole("region", { name: "Calendar export" }))
    for (const checkbox of panel.getAllByRole("checkbox")) fireEvent.click(checkbox)
    fireEvent.click(panel.getByRole("button", { name: "Download .ics" }))
    expect(mocks.exportCalendar).toHaveBeenCalledWith(["overlap", "last"])
  })
})

describe("CAL-04 annual and Multi-Week integration", () => {
  it("counts filtered local items and selected sources in Year and retains them through Multi-Week and Month", () => {
    useUi.setState({ scope: { kind: "list", id: "work" }, search: "plan" })
    mocks.blocks = [block("planned", "Planning", "2026-03-08", "2026-03-10"), block("hidden", "Home plan", "2026-03-08", "2026-03-09")]
    render(view([task("Planning"), task("Tagged", { tags: ["PLAN"] }), task("Home plan", { list_id: "home" }), task("Unrelated")]))
    mode("year")
    expect(within(screen.getByRole("region", { name: "March 2026" })).getByRole("button", { name: "2026-03-08, 3 items: 2 task deadlines, 1 work blocks, 0 imported events, 0 live events" })).toBeTruthy()
    selectSources()
    fireEvent.click(within(screen.getByRole("region", { name: "March 2026" })).getByRole("button", { name: "2026-03-08, 5 items: 2 task deadlines, 1 work blocks, 1 imported events, 1 live events" }))
    const dialog = within(screen.getByRole("dialog"))
    expect(dialog.getByText("5 items: 2 task deadlines, 1 work blocks, 1 imported events, 1 live events")).toBeTruthy()
    for (const title of ["Planning", "Tagged", "Dentist", "Remote meeting"]) expect(dialog.getAllByText(title).length).toBeGreaterThan(0)
    expect(dialog.queryByText("Home plan")).toBeNull()
    expect(dialog.queryByText("Unrelated")).toBeNull()
    expect(dialog.getAllByText(/Read-only/)).toHaveLength(2)
    fireEvent.click(dialog.getByRole("button", { name: "Close" }))
    expect(within(screen.getByRole("region", { name: "March 2026" })).getByRole("button", { name: "2026-03-09, 1 items: 0 task deadlines, 1 work blocks, 0 imported events, 0 live events" })).toBeTruthy()
    for (const target of ["multi-week", "month"] as const) {
      mode(target)
      expect(screen.getByText("Dentist")).toBeTruthy()
      expect(screen.getByText("Remote meeting")).toBeTruthy()
      expect(screen.queryByRole("button", { name: /^Home plan/ })).toBeNull()
      sources()
      expect((screen.getByLabelText("Imported calendar") as HTMLSelectElement).value).toBe("import")
      expect((screen.getByLabelText("Live calendar") as HTMLSelectElement).value).toBe("live")
      sources()
    }
    expect(useUi.getState().scope).toEqual({ kind: "list", id: "work" })
    expect(useUi.getState().search).toBe("plan")
  })

  it("navigates years and drills the selected month down without losing its anchor", () => {
    render(view())
    mode("year")
    fireEvent.click(screen.getByLabelText("Previous year"))
    expect(screen.getByRole("region", { name: "2025 year overview" })).toBeTruthy()
    fireEvent.click(screen.getByLabelText("Next year"))
    expect(screen.getByRole("region", { name: "2026 year overview" })).toBeTruthy()
    fireEvent.click(within(screen.getByRole("region", { name: "March 2026" })).getByRole("button", { name: "Open March 2026 in Month" }))
    expect(useUi.getState().calendarMode).toBe("month")
    mode("agenda")
    expect(days()[0]).toBe("Add task on 2026-03-07")
  })

  it.each([2, 3, 4, 5, 6])("uses a Monday-start %i-week window while preserving the separate day count and scope", count => {
    useUi.setState({ scope: { kind: "list", id: "work" }, search: "plan" })
    render(view())
    mode("multi-day")
    fireEvent.change(screen.getByLabelText("Multi-Day day count"), { target: { value: "5" } })
    mode("multi-week")
    expect((screen.getByLabelText("Multi-Week week count") as HTMLSelectElement).value).toBe("2")
    expect(days()).toHaveLength(14)
    expect(days()[0]).toBe("Add task on 2026-03-02")
    expect(days().at(-1)).toBe("Add task on 2026-03-15")
    expect(within(screen.getByLabelText("Multi-Week week count")).getAllByRole("option").map(option => (option as HTMLOptionElement).value)).toEqual(["2", "3", "4", "5", "6"])
    fireEvent.change(screen.getByLabelText("Multi-Week week count"), { target: { value: String(count) } })
    expect(days()).toHaveLength(count * 7)
    fireEvent.click(screen.getByRole("button", { name: `Next ${count} weeks` }))
    expect(days()[0]).not.toBe("Add task on 2026-03-02")
    fireEvent.click(screen.getByRole("button", { name: `Previous ${count} weeks` }))
    expect(days()[0]).toBe("Add task on 2026-03-02")
    mode("multi-day")
    expect(days()).toHaveLength(5)
    expect(days()[0]).toBe("Add task on 2026-03-07")
    expect(useUi.getState().scope).toEqual({ kind: "list", id: "work" })
    expect(useUi.getState().search).toBe("plan")
  })

  it.each(["year", "multi-week"] as const)("creates a task with the opened date and active list in %s", target => {
    useUi.setState({ scope: { kind: "list", id: "work" } })
    render(view())
    mode(target)
    const calendar = target === "year" ? within(screen.getByRole("region", { name: "March 2026" })) : screen
    fireEvent.click(calendar.getByRole("button", { name: target === "year" ? /^2026-03-08, 0 items:/ : "Add task on 2026-03-08" }))
    const input = within(screen.getByRole("dialog")).getByLabelText("New task deadline")
    fireEvent.change(input, { target: { value: "New plan" } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(mocks.create).toHaveBeenCalledExactlyOnceWith({ title: "New plan", list_id: "work", deadline: { kind: "date", date: "2026-03-08" } })
  })

  it.each(["year", "multi-week"] as const)("exports only eligible overlapping local blocks in %s", target => {
    useUi.setState({ scope: { kind: "list", id: "work" }, search: "plan" })
    const start = target === "year" ? "2026-01-01" : "2026-03-02"
    const end = target === "year" ? "2027-01-01" : "2026-03-16"
    mocks.blocks = [block("overlap", "Planning", "2025-12-31", "2026-03-03"), block("inside", "Planning", "2026-03-08", "2026-03-09"),
      block("before", "Planning", "2025-12-30", start), block("after", "Planning", end, "2027-01-02"),
      block("other-list", "Home plan", "2026-03-08", "2026-03-09"), block("other-search", "Unrelated", "2026-03-08", "2026-03-09")]
    render(view([task("Planning"), task("Home plan", { list_id: "home" }), task("Unrelated")]))
    selectSources()
    mode(target)
    fireEvent.click(screen.getByText("Export work blocks", { selector: "button" }))
    const panel = within(screen.getByRole("region", { name: "Calendar export" }))
    expect(panel.getAllByRole("checkbox")).toHaveLength(2)
    expect(panel.queryByText("Dentist")).toBeNull()
    expect(panel.queryByText("Remote meeting")).toBeNull()
    for (const checkbox of panel.getAllByRole("checkbox")) fireEvent.click(checkbox)
    fireEvent.click(panel.getByRole("button", { name: "Download .ics" }))
    expect(mocks.exportCalendar).toHaveBeenCalledExactlyOnceWith(["overlap", "inside"])
  })
})
