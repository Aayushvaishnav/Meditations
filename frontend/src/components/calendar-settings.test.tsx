// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { api } from "@/api/client"
import { CalendarSettings } from "./calendar-settings"
import { calendarKey, qk, useCalendarControl } from "@/hooks/api"

vi.mock("@/api/client", () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() }, ApiError: class extends Error {} }))
const connection = { id: "one", server_url: "https://calendar.test/", calendar_url: "https://calendar.test/events/", state: "connected", credential_state: "present", enabled: false }
let client: QueryClient
function wrapper({ children }: { children: ReactNode }) { return <QueryClientProvider client={client}>{children}</QueryClientProvider> }
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  vi.mocked(api.get).mockImplementation(async path => path.endsWith("/status") ? { queued_count: 2, conflict_count: 1, error_count: 0, last_success_at: null } : path === "/calendar/connections" ? [] : [])
})
afterEach(() => { cleanup(); client.clear(); vi.resetAllMocks() })

it("requires no account and does not contact a remote server on opening Settings", async () => {
  render(<CalendarSettings />, { wrapper })
  await waitFor(() => expect(api.get).toHaveBeenCalledWith("/calendar/connections"))
  expect(api.post).not.toHaveBeenCalled()
  expect(screen.getByLabelText("Server URL")).toBeTruthy()
})

it("discovers writable event calendars and connects without retaining passwords in Query caches", async () => {
  vi.mocked(api.post).mockImplementation(async path => path === "/calendar/connections" ? connection : path.endsWith("/discover") ? [
    { url: "https://calendar.test/events/", display_name: "Events", writable: true, supports_vevent: true },
    { url: "https://calendar.test/read/", display_name: "Read only", writable: false, supports_vevent: true },
  ] : connection)
  render(<CalendarSettings />, { wrapper })
  fireEvent.change(screen.getByLabelText("Server URL"), { target: { value: connection.server_url } })
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: "person" } })
  fireEvent.change(screen.getByLabelText("Password or app password"), { target: { value: "secret-canary" } })
  fireEvent.change(screen.getByLabelText("Authentication"), { target: { value: "digest" } })
  fireEvent.click(screen.getByRole("button", { name: "Discover calendars" }))
  await screen.findByLabelText("Remote calendar")
  expect((screen.getByRole("option", { name: "Read only (unavailable)" }) as HTMLOptionElement).disabled).toBe(true)
  fireEvent.change(screen.getByLabelText("Remote calendar"), { target: { value: connection.calendar_url } })
  fireEvent.click(screen.getByRole("button", { name: "Connect and save credentials" }))
  await waitFor(() => expect((screen.getByLabelText("Password or app password") as HTMLInputElement).value).toBe(""))
  expect(api.post).toHaveBeenCalledWith("/calendar/connections/one/connect", { username: "person", password: "secret-canary", auth_type: "digest", calendar_url: connection.calendar_url })
  expect(JSON.stringify(client.getQueryCache().getAll().map(query => query.state))).not.toContain("secret-canary")
  expect(client.getMutationCache().getAll()).toHaveLength(0)
})

it("clears rejected credentials and permits retry", async () => {
  client.setQueryData(calendarKey, [connection])
  vi.mocked(api.post).mockRejectedValue(new Error("Authentication denied"))
  render(<CalendarSettings />, { wrapper })
  fireEvent.change(screen.getByLabelText("Connection"), { target: { value: "one" } })
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: "person" } })
  fireEvent.change(screen.getByLabelText("Password or app password"), { target: { value: "bad" } })
  fireEvent.click(screen.getByRole("button", { name: "Discover calendars" }))
  expect(await screen.findByRole("alert")).toBeTruthy()
  expect((screen.getByLabelText("Password or app password") as HTMLInputElement).value).toBe("")
})

it("keeps public control locks across remounts and never invalidates tasks", async () => {
  client.setQueryData(qk.tasks, [{ id: "task" }])
  let resolve!: (value: unknown) => void
  vi.mocked(api.patch).mockReturnValue(new Promise(yes => { resolve = yes }))
  const first = renderHook(useCalendarControl, { wrapper })
  act(() => first.result.current.mutate({ path: "/one/sync", method: "patch", body: { enabled: true } }))
  await waitFor(() => expect(first.result.current.isPending).toBe(true))
  first.unmount()
  const second = renderHook(useCalendarControl, { wrapper })
  expect(second.result.current.isPending).toBe(true)
  await act(async () => resolve(connection))
  await waitFor(() => expect(second.result.current.isPending).toBe(false))
  expect(client.getQueryState(qk.tasks)?.isInvalidated).toBe(false)
  expect(client.getQueryData(qk.tasks)).toEqual([{ id: "task" }])
})

it("publishes only an explicitly selected block and distinguishes unlinking from remote removal", async () => {
  const block = { id: "block", task_id: "task", kind: "all_day", start_date: "2026-11-02", end_date: "2026-11-04" }
  const linked = { id: "link", connection_id: "one", local_block_id: "linked", state: "synced", selection_state: "opted_in", desired_action: "upsert", last_error: "Remote event changed" }
  vi.mocked(api.get).mockImplementation(async path => {
    if (path === "/calendar/connections") return [connection]
    if (path === "/tasks") return [{ id: "task", title: "Prepare presentation" }]
    if (path === "/time-blocks") return [block, { ...block, id: "linked" }]
    if (path.endsWith("/links")) return [linked]
    return { queued_count: 1, conflict_count: 1, error_count: 0, last_success_at: null, last_success_state: "never" }
  })
  vi.mocked(api.post).mockResolvedValue(linked)
  render(<CalendarSettings />, { wrapper })
  const option = await screen.findByRole("option", { name: /Prepare presentation.*Not published/ })
  expect(option.textContent).toContain("2026-11-04 (exclusive)")
  expect(api.post).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText("Time block to publish"), { target: { value: "block" } })
  fireEvent.click(screen.getByRole("button", { name: "Publish selected block" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/calendar/connections/one/blocks/block/opt-in", {}))
  await waitFor(() => expect((screen.getByRole("button", { name: "Stop syncing; keep remote" }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole("button", { name: "Stop syncing; keep remote" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/calendar/connections/one/links/link/detach", {}))
  await waitFor(() => expect((screen.getByRole("button", { name: "Remove remote event" }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole("button", { name: "Remove remote event" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/calendar/connections/one/blocks/linked/opt-out", {}))
  expect(screen.getByText(/No events synced yet/)).toBeTruthy()
})

it("preserves a newer password edit when an earlier credential request finishes", async () => {
  let reject!: (error: Error) => void
  vi.mocked(api.post).mockImplementation(async path => path === "/calendar/connections" ? connection : new Promise((_yes, no) => { reject = no }))
  render(<CalendarSettings />, { wrapper })
  fireEvent.change(screen.getByLabelText("Server URL"), { target: { value: connection.server_url } })
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: "person" } })
  fireEvent.change(screen.getByLabelText("Password or app password"), { target: { value: "first" } })
  fireEvent.click(screen.getByRole("button", { name: "Discover calendars" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/calendar/connections/one/discover", expect.anything()))
  fireEvent.change(screen.getByLabelText("Password or app password"), { target: { value: "newer" } })
  await act(async () => reject(new Error("Authentication denied")))
  await waitFor(() => expect((screen.getByLabelText("Password or app password") as HTMLInputElement).disabled).toBe(false))
  expect((screen.getByLabelText("Password or app password") as HTMLInputElement).value).toBe("newer")
})

function serveConnection(initial = connection) {
  let current = initial
  vi.mocked(api.get).mockImplementation(async path => {
    if (path === "/calendar/connections") return [current]
    if (path.endsWith("/status")) return { connection: current, queued_count: 0, conflict_count: 0, error_count: 0, last_success_at: null, last_success_state: "never" }
    return []
  })
  return (next: typeof connection) => { current = next }
}

it("requires explicit verification after restart and enablement after authentication recovery", async () => {
  const setConnection = serveConnection({ ...connection, state: "authentication_required" })
  vi.mocked(api.post).mockImplementation(async () => { setConnection(connection); return connection })
  vi.mocked(api.patch).mockImplementation(async (_path, body) => {
    const next = { ...connection, enabled: (body as { enabled: boolean }).enabled }
    setConnection(next); return next
  })
  render(<CalendarSettings />, { wrapper })
  const enable = await screen.findByRole("button", { name: "Enable sync" }) as HTMLButtonElement
  expect(enable.disabled).toBe(true)
  expect(api.post).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button", { name: "Verify connection" }))
  await waitFor(() => expect(enable.disabled).toBe(false))
  fireEvent.click(enable)
  const pause = await screen.findByRole("button", { name: "Pause sync" })
  expect(api.patch).toHaveBeenCalledWith("/calendar/connections/one/sync", { enabled: true })
  await waitFor(() => expect((pause as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(pause)
  await screen.findByRole("button", { name: "Enable sync" })
  expect(api.patch).toHaveBeenCalledWith("/calendar/connections/one/sync", { enabled: false })
})

it("shows manual sync errors and allows an explicit retry", async () => {
  serveConnection({ ...connection, enabled: true })
  vi.mocked(api.post).mockRejectedValueOnce(new Error("Server unavailable")).mockResolvedValueOnce({})
  render(<CalendarSettings />, { wrapper })
  fireEvent.click(await screen.findByRole("button", { name: "Sync now" }))
  expect((await screen.findByRole("alert")).textContent).toContain("Server unavailable")
  await waitFor(() => expect((screen.getByRole("button", { name: "Sync now" }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole("button", { name: "Sync now" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull())
})

it("makes interrupted credential removal recoverable through Disconnect", async () => {
  const setConnection = serveConnection({ ...connection, state: "disconnected", credential_state: "removal_pending" })
  vi.mocked(api.post).mockImplementation(async () => {
    const next = { ...connection, state: "disconnected", credential_state: "absent" }
    setConnection(next); return next
  })
  render(<CalendarSettings />, { wrapper })
  await screen.findByText(/Credential removal incomplete/)
  expect((screen.getByRole("button", { name: "Verify connection" }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole("button", { name: "Disconnect" }))
  await waitFor(() => expect(screen.queryByText(/Credential removal incomplete/)).toBeNull())
  expect(api.post).toHaveBeenCalledWith("/calendar/connections/one/disconnect", {})
})

it("does not apply an old discovery result after changing the setup target", async () => {
  serveConnection()
  let resolve!: (value: unknown) => void
  vi.mocked(api.post).mockReturnValue(new Promise(yes => { resolve = yes }))
  render(<CalendarSettings />, { wrapper })
  await screen.findByRole("option", { name: connection.server_url })
  fireEvent.change(screen.getByLabelText("Connection"), { target: { value: "one" } })
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: "person" } })
  fireEvent.change(screen.getByLabelText("Password or app password"), { target: { value: "old-secret" } })
  fireEvent.click(screen.getByRole("button", { name: "Discover calendars" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1))
  fireEvent.change(screen.getByLabelText("Connection"), { target: { value: "" } })
  await act(async () => resolve([{ url: connection.calendar_url, display_name: "Old destination", writable: true, supports_vevent: true }]))
  expect(screen.queryByLabelText("Remote calendar")).toBeNull()
  expect(screen.getByLabelText("Server URL")).toBeTruthy()
  expect((screen.getByLabelText("Password or app password") as HTMLInputElement).value).toBe("")
})

it("never restores credentials or discovery results after leaving and returning", async () => {
  serveConnection()
  let resolve!: (value: unknown) => void
  vi.mocked(api.post).mockReturnValue(new Promise(yes => { resolve = yes }))
  const first = render(<CalendarSettings />, { wrapper })
  await screen.findByRole("option", { name: connection.server_url })
  fireEvent.change(screen.getByLabelText("Connection"), { target: { value: "one" } })
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: "person" } })
  fireEvent.change(screen.getByLabelText("Password or app password"), { target: { value: "ephemeral" } })
  fireEvent.click(screen.getByRole("button", { name: "Discover calendars" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1))
  first.unmount()
  render(<CalendarSettings />, { wrapper })
  expect(screen.getByLabelText("Connection").matches(":disabled")).toBe(true)
  expect(screen.getByText("Contacting calendar server…")).toBeTruthy()
  await act(async () => resolve([{ url: connection.calendar_url, display_name: "Old destination", writable: true, supports_vevent: true }]))
  expect(screen.queryByLabelText("Remote calendar")).toBeNull()
  expect((screen.getByLabelText("Password or app password") as HTMLInputElement).value).toBe("")
  expect(client.getMutationCache().getAll()).toHaveLength(0)
})

it.each(["Username", "Password or app password", "Authentication"])("invalidates discovered calendars when %s changes", async field => {
  serveConnection()
  vi.mocked(api.post).mockResolvedValue([{ url: connection.calendar_url, display_name: "Events", writable: true, supports_vevent: true }])
  render(<CalendarSettings />, { wrapper })
  await screen.findByRole("option", { name: connection.server_url })
  fireEvent.change(screen.getByLabelText("Connection"), { target: { value: "one" } })
  fireEvent.change(screen.getByLabelText("Username"), { target: { value: "person" } })
  fireEvent.change(screen.getByLabelText("Password or app password"), { target: { value: "secret" } })
  fireEvent.click(screen.getByRole("button", { name: "Discover calendars" }))
  await screen.findByLabelText("Remote calendar")
  fireEvent.change(screen.getByLabelText(field), { target: { value: field === "Authentication" ? "digest" : "changed" } })
  expect(screen.queryByLabelText("Remote calendar")).toBeNull()
  expect(screen.queryByRole("button", { name: "Connect and save credentials" })).toBeNull()
})

it("offers safe detachment, not remote deletion, for a conflict", async () => {
  serveConnection()
  const get = vi.mocked(api.get).getMockImplementation()!
  vi.mocked(api.get).mockImplementation(async path => path.endsWith("/links") ? [{ id: "link", connection_id: "one", local_block_id: "block", state: "conflict", selection_state: "opted_in", desired_action: "upsert", last_error: "Remote event changed" }] : get(path))
  vi.mocked(api.post).mockResolvedValue({})
  render(<CalendarSettings />, { wrapper })
  await screen.findByText("Remote event changed")
  expect(screen.queryByRole("button", { name: "Remove remote event" })).toBeNull()
  fireEvent.click(screen.getByRole("button", { name: "Stop syncing; keep remote" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/calendar/connections/one/links/link/detach", {}))
})

it("distinguishes acknowledged remote removal from queued deletion and deliberate detachment", async () => {
  const block = { id: "block", task_id: "task", kind: "all_day", start_date: "2026-11-02", end_date: "2026-11-04" }
  const removed = { id: "removed", connection_id: "one", local_block_id: "block", state: "detached", selection_state: "opted_out", desired_action: "delete", acknowledged_action: "delete", local_revision: 2, acknowledged_revision: 2, last_error: null }
  vi.mocked(api.get).mockImplementation(async path => {
    if (path === "/calendar/connections") return [connection]
    if (path === "/tasks") return [{ id: "task", title: "Prepare presentation" }]
    if (path === "/time-blocks") return [block]
    if (path.endsWith("/links")) return [removed, { ...removed, id: "pending", local_block_id: "pending", state: "pending", local_revision: 3 }, { ...removed, id: "detached", local_block_id: "detached", selection_state: "detached" }]
    return { connection, queued_count: 1, conflict_count: 0, error_count: 0, last_success_at: null, last_success_state: "unknown" }
  })
  render(<CalendarSettings />, { wrapper })
  const option = await screen.findByRole("option", { name: /Prepare presentation.*Remote removal complete/ })
  expect((option as HTMLOptionElement).disabled).toBe(false)
  expect(screen.getByText("Remote removal complete", { exact: true })).toBeTruthy()
  expect(screen.getByText("pending · removal queued", { exact: true })).toBeTruthy()
  expect(screen.getByText("Detached; further sync stopped", { exact: true })).toBeTruthy()
  expect(screen.getByText(/Earlier sync time unavailable/)).toBeTruthy()
})
