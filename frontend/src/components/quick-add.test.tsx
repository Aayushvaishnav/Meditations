// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { useUi } from "@/stores/ui"
import { QuickAdd } from "./quick-add"

const mocks = vi.hoisted(() => ({ create: vi.fn() }))
vi.mock("@/hooks/api", () => ({
  useLists: () => ({ data: [{ id: "work", name: "work" }] }),
  useCreateTask: () => ({ mutateAsync: mocks.create }),
  useCreateList: () => ({ mutateAsync: vi.fn() }),
  useCapture: () => ({ isPending: false }),
}))
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] })
  vi.setSystemTime(new Date(2026, 10, 2, 16))
  useUi.setState({ captureOpen: false })
  mocks.create.mockResolvedValue({})
})
afterEach(() => { cleanup(); vi.useRealTimers(); vi.resetAllMocks() })

it.each([
  ["Review #work", { kind: "none" }],
  ["Review today #work", { kind: "date", date: "2026-11-02" }],
  ["Review tomorrow #work", { kind: "date", date: "2026-11-03" }],
  ["Review tomorrow 9am #work", { kind: "timed", at: new Date(2026, 10, 3, 9).toISOString() }],
])("creates %s with explicit deadline intent", async (text, deadline) => {
  render(<QuickAdd />)
  const input = screen.getByRole("textbox")
  fireEvent.change(input, { target: { value: text } })
  fireEvent.keyDown(input, { key: "Enter" })
  await waitFor(() => expect(mocks.create).toHaveBeenCalledOnce())
  const payload = mocks.create.mock.calls[0][0]
  expect(payload).toMatchObject({ title: "Review", list_id: "work", deadline })
  expect(payload).not.toHaveProperty("due_date")
  await waitFor(() => expect((input as HTMLInputElement).value).toBe(""))
})
