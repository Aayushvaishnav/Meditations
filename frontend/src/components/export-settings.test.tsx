// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { save } from "@tauri-apps/plugin-dialog"
import { writeFile } from "@tauri-apps/plugin-fs"
import { api } from "@/api/client"
import { BackupSettings } from "./backup-settings"
import { ExportSettings } from "./export-settings"

vi.mock("@/api/client", () => ({ api: { download: vi.fn() }, ApiError: class extends Error {} }))
vi.mock("@tauri-apps/plugin-dialog", () => ({ save: vi.fn() }))
vi.mock("@tauri-apps/plugin-fs", () => ({ writeFile: vi.fn() }))

const clients: QueryClient[] = []
const payload = new Uint8Array([80, 75, 3, 4, 0, 255])
const blob = { arrayBuffer: async () => payload.buffer } as Blob
const createURL = vi.fn(() => "blob:export-test")
const revokeURL = vi.fn()
const clickDownload = vi.fn()

function mount(withBackup = false) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  clients.push(client)
  return render(
    <QueryClientProvider client={client}>
      {withBackup && <BackupSettings />}
      <ExportSettings />
    </QueryClientProvider>,
  )
}

function desktop() {
  Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {}, configurable: true })
}

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
  clients.splice(0).forEach((client) => client.clear())
  Reflect.deleteProperty(window, "__TAURI_INTERNALS__")
  vi.restoreAllMocks()
  vi.resetAllMocks()
  createURL.mockReturnValue("blob:export-test")
})

it("downloads the ZIP once while pending and releases its object URL on exit", async () => {
  let finish!: (value: Blob) => void
  vi.mocked(api.download).mockReturnValue(new Promise((resolve) => { finish = resolve }))
  const view = mount()
  const button = screen.getByRole("button")
  fireEvent.click(button)
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(true))
  fireEvent.click(button)
  expect(api.download).toHaveBeenCalledExactlyOnceWith("/export")
  expect(clickDownload).not.toHaveBeenCalled()
  await act(async () => finish(blob))
  await waitFor(() => expect(clickDownload).toHaveBeenCalledOnce())
  expect(clickDownload).toHaveBeenCalledWith({
    href: "blob:export-test", filename: expect.stringMatching(/^journal-export-.*\.zip$/), attached: true,
  })
  expect(document.querySelector("a[download]")).toBeNull()
  expect(revokeURL).not.toHaveBeenCalled()
  view.unmount()
  expect(revokeURL).toHaveBeenCalledExactlyOnceWith("blob:export-test")
})

it("keeps export and backup requests and download lifetimes independent", async () => {
  createURL.mockReturnValueOnce("blob:backup").mockReturnValueOnce("blob:export")
  const view = mount(true)
  const backup = within(screen.getByRole("region", { name: "Database backup" }))
  const portable = within(screen.getByRole("region", { name: "Portable data export" }))
  fireEvent.click(backup.getByRole("button"))
  await waitFor(() => expect(clickDownload).toHaveBeenCalledTimes(1))
  fireEvent.click(portable.getByRole("button"))
  await waitFor(() => expect(clickDownload).toHaveBeenCalledTimes(2))
  expect(vi.mocked(api.download).mock.calls.map(([path]) => path)).toEqual(["/backup", "/export"])
  expect(revokeURL).not.toHaveBeenCalled()
  fireEvent.click(portable.getByRole("button"))
  await waitFor(() => expect(clickDownload).toHaveBeenCalledTimes(3))
  expect(revokeURL).toHaveBeenCalledExactlyOnceWith("blob:export")
  view.unmount()
  expect(revokeURL).toHaveBeenCalledWith("blob:backup")
})

it("reports API failures without a download and permits retry", async () => {
  vi.mocked(api.download).mockRejectedValueOnce(new Error("Export unavailable"))
  mount()
  fireEvent.click(screen.getByRole("button"))
  await screen.findByRole("alert")
  expect(createURL).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button"))
  await waitFor(() => expect(clickDownload).toHaveBeenCalledOnce())
  expect(screen.queryByRole("alert")).toBeNull()
})

it("does not start a browser download after the view unmounts", async () => {
  let finish!: (value: Blob) => void
  vi.mocked(api.download).mockReturnValue(new Promise((resolve) => { finish = resolve }))
  const view = mount()
  fireEvent.click(screen.getByRole("button"))
  await waitFor(() => expect(api.download).toHaveBeenCalledOnce())
  view.unmount()
  await act(async () => finish(blob))
  expect(createURL).not.toHaveBeenCalled()
  expect(clickDownload).not.toHaveBeenCalled()
})

it.each(["url", "click"])("cleans up after a browser %s failure and allows retry", async (failure) => {
  if (failure === "url") createURL.mockImplementationOnce(() => { throw new Error("URL unavailable") })
  else vi.mocked(HTMLAnchorElement.prototype.click).mockImplementationOnce(() => { throw new Error("Download blocked") })
  mount()
  fireEvent.click(screen.getByRole("button"))
  await screen.findByRole("alert")
  expect(document.querySelector("a[download]")).toBeNull()
  if (failure === "click") expect(revokeURL).toHaveBeenCalledWith("blob:export-test")
  fireEvent.click(screen.getByRole("button"))
  await waitFor(() => expect(clickDownload).toHaveBeenCalledOnce())
  expect(screen.queryByRole("alert")).toBeNull()
})

it("cancels the desktop dialog without requesting data or writing a file", async () => {
  desktop()
  vi.mocked(save).mockResolvedValue(null)
  mount()
  fireEvent.click(screen.getByRole("button"))
  await waitFor(() => expect(save).toHaveBeenCalledOnce())
  await waitFor(() => expect(screen.getByRole("button").hasAttribute("disabled")).toBe(false))
  expect(vi.mocked(save).mock.calls[0][0]).toMatchObject({
    defaultPath: expect.stringMatching(/^journal-export-.*\.zip$/),
    filters: [{ name: "ZIP archive", extensions: ["zip"] }],
  })
  expect(api.download).not.toHaveBeenCalled()
  expect(writeFile).not.toHaveBeenCalled()
})

it("writes the ZIP to a new native file with private permissions", async () => {
  desktop()
  vi.mocked(save).mockResolvedValue("/chosen/export.zip")
  mount()
  fireEvent.click(screen.getByRole("button"))
  await waitFor(() => expect(writeFile).toHaveBeenCalledOnce())
  expect(api.download).toHaveBeenCalledExactlyOnceWith("/export")
  expect(writeFile).toHaveBeenCalledWith("/chosen/export.zip", payload, { createNew: true, mode: 0o600 })
  expect(createURL).not.toHaveBeenCalled()
})

it.each(["dialog", "api", "write"])("reports a native %s failure and permits retry", async (failure) => {
  desktop()
  vi.mocked(save).mockResolvedValue("/chosen/export.zip")
  if (failure === "dialog") vi.mocked(save).mockRejectedValueOnce(new Error("Dialog unavailable"))
  if (failure === "api") vi.mocked(api.download).mockRejectedValueOnce(new Error("Export unavailable"))
  if (failure === "write") vi.mocked(writeFile).mockRejectedValueOnce(new Error("File exists"))
  mount()
  fireEvent.click(screen.getByRole("button"))
  await screen.findByRole("alert")
  expect(clickDownload).not.toHaveBeenCalled()
  if (failure !== "write") expect(writeFile).not.toHaveBeenCalled()
  vi.mocked(save).mockResolvedValue("/chosen/new.zip")
  fireEvent.click(screen.getByRole("button"))
  await waitFor(() => expect(writeFile).toHaveBeenLastCalledWith("/chosen/new.zip", payload, { createNew: true, mode: 0o600 }))
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull())
})

it("finishes an already selected native save after leaving Settings", async () => {
  desktop()
  vi.mocked(save).mockResolvedValue("/chosen/export.zip")
  let finish!: (value: Blob) => void
  vi.mocked(api.download).mockReturnValue(new Promise((resolve) => { finish = resolve }))
  const view = mount()
  fireEvent.click(screen.getByRole("button"))
  await waitFor(() => expect(api.download).toHaveBeenCalledOnce())
  view.unmount()
  await act(async () => finish(blob))
  expect(writeFile).toHaveBeenCalledWith("/chosen/export.zip", payload, { createNew: true, mode: 0o600 })
  expect(clickDownload).not.toHaveBeenCalled()
})
