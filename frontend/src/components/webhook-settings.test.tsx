// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor
} from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { api } from "@/api/client"
import { WebhookSettings } from "./webhook-settings"
vi.mock("@/api/client", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  ApiError: class extends Error {}
}))
const endpoint = {
  id: "one",
  name: "Automation",
  url: "https://automation.test/hook",
  enabled: true,
  events: ["task.completed"],
  scope: { kind: "all", list_ids: [] },
  include_titles: false,
  has_secret: true
}
let client: QueryClient
beforeEach(() => {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } }
  })
  vi.mocked(api.get).mockImplementation(async (path) =>
    path === "/webhooks"
      ? []
      : path === "/lists"
        ? [{ id: "work", name: "Work" }]
        : []
  )
})
afterEach(() => {
  cleanup()
  client.clear()
  vi.resetAllMocks()
})
function mount() {
  render(
    <QueryClientProvider client={client}>
      <WebhookSettings />
    </QueryClientProvider>
  )
}
it("opens without transmitting events and requires explicit event and enable choices", async () => {
  mount()
  await screen.findByText(/No webhooks configured/)
  expect(api.post).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button", { name: "Add webhook" }))
  expect(
    (
      screen.getByLabelText(
        "Enable delivery to this destination"
      ) as HTMLInputElement
    ).checked
  ).toBe(false)
  expect(
    (
      screen.getByLabelText(
        "Include task titles in shared events"
      ) as HTMLInputElement
    ).checked
  ).toBe(false)
  expect(
    (screen.getByRole("button", { name: "Save webhook" }) as HTMLButtonElement)
      .disabled
  ).toBe(true)
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "Automation" }
  })
  fireEvent.change(screen.getByLabelText("Destination URL"), {
    target: { value: endpoint.url }
  })
  fireEvent.change(screen.getByLabelText("Signing secret"), {
    target: { value: "canary-secret" }
  })
  fireEvent.click(screen.getByLabelText("task.completed"))
  fireEvent.change(screen.getByLabelText("Task scope"), {
    target: { value: "lists" }
  })
  fireEvent.click(await screen.findByLabelText("Work"))
  vi.mocked(api.post).mockResolvedValue(endpoint)
  fireEvent.click(screen.getByRole("button", { name: "Save webhook" }))
  await waitFor(() =>
    expect(screen.queryByLabelText("Signing secret")).toBeNull()
  )
  expect(api.post).toHaveBeenCalledWith(
    "/webhooks",
    expect.objectContaining({
      enabled: false,
      include_titles: false,
      scope: { kind: "lists", list_ids: ["work"] },
      secret: "canary-secret"
    })
  )
  expect(
    JSON.stringify(
      client
        .getQueryCache()
        .getAll()
        .map((q) => q.state)
    )
  ).not.toContain("canary-secret")
  expect(client.getMutationCache().getAll()).toHaveLength(0)
})
it("keeps a failed save editable then omits unchanged secrets on edit", async () => {
  vi.mocked(api.get).mockImplementation(async (path) =>
    path === "/webhooks" ? [endpoint] : []
  )
  mount()
  fireEvent.click(await screen.findByRole("button", { name: /^Edit/ }))
  vi.mocked(api.patch).mockRejectedValueOnce(
    new Error("Destination unavailable")
  )
  fireEvent.click(screen.getByRole("button", { name: "Save webhook" }))
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Destination unavailable"
  )
  vi.mocked(api.patch).mockResolvedValue(endpoint)
  fireEvent.click(screen.getByRole("button", { name: "Save webhook" }))
  await waitFor(() =>
    expect(
      screen.queryByLabelText("Replace signing secret (optional)")
    ).toBeNull()
  )
  expect(api.patch).toHaveBeenCalledWith(
    "/webhooks/one",
    expect.not.objectContaining({ secret: expect.anything() })
  )
})
it("shows delivery failure, retries manually, tests and confirms removal", async () => {
  vi.mocked(api.get).mockImplementation(async (path) =>
    path === "/webhooks"
      ? [endpoint]
      : [
          {
            id: "delivery",
            event_type: "webhook.test",
            state: "failed",
            attempts: 3,
            created_at: "2026-11-03T00:00:00",
            last_error: "HTTP 503"
          }
        ]
  )
  vi.mocked(api.post).mockResolvedValue({})
  mount()
  fireEvent.click(
    await screen.findByRole("button", { name: /^View deliveries/ })
  )
  await screen.findByText("HTTP 503")
  fireEvent.click(screen.getByRole("button", { name: /^Retry delivery/ }))
  await waitFor(() =>
    expect(api.post).toHaveBeenCalledWith(
      "/webhooks/one/deliveries/delivery/retry",
      {}
    )
  )
  fireEvent.click(screen.getByRole("button", { name: /^Send test/ }))
  await waitFor(() =>
    expect(api.post).toHaveBeenCalledWith("/webhooks/one/test", {})
  )
  fireEvent.click(screen.getByRole("button", { name: /^Remove/ }))
  expect(api.delete).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button", { name: /^Confirm removal/ }))
  await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/webhooks/one"))
})

it("retries an offline pending delivery with an error, but not an unattempted delivery", async () => {
  vi.mocked(api.get).mockImplementation(async (path) =>
    path === "/webhooks"
      ? [endpoint]
      : [
          {
            id: "offline",
            event_type: "webhook.test",
            state: "pending",
            attempts: 1,
            created_at: "2026-11-03T00:00:00",
            last_error: "Connection refused"
          },
          {
            id: "queued",
            event_type: "task.completed",
            state: "pending",
            attempts: 0,
            created_at: "2026-11-03T00:00:00",
            last_error: null
          }
        ]
  )
  vi.mocked(api.post).mockResolvedValue({})
  mount()
  fireEvent.click(
    await screen.findByRole("button", { name: /^View deliveries/ })
  )
  await screen.findByText("Connection refused")
  expect(
    screen.getAllByRole("button", { name: /^Retry delivery/ })
  ).toHaveLength(1)
  fireEvent.click(screen.getByRole("button", { name: /^Retry delivery/ }))
  await waitFor(() =>
    expect(api.post).toHaveBeenCalledWith(
      "/webhooks/one/deliveries/offline/retry",
      {}
    )
  )
})

it.each(["delivered", "cancelled", "failed"])(
  "hides stale next-attempt timestamps for %s deliveries",
  async (state) => {
    vi.mocked(api.get).mockImplementation(async (path) =>
      path === "/webhooks"
        ? [endpoint]
        : [
            {
              id: "terminal",
              event_type: "webhook.test",
              state,
              attempts: 1,
              created_at: "2026-11-03T00:00:00",
              next_attempt_at: "2026-11-04T00:00:00",
              last_error: null
            }
          ]
    )
    mount()
    fireEvent.click(
      await screen.findByRole("button", { name: /^View deliveries/ })
    )
    await screen.findByText(new RegExp(`webhook.test · ${state}`))
    expect(screen.queryByText(/Next attempt:/)).toBeNull()
    if (state !== "failed")
      expect(
        screen.queryByRole("button", { name: /^Retry delivery/ })
      ).toBeNull()
  }
)

it("shows pending attempt times and interprets naive timestamps as UTC", async () => {
  const created = "2026-11-03T00:00:00"
  const next = "2026-11-04T00:00:00"
  vi.mocked(api.get).mockImplementation(async (path) =>
    path === "/webhooks"
      ? [endpoint]
      : [
          {
            id: "pending",
            event_type: "webhook.test",
            state: "pending",
            attempts: 0,
            created_at: created,
            next_attempt_at: next,
            last_error: null
          }
        ]
  )
  mount()
  fireEvent.click(
    await screen.findByRole("button", { name: /^View deliveries/ })
  )
  const timestamp = await screen.findByText(/Next attempt:/)
  expect(timestamp.textContent).toBe(
    `Created: ${new Date(`${created}Z`).toLocaleString()} · Next attempt: ${new Date(`${next}Z`).toLocaleString()}`
  )
})

it("returns keyboard focus to the add trigger after cancelling", async () => {
  mount()
  const trigger = await screen.findByRole("button", { name: "Add webhook" })
  trigger.focus()
  fireEvent.click(trigger)
  const cancel = screen.getByRole("button", { name: "Cancel" })
  cancel.focus()
  fireEvent.click(cancel)
  await waitFor(() =>
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Add webhook" })
    )
  )
})

it.each(["cancel", "save"])(
  "returns focus to the endpoint edit trigger after %s",
  async (action) => {
    vi.mocked(api.get).mockImplementation(async (path) =>
      path === "/webhooks" ? [endpoint] : []
    )
    vi.mocked(api.patch).mockResolvedValue(endpoint)
    mount()
    const trigger = await screen.findByRole("button", {
      name: "Edit Automation"
    })
    trigger.focus()
    fireEvent.click(trigger)
    const button = screen.getByRole("button", {
      name: action === "cancel" ? "Cancel" : "Save webhook"
    })
    button.focus()
    fireEvent.click(button)
    await waitFor(() => expect(document.activeElement).toBe(trigger))
  }
)
