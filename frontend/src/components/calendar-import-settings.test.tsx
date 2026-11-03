// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { api } from "@/api/client"
import { CalendarImportSettings } from "./calendar-import-settings"
import type { ImportedCalendarEvent, ImportedCalendarSource } from "@/api/calendar-import-types"

vi.mock("@/api/client", () => ({ api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() }, ApiError: class extends Error {} }))
let client: QueryClient
let sources: ImportedCalendarSource[]
let inventory: ImportedCalendarEvent[]
const content = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
const source = { id: "source-1", name: "Personal", event_count: 1, updated_at: "2026-11-03T00:00:00" }
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function mount() {
  return render(<QueryClientProvider client={client}><CalendarImportSettings /></QueryClientProvider>)
}
function chooseFile(buffer: ArrayBuffer = new TextEncoder().encode(content).buffer) {
  const file = new File([content], "appointments.ics", { type: "text/calendar" })
  Object.defineProperty(file, "arrayBuffer", { value: vi.fn().mockResolvedValue(buffer), configurable: true })
  fireEvent.change(screen.getByLabelText("iCalendar file"), { target: { files: [file] } })
  return file
}
function chooseSource(id = source.id) {
  fireEvent.change(screen.getByLabelText("Import destination"), { target: { value: id } })
}
async function ready() {
  await waitFor(() => expect(screen.getByRole("group", { name: "Import an iCalendar file" }).hasAttribute("disabled")).toBe(false))
}
function importButton() { return screen.getByRole("button", { name: "Import .ics file" }) }
function submitImport() {
  expect(importButton().hasAttribute("disabled")).toBe(false)
  // Synthetic files do not update jsdom's native file-input validity
  fireEvent.submit(importButton().closest("form")!)
}

beforeEach(() => {
  sources = [source]
  inventory = [{ id: "event-1", uid: "source-uid", summary: "Meet Alex", recurrence_kind: "master", recurrence_id: "", time_zone: "America/New_York", recurrence_time_zone: "America/New_York", start_kind: "local", status: "CONFIRMED", has_recurrence: true, start_value: "20261103T100000", end_value: "20261103T110000", representation: "opaque" }]
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  vi.mocked(api.get).mockImplementation(async path => path.endsWith("/events") ? inventory : sources)
  vi.mocked(api.post).mockImplementation(async () => ({ source_id: source.id, created: 1, updated: 0, unchanged: 0 }))
  vi.mocked(api.delete).mockImplementation(async () => { sources = []; return undefined })
})
afterEach(() => { cleanup(); client.clear(); vi.resetAllMocks() })

it("requires an explicit file and name for a new source, then selects the saved inventory", async () => {
  mount(); await ready()
  expect(importButton().hasAttribute("disabled")).toBe(true)
  chooseFile()
  expect(importButton().hasAttribute("disabled")).toBe(true)
  fireEvent.change(screen.getByLabelText("Calendar name"), { target: { value: "Appointments" } })
  submitImport()
  await waitFor(() => expect(api.post).toHaveBeenCalledExactlyOnceWith("/calendar/imports", { target: { kind: "new", name: "Appointments" }, content }))
  await screen.findByText(/1 added, 0 updated, 0 unchanged/)
  await screen.findByText("Meet Alex")
  expect((screen.getByLabelText("Import destination") as HTMLSelectElement).value).toBe(source.id)
  expect(importButton().hasAttribute("disabled")).toBe(true)
})

it("reimports into an explicitly selected source without using filenames for identity", async () => {
  mount(); await ready(); chooseSource(); chooseFile()
  expect(importButton().hasAttribute("disabled")).toBe(false)
  submitImport()
  await waitFor(() => expect(api.post).toHaveBeenCalledExactlyOnceWith("/calendar/imports", { target: { kind: "existing", source_id: source.id }, content }))
})

it("retains destination and file after rejection and permits a retry", async () => {
  vi.mocked(api.post).mockRejectedValueOnce(new Error("Unsupported VTODO component; no changes saved"))
  mount(); await ready(); chooseSource(); chooseFile(); submitImport()
  await screen.findByRole("alert")
  expect((screen.getByLabelText("Import destination") as HTMLSelectElement).value).toBe(source.id)
  submitImport()
  await screen.findByText(/Import saved/)
  expect(api.post).toHaveBeenCalledTimes(2)
})

it("freezes a pending upload and locks mutation controls until file reading and import finish", async () => {
  const pending = deferred<unknown>()
  vi.mocked(api.post).mockReturnValue(pending.promise)
  mount(); await ready(); chooseSource(); chooseFile(); submitImport()
  await waitFor(() => expect(api.post).toHaveBeenCalledOnce())
  expect(screen.getByRole("group", { name: "Import an iCalendar file" }).hasAttribute("disabled")).toBe(true)
  expect(screen.getByRole("button", { name: "Remove imported calendar" }).hasAttribute("disabled")).toBe(true)
  await act(async () => pending.resolve({ source_id: source.id, created: 0, updated: 1, unchanged: 0 }))
  await screen.findByText(/0 added, 1 updated/)
})

it("keeps in-flight imports locked across navigation and invalidates their inventory on completion", async () => {
  const pending = deferred<unknown>()
  vi.mocked(api.post).mockReturnValue(pending.promise)
  const view = mount(); await ready(); chooseSource(); chooseFile(); submitImport()
  await waitFor(() => expect(api.post).toHaveBeenCalledOnce())
  view.unmount(); mount()
  expect(screen.getByRole("group", { name: "Import an iCalendar file" }).hasAttribute("disabled")).toBe(true)
  await act(async () => pending.resolve({ source_id: source.id, created: 1, updated: 0, unchanged: 0 }))
  await ready()
  expect(screen.queryByText(/Import saved/)).toBeNull()
  expect(api.post).toHaveBeenCalledOnce()
})

it("rejects unreadable or non-UTF-8 input before contacting the API", async () => {
  mount(); await ready(); chooseSource(); chooseFile(new Uint8Array([0xff, 0xfe]).buffer)
  submitImport()
  await screen.findByRole("alert")
  expect(api.post).not.toHaveBeenCalled()
  expect(screen.getByRole("alert").textContent).toContain("UTF-8")
})

it("shows original values and recurrence exceptions as an inventory without task mutations", async () => {
  inventory.push({ ...inventory[0], id: "cancelled", summary: "Moved occurrence", recurrence_kind: "local", recurrence_id: "20261104T100000", status: "CANCELLED" })
  client.setQueryData(["tasks"], [{ id: "task", status: "todo" }])
  client.setQueryData(["scores-daily"], { score: 50 })
  mount(); await ready(); chooseSource()
  await screen.findByText("Moved occurrence")
  expect(screen.getByText(/Occurrence exception; cancelled/)).toBeTruthy()
  expect(screen.getByText(/Original occurrence \(local\): 20261104T100000/)).toBeTruthy()
  chooseFile(); submitImport(); await screen.findByText(/Import saved/)
  expect(client.getQueryState(["tasks"])?.isInvalidated).toBe(false)
  expect(client.getQueryState(["scores-daily"])?.isInvalidated).toBe(false)
  expect(api.delete).not.toHaveBeenCalled()
})

it("requires confirmation for removal and preserves the source when cancelled", async () => {
  mount(); await ready(); chooseSource()
  fireEvent.click(screen.getByRole("button", { name: "Remove imported calendar" }))
  expect(api.delete).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button", { name: "Keep calendar" }))
  expect(api.delete).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button", { name: "Remove imported calendar" }))
  fireEvent.click(screen.getByRole("button", { name: "Confirm removal" }))
  await screen.findByText(/Imported calendar removed/)
  expect(api.delete).toHaveBeenCalledExactlyOnceWith(`/calendar/imports/${source.id}`)
  expect(screen.queryByText("Meet Alex")).toBeNull()
})

it("keeps removal failures actionable and allows retry", async () => {
  vi.mocked(api.delete).mockRejectedValueOnce(new Error("Database unavailable"))
  mount(); await ready(); chooseSource()
  fireEvent.click(screen.getByRole("button", { name: "Remove imported calendar" }))
  fireEvent.click(screen.getByRole("button", { name: "Confirm removal" }))
  await screen.findByRole("alert")
  fireEvent.click(screen.getByRole("button", { name: "Confirm removal" }))
  await screen.findByText(/Imported calendar removed/)
  expect(api.delete).toHaveBeenCalledTimes(2)
})

it("blocks imports until a failed source listing recovers", async () => {
  vi.mocked(api.get).mockRejectedValueOnce(new Error("Offline"))
  mount()
  await screen.findByRole("alert")
  expect(screen.getByRole("group", { name: "Import an iCalendar file" }).hasAttribute("disabled")).toBe(true)
  fireEvent.click(screen.getByRole("button", { name: "Retry imported calendars" }))
  await ready()
})

it("does not show a departed source's late inventory in another source", async () => {
  const late = deferred<unknown>()
  sources = [source, { ...source, id: "second", name: "Other" }]
  vi.mocked(api.get).mockImplementation(async path => {
    if (path.includes("source-1/events")) return late.promise
    return path.endsWith("/events") ? [{ ...inventory[0], id: "other", summary: "Other appointment" }] : sources
  })
  mount(); await ready(); chooseSource(); chooseSource("second")
  await screen.findByText("Other appointment")
  await act(async () => late.resolve(inventory))
  expect(screen.queryByText("Meet Alex")).toBeNull()
})

it("renders imported text literally instead of HTML", async () => {
  inventory = [{ ...inventory[0], summary: "<img src=x onerror=alert(1)>" }]
  mount(); await ready(); chooseSource()
  await screen.findByText("<img src=x onerror=alert(1)>")
  expect(document.querySelector("img")).toBeNull()
})

it("holds the mutation lock during a deferred file read and reports file-read errors", async () => {
  const read = deferred<ArrayBuffer>()
  mount(); await ready(); chooseSource()
  const file = chooseFile()
  Object.defineProperty(file, "arrayBuffer", { value: () => read.promise, configurable: true })
  submitImport()
  await waitFor(() => expect(screen.getByRole("group", { name: "Import an iCalendar file" }).hasAttribute("disabled")).toBe(true))
  expect(api.post).not.toHaveBeenCalled()
  await act(async () => read.reject(new Error("File unavailable")))
  await screen.findByRole("alert")
  expect(api.post).not.toHaveBeenCalled()
  chooseFile(); submitImport()
  await screen.findByText(/Import saved/)
})

it("preserves a UTF-8 signature in the uploaded source text", async () => {
  mount(); await ready(); chooseSource()
  chooseFile(new TextEncoder().encode("\ufeff" + content).buffer)
  submitImport()
  await waitFor(() => expect(api.post).toHaveBeenCalledExactlyOnceWith("/calendar/imports", {
    target: { kind: "existing", source_id: source.id }, content: "\ufeff" + content,
  }))
})

it("clears removal confirmation when the destination changes", async () => {
  sources = [source, { ...source, id: "second", name: "Other" }]
  mount(); await ready(); chooseSource()
  fireEvent.click(screen.getByRole("button", { name: "Remove imported calendar" }))
  chooseSource("second")
  expect(screen.queryByRole("button", { name: "Confirm removal" })).toBeNull()
  expect(api.delete).not.toHaveBeenCalled()
})

it("keeps deletion locked across remount and refreshes destinations when it completes", async () => {
  const pending = deferred<void>()
  vi.mocked(api.delete).mockReturnValue(pending.promise)
  const view = mount(); await ready(); chooseSource()
  fireEvent.click(screen.getByRole("button", { name: "Remove imported calendar" }))
  fireEvent.click(screen.getByRole("button", { name: "Confirm removal" }))
  await waitFor(() => expect(api.delete).toHaveBeenCalledOnce())
  view.unmount(); mount()
  expect(screen.getByRole("group", { name: "Import an iCalendar file" }).hasAttribute("disabled")).toBe(true)
  sources = []
  await act(async () => pending.resolve())
  await ready()
  expect(screen.queryByRole("option", { name: "Personal (1)" })).toBeNull()
})
