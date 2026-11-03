// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { save } from "@tauri-apps/plugin-dialog"
import { writeFile } from "@tauri-apps/plugin-fs"
import { api } from "@/api/client"
import { CalendarExport } from "./calendar-export"
import type { Task, TimeBlock } from "@/api/types"

vi.mock("@/api/client", () => ({ api: { download: vi.fn() }, ApiError: class extends Error {} }))
vi.mock("@tauri-apps/plugin-dialog", () => ({ save: vi.fn() }))
vi.mock("@tauri-apps/plugin-fs", () => ({ writeFile: vi.fn() }))

const clients: QueryClient[] = []
const payload = new Uint8Array([80, 75, 3, 4, 0, 255])
const blob = { arrayBuffer: async () => payload.buffer } as Blob
const createURL = vi.fn(() => "blob:export-test")
const revokeURL = vi.fn()
const clickDownload = vi.fn()

const blocks: TimeBlock[] = ["first", "second"].map(id => ({
  id, task_id: id, kind: "all_day", start_date: "2026-11-01", end_date: "2026-11-02",
  start_at: null, end_at: null, timezone: null, created_at: "2026-11-01", updated_at: "2026-11-01",
}))
const taskById = new Map(blocks.map(block => [block.task_id, { title: block.id } as Task]))

function mount(initialBlocks = blocks, unavailable = false) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  clients.push(client)
  const content = (items: TimeBlock[], disabled: boolean) => <QueryClientProvider client={client}>
    <CalendarExport blocks={items} taskById={taskById} unavailable={disabled} />
  </QueryClientProvider>
  const view = render(content(initialBlocks, unavailable))
  fireEvent.click(screen.getByRole("button", { name: "Export work blocks" }))
  return { ...view, update: (items: TimeBlock[], disabled = false) => view.rerender(content(items, disabled)) }
}
function downloadButton() { return screen.getByRole("button", { name: "Download .ics" }) }
function selectFirst() { fireEvent.click(screen.getAllByRole("checkbox")[0]) }
function desktop() { Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {}, configurable: true }) }

beforeEach(() => {
  vi.spyOn(URL, "createObjectURL").mockImplementation(createURL)
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(revokeURL)
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clickDownload({ href: this.href, filename: this.download, attached: document.body.contains(this) })
  })
  vi.mocked(api.download).mockResolvedValue(blob)
  vi.mocked(writeFile).mockResolvedValue(undefined)
})
afterEach(() => {
  cleanup()
  clients.splice(0).forEach(client => client.clear())
  Reflect.deleteProperty(window, "__TAURI_INTERNALS__")
  vi.restoreAllMocks()
  vi.resetAllMocks()
  createURL.mockReturnValue("blob:export-test")
})

it("requires explicit selection and sends only selected block IDs", async () => {
  mount()
  expect(screen.getAllByRole("checkbox").every(input => !(input as HTMLInputElement).checked)).toBe(true)
  expect(downloadButton().hasAttribute("disabled")).toBe(true)
  fireEvent.click(downloadButton())
  expect(api.download).not.toHaveBeenCalled()
  selectFirst()
  fireEvent.click(downloadButton())
  await waitFor(() => expect(api.download).toHaveBeenCalledExactlyOnceWith("/calendar/export", { block_ids: ["first"] }))
})

it("excludes removed blocks from the next export payload", async () => {
  const view = mount()
  screen.getAllByRole("checkbox").forEach(input => fireEvent.click(input))
  view.update([blocks[1]])
  fireEvent.click(downloadButton())
  await waitFor(() => expect(api.download).toHaveBeenCalledExactlyOnceWith("/calendar/export", { block_ids: ["second"] }))
})

it("prevents duplicate pending exports and freezes selection across prop changes", async () => {
  desktop()
  let choose!: (path: string) => void
  vi.mocked(save).mockReturnValue(new Promise(resolve => { choose = resolve }))
  const view = mount()
  selectFirst()
  fireEvent.click(downloadButton())
  await waitFor(() => expect(save).toHaveBeenCalledOnce())
  fireEvent.click(screen.getByRole("button", { name: "Preparing calendar…" }))
  view.update([blocks[1]])
  expect(api.download).not.toHaveBeenCalled()
  await act(async () => choose("/chosen/calendar.ics"))
  await waitFor(() => expect(writeFile).toHaveBeenCalledOnce())
  expect(api.download).toHaveBeenCalledExactlyOnceWith("/calendar/export", { block_ids: ["first"] })
})

it.each(["api", "url", "click"])("reports %s failure and permits retry without losing selection", async failure => {
  if (failure === "api") vi.mocked(api.download).mockRejectedValueOnce(new Error("Unavailable"))
  if (failure === "url") createURL.mockImplementationOnce(() => { throw new Error("URL unavailable") })
  if (failure === "click") vi.mocked(HTMLAnchorElement.prototype.click).mockImplementationOnce(() => { throw new Error("Blocked") })
  mount()
  selectFirst()
  fireEvent.click(downloadButton())
  await screen.findByRole("alert")
  expect(document.querySelector("a[download]")).toBeNull()
  if (failure === "click") expect(revokeURL).toHaveBeenCalledWith("blob:export-test")
  fireEvent.click(downloadButton())
  await waitFor(() => expect(clickDownload).toHaveBeenCalledOnce())
  expect(screen.queryByRole("alert")).toBeNull()
})

it("cleans browser anchors immediately and URLs on replacement and unmount", async () => {
  createURL.mockReturnValueOnce("blob:first").mockReturnValueOnce("blob:second")
  const view = mount()
  selectFirst()
  fireEvent.click(downloadButton())
  await waitFor(() => expect(clickDownload).toHaveBeenCalledOnce())
  expect(clickDownload).toHaveBeenCalledWith({ href: "blob:first", filename: "meditations-calendar.ics", attached: true })
  expect(document.querySelector("a[download]")).toBeNull()
  expect(revokeURL).not.toHaveBeenCalled()
  await waitFor(() => expect(downloadButton().hasAttribute("disabled")).toBe(false))
  fireEvent.click(downloadButton())
  await waitFor(() => expect(clickDownload).toHaveBeenCalledTimes(2))
  expect(revokeURL).toHaveBeenCalledExactlyOnceWith("blob:first")
  view.unmount()
  expect(revokeURL).toHaveBeenCalledWith("blob:second")
})

it("does not create a browser download after unmount during a request", async () => {
  let finish!: (value: Blob) => void
  vi.mocked(api.download).mockReturnValue(new Promise(resolve => { finish = resolve }))
  const view = mount()
  selectFirst()
  fireEvent.click(downloadButton())
  await waitFor(() => expect(api.download).toHaveBeenCalledOnce())
  view.unmount()
  await act(async () => finish(blob))
  expect(createURL).not.toHaveBeenCalled()
  expect(clickDownload).not.toHaveBeenCalled()
})

it("cancels native export before any API request", async () => {
  desktop()
  vi.mocked(save).mockResolvedValue(null)
  mount()
  selectFirst()
  fireEvent.click(downloadButton())
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("cancelled"))
  expect(save).toHaveBeenCalledWith({ title: "Export work blocks", defaultPath: "meditations-calendar.ics", filters: [{ name: "iCalendar", extensions: ["ics"] }] })
  expect(api.download).not.toHaveBeenCalled()
  expect(writeFile).not.toHaveBeenCalled()
})

it("writes native calendar bytes exclusively with private permissions", async () => {
  desktop()
  vi.mocked(save).mockResolvedValue("/chosen/calendar.ics")
  mount()
  selectFirst()
  fireEvent.click(downloadButton())
  await waitFor(() => expect(writeFile).toHaveBeenCalledExactlyOnceWith("/chosen/calendar.ics", payload, { createNew: true, mode: 0o600 }))
  expect(createURL).not.toHaveBeenCalled()
})

it.each(["empty", "unavailable"])("does not request exports when %s", state => {
  mount(state === "empty" ? [] : blocks, state === "unavailable")
  if (state === "unavailable") expect((screen.getAllByRole("checkbox")[0] as HTMLInputElement).disabled || screen.getByRole("group").hasAttribute("disabled")).toBe(true)
  expect(downloadButton().hasAttribute("disabled")).toBe(true)
  fireEvent.click(downloadButton())
  expect(api.download).not.toHaveBeenCalled()
})
