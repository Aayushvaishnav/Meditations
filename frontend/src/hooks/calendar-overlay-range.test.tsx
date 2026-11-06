// @vitest-environment jsdom
import type { PropsWithChildren } from "react"
import { act, cleanup, renderHook, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, expect, it, vi } from "vitest"
import { api } from "@/api/client"
import { useImportedCalendarOverlay } from "./calendar-imports"
import { useInboundOverlay } from "./calendar-inbound"
import type { CalendarOverlayWindow } from "@/lib/calendar-overlay-window"

afterEach(() => { cleanup(); vi.restoreAllMocks() })

it.each(["imported", "live"] as const)("isolates %s source, range and legacy caches without displaying a prior range while fetching", async kind => {
  const first = { start: "2026-03-01", end: "2026-04-01" }
  const second = { start: "2026-04-01", end: "2026-05-01" }
  let resolveNext!: (value: unknown) => void
  const get = vi.spyOn(api, "get").mockResolvedValue({ items: [{ id: "march-instance" }], unplaced: [] })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  const useOverlay = (id: string, window?: CalendarOverlayWindow) => {
    const imported = useImportedCalendarOverlay(kind === "imported" ? { kind: "source", id } : { kind: "none" }, window)
    const live = useInboundOverlay(kind === "live" ? { kind: "connection", id } : { kind: "none" }, window)
    return kind === "imported" ? imported : live
  }
  const { result, rerender } = renderHook(({ id, window }: { id: string; window?: CalendarOverlayWindow }) => useOverlay(id, window), { wrapper, initialProps: { id: "source/a", window: first } as { id: string; window?: CalendarOverlayWindow } })
  const base = kind === "imported" ? "/calendar/imports/source%2Fa/overlay" : "/calendar/connections/source%2Fa/inbound/overlay"
  await waitFor(() => expect(result.current.isSuccess).toBe(true))
  expect(get).toHaveBeenLastCalledWith(`${base}?start=2026-03-01&end=2026-04-01`)
  get.mockImplementationOnce(() => new Promise(resolve => { resolveNext = resolve }))
  rerender({ id: "source/a", window: second })
  await waitFor(() => expect(result.current.isFetching).toBe(true))
  expect(result.current.data).toBeUndefined()
  await act(async () => resolveNext({ items: [{ id: "april-instance" }], unplaced: [] }))
  await waitFor(() => expect(result.current.data?.items[0].id).toBe("april-instance"))
  const calls = get.mock.calls.length
  rerender({ id: "source/a", window: first })
  expect(result.current.data?.items[0].id).toBe("march-instance")
  expect(get.mock.calls).toHaveLength(calls)
  rerender({ id: "source/a", window: undefined })
  await waitFor(() => expect(get).toHaveBeenLastCalledWith(base))
  rerender({ id: "other", window: first })
  await waitFor(() => expect(get.mock.calls.at(-1)?.[0]).toContain(kind === "imported" ? "/imports/other/overlay?" : "/connections/other/inbound/overlay?"))
  expect(client.getQueryCache().findAll({ predicate: query => query.state.status === "success" })).toHaveLength(4)
  client.clear()
})
