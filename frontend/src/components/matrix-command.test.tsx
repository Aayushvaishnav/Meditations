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

it("opens Matrix from the command menu while retaining the selected task scope", () => {
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() })
  useUi.setState({ section: "journal", view: "list", paletteOpen: true, scope: { kind: "list", id: "work" } })
  render(<CommandPalette />)
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "Matrix" } })
  fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" })
  expect(useUi.getState()).toMatchObject({ section: "tasks", view: "matrix", scope: { kind: "list", id: "work" }, paletteOpen: false })
})
