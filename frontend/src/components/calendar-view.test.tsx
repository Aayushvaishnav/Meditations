// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react"
import { useDraggable, type DragEndEvent } from "@dnd-kit/core"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { Task, TimeBlock } from "@/api/types"
import { deadlineFromLegacy } from "@/lib/task-deadlines"
import { useUi } from "@/stores/ui"
import App from "@/App"

const mocks = vi.hoisted(() => ({ tasks: [] as Task[], blocks: [] as TimeBlock[], exportCalendar: vi.fn(), blocksPending: false, blocksError: false, replacePending: false, replace: vi.fn(), refetch: vi.fn(), create: vi.fn(), update: vi.fn(), dragEnd: (_event: DragEndEvent) => {} }))
vi.mock("@/hooks/api", () => ({
  useCalendarConnections: () => ({ data: [], isSuccess: true }),
  useInboundOverlay: () => ({ data: undefined }),
  useResumeCalendarReconciliation: () => {},
  useImportedCalendars: () => ({ data: [], isSuccess: true }),
  useImportedCalendarOverlay: () => ({ data: undefined }),
  useCalendarExport: () => ({ mutate: mocks.exportCalendar, isPending: false, isSuccess: false, isError: false }),
  useTimeBlocks: () => ({ data: mocks.blocks, isPending: mocks.blocksPending, isError: mocks.blocksError, refetch: mocks.refetch }),
  useReplaceTimeBlock: () => ({ mutate: mocks.replace, isPending: mocks.replacePending }),
  useTasks: () => ({ data: mocks.tasks }), useLists: () => ({ data: [] }),
  useCreateTask: () => ({ mutate: mocks.create }), useUpdateTask: () => ({ mutate: mocks.update }),
}))
vi.mock("@dnd-kit/core", () => ({
  DndContext: ({ children, onDragEnd }: { children: ReactNode; onDragEnd: typeof mocks.dragEnd }) => { mocks.dragEnd = onDragEnd; return children },
  PointerSensor: class {}, useSensor: vi.fn(), useSensors: vi.fn(),
  useDraggable: vi.fn(() => ({ attributes: {}, listeners: {}, setNodeRef: vi.fn(), isDragging: false })),
  useDroppable: () => ({ setNodeRef: vi.fn(), isOver: false }),
}))
vi.mock("@/components/focus-timer", () => ({ FocusTimer: () => null }))
vi.mock("@/components/header", () => ({ Header: () => null }))
vi.mock("@/components/journal-editor", () => ({ JournalView: () => null }))
vi.mock("@/components/briefing-card", () => ({ BriefingCard: () => null }))
vi.mock("@/components/command-palette", () => ({ CommandPalette: () => null }))
vi.mock("@/components/kanban-board", () => ({ KanbanBoard: () => null }))
vi.mock("@/components/quick-add", () => ({ QuickAdd: () => null }))
vi.mock("@/components/insights", () => ({ InsightsView: () => null }))
vi.mock("@/components/second-brain", () => ({ SecondBrain: () => null }))
vi.mock("@/components/settings", () => ({ SettingsView: () => null }))
vi.mock("@/components/sidebar", () => ({ Sidebar: () => null }))
vi.mock("@/components/task-sections", () => ({ TaskSections: () => null }))
vi.mock("@/components/skeletons", () => ({ KanbanSkeleton: () => null, TaskListSkeleton: () => null }))

function task(id: string, patch: Partial<Task> = {}): Task {
  return { id, title: id, description: null, list_id: null, parent_id: null, priority: 0, importance: "unassigned", urgency: "unassigned", status: "todo", due_date: new Date(2026, 2, 8, 9).toISOString(),
    deadline: deadlineFromLegacy(patch.due_date !== undefined ? patch.due_date : new Date(2026, 2, 8, 9).toISOString()),
    estimated_minutes: null, actual_minutes: 0, recurrence_rule: null, recurrence_series_id: null, recurrence_occurrence: null,
    tags: [], order_index: 0, completed_at: null, created_at: "2026-03-01T00:00:00", updated_at: "2026-03-01T00:00:00", ...patch }
}
function cell(day: string) {
  return within(screen.getByRole("button", { name: `Add task on ${day}` }).parentElement!.parentElement!)
}
function drop(id: string, target: Date | undefined, type = "day") {
  act(() => mocks.dragEnd({ active: { id }, over: target ? { data: { current: { type, date: target } } } : null } as DragEndEvent))
}
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] })
  vi.setSystemTime(new Date(2026, 2, 7, 12))
  useUi.setState({ section: "tasks", view: "calendar", scope: { kind: "smart", id: "all" }, search: "" })
  mocks.tasks = []
  mocks.blocks = []
  mocks.blocksPending = false
  mocks.blocksError = false
  mocks.replacePending = false
  vi.clearAllMocks()
})
afterEach(() => { cleanup(); vi.useRealTimers() })

describe("calendar task context", () => {
  it("follows selected list and title/tag search through the application", async () => {
    mocks.tasks = [task("Planning", { list_id: "work" }), task("Other", { list_id: "home" }), task("Review", { list_id: "work", tags: ["PLAN"] })]
    useUi.setState({ scope: { kind: "list", id: "work" }, search: "plan" })
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    expect(screen.getByRole("button", { name: /^Planning/ })).toBeTruthy()
    expect(screen.getByRole("button", { name: /^Review/ })).toBeTruthy()
    expect(screen.queryByRole("button", { name: /^Other/ })).toBeNull()
    act(() => useUi.getState().setSearch("other"))
    expect(screen.queryByRole("button", { name: /^Planning/ })).toBeNull()
    expect(screen.queryByRole("button", { name: /^Other/ })).toBeNull()
  })

  it.each([
    { scope: "today", visible: ["overdue", "today"] },
    { scope: "overdue", visible: ["overdue"] },
    { scope: "upcoming", visible: ["tomorrow", "future"] },
    { scope: "all", visible: ["overdue", "today", "tomorrow", "future"] },
    { scope: "completed", visible: ["done"] },
  ] as const)("matches $scope smart scope and excludes canceled tasks", async ({ scope, visible }) => {
    mocks.tasks = [
      task("overdue", { due_date: new Date(2026, 2, 6, 23, 59).toISOString() }),
      task("today", { due_date: new Date(2026, 2, 7, 0).toISOString() }),
      task("tomorrow"), task("future", { due_date: new Date(2026, 2, 12, 9).toISOString() }),
      task("done", { status: "completed" }), task("canceled", { status: "canceled" }), task("undated", { due_date: null }),
    ]
    useUi.setState({ scope: { kind: "smart", id: scope } })
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    for (const id of ["overdue", "today", "tomorrow", "future", "done", "canceled", "undated"]) {
      expect(screen.queryByRole("button", { name: new RegExp(`^${id}`) }) !== null, id).toBe((visible as readonly string[]).includes(id))
    }
  })

  it("creates on the selected local date in the selected list", async () => {
    useUi.setState({ scope: { kind: "list", id: "work" } })
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    fireEvent.click(screen.getByRole("button", { name: "Add task on 2026-03-08" }))
    const input = screen.getByRole("textbox")
    fireEvent.change(input, { target: { value: "  New task  " } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(mocks.create).toHaveBeenCalledWith({ title: "New task", list_id: "work", deadline: { kind: "date", date: "2026-03-08" } })
    expect((input as HTMLInputElement).value).toBe("")
  })

  it("creates an unassigned task from a smart scope and ignores blank titles", async () => {
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    fireEvent.click(screen.getByRole("button", { name: "Add task on 2026-03-08" }))
    const input = screen.getByRole("textbox")
    fireEvent.change(input, { target: { value: "  " } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(mocks.create).not.toHaveBeenCalled()
    fireEvent.change(input, { target: { value: "New task" } })
    fireEvent.keyDown(input, { key: "Enter" })
    expect(mocks.create).toHaveBeenCalledWith({ title: "New task", list_id: null, deadline: { kind: "date", date: "2026-03-08" } })
  })
})

describe("calendar dates and rescheduling", () => {
  it("groups naive UTC instants by local date and sorts by time", async () => {
    mocks.tasks = [task("Late", { due_date: new Date(2026, 2, 8, 23, 59).toISOString().slice(0, -1) }),
      task("Early", { due_date: new Date(2026, 2, 8, 0, 1).toISOString().slice(0, -1) }),
      task("Next day", { due_date: new Date(2026, 2, 9, 0).toISOString().slice(0, -1) }), task("Invalid", { due_date: "invalid" })]
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    expect(cell("2026-03-08").getAllByRole("button").slice(1).map(button => button.textContent)).toEqual([
      expect.stringContaining("Early"), expect.stringContaining("Late"),
    ])
    expect(cell("2026-03-09").getByRole("button", { name: /^Next day/ })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Invalid" })).toBeNull()
  })

  it.each([
    { month: 2, from: 7, to: 8, hour: 9, minute: 15 },
    { month: 9, from: 31, to: 1, hour: 9, minute: 15 },
    { month: 9, from: 31, to: 1, hour: 1, minute: 30 },
    { month: 2, from: 7, to: 8, hour: 2, minute: 30 },
  ])("preserves local clock intent across calendar moves: %j", async ({ month, from, to, hour, minute }) => {
    const source = new Date(2026, month, from, hour, minute, 42, 123)
    const target = new Date(2026, to === 1 ? month + 1 : month, to)
    mocks.tasks = [task("Move", { due_date: source.toISOString() })]
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    drop("Move", target)
    const expected = new Date(target.getFullYear(), target.getMonth(), target.getDate(), hour, minute, 42, 123)
    expect(mocks.update).toHaveBeenCalledWith({ id: "Move", patch: { deadline: { kind: "timed", at: expected.toISOString() } } })
  })

  it("ignores canceled drops, other targets, unknown tasks, unscheduled tasks and same-day moves", async () => {
    mocks.tasks = [task("Move"), task("Undated", { due_date: null })]
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    drop("Move", undefined)
    drop("Move", new Date(2026, 2, 10), "other")
    drop("missing", new Date(2026, 2, 10))
    drop("Undated", new Date(2026, 2, 10))
    drop("Move", new Date(2026, 2, 8))
    expect(mocks.update).not.toHaveBeenCalled()
  })

  it("removes a task date from the selected day's dialog", async () => {
    mocks.tasks = [task("Scheduled")]
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    fireEvent.click(screen.getByRole("button", { name: "Add task on 2026-03-08" }))
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "clear deadline" }))
    expect(mocks.update).toHaveBeenCalledWith({ id: "Scheduled", patch: { deadline: { kind: "none" } } })
  })

  it("navigates year boundaries and returns to today's month", async () => {
    vi.setSystemTime(new Date(2026, 11, 31, 12))
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    fireEvent.click(screen.getByRole("button", { name: "Next month" }))
    expect(screen.getByRole("button", { name: "Add task on 2027-01-31" })).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Previous month" }))
    expect(screen.getByRole("button", { name: "Add task on 2026-12-01" })).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Previous month" }))
    fireEvent.click(screen.getByRole("button", { name: "Today" }))
    expect(screen.getByRole("button", { name: "Add task on 2026-12-31" })).toBeTruthy()
  })
})

describe("explicit deadline intent", () => {
  it("keeps date-only labels on the chosen day and shows timed 09:00 explicitly", async () => {
    mocks.tasks = [
      task("Date only", { due_date: null, deadline: { kind: "date", date: "2026-03-08" } }),
      task("Timed", { due_date: new Date(2026, 2, 8, 9).toISOString() }),
    ]
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    const buttons = cell("2026-03-08").getAllByRole("button").slice(1)
    expect(buttons.map(button => button.textContent)).toEqual([
      "Date onlyDue", expect.stringContaining("Timed"),
    ])
    const time = new Date(2026, 2, 8, 9).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
    expect(buttons[1].textContent).toContain(time)
  })

  it("moves a date-only deadline without inventing a time or a work block", async () => {
    mocks.tasks = [task("Date only", { due_date: null, deadline: { kind: "date", date: "2026-03-08" } })]
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    drop("Date only", new Date(2026, 2, 10))
    expect(mocks.update).toHaveBeenCalledWith({ id: "Date only", patch: { deadline: { kind: "date", date: "2026-03-10" } } })
  })
})

function allDayBlock(id: string, owner: string): Extract<TimeBlock, { kind: "all_day" }> {
  return { id, task_id: owner, kind: "all_day", start_date: "2026-03-08", end_date: "2026-03-10", start_at: null, end_at: null, timezone: null,
    created_at: "2026-03-01T00:00:00", updated_at: "2026-03-01T00:00:00" }
}
function timedBlock(id: string, owner: string, start: Date, end: Date): TimeBlock {
  return { id, task_id: owner, kind: "timed", start_at: start.toISOString(), end_at: end.toISOString(), timezone: "Asia/Kolkata",
    start_date: null, end_date: null, created_at: "2026-03-01T00:00:00", updated_at: "2026-03-01T00:00:00" }
}
function dropBlock(id: string, day: string, target: Date) {
  act(() => mocks.dragEnd({ active: { id: `block:${id}`, data: { current: { type: "calendar-block", blockId: id, day } } },
    over: { data: { current: { type: "day", date: target } } } } as unknown as DragEndEvent))
}

describe("calendar work blocks", () => {
  it("shows multiple timed and all-day blocks independently of deadlines, with exclusive end occupancy", async () => {
    mocks.tasks = [task("Owner", { due_date: null }), task("Due", { deadline: { kind: "date", date: "2026-03-12" } })]
    mocks.blocks = [allDayBlock("days", "Owner"),
      timedBlock("night", "Due", new Date(2026, 2, 8, 23), new Date(2026, 2, 9, 1)),
      timedBlock("midnight", "Owner", new Date(2026, 2, 8, 22), new Date(2026, 2, 9, 0))]
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    expect(cell("2026-03-08").getAllByRole("button", { name: /work block/ })).toHaveLength(3)
    expect(cell("2026-03-09").getAllByRole("button", { name: /work block/ })).toHaveLength(2)
    expect(cell("2026-03-10").queryByRole("button", { name: /work block/ })).toBeNull()
    expect(cell("2026-03-08").queryByRole("button", { name: /DueDue/ })).toBeNull()
    expect(cell("2026-03-12").getByRole("button", { name: /DueDue/ })).toBeTruthy()
  })

  it("applies list, title/tag search and terminal selection through block owners", async () => {
    mocks.tasks = [task("Planning", { list_id: "work" }), task("Tagged", { list_id: "work", tags: ["PLAN"] }),
      task("Other", { list_id: "home" }), task("Done", { status: "completed" }), task("Canceled", { status: "canceled" })]
    mocks.blocks = mocks.tasks.map(owner => allDayBlock(owner.id, owner.id))
    useUi.setState({ scope: { kind: "list", id: "work" }, search: "plan" })
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    expect(cell("2026-03-08").getAllByRole("button", { name: /work block/ }).map(button => button.getAttribute("aria-label"))).toEqual([
      expect.stringContaining("Planning"), expect.stringContaining("Tagged"),
    ])
    act(() => useUi.setState({ scope: { kind: "smart", id: "completed" }, search: "" }))
    expect(cell("2026-03-08").getAllByRole("button", { name: /work block/ })).toHaveLength(1)
    expect(cell("2026-03-08").getByRole("button", { name: /Done, work block/ })).toBeTruthy()
  })

  it("fully replaces a dragged timed block, preserving duration and leaving the deadline alone", async () => {
    mocks.tasks = [task("Owner")]
    mocks.blocks = [timedBlock("timed", "Owner", new Date(2026, 2, 8, 9, 15), new Date(2026, 2, 8, 10, 45))]
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    dropBlock("timed", "2026-03-08", new Date(2026, 2, 10))
    expect(mocks.replace).toHaveBeenCalledExactlyOnceWith({ id: "timed", input: { kind: "timed", task_id: "Owner", timezone: "Asia/Kolkata",
      start_at: new Date(2026, 2, 10, 9, 15).toISOString(), end_at: new Date(2026, 2, 10, 10, 45).toISOString() } })
    expect(mocks.update).not.toHaveBeenCalled()
  })

  it("uses continuation drag delta while keeping all-day blocks date-only", async () => {
    mocks.tasks = [task("Owner")]
    mocks.blocks = [allDayBlock("days", "Owner")]
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    dropBlock("days", "2026-03-09", new Date(2026, 2, 12))
    expect(mocks.replace).toHaveBeenCalledExactlyOnceWith({ id: "days", input: { kind: "all_day", task_id: "Owner", start_date: "2026-03-11", end_date: "2026-03-13" } })
    expect(mocks.update).not.toHaveBeenCalled()
  })

  it("offers a focusable date input and Move block action without dragging", async () => {
    mocks.tasks = [task("Owner", { due_date: null })]
    mocks.blocks = [allDayBlock("days", "Owner")]
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    fireEvent.click(cell("2026-03-08").getByRole("button", { name: /Owner, work block/ }))
    const dialog = within(screen.getByRole("dialog"))
    const input = dialog.getByLabelText("New start date for Owner block days")
    input.focus()
    expect(document.activeElement).toBe(input)
    expect((dialog.getByRole("button", { name: "Move block" }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(input, { target: { value: "2026-03-15" } })
    fireEvent.click(dialog.getByRole("button", { name: "Move block" }))
    expect(mocks.replace).toHaveBeenCalledExactlyOnceWith({ id: "days", input: { kind: "all_day", task_id: "Owner", start_date: "2026-03-15", end_date: "2026-03-17" } })
    expect(mocks.update).not.toHaveBeenCalled()
  })

  it("disables block chips, dialog moves and drag changes during replacement", async () => {
    mocks.tasks = [task("Owner")]
    mocks.blocks = [allDayBlock("days", "Owner")]
    mocks.replacePending = true
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    expect((cell("2026-03-08").getByRole("button", { name: /Owner, work block/ }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole("button", { name: "Add task on 2026-03-08" }))
    const dialog = within(screen.getByRole("dialog"))
    fireEvent.change(dialog.getByLabelText("New start date for Owner block days"), { target: { value: "2026-03-15" } })
    const move = dialog.getByRole("button", { name: "Move block" }) as HTMLButtonElement
    expect(move.disabled).toBe(true)
    fireEvent.click(move)
    dropBlock("days", "2026-03-08", new Date(2026, 2, 15))
    expect(mocks.replace).not.toHaveBeenCalled()
  })

  it("shows query loading and retries block query errors", async () => {
    mocks.blocksPending = true
    let view!: ReturnType<typeof render>
    await act(async () => { view = render(<App />); await import("@/components/calendar-view") })
    expect(screen.getByRole("status")).toBeTruthy()
    mocks.blocksPending = false
    mocks.blocksError = true
    view.rerender(<App />)
    fireEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: "Retry" }))
    expect(mocks.refetch).toHaveBeenCalledOnce()
  })
})


it("registers distinct drag identities for each continuation while retaining block identity", async () => {
  mocks.tasks = [task("Owner")]
  mocks.blocks = [{ id: "span", task_id: "Owner", kind: "all_day", start_date: "2026-03-07", end_date: "2026-03-10", timezone: null, start_at: null, end_at: null, created_at: "2026-03-01T00:00:00", updated_at: "2026-03-01T00:00:00" }]
  await act(async () => { render(<App />); await import("@/components/calendar-view") })
  const segments = vi.mocked(useDraggable).mock.calls.map(([options]) => options).filter(options => options.data?.blockId === "span")
  expect(segments).toHaveLength(3)
  expect(new Set(segments.map(segment => segment.id)).size).toBe(3)
  expect(segments.map(segment => segment.data?.day)).toEqual(["2026-03-07", "2026-03-08", "2026-03-09"])
})


describe("calendar export context", () => {
  it("offers only month-overlapping blocks from matching owners, without deadlines or spillover days", async () => {
    mocks.tasks = [task("Planning", { list_id: "work" }), task("Other", { list_id: "home" }), task("Deadline only", { list_id: "work" })]
    mocks.blocks = [allDayBlock("inside", "Planning"),
      { ...allDayBlock("outside", "Planning"), start_date: "2026-04-01", end_date: "2026-04-02" },
      { ...allDayBlock("overlap", "Planning"), start_date: "2026-02-28", end_date: "2026-03-02" },
      allDayBlock("hidden", "Other")]
    useUi.setState({ scope: { kind: "list", id: "work" }, search: "" })
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    fireEvent.click(screen.getByRole("button", { name: "Export work blocks" }))
    const panel = within(screen.getByRole("region", { name: "Calendar export" }))
    expect(panel.getAllByRole("checkbox")).toHaveLength(2)
    expect(panel.queryByText("Deadline only")).toBeNull()
    panel.getAllByRole("checkbox").forEach(checkbox => fireEvent.click(checkbox))
    fireEvent.click(panel.getByRole("button", { name: "Download .ics" }))
    expect(mocks.exportCalendar).toHaveBeenCalledExactlyOnceWith(["inside", "overlap"])
  })

  it.each(["month", "scope", "search"])("clears opt-in selection when %s changes", async change => {
    mocks.tasks = [task("Owner")]
    mocks.blocks = [allDayBlock("block", "Owner")]
    await act(async () => { render(<App />); await import("@/components/calendar-view") })
    fireEvent.click(screen.getByRole("button", { name: "Export work blocks" }))
    fireEvent.click(screen.getByRole("checkbox"))
    if (change === "month") fireEvent.click(screen.getByRole("button", { name: "Next month" }))
    else act(() => useUi.setState(change === "scope" ? { scope: { kind: "smart", id: "completed" } } : { search: "owner" }))
    expect(screen.queryByRole("region", { name: "Calendar export" })).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "Export work blocks" }))
    expect(screen.getByRole("button", { name: "Download .ics" }).hasAttribute("disabled")).toBe(true)
    expect(mocks.exportCalendar).not.toHaveBeenCalled()
  })
})
