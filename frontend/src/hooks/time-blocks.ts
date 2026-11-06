import { useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { TimeBlock, TimeBlockInput } from "@/api/types"
import { qk } from "./query-keys"

export function useCreateTimeBlock() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: TimeBlockInput) => api.post<TimeBlock>("/time-blocks", input),
    onSuccess: block => {
      client.setQueryData<TimeBlock[]>(qk.timeBlocks, blocks => [...(blocks ?? []).filter(item => item.id !== block.id), block])
    },
    onSettled: () => client.invalidateQueries({ queryKey: qk.timeBlocks }),
  })
}
