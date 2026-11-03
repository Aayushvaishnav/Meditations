// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import type { AISettingsView } from "@/api/types"
import { api } from "@/api/client"
import { SettingsView } from "./settings"

vi.mock("@/api/client", () => ({ api: { get: vi.fn(), put: vi.fn(), delete: vi.fn() }, ApiError: class extends Error {} }))
vi.mock("@/components/backup-settings", () => ({ BackupSettings: () => null }))
vi.mock("@/components/export-settings", () => ({ ExportSettings: () => null }))
vi.mock("@/components/calendar-settings", () => ({ CalendarSettings: () => null }))
vi.mock("@/components/webhook-settings", () => ({ WebhookSettings: () => null }))
vi.mock("@/components/calendar-import-settings", () => ({ CalendarImportSettings: () => null }))

const initial: AISettingsView = { provider: "anthropic", model_name: "initial", fast_model_name: "fast", base_url: "https://initial.test", api_key_set: true }
const defaults = { ...initial, provider: "openai_compatible", model_name: "default", base_url: null }
let serverAI = initial
let serverPrefs = { target_deep_work_hours: 6 }
let client: QueryClient

beforeEach(() => {
  serverAI = initial
  serverPrefs = { target_deep_work_hours: 6 }
  vi.mocked(api.get).mockImplementation(async (path) => {
    if (path === "/settings/ai") return serverAI
    if (path === "/settings/app") return serverPrefs
    return {}
  })
  vi.mocked(api.put).mockImplementation(async (path, input) => {
    if (path === "/settings/ai") return (serverAI = { ...serverAI, ...(input as object) })
    return (serverPrefs = input as typeof serverPrefs)
  })
  vi.mocked(api.delete).mockImplementation(async () => (serverAI = defaults))
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
})
afterEach(() => { cleanup(); client.clear(); vi.resetAllMocks() })
function mount() {
  render(<QueryClientProvider client={client}><SettingsView /></QueryClientProvider>)
}
function input(name: string) { return screen.getByLabelText(new RegExp(name)) as HTMLInputElement }
async function loaded() { await waitFor(() => expect(input("Model name").value).toBe("initial")) }

it("loads asynchronous settings without ever prefilling the API key", async () => {
  mount()
  expect(input("API key").value).toBe("")
  await loaded()
  expect(input("Provider").value).toBe("anthropic")
  expect(input("Base URL").value).toBe(initial.base_url)
  expect(input("Daily deep-work").value).toBe("6")
  expect(input("API key").value).toBe("")
})

it("preserves edited provider, model, URL, key and preferences across refetches", async () => {
  mount(); await loaded()
  fireEvent.change(input("Provider"), { target: { value: "openai_compatible" } })
  fireEvent.change(input("Model name"), { target: { value: "draft" } })
  fireEvent.change(input("Base URL"), { target: { value: "https://draft.test" } })
  fireEvent.change(input("API key"), { target: { value: "new-key" } })
  fireEvent.change(input("Daily deep-work"), { target: { value: "8" } })
  await act(async () => {
    client.setQueryData(["ai-settings"], { ...initial, model_name: "refetched", base_url: "https://refetched.test" })
    client.setQueryData(["app-prefs"], { target_deep_work_hours: 3 })
  })
  expect(input("Provider").value).toBe("openai_compatible")
  expect(input("Model name").value).toBe("draft")
  expect(input("Base URL").value).toBe("https://draft.test")
  expect(input("API key").value).toBe("new-key")
  expect(input("Daily deep-work").value).toBe("8")
  fireEvent.blur(input("Daily deep-work"))
  await waitFor(() => expect(api.put).toHaveBeenCalledWith("/settings/app", { target_deep_work_hours: 8 }))
  fireEvent.click(screen.getAllByRole("button", { name: /^Save$/ })[0])
  await waitFor(() => expect(api.put).toHaveBeenCalledWith("/settings/ai", {
    provider: "openai_compatible", model_name: "draft", fast_model_name: "fast", base_url: "https://draft.test", api_key: "new-key",
  }))
  await waitFor(() => expect(input("API key").value).toBe(""))
  expect(input("Model name").value).toBe("draft")
  expect(input("Daily deep-work").value).toBe("8")
})

it("intentionally replaces drafts on reset, clears the key, and omits an unchanged key on save", async () => {
  mount(); await loaded()
  fireEvent.change(input("Model name"), { target: { value: "discard" } })
  fireEvent.change(input("API key"), { target: { value: "discard-key" } })
  fireEvent.click(screen.getByRole("button", { name: "Reset to defaults" }))
  await waitFor(() => expect(input("Model name").value).toBe("default"))
  expect(input("Base URL").value).toBe("")
  expect(input("API key").value).toBe("")
  fireEvent.click(screen.getAllByRole("button", { name: /^Save$/ })[0])
  await waitFor(() => expect(api.put).toHaveBeenCalledWith("/settings/ai", {
    provider: "openai_compatible", model_name: "default", fast_model_name: "fast", base_url: null,
  }))
})

it("keeps edits made before the initial response while filling untouched fields", async () => {
  let resolve!: (value: typeof initial) => void
  const pending = new Promise<typeof initial>((done) => { resolve = done })
  vi.mocked(api.get).mockImplementation(async (path) => path === "/settings/ai" ? pending : {})
  mount()
  fireEvent.change(input("Model name"), { target: { value: "early edit" } })
  fireEvent.change(input("Daily deep-work"), { target: { value: "9" } })
  await act(async () => {
    resolve(initial)
    client.setQueryData(["app-prefs"], { target_deep_work_hours: 2 })
  })
  await waitFor(() => expect(input("Provider").value).toBe("anthropic"))
  expect(input("Model name").value).toBe("early edit")
  expect(input("Base URL").value).toBe(initial.base_url)
  expect(input("Daily deep-work").value).toBe("9")
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

it.each(["save", "reset"])("acknowledges each unchanged field during pending %s", async (operation) => {
  mount(); await loaded()
  fireEvent.change(input("Model name"), { target: { value: "submitted" } })
  fireEvent.change(input("API key"), { target: { value: "submitted-key" } })
  const response = deferred<typeof initial>()
  if (operation === "save") vi.mocked(api.put).mockImplementationOnce(() => response.promise)
  else vi.mocked(api.delete).mockImplementationOnce(() => response.promise)
  fireEvent.click(operation === "save" ? screen.getAllByRole("button", { name: /^Save$/ })[0] : screen.getByRole("button", { name: "Reset to defaults" }))
  fireEvent.change(input("Model name"), { target: { value: "newer" } })
  await act(async () => { serverAI = defaults; response.resolve(defaults) })
  await waitFor(() => expect(input("API key").value).toBe(""))
  expect(input("Model name").value).toBe("newer")
  expect(input("Provider").value).toBe(defaults.provider)
  expect(input("Base URL").value).toBe("")
})

it("preserves a newer API key during acknowledgement", async () => {
  mount(); await loaded()
  fireEvent.change(input("API key"), { target: { value: "submitted-key" } })
  const response = deferred<typeof initial>()
  vi.mocked(api.put).mockImplementationOnce(() => response.promise)
  fireEvent.click(screen.getAllByRole("button", { name: /^Save$/ })[0])
  fireEvent.change(input("API key"), { target: { value: "newer-key" } })
  await act(async () => { response.resolve(initial) })
  await waitFor(() => expect(client.isMutating()).toBe(0))
  expect(input("API key").value).toBe("newer-key")
})

it("preserves preference typing during save then follows refetch after acknowledgement", async () => {
  mount(); await loaded()
  const response = deferred<typeof serverPrefs>()
  vi.mocked(api.put).mockImplementationOnce(() => response.promise)
  fireEvent.change(input("Daily deep-work"), { target: { value: "8" } })
  fireEvent.blur(input("Daily deep-work"))
  fireEvent.change(input("Daily deep-work"), { target: { value: "9" } })
  await act(async () => { serverPrefs = { target_deep_work_hours: 8 }; response.resolve(serverPrefs) })
  await waitFor(() => expect(client.isMutating()).toBe(0))
  expect(input("Daily deep-work").value).toBe("9")
  fireEvent.blur(input("Daily deep-work"))
  await waitFor(() => expect(api.put).toHaveBeenCalledTimes(2))
  await act(async () => { await client.invalidateQueries({ queryKey: ["app-prefs"] }) })
  await act(async () => { serverPrefs = { target_deep_work_hours: 3 }; await client.invalidateQueries({ queryKey: ["app-prefs"] }) })
  await waitFor(() => expect(input("Daily deep-work").value).toBe("3"))
})

it("follows later server refetch after a pristine successful save", async () => {
  mount(); await loaded()
  fireEvent.change(input("Model name"), { target: { value: "saved" } })
  fireEvent.click(screen.getAllByRole("button", { name: /^Save$/ })[0])
  await waitFor(() => expect(serverAI.model_name).toBe("saved"))
  await act(async () => { await client.invalidateQueries({ queryKey: ["ai-settings"] }) })
  await act(async () => { serverAI = { ...initial, model_name: "external" }; await client.invalidateQueries({ queryKey: ["ai-settings"] }) })
  await waitFor(() => expect(input("Model name").value).toBe("external"))
})
