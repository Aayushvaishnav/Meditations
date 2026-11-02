// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { api } from "@/api/client"
import { save } from "@tauri-apps/plugin-dialog"
import { writeFile } from "@tauri-apps/plugin-fs"
import { BackupSettings } from "./backup-settings"

vi.mock("@/api/client", () => ({ api: { download: vi.fn() }, ApiError: class extends Error {} }))
vi.mock("@tauri-apps/plugin-dialog", () => ({ save: vi.fn() }))
vi.mock("@tauri-apps/plugin-fs", () => ({ writeFile: vi.fn() }))

const clients: QueryClient[] = []
const createURL = vi.fn(() => "blob:backup-test")
const revokeURL = vi.fn()
const clickDownload = vi.fn()
const payload = new Uint8Array([83, 81, 76, 105, 116, 101, 0, 255])
const blob = { arrayBuffer: async () => payload.buffer } as Blob

function mount() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  clients.push(client)
  return render(<QueryClientProvider client={client}><BackupSettings /></QueryClientProvider>)
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
  createURL.mockReturnValue("blob:backup-test")
})

it("blocks duplicate requests while pending, then initiates a binary browser download and releases it on exit", async () => {
  let finish!: (value: Blob) => void
  vi.mocked(api.download).mockReturnValue(new Promise((resolve) => { finish = resolve }))
  const view = mount()
  const button = screen.getByRole("button")
  fireEvent.click(button)
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(true))
  fireEvent.click(button)
  expect(api.download).toHaveBeenCalledTimes(1)
  expect(clickDownload).not.toHaveBeenCalled()
  await act(async () => finish(blob))
  await waitFor(() => expect(clickDownload).toHaveBeenCalledOnce())
  expect(api.download).toHaveBeenCalledWith("/backup")
  expect(createURL).toHaveBeenCalledWith(blob)
  expect(clickDownload).toHaveBeenCalledWith({ href: "blob:backup-test", filename: expect.stringMatching(/^journal-backup-.*\.db$/), attached: true })
  expect(document.querySelector("a[download]")).toBeNull()
  expect(revokeURL).not.toHaveBeenCalled()
  view.unmount()
  expect(revokeURL).toHaveBeenCalledWith("blob:backup-test")
})

it("shows a creation failure without downloading and permits a retry", async () => {
  vi.mocked(api.download).mockRejectedValueOnce(new Error("Database is unavailable"))
  mount()
  fireEvent.click(screen.getByRole("button"))
  await screen.findByRole("alert")
  expect(clickDownload).not.toHaveBeenCalled()
  expect(createURL).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button"))
  await waitFor(() => expect(clickDownload).toHaveBeenCalledOnce())
  expect(screen.queryByRole("alert")).toBeNull()
})

it("releases a previous browser download when another backup replaces it", async () => {
  mount()
  fireEvent.click(screen.getByRole("button"))
  await waitFor(() => expect(clickDownload).toHaveBeenCalledTimes(1))
  fireEvent.click(screen.getByRole("button"))
  await waitFor(() => expect(clickDownload).toHaveBeenCalledTimes(2))
  expect(revokeURL).toHaveBeenCalledTimes(1)
})

it("does not initiate a late download after leaving Settings", async () => {
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

it("cancels desktop saving before creating or fetching a backup", async () => {
  Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {}, configurable: true })
  vi.mocked(save).mockResolvedValue(null)
  mount()
  fireEvent.click(screen.getByRole("button"))
  await waitFor(() => expect(save).toHaveBeenCalledOnce())
  await waitFor(() => expect(screen.getByRole("button").hasAttribute("disabled")).toBe(false))
  expect(api.download).not.toHaveBeenCalled()
  expect(writeFile).not.toHaveBeenCalled()
  expect(clickDownload).not.toHaveBeenCalled()
})

it("saves desktop bytes exclusively to the path chosen by the native dialog", async () => {
  Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {}, configurable: true })
  vi.mocked(save).mockResolvedValue("/chosen/backup.db")
  mount()
  fireEvent.click(screen.getByRole("button"))
  await waitFor(() => expect(writeFile).toHaveBeenCalledOnce())
  expect(writeFile).toHaveBeenCalledWith("/chosen/backup.db", payload, { createNew: true, mode: 0o600 })
  expect(clickDownload).not.toHaveBeenCalled()
  expect(createURL).not.toHaveBeenCalled()
})

it("reports a native write failure and allows a new destination on retry", async () => {
  Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {}, configurable: true })
  vi.mocked(save).mockResolvedValueOnce("/chosen/existing.db").mockResolvedValueOnce("/chosen/new.db")
  vi.mocked(writeFile).mockRejectedValueOnce(new Error("already exists"))
  mount()
  fireEvent.click(screen.getByRole("button"))
  await screen.findByRole("alert")
  fireEvent.click(screen.getByRole("button"))
  await waitFor(() => expect(writeFile).toHaveBeenCalledTimes(2))
  expect(writeFile).toHaveBeenLastCalledWith("/chosen/new.db", payload, { createNew: true, mode: 0o600 })
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull())
})

it.each(["url", "click"])("handles a browser %s failure as a retryable error", async (failure) => {
  if (failure === "url") createURL.mockImplementationOnce(() => { throw new Error("Download could not start") })
  else vi.mocked(HTMLAnchorElement.prototype.click).mockImplementationOnce(() => { throw new Error("Download could not start") })
  mount()
  fireEvent.click(screen.getByRole("button"))
  await screen.findByRole("alert")
  expect(screen.getByRole("status").textContent).toBe("")
  if (failure === "click") expect(revokeURL).toHaveBeenCalledWith("blob:backup-test")
  fireEvent.click(screen.getByRole("button"))
  await waitFor(() => expect(clickDownload).toHaveBeenCalledOnce())
  expect(screen.queryByRole("alert")).toBeNull()
})

it("reports native dialog errors without creating a backup", async () => {
  Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {}, configurable: true })
  vi.mocked(save).mockRejectedValue(new Error("Dialog unavailable"))
  mount()
  fireEvent.click(screen.getByRole("button"))
  await screen.findByRole("alert")
  expect(api.download).not.toHaveBeenCalled()
  expect(writeFile).not.toHaveBeenCalled()
})

it("does not write a native file when snapshot creation fails", async () => {
  Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {}, configurable: true })
  vi.mocked(save).mockResolvedValue("/chosen/backup.db")
  vi.mocked(api.download).mockRejectedValue(new Error("Snapshot unavailable"))
  mount()
  fireEvent.click(screen.getByRole("button"))
  await screen.findByRole("alert")
  expect(writeFile).not.toHaveBeenCalled()
})

it("finishes a desktop save to an already selected destination after Settings unmounts", async () => {
  Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {}, configurable: true })
  vi.mocked(save).mockResolvedValue("/chosen/backup.db")
  let finish!: (value: Blob) => void
  vi.mocked(api.download).mockReturnValue(new Promise((resolve) => { finish = resolve }))
  const view = mount()
  fireEvent.click(screen.getByRole("button"))
  await waitFor(() => expect(api.download).toHaveBeenCalledOnce())
  view.unmount()
  await act(async () => finish(blob))
  expect(writeFile).toHaveBeenCalledWith("/chosen/backup.db", payload, { createNew: true, mode: 0o600 })
  expect(clickDownload).not.toHaveBeenCalled()
})
