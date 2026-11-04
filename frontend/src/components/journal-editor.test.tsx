// @vitest-environment jsdom
import { StrictMode } from "react"
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { Editor } from "@tiptap/core"
import { closeHistory } from "@tiptap/pm/history"
import { JournalView } from "./journal-editor"
import { useUi } from "@/stores/ui"

const mocks = vi.hoisted(() => ({
  editor: undefined as Editor | undefined,
  mutate: vi.fn(),
  refetch: vi.fn(),
  entries: {} as Record<string, { raw_markdown: string; mood: number | null; energy: number | null } | null | undefined>,
}))

vi.mock("@tiptap/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tiptap/react")>()
  return { ...actual, useEditor: (...args: Parameters<typeof actual.useEditor>) => {
    const editor = actual.useEditor(...args)
    mocks.editor = editor ?? undefined
    return editor
  } }
})

vi.mock("@/hooks/api", () => ({
  useJournalEntry: (day: string) => ({ data: day in mocks.entries ? mocks.entries[day] : null }),
  useSaveJournal: () => ({ mutate: mocks.mutate }),
  useJournalActivity: () => ({ refetch: mocks.refetch }),
  useJournalDays: () => ({ data: [] }),
  useEditorAssist: () => ({ clear: vi.fn() }),
}))
vi.mock("@/components/daily-review-card", () => ({ DailyReviewCard: () => null }))
vi.mock("@/components/journal-calendar", () => ({ MiniMonth: () => null }))
vi.mock("@/components/journal-calendar-view", () => ({ JournalCalendar: () => null }))

// Keep the real editor and history; stub remote calls and unrelated UI.
function edit(text: string) {
  act(() => {
    const editor = mocks.editor!
    editor.view.dispatch(closeHistory(editor.state.tr))
    editor.commands.insertContentAt({ from: 1, to: editor.state.doc.content.size - 1 }, text)
  })
}

function undo() {
  act(() => { mocks.editor!.commands.undo() })
}

function advance() {
  act(() => vi.advanceTimersByTime(700))
}

function mount({ strict = false, conditional = false } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  for (const [day, entry] of Object.entries(mocks.entries)) client.setQueryData(["journal", day], entry)
  function Harness() {
    const section = useUi((state) => state.section)
    return !conditional || section === "journal" ? <JournalView /> : null
  }
  const tree = () => {
    const content = <QueryClientProvider client={client}><Harness /></QueryClientProvider>
    return strict ? <StrictMode>{content}</StrictMode> : content
  }
  const view = render(tree())
  return { ...view, refresh: () => view.rerender(tree()) }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date(2026, 9, 20, 12))
  mocks.mutate.mockReset()
  mocks.refetch.mockReset()
  mocks.entries = { "2026-10-20": { raw_markdown: "A", mood: null, energy: null } }
  useUi.setState({ section: "journal", journalDay: null })
})

afterEach(() => {
  cleanup()
  act(() => vi.advanceTimersByTime(1))
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe("journal debounced saves", () => {
  it("keeps the editor and frozen pending save through sidebar preference changes", () => {
    mount()
    const editor = mocks.editor
    edit("Draft before collapsing")
    act(() => useUi.getState().setSidebar("collapsed"))
    expect(mocks.editor).toBe(editor)
    expect(document.querySelector(".tiptap")!.textContent).toBe("Draft before collapsing")
    act(() => useUi.getState().setSidebar("expanded"))
    fireEvent.click(screen.getByRole("button", { name: "Next day" }))
    expect(mocks.mutate).toHaveBeenCalledExactlyOnceWith({ day: "2026-10-20", raw_markdown: "Draft before collapsing", mood: null, energy: null })
  })

  it.each(["B", ""])("persists final content after editing to %j and undoing", (text) => {
    mount()
    edit(text)
    undo()
    expect(document.querySelector(".tiptap")!.textContent).toBe("A")
    advance()
    expect(mocks.mutate).toHaveBeenCalledExactlyOnceWith({ day: "2026-10-20", raw_markdown: "A", mood: null, energy: null })
  })

  it("replaces the original deadline when undo occurs partway through the debounce", () => {
    mount()
    edit("B")
    act(() => vi.advanceTimersByTime(400))
    undo()
    act(() => vi.advanceTimersByTime(300))
    expect(mocks.mutate).not.toHaveBeenCalled()
    act(() => vi.advanceTimersByTime(400))
    expect(mocks.mutate).toHaveBeenCalledExactlyOnceWith({ day: "2026-10-20", raw_markdown: "A", mood: null, energy: null })
  })

  it("preserves existing ratings and an explicit rating clear through undo", () => {
    mocks.entries["2026-10-20"] = { raw_markdown: "A", mood: 4, energy: 2 }
    mount()
    edit("B")
    fireEvent.click(screen.getByRole("button", { name: "Mood 4 of 5" }))
    undo()
    advance()
    expect(mocks.mutate).toHaveBeenCalledExactlyOnceWith({ day: "2026-10-20", raw_markdown: "A", mood: null, energy: 2 })
  })

  it.each(["Mood", "Energy"])("retains %s changes when text is undone", (rating) => {
    mount()
    edit("B")
    fireEvent.click(screen.getByRole("button", { name: `${rating} 4 of 5` }))
    undo()
    advance()
    expect(mocks.mutate).toHaveBeenLastCalledWith({ day: "2026-10-20", raw_markdown: "A", mood: rating === "Mood" ? 4 : null, energy: rating === "Energy" ? 4 : null })
  })

  it("saves the clicked rating before refs have rerendered", () => {
    mount()
    fireEvent.click(screen.getByRole("button", { name: "Energy 3 of 5" }))
    advance()
    expect(mocks.mutate).toHaveBeenCalledExactlyOnceWith({ day: "2026-10-20", raw_markdown: "A", mood: null, energy: 3 })
  })

  it("does not save a programmatically loaded entry", () => {
    mount()
    advance()
    expect(mocks.mutate).not.toHaveBeenCalled()
  })

  it("does not create an entry when visiting an empty day", () => {
    mocks.entries["2026-10-20"] = null
    mount()
    advance()
    expect(mocks.mutate).not.toHaveBeenCalled()
  })

  it("flushes final text and ratings to their original day before navigation", () => {
    mocks.entries["2026-10-21"] = { raw_markdown: "Next day", mood: 1, energy: 2 }
    mount()
    edit("B")
    fireEvent.click(screen.getByRole("button", { name: "Mood 4 of 5" }))
    undo()
    fireEvent.click(screen.getByRole("button", { name: "Next day" }))
    advance()
    expect(mocks.mutate).toHaveBeenCalledExactlyOnceWith({ day: "2026-10-20", raw_markdown: "A", mood: 4, energy: null })
    expect(document.querySelector(".tiptap")!.textContent).toBe("Next day")
    edit("Edited next day")
    advance()
    expect(mocks.mutate).toHaveBeenLastCalledWith({ day: "2026-10-21", raw_markdown: "Edited next day", mood: 1, energy: 2 })
  })
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

const activityData = { tasks_done: [{ title: "Completed task" }], focus_minutes: 0, focus_sessions: 0, habits: [] }

describe("journal lifecycle", () => {
  it("loads a delayed initial entry without saving it", () => {
    mocks.entries = { "2026-10-20": undefined }
    const view = mount()
    advance()
    mocks.entries["2026-10-20"] = { raw_markdown: "Arrived", mood: 3, energy: 2 }
    view.refresh()
    expect(document.querySelector(".tiptap")!.textContent).toBe("Arrived")
    advance()
    expect(mocks.mutate).not.toHaveBeenCalled()
  })

  it("does not save the previous entry while the selected day is loading", () => {
    mocks.entries["2026-10-21"] = undefined
    const view = mount()
    fireEvent.click(screen.getByRole("button", { name: "Next day" }))
    fireEvent.click(screen.getByRole("button", { name: "Mood 5 of 5" }))
    expect(document.querySelector(".tiptap")!.getAttribute("contenteditable")).toBe("false")
    expect((screen.getByRole("button", { name: "Mood 5 of 5" }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole("button", { name: "Day activity" }) as HTMLButtonElement).disabled).toBe(true)
    advance()
    expect(mocks.mutate).not.toHaveBeenCalled()
    mocks.entries["2026-10-21"] = { raw_markdown: "Loaded next", mood: 1, energy: 2 }
    view.refresh()
    expect(document.querySelector(".tiptap")!.textContent).toBe("Loaded next")
    expect(document.querySelector(".tiptap")!.getAttribute("contenteditable")).toBe("true")
    edit("After load")
    advance()
    expect(mocks.mutate).toHaveBeenCalledExactlyOnceWith({ day: "2026-10-21", raw_markdown: "After load", mood: 1, energy: 2 })
  })

  it("debounces the latest text and ratings", () => {
    mount()
    edit("First")
    act(() => vi.advanceTimersByTime(400))
    edit("Latest")
    fireEvent.click(screen.getByRole("button", { name: "Mood 5 of 5" }))
    act(() => vi.advanceTimersByTime(300))
    expect(mocks.mutate).not.toHaveBeenCalled()
    advance()
    expect(mocks.mutate).toHaveBeenCalledExactlyOnceWith({ day: "2026-10-20", raw_markdown: "Latest", mood: 5, energy: null })
  })

  it.each(["section", "unmount", "conditional", "strict"])("flushes pending saves on %s leave", (leave) => {
    const view = mount({ strict: leave === "strict", conditional: leave === "conditional" })
    edit("Pending")
    if (leave === "section" || leave === "conditional") act(() => useUi.setState({ section: "tasks" }))
    else view.unmount()
    expect(mocks.mutate).toHaveBeenCalledExactlyOnceWith({ day: "2026-10-20", raw_markdown: "Pending", mood: null, energy: null })
    advance()
    expect(mocks.mutate).toHaveBeenCalledTimes(1)
  })

  it.each(["Today", "external"])("flushes before %s navigation", (navigation) => {
    useUi.setState({ journalDay: "2026-10-19" })
    mount()
    edit("Yesterday")
    fireEvent.click(screen.getByRole("button", { name: "Energy 4 of 5" }))
    if (navigation === "Today") fireEvent.click(screen.getByRole("button", { name: "Today" }))
    else act(() => useUi.setState({ journalDay: "2026-10-21" }))
    expect(mocks.mutate).toHaveBeenCalledExactlyOnceWith({ day: "2026-10-19", raw_markdown: "Yesterday", mood: null, energy: 4 })
    expect(document.querySelector(".tiptap")!.textContent).toBe(navigation === "Today" ? "A" : "")
    edit("Destination")
    advance()
    expect(mocks.mutate).toHaveBeenLastCalledWith({ day: navigation === "Today" ? "2026-10-20" : "2026-10-21", raw_markdown: "Destination", mood: null, energy: null })
  })

  it.each(["day", "day roundtrip", "section", "section roundtrip", "unmount"])("discards activity after %s leave", async (leave) => {
    const result = deferred<{ data: typeof activityData }>()
    mocks.refetch.mockReturnValue(result.promise)
    const view = mount()
    fireEvent.click(screen.getByRole("button", { name: "Day activity" }))
    if (leave.startsWith("day")) {
      fireEvent.click(screen.getByRole("button", { name: "Next day" }))
      if (leave.endsWith("roundtrip")) fireEvent.click(screen.getByRole("button", { name: "Previous day" }))
    } else if (leave.startsWith("section")) {
      act(() => useUi.setState({ section: "tasks" }))
      if (leave.endsWith("roundtrip")) act(() => useUi.setState({ section: "journal" }))
    } else view.unmount()
    await act(async () => { result.resolve({ data: activityData }); await result.promise })
    advance()
    expect(mocks.mutate).not.toHaveBeenCalled()
    expect(document.querySelector(".tiptap")?.textContent ?? "").not.toContain("Completed task")
  })

  it("uses the current day when activity is inserted through the slash extension", async () => {
    mocks.refetch.mockResolvedValue({ data: activityData })
    mount()
    fireEvent.click(screen.getByRole("button", { name: "Next day" }))
    const editor = mocks.editor!
    const extension = editor.extensionManager.extensions.find((item) => item.name === "slashCommands")!
    await act(async () => { await extension.options.onActivity(editor) })
    expect(mocks.refetch).toHaveBeenCalledTimes(1)
    advance()
    expect(mocks.mutate).toHaveBeenCalledWith(expect.objectContaining({ day: "2026-10-21", raw_markdown: expect.stringContaining("Completed task") }))
  })

  it("handles a rejected activity request without changing the entry", async () => {
    mocks.refetch.mockRejectedValue(new Error("Offline"))
    mount()
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Day activity" })) })
    advance()
    expect(mocks.mutate).not.toHaveBeenCalled()
    expect(document.querySelector(".tiptap")!.textContent).toBe("A")
  })

  it("appends activity to same-day edits made while awaiting it", async () => {
    const result = deferred<{ data: typeof activityData }>()
    mocks.refetch.mockReturnValue(result.promise)
    mount()
    fireEvent.click(screen.getByRole("button", { name: "Day activity" }))
    edit("Latest thoughts")
    await act(async () => { result.resolve({ data: activityData }); await result.promise })
    advance()
    expect(mocks.mutate).toHaveBeenLastCalledWith(expect.objectContaining({ day: "2026-10-20", raw_markdown: expect.stringContaining("Latest thoughts") }))
    expect(document.querySelector(".tiptap")!.textContent).toContain("Completed task")
  })
})

// Suggestions resolve asynchronously; stub layout, not the editor or plugin.
async function openSlashMenu(query = "") {
  const editor = mocks.editor!
  vi.spyOn(editor.view, "coordsAtPos").mockReturnValue({ left: 20, right: 20, top: 20, bottom: 40 })
  await act(async () => {
    editor.commands.setTextSelection(editor.state.doc.content.size - 1)
    editor.commands.insertContent(` /${query}`)
  })
  expect((screen.getByRole("listbox") as HTMLElement).hidden).toBe(false)
  return editor
}

describe("journal slash menu lifecycle", () => {
  const originalBounds = HTMLElement.prototype.getBoundingClientRect
  let restoreBounds: () => void

  beforeEach(() => {
    const bounds = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const editor = document.querySelector(".tiptap")
      if (editor && (this === editor || this.contains(editor))) return new DOMRect(10, 10, 900, 600)
      if (editor?.contains(this)) return new DOMRect(20, 20, 100, 20)
      return originalBounds.call(this)
    })
    restoreBounds = () => bounds.mockRestore()
  })

  afterEach(() => restoreBounds())

  it.each(["click", "Enter"])("applies the hovered command once with %s and saves the result", async (activation) => {
    mount()
    const editor = await openSlashMenu("head")
    const textbox = screen.getByRole("textbox", { name: "Journal entry" })
    const menu = screen.getByRole("listbox")
    expect(textbox.getAttribute("aria-controls")).toBe(menu.id)
    const option = screen.getByRole("option", { name: /Heading 2/ })
    fireEvent.pointerMove(option)
    expect(textbox.getAttribute("aria-activedescendant")).toBe(option.id)
    await act(async () => {
      if (activation === "click") fireEvent.click(option)
      else fireEvent.keyDown(textbox, { key: "Enter" })
    })
    expect(screen.queryByRole("listbox")).toBeNull()
    expect(editor.isActive("heading", { level: 2 })).toBe(true)
    expect(editor.getText().trim()).toBe("A")
    advance()
    expect(mocks.mutate).toHaveBeenLastCalledWith(expect.objectContaining({ day: "2026-10-20", raw_markdown: expect.stringMatching(/^## A\s*$/) }))
  })

  it("dismisses with Escape while preserving the query and continued typing", async () => {
    mount()
    const editor = await openSlashMenu("head")
    const text = editor.getText()
    fireEvent.keyDown(editor.view.dom, { key: "Escape" })
    expect(screen.queryByRole("listbox")).toBeNull()
    expect(editor.getText()).toBe(text)
    await act(async () => { editor.commands.insertContent("ing") })
    expect(screen.queryByRole("listbox")).toBeNull()
    expect(editor.getText()).toBe(`${text}ing`)
    advance()
    expect(mocks.mutate).toHaveBeenLastCalledWith(expect.objectContaining({ raw_markdown: expect.stringContaining("/heading") }))
  })

  it("opens a fresh suggestion after Escape", async () => {
    mount()
    const editor = await openSlashMenu("head")
    fireEvent.keyDown(editor.view.dom, { key: "Escape" })
    await act(async () => { editor.commands.insertContent(" /quote") })
    expect((screen.getByRole("listbox") as HTMLElement).hidden).toBe(false)
    expect(screen.getByRole("option", { name: /Quote/ })).toBeTruthy()
    expect(editor.getText()).toContain("/head /quote")
  })

  it("cleans up on day navigation and allows a fresh suggestion", async () => {
    mocks.entries["2026-10-21"] = { raw_markdown: "Next entry", mood: null, energy: null }
    mount()
    await openSlashMenu("head")
    fireEvent.click(screen.getByRole("button", { name: "Next day" }))
    expect(screen.queryByRole("listbox")).toBeNull()
    expect(mocks.editor!.getText()).toBe("Next entry")
    expect(mocks.mutate).toHaveBeenLastCalledWith(expect.objectContaining({ day: "2026-10-20", raw_markdown: expect.stringContaining("/head") }))
    await openSlashMenu("quote")
    expect(screen.getAllByRole("listbox")).toHaveLength(1)
    expect(screen.getByRole("option", { name: /Quote/ })).toBeTruthy()
  })

  it("cleans up on section changes without losing text or restoring a stale popup", async () => {
    mount()
    const editor = await openSlashMenu("head")
    const text = editor.getText()
    act(() => useUi.setState({ section: "tasks" }))
    expect(screen.queryByRole("listbox")).toBeNull()
    expect(editor.getText()).toBe(text)
    act(() => useUi.setState({ section: "journal" }))
    expect(screen.queryByRole("listbox")).toBeNull()
    await act(async () => { editor.commands.insertContent("ing") })
    expect(screen.queryByRole("listbox")).toBeNull()
    expect(editor.getText()).toBe(`${text}ing`)
  })

  it.each(["destroy", "unmount"])("removes the popup on editor %s", async (leave) => {
    const view = mount()
    const editor = await openSlashMenu("head")
    if (leave === "destroy") act(() => editor.destroy())
    else {
      view.unmount()
      act(() => vi.advanceTimersByTime(1))
    }
    expect(editor.isDestroyed).toBe(true)
    expect(screen.queryByRole("listbox")).toBeNull()
    expect(document.querySelector(".slash-menu")).toBeNull()
    await act(async () => { vi.advanceTimersByTime(700) })
    expect(screen.queryByRole("listbox")).toBeNull()
  })
})
