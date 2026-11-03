export const webhookEvents = [
  "time_block.created",
  "time_block.updated",
  "time_block.deleted",
  "task.completed"
] as const
export type WebhookEvent = (typeof webhookEvents)[number]
export interface WebhookEndpoint {
  id: string
  name: string
  url: string
  enabled: boolean
  events: WebhookEvent[]
  scope: { kind: "all" | "lists"; list_ids: string[] }
  include_titles: boolean
  has_secret: boolean
}
export type WebhookInput = Omit<WebhookEndpoint, "id" | "has_secret"> & {
  secret?: string
}
export interface WebhookDelivery {
  id: string
  event_id: string
  event_type: WebhookEvent | "webhook.test"
  entity_id: string
  entity_version: number
  state: "pending" | "delivered" | "failed" | "cancelled"
  attempts: number
  last_error: string | null
  next_attempt_at: string
  created_at: string
}
