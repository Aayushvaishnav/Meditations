// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, expect, it } from "vitest"
import { CalendarSources } from "./calendar-sources"
import { useUi } from "@/stores/ui"

afterEach(cleanup)

it("retains controls and their state while hidden and routes management to Settings", () => {
  useUi.setState({ section: "tasks" })
  render(<CalendarSources summary="Live hidden · Imported hidden"><input aria-label="Source state" defaultValue="retained" /></CalendarSources>)
  const trigger = screen.getByRole("button", { name: "Calendar sources" })
  expect(trigger.getAttribute("aria-expanded")).toBe("false")
  expect(screen.queryByRole("textbox")).toBeNull()
  fireEvent.click(trigger)
  const input = screen.getByRole("textbox") as HTMLInputElement
  fireEvent.change(input, { target: { value: "chosen" } })
  fireEvent.click(trigger)
  expect(screen.queryByRole("textbox")).toBeNull()
  expect(input.isConnected).toBe(true)
  fireEvent.click(trigger)
  expect(screen.getByRole("textbox")).toBe(input)
  expect(input.value).toBe("chosen")
  fireEvent.click(screen.getByRole("button", { name: "Manage calendars in Settings" }))
  expect(useUi.getState().section).toBe("settings")
})
