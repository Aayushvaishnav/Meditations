// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import type { Editor } from "@tiptap/core"
import { JournalView } from "./journal-editor"
import { useUi } from "@/stores/ui"

const mocks = vi.hoisted(() => ({ mutate: vi.fn(), editor: undefined as Editor | undefined }))
vi.mock("@tiptap/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tiptap/react")>()
  return { ...actual, useEditor: (...args: Parameters<typeof actual.useEditor>) => {
    const editor = actual.useEditor(...args)
    mocks.editor = editor ?? undefined
    return editor
  } }
})
vi.mock("@/hooks/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/hooks/api")>(),
  useSaveJournal: () => ({ mutate: mocks.mutate }),
  useJournalActivity: () => ({ refetch: vi.fn() }),
  useJournalDays: () => ({ data: [] }),
  useEditorAssist: () => ({ clear: vi.fn(), pending: false, text: "", error: null }),
}))
vi.mock("@/components/daily-review-card", () => ({ DailyReviewCard: () => null }))
vi.mock("@/components/journal-calendar", () => ({ MiniMonth: () => null }))
vi.mock("@/components/journal-calendar-view", () => ({ JournalCalendar: () => null }))

let client: QueryClient
const fetchMock = vi.fn<typeof fetch>()
const response = (status: number, markdown = "Recovered entry") => new Response(JSON.stringify(status === 200
  ? { raw_markdown: markdown, mood: null, energy: null, tasks_done: 0, tasks_planned: 0, hours_deep_work: 0 }
  : { detail: "Unavailable" }), { status, headers: { "Content-Type": "application/json" } })
function mount() {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><JournalView /></QueryClientProvider>)
}
const editor = () => screen.getByRole("textbox", { name: "Journal entry" })
const main = () => document.querySelector("main")!

beforeEach(() => {
  mocks.mutate.mockReset()
  fetchMock.mockReset()
  vi.stubGlobal("fetch", fetchMock)
  useUi.setState({ section: "journal", journalDay: "2026-10-20" })
})
afterEach(() => { cleanup(); client.clear(); vi.unstubAllGlobals() })

it("announces pending and settled failure, stays read-only, and retries the selected day without saving", async () => {
  let resolve!: (value: Response) => void
  fetchMock.mockImplementationOnce(() => new Promise((done) => { resolve = done }))
  mount()
  expect(screen.getByRole("status", { name: "Loading journal entry" })).toBeTruthy()
  expect(editor().getAttribute("contenteditable")).toBe("false")
  await act(async () => resolve(response(500)))
  expect((await screen.findByRole("alert")).textContent).toContain("Couldn't load journal entry")
  expect(main().getAttribute("aria-busy")).toBe("false")
  expect(editor().getAttribute("contenteditable")).toBe("false")
  expect((screen.getByRole("button", { name: "Mood 3 of 5" }) as HTMLButtonElement).disabled).toBe(true)
  fetchMock.mockImplementationOnce(() => new Promise((done) => { resolve = done }))
  fireEvent.click(screen.getByRole("button", { name: "Retry loading entry" }))
  expect(await screen.findByRole("status", { name: "Loading journal entry" })).toBeTruthy()
  await act(async () => resolve(response(200)))
  await waitFor(() => expect(editor().getAttribute("contenteditable")).toBe("true"))
  expect(editor().textContent).toContain("Recovered entry")
  expect(screen.queryByRole("alert")).toBeNull()
  expect(fetchMock.mock.calls.at(-1)![0]).toContain("/journal/2026-10-20")
  expect(mocks.mutate).not.toHaveBeenCalled()
})

it("treats a 404 as a loaded empty day, not an error or a save", async () => {
  fetchMock.mockResolvedValue(response(404))
  mount()
  await waitFor(() => expect(editor().getAttribute("contenteditable")).toBe("true"))
  expect(editor().textContent).toBe("")
  expect(screen.queryByRole("alert")).toBeNull()
  expect(mocks.mutate).not.toHaveBeenCalled()
})

it("keeps loaded content editable after a background refetch fails", async () => {
  fetchMock.mockResolvedValueOnce(response(200)).mockResolvedValue(response(500))
  mount()
  await waitFor(() => expect(editor().getAttribute("contenteditable")).toBe("true"))
  act(() => { mocks.editor!.commands.setContent("Unsaved draft", { emitUpdate: true }) })
  await act(async () => { await client.refetchQueries({ queryKey: ["journal", "2026-10-20"] }) })
  expect(client.getQueryState(["journal", "2026-10-20"])?.status).toBe("error")
  expect(editor().getAttribute("contenteditable")).toBe("true")
  expect(editor().textContent).toContain("Unsaved draft")
  expect(screen.queryByRole("alert")).toBeNull()
  expect(main().getAttribute("aria-busy")).toBe("false")
  expect(mocks.mutate).not.toHaveBeenCalled()
})

it("recovers a failed next day in that day's context, not the previous entry", async () => {
  fetchMock.mockResolvedValueOnce(response(200, "Previous day")).mockResolvedValue(response(500))
  mount()
  await waitFor(() => expect(editor().getAttribute("contenteditable")).toBe("true"))
  fireEvent.click(screen.getByRole("button", { name: "Next day" }))
  await screen.findByRole("alert")
  expect(editor().getAttribute("contenteditable")).toBe("false")
  fetchMock.mockResolvedValue(response(200, "Next day recovered"))
  fireEvent.click(screen.getByRole("button", { name: "Retry loading entry" }))
  await waitFor(() => expect(editor().textContent).toContain("Next day recovered"))
  expect(fetchMock.mock.calls.at(-1)![0]).toContain("/journal/2026-10-21")
  expect(mocks.mutate).not.toHaveBeenCalled()
})
