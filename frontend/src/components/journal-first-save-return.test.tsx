// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import type { Editor } from "@tiptap/core"
import { JournalView } from "./journal-editor"
import { useUi } from "@/stores/ui"

const captured = vi.hoisted(() => ({ editor: undefined as Editor | undefined }))
vi.mock("@tiptap/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tiptap/react")>()
  return { ...actual, useEditor: (...args: Parameters<typeof actual.useEditor>) => {
    const editor = actual.useEditor(...args)
    captured.editor = editor ?? undefined
    return editor
  } }
})
vi.mock("@/hooks/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/hooks/api")>(),
  useJournalActivity: () => ({ refetch: vi.fn() }),
  useJournalDays: () => ({ data: [] }),
  useEditorAssist: () => ({ clear: vi.fn(), pending: false, text: "", error: null }),
}))
vi.mock("@/components/daily-review-card", () => ({ DailyReviewCard: () => null }))
vi.mock("@/components/journal-calendar", () => ({ MiniMonth: () => null }))
vi.mock("@/components/journal-calendar-view", () => ({ JournalCalendar: () => null }))

let client: QueryClient
const day = "2026-10-20"
const text = "First saved **bold** entry"
const entry = (raw_markdown: string) => ({ raw_markdown, mood: null, energy: null })
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
})
const textbox = () => screen.getByRole("textbox", { name: "Journal entry" })
beforeEach(() => {
  useUi.setState({ section: "journal", journalDay: day })
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
})
afterEach(() => { cleanup(); client.clear(); vi.unstubAllGlobals() })

// Exercise navigation with real query/mutation hooks and a real editor.
it.each([
  { existing: false, pendingWrite: false },
  { existing: true, pendingWrite: false },
  { existing: false, pendingWrite: true },
])("restores the saved document on return; existing=$existing pendingWrite=$pendingWrite", async ({ existing, pendingWrite }) => {
  let finishWrite!: () => void
  let stored = existing ? entry("Original entry") : null
  let finishReturn!: () => void
  let originalGets = 0
  const fetchMock = vi.fn<typeof fetch>(async (url, init) => {
    const path = String(url)
    if (init?.method === "PUT") {
      stored = JSON.parse(String(init.body))
      if (pendingWrite) await new Promise<void>((resolve) => { finishWrite = resolve })
      return json({ saved: true })
    }
    if (path.endsWith(`/journal/${day}`)) {
      originalGets += 1
      if (originalGets === 2) await new Promise<void>((resolve) => { finishReturn = resolve })
      return stored ? json({ ...stored, date: day, tasks_done: 2, tasks_planned: 3, hours_deep_work: 1 }) : json({ detail: "Not found" }, 404)
    }
    return json({ detail: "Not found" }, 404)
  })
  vi.stubGlobal("fetch", fetchMock)
  render(<QueryClientProvider client={client}><JournalView /></QueryClientProvider>)
  await waitFor(() => expect(textbox().getAttribute("contenteditable")).toBe("true"))
  act(() => { captured.editor!.commands.setContent(text) })
  expect(screen.getByText("Unsaved changes")).toBeTruthy()
  // Navigation flushes before the 700 ms debounce, matching QA-07.
  fireEvent.click(screen.getByRole("button", { name: "Next day" }))
  await waitFor(() => expect(stored?.raw_markdown).toBe(text))
  await waitFor(() => expect(textbox().textContent).toBe(""))
  await waitFor(() => expect(client.getMutationCache().getAll()[0]?.state.status).toBe(pendingWrite ? "pending" : "success"))
  expect(client.getQueryData(["journal", day])).toEqual(expect.objectContaining(entry(text)))
  fireEvent.click(screen.getByRole("button", { name: "Previous day" }))
  await waitFor(() => expect(originalGets).toBe(2))
  await waitFor(() => expect(textbox().getAttribute("contenteditable")).toBe("true"))
  expect(textbox().textContent).toBe("First saved bold entry")
  await act(async () => { finishReturn() })
  await waitFor(() => expect(client.getQueryData(["journal", day])).toEqual(expect.objectContaining(entry(text))))
  expect(screen.getByText(/2\/3 tasks/)).toBeTruthy()
  // Refetching must not blank the hydrated document.
  expect(textbox().textContent).toBe("First saved bold entry")
  if (pendingWrite) {
    await act(async () => { finishWrite() })
    await waitFor(() => expect(client.getMutationCache().getAll()[0]?.state.status).toBe("success"))
    await waitFor(() => expect(originalGets).toBe(3))
    await waitFor(() => expect(client.isFetching()).toBe(0))
    expect(textbox().textContent).toBe("First saved bold entry")
  }
  expect(screen.getByText("Saved locally")).toBeTruthy()
})

it.each([false, true])("retries failed ratings without replacing them from query rollback; existing=%s", async (existing) => {
  const stored = existing ? { date: day, raw_markdown: "Saved text", mood: 2, energy: 3 } : null
  const writes: unknown[] = []
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (_url, init) => {
    if (init?.method === "PUT") {
      writes.push(JSON.parse(String(init.body)))
      return writes.length === 1 ? json({ detail: "Offline" }, 503) : json({ saved: true })
    }
    return stored ? json(stored) : json({ detail: "Not found" }, 404)
  }))
  render(<QueryClientProvider client={client}><JournalView /></QueryClientProvider>)
  await waitFor(() => expect(textbox().getAttribute("contenteditable")).toBe("true"))
  fireEvent.click(screen.getByRole("button", { name: "Mood 5 of 5" }))
  fireEvent.click(screen.getByRole("button", { name: "Energy 1 of 5" }))
  const retry = await screen.findByRole("button", { name: "Retry local save" })
  await waitFor(() => expect(client.isFetching()).toBe(0))
  fireEvent.click(retry)
  await waitFor(() => expect(writes).toHaveLength(2))
  expect(writes[0]).toEqual({ raw_markdown: existing ? "Saved text" : "", mood: 5, energy: 1 })
  expect(writes[1]).toEqual(writes[0])
  await screen.findByText("Saved locally")
  expect(textbox().textContent).toBe(existing ? "Saved text" : "")
})
