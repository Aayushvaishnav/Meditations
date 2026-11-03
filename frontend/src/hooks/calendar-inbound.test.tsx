// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import { useResumeCalendarReconciliation, useCalendarControl } from './api'

afterEach(() => { cleanup(); vi.restoreAllMocks() })
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const wrapper = ({ children }: {children: ReactNode}) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  return {client, wrapper}
}
it('subscribes while hidden, deduplicates overlapping signals and cleans up', async () => {
  let visibility = 'hidden'
  vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility as DocumentVisibilityState)
  let finish!: () => void
  const post = vi.spyOn(api, 'post').mockImplementation(() => new Promise<void>(resolve => { finish = resolve }) as never)
  const {wrapper} = setup()
  const hook = renderHook(() => useResumeCalendarReconciliation(), {wrapper})
  visibility = 'visible'
  act(() => { document.dispatchEvent(new Event('visibilitychange')); window.dispatchEvent(new Event('focus')) })
  await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
  act(() => finish())
  hook.unmount()
  act(() => window.dispatchEvent(new Event('focus')))
  expect(post).toHaveBeenCalledTimes(1)
})
it('sync controls invalidate inbound without touching tasks', async () => {
  vi.spyOn(api, 'post').mockResolvedValue({})
  const {client, wrapper} = setup()
  client.setQueryData(['calendar-inbound', 'overlay', 'c1'], {})
  client.setQueryData(['tasks'], [])
  const hook = renderHook(() => useCalendarControl(), {wrapper})
  await act(() => hook.result.current.mutateAsync({path: '/c1/sync'}))
  expect(client.getQueryState(['calendar-inbound', 'overlay', 'c1'])?.isInvalidated).toBe(true)
  expect(client.getQueryState(['tasks'])?.isInvalidated).toBe(false)
})

it('keeps event subscriptions stable across renders and deduplicates across consumers', async () => {
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  const add = vi.spyOn(window, 'addEventListener')
  let finish!: () => void
  const post = vi.spyOn(api, 'post').mockImplementation(() => new Promise<void>(resolve => { finish = resolve }) as never)
  const {client, wrapper} = setup()
  client.setQueryData(['calendar-inbound'], {})
  client.setQueryData(['calendar-connections'], [])
  const first = renderHook(() => useResumeCalendarReconciliation(), {wrapper})
  renderHook(() => useResumeCalendarReconciliation(), {wrapper})
  const before = add.mock.calls.filter(([type]) => type === 'focus').length
  first.rerender()
  expect(add.mock.calls.filter(([type]) => type === 'focus').length).toBe(before)
  act(() => window.dispatchEvent(new Event('focus')))
  await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
  await act(async () => finish())
  expect(client.getQueryState(['calendar-inbound'])?.isInvalidated).toBe(true)
  expect(client.getQueryState(['calendar-connections'])?.isInvalidated).toBe(true)
  act(() => window.dispatchEvent(new Event('focus')))
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2))
  await act(async () => finish())
})

it('releases a failed resume pass and invalidates last-good cache for status recovery', async () => {
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  const post = vi.spyOn(api, 'post').mockRejectedValueOnce(new Error('Resume failed')).mockResolvedValue(undefined)
  const {client, wrapper} = setup()
  client.setQueryData(['calendar-inbound'], {})
  renderHook(() => useResumeCalendarReconciliation(), {wrapper})
  await act(async () => { window.dispatchEvent(new Event('focus')) })
  expect(client.getQueryState(['calendar-inbound'])?.isInvalidated).toBe(true)
  await act(async () => { window.dispatchEvent(new Event('focus')) })
  expect(post).toHaveBeenCalledTimes(2)
})
