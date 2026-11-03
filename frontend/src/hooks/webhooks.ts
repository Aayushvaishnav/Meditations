import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/api/client"
import type {
  WebhookDelivery,
  WebhookEndpoint,
  WebhookInput
} from "@/api/webhook-types"
export const webhooksKey = ["webhooks"] as const
export function useWebhooks() {
  return useQuery({
    queryKey: webhooksKey,
    queryFn: () => api.get<WebhookEndpoint[]>("/webhooks")
  })
}
export function useWebhookDeliveries(id: string) {
  return useQuery({
    queryKey: [...webhooksKey, id, "deliveries"],
    queryFn: () => api.get<WebhookDelivery[]>(`/webhooks/${id}/deliveries`),
    refetchInterval: 10000
  })
}
type Action =
  | { kind: "toggle"; id: string; enabled: boolean }
  | { kind: "remove" | "test"; id: string }
  | { kind: "retry"; id: string; deliveryId: string }
export function useWebhookAction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (action: Action) => {
      const path = `/webhooks/${action.id}`
      if (action.kind === "toggle")
        return api.patch(path, { enabled: action.enabled })
      if (action.kind === "remove") return api.delete(path)
      return api.post(
        action.kind === "retry"
          ? `${path}/deliveries/${action.deliveryId}/retry`
          : `${path}/test`,
        {}
      )
    },
    onSettled: () => qc.invalidateQueries({ queryKey: webhooksKey })
  })
}
// Credentials bypass the mutation cache; only public responses enter queries
export function saveWebhook(
  input: WebhookInput,
  target: { kind: "create" } | { kind: "edit"; id: string }
) {
  return target.kind === "edit"
    ? api.patch<WebhookEndpoint>(`/webhooks/${target.id}`, input)
    : api.post<WebhookEndpoint>("/webhooks", input)
}
