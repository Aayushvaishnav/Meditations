// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import { Header } from "./header"
import { TooltipProvider } from "./ui/tooltip"
import { useUi } from "@/stores/ui"
vi.mock("@/hooks/api", () => ({ useLists: () => ({ data: [] }) }))
afterEach(cleanup)
it("keeps the calendar filter visible, editable, clearable and keyboard-accessible", () => {
  useUi.setState({ view: "calendar", scope: { kind: "smart", id: "all" }, search: "existing filter" })
  render(<TooltipProvider><Header /></TooltipProvider>)
  const input = screen.getByRole("textbox") as HTMLInputElement
  expect(input.value).toBe("existing filter")
  fireEvent.click(screen.getByRole("button", { name: "Clear filter" }))
  expect(input.value).toBe("")
  fireEvent.keyDown(window, { key: "/" })
  expect(document.activeElement).toBe(input)
  fireEvent.change(input, { target: { value: "next filter" } })
  expect(useUi.getState().search).toBe("next filter")
  fireEvent.keyDown(input, { key: "Escape" })
  expect(input.value).toBe("")
})
