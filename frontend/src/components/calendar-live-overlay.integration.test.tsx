// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query"
import { afterEach, expect, it, vi } from "vitest"
import { api } from "@/api/client"
import { CalendarLiveOverlay } from "./calendar-live-overlay"
import type { InboundOverlay } from "@/api/calendar-inbound-types"

const overlay: InboundOverlay = {
  connection_id: "c1",
  reconciliation: { state: "current", capability: "sync_token", last_synced_at: "2026-01-15T10:00:00", last_error: null },
  items: [{ connection_id: "c1", id: "e1", uid: "u1", summary: "Dentist", status: "CONFIRMED", interval: { kind: "timed", start: "2026-01-15T09:00:00Z", end: "2026-01-15T10:00:00Z" } }],
  unplaced: [{ connection_id: "c1", id: "e2", uid: "u2", summary: "Weekly series", reason: "recurrence" }],
}
function mount(state = "connected", enabled = true, data = overlay) {
  const get = vi.spyOn(api, "get").mockImplementation(async path => {
    if (path === "/calendar/connections") return [{id: "c1", calendar_url: "https://dav.test/calendar", state, enabled}]
    if (path === "/calendar/connections/c1/inbound/overlay") return data
    throw new Error(`Unexpected path ${path}`)
  })
  const client = new QueryClient({ defaultOptions: {queries: {retry: false}} })
  render(<QueryClientProvider client={client}><CalendarLiveOverlay>{items => <div data-testid="items">{items.map(item => item.summary).join(",")}</div>}</CalendarLiveOverlay></QueryClientProvider>)
  return {get, client}
}
async function select() {
  await screen.findByRole("option", {name: "https://dav.test/calendar"})
  fireEvent.change(screen.getByLabelText("Live calendar"), { target: {value: "c1"} })
  await screen.findByText(/1 mirrored appointments/)
}
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); focusManager.setFocused(undefined) })

it('starts hidden, loads explicit selection and hides it without changing task cache', async () => {
  const {get, client} = mount()
  client.setQueryData(['tasks'], ['local'])
  await screen.findByRole('option', {name: 'https://dav.test/calendar'})
  expect(get.mock.calls.some(([path]) => path.includes('inbound'))).toBe(false)
  await select()
  expect(screen.getByTestId('items').textContent).toBe('Dentist')
  fireEvent.click(screen.getByText('Outside the grid (1)'))
  expect(screen.getByText('Weekly series')).toBeDefined()
  expect(screen.getByText(/Last successful check:/)).toBeDefined()
  fireEvent.change(screen.getByLabelText('Live calendar'), {target: {value: ''}})
  expect(screen.getByTestId('items').textContent).toBe('')
  expect(client.getQueryData(['tasks'])).toEqual(['local'])
})
it.each([
  ['connected', false, 'current', /Sync paused/],
  ['authentication_required', true, 'current', /Authentication required/],
  ['connected', true, 'error', /Could not refresh this calendar/],
] as const)('preserves last-good events and identifies stale %s/%s/%s', async (state, enabled, result, message) => {
  mount(state, enabled, {...overlay, reconciliation: {...overlay.reconciliation, state: result, last_error: result === 'error' ? 'Remote calendar unavailable.' : null}})
  await select()
  expect(screen.getByText(message)).toBeDefined()
  expect(screen.getByText(/Showing stale cached appointments/)).toBeDefined()
  expect(screen.getByTestId('items').textContent).toBe('Dentist')
  expect(screen.queryByText(/Up to date/)).toBeNull()
})
it('polls backend caches every ten seconds and hides cached events on retrieval failure', async () => {
  focusManager.setFocused(true)
  vi.useFakeTimers()
  const {get} = mount()
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  fireEvent.change(screen.getByLabelText("Live calendar"), { target: {value: "c1"} })
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  const before = get.mock.calls.filter(([path]) => path.includes('inbound')).length
  await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
  expect(get.mock.calls.filter(([path]) => path.includes('inbound')).length).toBe(before + 1)
  get.mockImplementation(async path => { if (path.includes('inbound')) throw new Error('Could not retrieve cache'); return [{id: 'c1', calendar_url: 'https://dav.test/calendar', state: 'connected', enabled: true}] })
  await act(async () => { await vi.advanceTimersByTimeAsync(10_000); await vi.advanceTimersByTimeAsync(1) })
  vi.useRealTimers()
  await waitFor(() => expect(screen.getByTestId('items').textContent).toBe(''))
  expect(screen.getByRole('alert')).toBeDefined()
})
