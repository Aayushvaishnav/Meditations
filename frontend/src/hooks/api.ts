import type { ImportedOverlay } from "@/api/calendar-overlay-types"
import { calendarInboundKey } from "./calendar-inbound"
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react"
import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { calendarSetupPending, subscribeCalendarSetup } from "@/lib/calendar-setup-operation"
import { api, ApiError } from "@/api/client"
import type { CalendarImportTarget, CalendarImportResult, ImportedCalendarSource, ImportedCalendarEvent } from "@/api/calendar-import-types"
import { sseEvents } from "@/lib/stream"
import { createBackup } from "@/lib/backup"
import { createCalendarExport } from "@/lib/calendar-export"
import { createDataExport } from "@/lib/data-export"
import { startBrowserDownload, type FileDownloadResult } from "@/lib/file-download"
import { deadlineFromLegacy } from "@/lib/task-deadlines"
import { tasksKey, beginTaskChange, rollbackTaskChange, settleTaskChange, invalidateTasks, reconcileTasks, withoutTaskTree } from "./task-cache"
import type {
  AIConnectionTest,
  AiUsageView,
  Briefing,
  CaptureResult,
  CitationSource,
  DailyScoreResponse,
  InsightsResponse,
  AISettingsView,
  AppPrefs,
  JournalActivity,
  JournalDay,
  JournalEntry,
  JournalInput,
  PromptEntry,
  SearchHit,
  SearchStatus,
  Task,
  TaskInput,
  TaskList,
  TimeBlock,
  TimeBlockInput,
  CalendarConnection,
  CalendarSyncStatus,
  CalendarLinkView,
} from "@/api/types"

export const qk = {
  tasks: tasksKey,
  lists: ["lists"] as const,
  timeBlocks: ["time-blocks"] as const,
  health: ["health"] as const,
}

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

export function useHealth() {
  return useQuery({
    queryKey: qk.health,
    queryFn: () => api.get<{ status: string }>("/health"),
    refetchInterval: 30_000,
    retry: 0,
  })
}

function invalidateTelemetry(qc: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    qc.invalidateQueries({ queryKey: ["journal-activity"] }),
    qc.invalidateQueries({ queryKey: ["scores-daily"] }),
    qc.invalidateQueries({ queryKey: ["insights"] }),
  ])
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

export function useDecomposeTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (taskId: string) => api.post<{ subtasks: Task[]; advice: string }>(`/agents/decompose`, { task_id: taskId }),
    onSuccess: (data) => {
      invalidateTasks(qc)
      toast.success(data.subtasks.length > 0 ? `Added ${data.subtasks.length} subtasks` : "No subtasks suggested", {
        description: data.advice || undefined,
      })
    },
    onError: () => toast.error("AI breakdown failed — is the AI provider reachable?"),
  })
}

export function useSearch(query: string, enabled: boolean) {
  return useQuery({
    queryKey: ["search", query],
    queryFn: () => api.get<SearchHit[]>(`/search?q=${encodeURIComponent(query)}`),
    enabled: enabled && query.trim().length >= 2,
  })
}

export function useSearchStatus(enabled: boolean) {
  return useQuery({
    queryKey: ["search-status"],
    queryFn: () => api.get<SearchStatus>("/search/status"),
    enabled,
  })
}

export function useAISettings(enabled: boolean) {
  return useQuery({ queryKey: ["ai-settings"], queryFn: () => api.get<AISettingsView>("/settings/ai"), enabled })
}

export function useSaveAISettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: { provider: string; model_name: string; fast_model_name?: string; base_url: string | null; api_key?: string }) =>
      api.put<AISettingsView>("/settings/ai", input),
    onSuccess: (data) => {
      qc.setQueryData(["ai-settings"], data)
      qc.invalidateQueries({ queryKey: ["ai-settings"] })
      toast.success("AI settings saved")
    },
    onError: () => toast.error("Couldn't save AI settings"),
  })
}

export function useResetAISettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.delete<AISettingsView>("/settings/ai"),
    onSuccess: (data) => {
      qc.setQueryData(["ai-settings"], data)
      qc.invalidateQueries({ queryKey: ["ai-settings"] })
      toast.success("Reset to env defaults")
    },
    onError: () => toast.error("Couldn't reset AI settings"),
  })
}

export function useTestAI() {
  return useMutation({
    mutationFn: () => api.post<AIConnectionTest>("/settings/ai/test", {}),
    onError: () => toast.error("Test failed — is the backend running?"),
  })
}

export function useAppPrefs(enabled: boolean) {
  return useQuery({ queryKey: ["app-prefs"], queryFn: () => api.get<AppPrefs>("/settings/app"), enabled })
}

export function useSaveAppPrefs() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: { target_deep_work_hours?: number }) => api.put<AppPrefs>("/settings/app", input),
    onSuccess: (data) => {
      qc.setQueryData(["app-prefs"], data)
      return Promise.all([
        qc.invalidateQueries({ queryKey: ["app-prefs"] }),
        qc.invalidateQueries({ queryKey: ["scores-daily"] }),
      ])
    },
    onError: () => toast.error("Couldn't save preferences"),
  })
}

export function useBackup() {
  return useFileDownload(createBackup)
}

export function useDataExport() {
  return useFileDownload(createDataExport)
}

export function useCalendarExport() {
  return useFileDownload(createCalendarExport)
}

function useFileDownload<T = void>(create: (input: T) => Promise<FileDownloadResult>) {
  const active = useRef(false)
  const download = useRef<{ kind: "none" } | { kind: "active"; release: () => void }>({ kind: "none" })
  useEffect(() => {
    active.current = true
    return () => {
      active.current = false
      if (download.current.kind === "active") download.current.release()
      download.current = { kind: "none" }
    }
  }, [])
  return useMutation({
    mutationFn: async (input: T) => {
      const result = await create(input)
      if (result.kind !== "download") return result
      if (!active.current) return { kind: "left-view" } as const
      const release = startBrowserDownload(result.blob, result.filename)
      if (download.current.kind === "active") download.current.release()
      download.current = { kind: "active", release }
      return { kind: "download-started" } as const
    },
    retry: false,
    gcTime: 0,
  })
}

export function useReindex() {
  return useMutation({
    mutationFn: () => api.post<{ indexed: number; semantic: boolean }>("/search/reindex", {}),
    onSuccess: (data) =>
      toast.success(`Rebuilt index — ${data.indexed} documents`, {
        description: data.semantic ? "Semantic embeddings refreshed." : "Embedding model unavailable — keyword index only.",
      }),
    onError: () => toast.error("Couldn't rebuild the search index"),
  })
}

export function useInsights(days: number, enabled: boolean) {
  return useQuery({
    queryKey: ["insights", days],
    queryFn: () => api.get<InsightsResponse>(`/insights?days=${days}`),
    enabled,
  })
}

export function useDailyScore(day: string, enabled: boolean) {
  return useQuery({
    queryKey: ["scores-daily", day],
    queryFn: () => api.get<DailyScoreResponse>(`/scores/daily/${day}`),
    enabled,
  })
}

export function useCapture() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (text: string) => api.post<CaptureResult>("/agents/capture", { text }),
    onSuccess: (data) => {
      invalidateTasks(qc)
      qc.invalidateQueries({ queryKey: ["journal"] })
      qc.invalidateQueries({ queryKey: ["journal-days"] })
      void invalidateTelemetry(qc)
      toast.success(`Captured ${data.tasks.length} task${data.tasks.length === 1 ? "" : "s"}`, {
        description: data.journal_snippet ? "Snippet added to today's journal." : undefined,
      })
    },
    onError: (e) =>
      toast.error("Capture failed", {
        description: e instanceof Error && e.message ? e.message : "Is the AI provider reachable?",
      }),
  })
}

export function useJournalDays(start: string, end: string, enabled: boolean) {
  return useQuery({
    queryKey: ["journal-days", start, end],
    queryFn: () => api.get<JournalDay[]>(`/journal/days?from=${start}&to=${end}`),
    enabled,
  })
}

export function useJournalEntry(day: string) {
  return useQuery({
    queryKey: ["journal", day],
    queryFn: async () => {
      try {
        return await api.get<JournalEntry>(`/journal/${day}`)
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null // empty entry, not an error
        throw e
      }
    },
  })
}

export function useSaveJournal() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: JournalInput & { day: string }) =>
      api.put<{ saved: boolean } & Partial<JournalEntry>>(`/journal/${input.day}`, { raw_markdown: input.raw_markdown, mood: input.mood ?? null, energy: input.energy ?? null }),
    onMutate: async (input) => {
      await qc.cancelQueries({ queryKey: ["journal", input.day] })
      const prev = qc.getQueryData<JournalEntry>(["journal", input.day])
      if (prev) {
        qc.setQueryData<JournalEntry>(["journal", input.day], {
          ...prev,
          raw_markdown: input.raw_markdown,
          mood: input.mood ?? null,
          energy: input.energy ?? null,
          updated_at: new Date().toISOString(),
        })
      }
      return { prev }
    },
    onError: (_err, input, ctx) => {
      if (ctx?.prev) qc.setQueryData(["journal", input.day], ctx.prev)
      toast.error("Couldn't save journal entry")
    },
    onSettled: (_d, _e, input) => {
      qc.invalidateQueries({ queryKey: ["journal", input.day] })
      qc.invalidateQueries({ queryKey: ["journal-days"] })
    },
  })
}

export function useJournalActivity(day: string) {
  return useQuery({
    queryKey: ["journal-activity", day],
    queryFn: () => api.get<JournalActivity>(`/journal/${day}/activity`),
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

// --- streaming AI surfaces (SSE over fetch; imperative session state, not query cache) ---
export interface ChatMessage {
  role: "user" | "assistant"
  content: string
  sources?: CitationSource[]
  error?: boolean // failed turns are excluded from follow-up history
}

/** Ask-my-second-brain chat: answers stream in with citation sources attached. */
export function useSecondBrainChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [pending, setPending] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const send = useCallback(
    async (question: string) => {
      // error bubbles are not real assistant turns — never replay them as context
      const history = messages
        .filter((m) => !m.error)
        .map((m) => ({ role: m.role, content: m.content }))
      setPending(true)
      abortRef.current?.abort()
      const ac = new AbortController()
      abortRef.current = ac
      // patch by index: an aborted older stream must never touch the new turn
      const answerIdx = messages.length + 1
      setMessages((m) => [...m, { role: "user", content: question }, { role: "assistant", content: "" }])
      const patchAt = (patch: Partial<ChatMessage>) =>
        setMessages((m) => {
          if (ac.signal.aborted || m[answerIdx]?.role !== "assistant") return m
          const copy = [...m]
          copy[answerIdx] = { ...copy[answerIdx], ...patch }
          return copy
        })
      try {
        for await (const { event, data } of sseEvents("/agents/ask/stream", { question, history }, ac.signal)) {
          if (event === "partial") patchAt({ content: data.text })
          else if (event === "sources") patchAt({ sources: data })
          else if (event === "error") throw new Error(data.message)
        }
      } catch (e) {
        if (ac.signal.aborted) {
          patchAt({ content: "Stopped." })
        } else {
          patchAt({ content: `⚠ ${e instanceof Error ? e.message : "The answer failed."}`, error: true })
        }
      } finally {
        if (!ac.signal.aborted) setPending(false)
      }
    },
    [messages],
  )

  const reset = useCallback(() => {
    abortRef.current?.abort()
    setMessages([])
    setPending(false)
  }, [])

  return { messages, pending, send, reset }
}

/** The streamed daily review is a DailyReviewOutput, not yet a score row. */
export interface DailyReviewPartial {
  llm_nudge: number
  nudge_rationale: string
  feedback: string
  key_insight: string
  suggested_action_for_tomorrow: string
}

/** Streaming daily review: partials render live (keyed by day); the final one persists server-side. */
export function useDailyRollupStream() {
  const qc = useQueryClient()
  const [partial, setPartial] = useState<{ day: string; output: DailyReviewPartial } | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function review(day: string) {
    setPending(true)
    setPartial(null)
    setError(null)
    try {
      for await (const { event, data } of sseEvents(`/agents/rollup/daily/stream?day=${day}`, {})) {
        if (event === "partial") setPartial({ day, output: data })
        else if (event === "done") {
          setPartial(null)
          qc.invalidateQueries({ queryKey: ["scores-daily", day] })
          qc.invalidateQueries({ queryKey: ["journal-days"] })
          toast.success(`Daily review saved — score ${data.final_score.toFixed(1)}`)
        } else if (event === "error") throw new Error(data.message)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "AI review failed")
    } finally {
      setPending(false)
    }
  }

  return { partial, pending, error, review }
}

/** Streaming morning briefing. */
export function useBriefingStream() {
  const [partial, setPartial] = useState<Briefing | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function generate() {
    setPending(true)
    setPartial(null)
    setError(null)
    try {
      for await (const { event, data } of sseEvents("/agents/briefing/stream", {})) {
        if (event === "partial") setPartial(data)
        else if (event === "done") setPartial(data)
        else if (event === "error") throw new Error(data.message)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Briefing failed")
    } finally {
      setPending(false)
    }
  }

  return { partial, pending, error, generate }
}

export type AssistAction = "improve" | "continue" | "summarize"

/** Editor assist: streams the proposed markdown into `text`; caller decides accept/discard. */
export function useEditorAssist() {
  const [text, setText] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run(action: AssistAction, source: string): Promise<string | null> {
    setPending(true)
    setError(null)
    setText("")
    try {
      let final: string | null = null
      for await (const { event, data } of sseEvents("/agents/assist/stream", { action, text: source })) {
        if (event === "partial") setText(data.text)
        else if (event === "done") {
          final = data.text
          setText(data.text)
        } else if (event === "error") throw new Error(data.message)
      }
      return final
    } catch (e) {
      const message = e instanceof Error ? e.message : "The assist failed."
      setError(message)
      setText(null)
      toast.error("AI assist failed", { description: message })
      return null
    } finally {
      setPending(false)
    }
  }

  const clear = useCallback(() => {
    setText(null)
    setError(null)
  }, [])

  return { text, pending, error, run, clear }
}

// --- AI settings: prompts + usage ---
export function usePrompts(enabled: boolean) {
  return useQuery({
    queryKey: ["ai-prompts"],
    queryFn: () => api.get<{ prompts: PromptEntry[] }>("/settings/ai/prompts"),
    enabled,
  })
}

export function useSavePrompts() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (overrides: Record<string, string | null>) =>
      api.put<{ prompts: PromptEntry[] }>("/settings/ai/prompts", { overrides }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["ai-prompts"] })
      toast.success("Prompts saved")
    },
    onError: () => toast.error("Couldn't save prompts"),
  })
}

export function useAIUsage(days: number, enabled: boolean) {
  return useQuery({
    queryKey: ["ai-usage", days],
    queryFn: () => api.get<AiUsageView>(`/settings/ai/usage?days=${days}`),
    enabled,
  })
}

// Calendar control data never shares the canonical tasks cache
export const calendarKey = ["calendar-connections"] as const
const calendarMutationKey = ["calendar-control"] as const
export function useCalendarConnections() {
  return useQuery({ queryKey: calendarKey, queryFn: () => api.get<CalendarConnection[]>("/calendar/connections"), refetchInterval: 10_000 })
}
export function useCalendarStatus(id: string) {
  return useQuery({ queryKey: [...calendarKey, id, "status"], queryFn: () => api.get<CalendarSyncStatus>(`/calendar/connections/${id}/status`), refetchInterval: 10_000 })
}
export function useCalendarLinks(id: string) {
  return useQuery({ queryKey: [...calendarKey, id, "links"], queryFn: () => api.get<CalendarLinkView[]>(`/calendar/connections/${id}/links`), refetchInterval: 10_000 })
}
export function useCalendarControl() {
  const qc = useQueryClient()
  const pending = useIsMutating({ mutationKey: calendarMutationKey })
  const mutation = useMutation({
    mutationKey: calendarMutationKey,
    mutationFn: ({ path, method = "post", body = {} }: { path: string; method?: "post" | "patch"; body?: Record<string, unknown> }) => api[method](`/calendar/connections${path}`, body),
    onSettled: () => Promise.all([
      qc.invalidateQueries({ queryKey: calendarKey }),
      qc.invalidateQueries({ queryKey: calendarInboundKey }),
    ]),
  })
  return { ...mutation, isPending: pending > 0 }
}

export function useCalendarAllLinks() {
  return useQuery({
    queryKey: [...calendarKey, "all-links"],
    queryFn: async () => {
      const connections = await api.get<CalendarConnection[]>("/calendar/connections")
      return (await Promise.all(connections.map(connection =>
        api.get<CalendarLinkView[]>(`/calendar/connections/${connection.id}/links`),
      ))).flat()
    },
    refetchInterval: 10_000,
  })
}

export function useCalendarSetupPending() {
  return useSyncExternalStore(subscribeCalendarSetup, calendarSetupPending)
}

// Imported calendars have their own cache; uploads never change task telemetry
export const calendarImportsKey = ["calendar-imports"] as const
const calendarImportMutationKey = ["calendar-import-operation"] as const

export function useImportedCalendars() {
  return useQuery({
    queryKey: calendarImportsKey,
    queryFn: () => api.get<ImportedCalendarSource[]>("/calendar/imports"),
  })
}

export function useImportedCalendarEvents(target: CalendarImportTarget) {
  return useQuery({
    queryKey: [...calendarImportsKey, "events", target.kind === "existing" ? target.source_id : { kind: "new" }],
    enabled: target.kind === "existing",
    queryFn: () => {
      if (target.kind !== "existing") throw new Error("Choose an imported calendar first")
      return api.get<ImportedCalendarEvent[]>(`/calendar/imports/${encodeURIComponent(target.source_id)}/events`)
    },
  })
}

export function useCalendarImportPending() {
  return useIsMutating({ mutationKey: calendarImportMutationKey }) > 0
}

export function useImportCalendar() {
  const qc = useQueryClient()
  return useMutation({
    mutationKey: calendarImportMutationKey,
    mutationFn: async ({ target, file }: { target: CalendarImportTarget; file: File }) => {
      let content: string
      try {
        content = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(await file.arrayBuffer())
      } catch {
        throw new Error("Could not read this file as UTF-8. Choose a UTF-8 iCalendar file and retry.")
      }
      return api.post<CalendarImportResult>("/calendar/imports", { target, content })
    },
    onSettled: () => qc.invalidateQueries({ queryKey: calendarImportsKey }),
  })
}

export function useRemoveImportedCalendar() {
  const qc = useQueryClient()
  return useMutation({
    mutationKey: calendarImportMutationKey,
    mutationFn: (sourceId: string) => api.delete<void>(`/calendar/imports/${encodeURIComponent(sourceId)}`),
    onSettled: () => qc.invalidateQueries({ queryKey: calendarImportsKey }),
  })
}

export type OverlaySelection = { kind: "none" } | { kind: "source"; id: string }

export function useImportedCalendarOverlay(selection: OverlaySelection) {
  return useQuery({
    queryKey: ["calendar-imports", "overlay", selection],
    enabled: selection.kind === "source",
    queryFn: () => {
      if (selection.kind !== "source") throw new Error("Choose an imported calendar first")
      return api.get<ImportedOverlay>(`/calendar/imports/${encodeURIComponent(selection.id)}/overlay`)
    },
  })
}

export { webhooksKey, useWebhooks, useWebhookDeliveries, useWebhookAction } from "./webhooks"

export { calendarInboundKey, useInboundOverlay, useCalendarResume, useResumeCalendarReconciliation } from "./calendar-inbound"
