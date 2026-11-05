// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, expect, it, vi } from "vitest"
import { InsightsView } from "./insights"
import { LineChart, BarsChart } from "./charts"

const state = vi.hoisted(() => ({ loading: false, error: false }))
vi.mock("@/hooks/api", () => ({ useInsights: () => ({ isLoading: state.loading, isError: state.error, data: { series: [], habits: [], weekly: [], monthly: [] } }) }))
afterEach(() => { cleanup(); state.loading = false; state.error = false })

it("keeps the activated period control focused through loading and failure", () => {
  const view = render(<InsightsView />)
  const period = screen.getByRole("button", { name: "14d" })
  period.focus()
  fireEvent.click(period)
  expect(period.getAttribute("aria-pressed")).toBe("true")
  state.loading = true
  view.rerender(<InsightsView />)
  expect(document.activeElement).toBe(period)
  state.loading = false
  state.error = true
  view.rerender(<InsightsView />)
  expect(document.activeElement).toBe(period)
  expect(screen.getByRole("button", { name: "30d" }).getAttribute("aria-pressed")).toBe("false")
})

it("exposes meaningful accessible names for nonempty chart graphics", () => {
  render(<><LineChart label="Daily scores over 30 days" points={[{ x: 0, y: .5 }]} /><BarsChart label="Daily focus hours over 30 days" values={[2]} max={4} /></>)
  expect(screen.getByRole("img", { name: "Daily scores over 30 days" })).toBeTruthy()
  expect(screen.getByRole("img", { name: "Daily focus hours over 30 days" })).toBeTruthy()
})
