import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { DocumentIndexStatus } from "@/lib/progress-state"

export const journalStatusKey = (day: string) => ["journal-status", day] as const

export function useJournalStatus(day: string, enabled: boolean) {
  return useQuery({
    queryKey: journalStatusKey(day),
    queryFn: () => api.get<DocumentIndexStatus>(`/journal/${day}/status`),
    enabled,
  })
}

export function useReindexJournal() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (day: string) => api.post<DocumentIndexStatus>(`/journal/${day}/reindex`, {}),
    onSuccess: (status, day) => client.setQueryData(journalStatusKey(day), status),
    onSettled: (_status, _error, day) => {
      void client.invalidateQueries({ queryKey: journalStatusKey(day) })
      void client.invalidateQueries({ queryKey: ["search-status"] })
      void client.invalidateQueries({ queryKey: ["search"] })
    },
  })
}
