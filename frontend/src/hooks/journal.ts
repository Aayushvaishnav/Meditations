import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { api, ApiError } from "@/api/client"
import type { InsightsResponse, DailyScoreResponse, JournalDay, JournalEntry, JournalInput, JournalActivity } from "@/api/types"

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
export function useJournalDays(start: string, end: string, enabled: boolean) {
  return useQuery({
    queryKey: ["journal-days", start, end],
    queryFn: () => api.get<JournalDay[]>(`/journal/days?from=${start}&to=${end}`),
    enabled,
  })
}
type JournalEditableFields = Pick<JournalEntry, "date" | "raw_markdown" | "mood" | "energy">
export type JournalDocument = JournalEditableFields & Partial<Omit<JournalEntry, keyof JournalEditableFields>>
export function useJournalEntry(day: string) {
  return useQuery({
    queryKey: ["journal", day],
    queryFn: async (): Promise<JournalDocument | null> => {
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
      const prev = qc.getQueryData<JournalDocument | null>(["journal", input.day])
      const document: JournalDocument = {
        ...prev,
        date: input.day,
        raw_markdown: input.raw_markdown,
        mood: input.mood ?? null,
        energy: input.energy ?? null,
      }
      const hasContent = document.raw_markdown.trim() || document.mood !== null || document.energy !== null
      qc.setQueryData<JournalDocument | null>(["journal", input.day], hasContent ? document : null)
      return { prev }
    },
    onError: (_err, input, ctx) => {
      if (ctx) {
        if (ctx.prev === undefined) qc.removeQueries({ queryKey: ["journal", input.day], exact: true })
        else qc.setQueryData(["journal", input.day], ctx.prev)
      }
      toast.error("Couldn't save journal entry")
    },
    onSettled: (_d, _e, input) => {
      qc.invalidateQueries({ queryKey: ["journal", input.day] })
      qc.invalidateQueries({ queryKey: ["journal-status", input.day] })
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
