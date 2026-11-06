import { useUi } from "@/stores/ui"
import { useCallback, useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { api } from "@/api/client"
import { sseEvents } from "@/lib/stream"
import { invalidateTasks } from "./task-cache"
import { invalidateTelemetry } from "./invalidation"
import type { Task, AISettingsView, AIConnectionTest, CaptureResult, CitationSource, Briefing, PromptEntry, AiUsageView } from "@/api/types"

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
export function useCapture() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (text: string) => api.post<CaptureResult>("/agents/capture", { text }),
    onSuccess: (data) => {
      invalidateTasks(qc)
      qc.invalidateQueries({ queryKey: ["journal"] })
      qc.invalidateQueries({ queryKey: ["journal-status"] })
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
      let done = false
      for await (const { event, data } of sseEvents(`/agents/rollup/daily/stream?day=${day}`, {})) {
        if (event === "partial") setPartial({ day, output: data })
        else if (event === "done") {
          done = true
          setPartial(null)
          qc.invalidateQueries({ queryKey: ["scores-daily", day] })
          qc.invalidateQueries({ queryKey: ["journal-days"] })
          toast.success(useUi.getState().scoreDisplay === "reflection"
            ? "AI review saved locally"
            : `AI review saved locally; score ${data.final_score.toFixed(1)}`)
        } else if (event === "error") throw new Error(data.message)
      }
      if (!done) throw new Error("Review ended before completion. Run the review again to retry.")
    } catch (e) {
      setPartial(null)
      setError(e instanceof Error ? e.message : "AI review failed")
    } finally {
      setPending(false)
    }
  }

  return { partial, pending, error, review }
}

/** Streaming morning briefing; only a final server response enables task actions. */
export function useBriefingStream() {
  const [partial, setPartial] = useState<Briefing | null>(null)
  const [status, setStatus] = useState<"idle" | "streaming" | "complete" | "error">("idle")
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function generate() {
    setPending(true)
    setStatus("streaming")
    setPartial(null)
    setError(null)
    try {
      let done = false
      for await (const { event, data } of sseEvents("/agents/briefing/stream", {})) {
        if (event === "partial") setPartial(data)
        else if (event === "done") {
          setPartial(data)
          setStatus("complete")
          done = true
        } else if (event === "error") throw new Error(data.message)
      }
      if (!done) throw new Error("Briefing ended before completion. Try generating it again.")
    } catch (e) {
      setStatus("error")
      setError(e instanceof Error ? e.message : "Briefing failed")
    } finally {
      setPending(false)
    }
  }

  return { partial, pending, error, status, generate }
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
