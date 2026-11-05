// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import { CommandPalette } from "./command-palette"
import { useUi } from "@/stores/ui"

vi.mock("@/hooks/api", () => ({
  useLists: () => ({ data: [] }),
  useTasks: () => ({ data: [] }),
}))
afterEach(() => {
  cleanup()
  useUi.setState(useUi.getInitialState())
  localStorage.clear()
  Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView")
})

it.each(["board", "calendar"] as const)("opens Matrix from the command menu while retaining the selected task scope and %s view", (view) => {
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() })
  useUi.setState({ section: "journal", view, search: "draft", paletteOpen: true, scope: { kind: "list", id: "work" } })
  render(<CommandPalette />)
  expect(screen.getByRole("option", { name: /Eisenhower Matrix/ })).toBeTruthy()
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "Matrix" } })
  fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" })
  expect(useUi.getState()).toMatchObject({ section: "matrix", view, search: "draft", scope: { kind: "list", id: "work" }, paletteOpen: false })
})
