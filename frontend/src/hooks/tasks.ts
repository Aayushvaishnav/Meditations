import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { api } from "@/api/client"
import { deadlineFromLegacy } from "@/lib/task-deadlines"
import { beginTaskChange, rollbackTaskChange, settleTaskChange, invalidateTasks, reconcileTasks, withoutTaskTree } from "./task-cache"
import { qk } from "./query-keys"
import { invalidateTelemetry } from "./invalidation"
import type { Task, TaskInput, TaskList, TimeBlock, TimeBlockInput } from "@/api/types"

export function useTasks() {
  const qc = useQueryClient()
  return useQuery({
    queryKey: qk.tasks,
    queryFn: async ({ signal }) => {
      const tasks = await api.get<Task[]>("/tasks")
      return signal.aborted ? tasks : reconcileTasks(qc, tasks)
    },
  })
}
export function useTimeBlocks() {
  return useQuery({ queryKey: qk.timeBlocks, queryFn: () => api.get<TimeBlock[]>("/time-blocks") })
}
export function useReplaceTimeBlock() {
  const qc = useQueryClient()
  const mutationKey = ["replace-time-block"] as const
  const pendingCount = useIsMutating({ mutationKey })
  const mutation = useMutation({
    mutationKey,
    mutationFn: ({ id, input }: { id: string; input: TimeBlockInput }) =>
      api.put<TimeBlock>(`/time-blocks/${id}`, input),
    onSuccess: confirmed => {
      qc.setQueryData<TimeBlock[]>(qk.timeBlocks, blocks =>
        blocks?.map(block => block.id === confirmed.id ? confirmed : block),
      )
    },
    onError: () => toast.error("Couldn't update time block"),
    onSettled: () => qc.invalidateQueries({ queryKey: qk.timeBlocks }),
  })
  return { ...mutation, isPending: pendingCount > 0 }
}
export function useLists() {
  return useQuery({ queryKey: qk.lists, queryFn: () => api.get<TaskList[]>("/lists") })
}
export function useCreateTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: TaskInput) => api.post<Task>("/tasks", input),
    onMutate: async (input) => {
      const now = new Date().toISOString()
      const tempId = `temp-${crypto.randomUUID()}`
      const deadline = input.deadline ?? deadlineFromLegacy(input.due_date ?? null)
      const temp: Task = {
        id: tempId,
        list_id: input.list_id ?? null,
        parent_id: input.parent_id ?? null,
        title: input.title,
        description: input.description ?? null,
        priority: input.priority ?? 0,
        importance: input.importance ?? "unassigned",
        urgency: input.urgency ?? "unassigned",
        status: input.status ?? "todo",
        deadline,
        due_date: deadline.kind === "timed" ? deadline.at : null,
        estimated_minutes: input.estimated_minutes ?? null,
        actual_minutes: 0,
        recurrence_rule: input.recurrence_rule ?? null,
        recurrence_series_id: input.recurrence_rule ? tempId : null,
        recurrence_occurrence: input.recurrence_rule ? 0 : null,
        tags: input.tags ?? [],
        order_index: Date.now(),
        completed_at: null,
        created_at: now,
        updated_at: now,
      }
      const change = await beginTaskChange(qc, tasks => [...tasks, temp])
      return { change }
    },
    onError: (_err, _input, ctx) => {
      if (ctx) rollbackTaskChange(qc, ctx.change)
      toast.error("Couldn't create task")
    },
    onSettled: (data, _error, _input, ctx) => Promise.all([
      settleTaskChange(qc, ctx?.change, data ? tasks => {
        if (tasks.some(task => task.id === data.id)) return tasks
        return [...tasks, data]
      } : undefined),
      invalidateTelemetry(qc),
    ]),
  })
}
export function useUpdateTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<Task> }) =>
      api.patch<Task>(`/tasks/${id}`, patch),
    onMutate: async ({ id, patch }) => {
      const extras: Partial<Task> = {}
      if (patch.deadline !== undefined || patch.due_date !== undefined) {
        const deadline = patch.deadline ?? deadlineFromLegacy(patch.due_date ?? null)
        extras.deadline = deadline
        extras.due_date = deadline.kind === "timed" ? deadline.at : null
      }
      if (patch.status === "completed") extras.completed_at = new Date().toISOString()
      if (patch.status !== undefined && patch.status !== "completed") extras.completed_at = null
      const change = await beginTaskChange(qc, tasks => tasks.map(task => task.id === id ? { ...task, ...patch, ...extras } : task))
      return { change }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx) rollbackTaskChange(qc, ctx.change)
      toast.error("Couldn't update task")
    },
    onSettled: (_data, _error, _input, ctx) => Promise.all([
      settleTaskChange(qc, ctx?.change),
      invalidateTelemetry(qc),
    ]),
  })
}
export function useDeleteTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/tasks/${id}`),
    onMutate: async (id) => {
      const change = await beginTaskChange(qc, tasks => withoutTaskTree(tasks, id))
      return { change }
    },
    onError: (_err, _id, ctx) => {
      if (ctx) rollbackTaskChange(qc, ctx.change)
      toast.error("Couldn't delete task")
    },
    onSettled: (_data, _error, _input, ctx) => Promise.all([
      settleTaskChange(qc, ctx?.change),
      invalidateTelemetry(qc),
      qc.invalidateQueries({ queryKey: qk.timeBlocks }),
    ]),
  })
}
export function useCreateSession() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: { task_id?: string | null; duration_minutes: number; session_type?: string }) =>
      api.post<Task>("/focus/sessions", input),
    onSettled: () => Promise.all([
      invalidateTasks(qc),
      qc.invalidateQueries({ queryKey: ["focus-summary"] }),
      invalidateTelemetry(qc),
    ]),
  })
}
export function useCreateList() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: { name: string }) => api.post<TaskList>("/lists", input),
    onMutate: async (input) => {
      await qc.cancelQueries({ queryKey: qk.lists })
      const prev = qc.getQueryData<TaskList[]>(qk.lists)
      const temp: TaskList = {
        id: `temp-${crypto.randomUUID()}`,
        name: input.name,
        color: "#64748b",
        icon: null,
        is_favorite: false,
        created_at: new Date().toISOString(),
      }
      qc.setQueryData<TaskList[]>(qk.lists, (old) => [...(old ?? []), temp])
      return { prev }
    },
    onError: (_err, _input, ctx) => {
      if (ctx?.prev) qc.setQueryData(qk.lists, ctx.prev)
      toast.error("Couldn't create list")
    },
    onSettled: () => qc.invalidateQueries({ queryKey: qk.lists }),
  })
}
export function useUpdateList() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<TaskList> }) =>
      api.patch<TaskList>(`/lists/${id}`, patch),
    onMutate: async ({ id, patch }) => {
      await qc.cancelQueries({ queryKey: qk.lists })
      const prev = qc.getQueryData<TaskList[]>(qk.lists)
      qc.setQueryData<TaskList[]>(qk.lists, (old) =>
        (old ?? []).map((l) => (l.id === id ? { ...l, ...patch } : l)),
      )
      return { prev }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(qk.lists, ctx.prev)
      toast.error("Couldn't update list")
    },
    onSettled: () => qc.invalidateQueries({ queryKey: qk.lists }),
  })
}
export function useDeleteList() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/lists/${id}`),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: qk.lists })
      const prevLists = qc.getQueryData<TaskList[]>(qk.lists)
      const change = await beginTaskChange(qc, tasks => tasks.map(task => task.list_id === id ? { ...task, list_id: null } : task))
      qc.setQueryData<TaskList[]>(qk.lists, (old) => (old ?? []).filter((l) => l.id !== id))
      return { prevLists, change }
    },
    onError: (_err, _id, ctx) => {
      if (ctx?.prevLists) qc.setQueryData(qk.lists, ctx.prevLists)
      if (ctx) rollbackTaskChange(qc, ctx.change)
      toast.error("Couldn't delete list")
    },
    onSettled: (_data, _error, _id, ctx) => Promise.all([
      qc.invalidateQueries({ queryKey: qk.lists }),
      qc.invalidateQueries({ queryKey: qk.timeBlocks }),
      settleTaskChange(qc, ctx?.change),
    ]),
  })
}
