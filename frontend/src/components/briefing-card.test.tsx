// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, expect, it, vi } from "vitest"
import { BriefingCard } from "./briefing-card"

const state = vi.hoisted(() => ({ events: [] as { event: string; data: unknown }[] }))
vi.mock("@/lib/stream", () => ({ sseEvents: async function* () { for (const event of state.events) yield event } }))
vi.mock("./recommendations/task-actions", () => ({ RecommendationTaskActions: ({ taskId }: { taskId: string }) => <button>Linked {taskId}</button> }))
afterEach(cleanup)
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><BriefingCard /></QueryClientProvider>)
}
const data = { top_focus: ["Prepare report"], recommendations: [{ text: "Prepare report", task_id: "stable-id" }], reasoning: "A manageable priority", overdue_count: 0, due_today_count: 1 }
it("enables ID-based actions only after a final response", async () => {
  state.events = [{ event: "partial", data }, { event: "done", data }]
  mount()
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Generate" })))
  expect(screen.getByRole("button", { name: "Linked stable-id" })).toBeTruthy()
})
it("retains failed partial text without executable actions and offers retry", async () => {
  state.events = [{ event: "partial", data }, { event: "error", data: { message: "Provider unavailable" } }]
  mount()
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Generate" })))
  expect(screen.getByText("Prepare report")).toBeTruthy()
  expect(screen.queryByRole("button", { name: "Linked stable-id" })).toBeNull()
  state.events = [{ event: "done", data }]
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Retry briefing" })))
  expect(screen.getByRole("button", { name: "Linked stable-id" })).toBeTruthy()
})
it("treats an interrupted stream as incomplete instead of enabling partial IDs", async () => {
  state.events = [{ event: "partial", data }]
  mount()
  fireEvent.click(screen.getByRole("button", { name: "Generate" }))
  await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("before completion"))
  expect(screen.queryByRole("button", { name: "Linked stable-id" })).toBeNull()
})
it("keeps legacy text-only briefings readable without guessing task links", async () => {
  state.events = [{ event: "done", data: { top_focus: ["Prepare report"], reasoning: "Legacy prompt" } }]
  mount()
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Generate" })))
  expect(screen.getByText("Prepare report")).toBeTruthy()
  expect(screen.queryByRole("button", { name: /Linked/ })).toBeNull()
})
