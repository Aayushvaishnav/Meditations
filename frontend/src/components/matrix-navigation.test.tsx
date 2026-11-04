// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import { Header } from "./header"
import { TooltipProvider } from "./ui/tooltip"
import { useUi } from "@/stores/ui"
vi.mock("@/hooks/api", () => ({ useLists: () => ({ data: [] }) }))
afterEach(() => { cleanup(); localStorage.removeItem("journal-ui") })
it("selects and rehydrates Matrix without removing the other view choices", async () => {
  useUi.setState({ view: "list", scope: { kind: "smart", id: "all" } })
  render(<TooltipProvider><Header /></TooltipProvider>)
  fireEvent.click(screen.getByRole("button", { name: "Matrix view" }))
  expect(useUi.getState().view).toBe("matrix")
  expect(screen.getByRole("button", { name: "Matrix view" }).getAttribute("aria-pressed")).toBe("true")
  for (const name of ["List view", "Board view", "Calendar view"]) {
    expect(screen.getByRole("button", { name }).getAttribute("aria-pressed")).toBe("false")
  }
  const persisted = localStorage.getItem("journal-ui")!
  expect(JSON.parse(persisted).state.view).toBe("matrix")
  act(() => useUi.setState({ view: "board" }))
  localStorage.setItem("journal-ui", persisted)
  await act(async () => { await useUi.persist.rehydrate() })
  expect(screen.getByRole("button", { name: "Matrix view" }).getAttribute("aria-pressed")).toBe("true")
})
