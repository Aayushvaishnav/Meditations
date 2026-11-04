// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import type { Task } from "@/api/types"
import { DeadlineMove } from "./deadline-move"

const task = { title: "Prepare", deadline: { kind: "date", date: "2026-03-08" } } as Task
afterEach(cleanup)
it("freezes editing locally until an explicit keyboard-accessible submission", () => {
  const onMove = vi.fn()
  render(<DeadlineMove task={task} pending={false} onMove={onMove} />)
  const input = screen.getByLabelText("Move deadline for Prepare")
  fireEvent.change(input, { target: { value: "2026-03-12" } })
  expect(onMove).not.toHaveBeenCalled()
  fireEvent.submit(input.closest("form")!)
  expect(onMove).toHaveBeenCalledExactlyOnceWith(new Date(2026, 2, 12))
})
it("disables edits and submission while a mutation is pending", () => {
  render(<DeadlineMove task={task} pending onMove={vi.fn()} />)
  expect((screen.getByLabelText("Move deadline for Prepare") as HTMLInputElement).disabled).toBe(true)
  expect((screen.getByRole("button", { name: "Move deadline" }) as HTMLButtonElement).disabled).toBe(true)
})
it.each(["", "10000-01-01"])("rejects invalid native date input %s before invoking a move", value => {
  const onMove = vi.fn()
  render(<DeadlineMove task={task} pending={false} onMove={onMove} />)
  const input = screen.getByLabelText("Move deadline for Prepare") as HTMLInputElement
  fireEvent.change(input, { target: { value } })
  expect(input.checkValidity()).toBe(false)
  fireEvent.submit(input.closest("form")!)
  expect(onMove).not.toHaveBeenCalled()
})
it("accepts a valid leap-day date", () => {
  const onMove = vi.fn()
  render(<DeadlineMove task={task} pending={false} onMove={onMove} />)
  const input = screen.getByLabelText("Move deadline for Prepare") as HTMLInputElement
  fireEvent.change(input, { target: { value: "2028-02-29" } })
  expect(input.checkValidity()).toBe(true)
  fireEvent.submit(input.closest("form")!)
  expect(onMove).toHaveBeenCalledExactlyOnceWith(new Date(2028, 1, 29))
})
