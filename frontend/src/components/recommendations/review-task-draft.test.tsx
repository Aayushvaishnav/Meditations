// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, expect, it, vi } from "vitest"
import { api } from "@/api/client"
import { DailyReviewCard } from "@/components/daily-review-card"
import { ReviewTaskDraft } from "./review-task-draft"

const review = vi.hoisted(() => ({
  score: { persisted: true, final_score: 90, suggested_action_for_tomorrow: "  Take a walk  " },
  stream: { pending: false, partial: null as unknown, error: null, review: vi.fn() },
}))
vi.mock("@/api/client", () => ({ api: { post: vi.fn() } }))
vi.mock("@/hooks/api", async () => {
  const tasks = await import("@/hooks/tasks")
  return { useCreateTask: tasks.useCreateTask, useDailyScore: () => ({ data: review.score }), useDailyRollupStream: () => review.stream }
})
const clients: QueryClient[] = []
function mount(card = false) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  clients.push(client)
  const content = (day: string) => <QueryClientProvider client={client}>{card ? <DailyReviewCard day={day} /> :
    <ReviewTaskDraft key={day} day={day} recommendation="  Take a walk  " />}</QueryClientProvider>
  const view = render(content("2026-11-05"))
  return { update: (day = "2026-11-05") => view.rerender(content(day)) }
}
afterEach(() => {
  cleanup()
  clients.splice(0).forEach(client => client.clear())
  vi.resetAllMocks()
  review.stream.pending = false
  review.stream.partial = null
  review.score.persisted = true
})
it("requires explicit confirmation and submits edited title with a calendar date unchanged", async () => {
  vi.mocked(api.post).mockResolvedValue({ id: "created" })
  const view = mount()
  fireEvent.click(screen.getByRole("button", { name: "Draft task" }))
  expect(api.post).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText("Task title"), { target: { value: "Walk by the river" } })
  fireEvent.change(screen.getByLabelText("Deadline (optional calendar date)"), { target: { value: "2026-11-06" } })
  view.update()
  expect((screen.getByLabelText("Task title") as HTMLInputElement).value).toBe("Walk by the river")
  fireEvent.click(screen.getByRole("button", { name: "Create task" }))
  await screen.findByText("Task created")
  expect(api.post).toHaveBeenCalledExactlyOnceWith("/tasks", {
    title: "Walk by the river", deadline: { kind: "date", date: "2026-11-06" },
    description: "Follow-up from daily review 2026-11-05\n\n  Take a walk  ",
  })
  expect(screen.queryByRole("button", { name: "Create task" })).toBeNull()
})
it("preserves failed drafts for retry and prevents concurrent submission", async () => {
  vi.mocked(api.post).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ id: "created" })
  mount()
  fireEvent.click(screen.getByText("Draft task"))
  fireEvent.change(screen.getByLabelText("Task title"), { target: { value: "Edited walk" } })
  const form = screen.getByRole("button", { name: "Create task" }).closest("form")!
  fireEvent.submit(form)
  fireEvent.submit(form)
  await screen.findByRole("alert")
  expect(api.post).toHaveBeenCalledTimes(1)
  expect((screen.getByLabelText("Task title") as HTMLInputElement).value).toBe("Edited walk")
  fireEvent.submit(form)
  await screen.findByText("Task created")
  expect(api.post).toHaveBeenCalledTimes(2)
})
it("does not move an edited draft to another day", () => {
  const view = mount(true)
  fireEvent.click(screen.getByText("Draft task"))
  fireEvent.change(screen.getByLabelText("Task title"), { target: { value: "Old day draft" } })
  view.update("2026-11-06")
  expect(screen.queryByLabelText("Task title")).toBeNull()
  fireEvent.click(screen.getByText("Draft task"))
  expect((screen.getByLabelText("Task title") as HTMLInputElement).value).toBe("Take a walk")
  expect(api.post).not.toHaveBeenCalled()
})
it("never exposes an actionable draft for partial or unsaved reviews", async () => {
  review.stream.pending = true
  review.stream.partial = { day: "2026-11-05", output: { suggested_action_for_tomorrow: "Partial suggestion" } }
  const view = mount(true)
  expect(screen.queryByRole("button", { name: "Draft task" })).toBeNull()
  review.stream.pending = false
  view.update()
  expect(screen.queryByRole("button", { name: "Draft task" })).toBeNull()
  review.stream.partial = null
  review.score.persisted = false
  view.update()
  expect(screen.queryByRole("button", { name: "Draft task" })).toBeNull()
  review.score.persisted = true
  view.update()
  await waitFor(() => expect(screen.getByText("Draft task")).toBeTruthy())
})
it("cancel does not create a task", () => {
  mount()
  fireEvent.click(screen.getByText("Draft task"))
  fireEvent.click(screen.getByText("Cancel"))
  expect(screen.queryByLabelText("Task title")).toBeNull()
  expect(api.post).not.toHaveBeenCalled()
})
it("keeps edited drafts when a same-day review rerun fails", () => {
  const view = mount(true)
  fireEvent.click(screen.getByRole("button", { name: "Draft task" }))
  fireEvent.change(screen.getByLabelText("Task title"), { target: { value: "Keep this edit" } })
  fireEvent.change(screen.getByLabelText("Deadline (optional calendar date)"), { target: { value: "2026-11-10" } })
  review.stream.pending = true
  view.update()
  expect(screen.queryByRole("button", { name: "Create task" })).toBeNull()
  review.stream.pending = false
  view.update()
  expect((screen.getByLabelText("Task title") as HTMLInputElement).value).toBe("Keep this edit")
  expect((screen.getByLabelText("Deadline (optional calendar date)") as HTMLInputElement).value).toBe("2026-11-10")
})
it("keeps successful creation protection after a failed same-day review rerun", async () => {
  vi.mocked(api.post).mockResolvedValue({ id: "created" })
  const view = mount(true)
  fireEvent.click(screen.getByRole("button", { name: "Draft task" }))
  fireEvent.click(screen.getByRole("button", { name: "Create task" }))
  await screen.findByText("Task created")
  review.stream.pending = true
  view.update()
  review.stream.pending = false
  view.update()
  expect(screen.getByText("Task created")).toBeTruthy()
  expect(screen.queryByRole("button", { name: "Draft task" })).toBeNull()
  expect(api.post).toHaveBeenCalledTimes(1)
})
