import { useEffect, useId, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Webhook } from "lucide-react"
import {
  webhookEvents,
  type WebhookEndpoint,
  type WebhookInput
} from "@/api/webhook-types"
import {
  useLists,
  useWebhooks,
  useWebhookDeliveries,
  useWebhookAction,
  webhooksKey
} from "@/hooks/api"
import { saveWebhook } from "@/hooks/webhooks"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { parseUTC } from "@/lib/date-values"
function useFormTrigger(open: boolean) {
  const trigger = useRef<HTMLButtonElement>(null)
  const wasOpen = useRef(open)
  useEffect(() => {
    if (wasOpen.current && !open) trigger.current?.focus()
    wasOpen.current = open
  }, [open])
  return trigger
}

function WebhookForm({
  endpoint,
  close
}: {
  endpoint?: WebhookEndpoint
  close: () => void
}) {
  const qc = useQueryClient()
  const lists = useLists()
  const [input, setInput] = useState<WebhookInput>(() => ({
    name: endpoint?.name ?? "",
    url: endpoint?.url ?? "",
    enabled: endpoint?.enabled ?? false,
    events: endpoint?.events ?? [],
    scope: endpoint?.scope ?? { kind: "all", list_ids: [] },
    include_titles: endpoint?.include_titles ?? false
  }))
  const [secret, setSecret] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  async function save() {
    setBusy(true)
    setError("")
    try {
      await saveWebhook(
        { ...input, ...(secret ? { secret } : {}) },
        endpoint ? { kind: "edit", id: endpoint.id } : { kind: "create" }
      )
      setSecret("")
      close()
      void qc.invalidateQueries({ queryKey: webhooksKey })
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Could not save webhook. Check the fields and retry."
      )
    } finally {
      setBusy(false)
    }
  }
  return (
    <form
      className="mt-4 space-y-3"
      onSubmit={(event) => {
        event.preventDefault()
        void save()
      }}
    >
      <fieldset disabled={busy} className="min-w-0 space-y-3">
        <legend className="mb-2 text-sm font-medium">
          {endpoint ? "Edit webhook" : "New webhook"}
        </legend>
        <label className="block text-sm">
          Name
          <Input
            required
            className="mt-1 min-h-11"
            value={input.name}
            onChange={(event) =>
              setInput({ ...input, name: event.target.value })
            }
          />
        </label>
        <label className="block text-sm">
          Destination URL
          <Input
            required
            type="url"
            className="mt-1 min-h-11"
            value={input.url}
            onChange={(event) =>
              setInput({ ...input, url: event.target.value })
            }
          />
        </label>
        <p className="text-xs text-muted-foreground">
          Use HTTPS outside a trusted local network. Leave credentials, query
          parameters and fragments out of the URL.
        </p>
        <label className="block text-sm">
          {endpoint ? "Replace signing secret (optional)" : "Signing secret"}
          <Input
            required={!endpoint}
            type="password"
            autoComplete="new-password"
            className="mt-1 min-h-11"
            value={secret}
            onChange={(event) => setSecret(event.target.value)}
          />
        </label>
        {endpoint && (
          <p className="text-xs text-muted-foreground">
            {endpoint.has_secret
              ? "A secret is stored. Leave blank to keep it."
              : "No secret is stored."}
          </p>
        )}
        <fieldset>
          <legend className="text-sm font-medium">Events to share</legend>
          {webhookEvents.map((item) => (
            <label
              key={item}
              className="flex min-h-11 items-center gap-2 text-sm"
            >
              <input
                type="checkbox"
                checked={input.events.includes(item)}
                onChange={(event) =>
                  setInput({
                    ...input,
                    events: event.target.checked
                      ? [...input.events, item]
                      : input.events.filter((value) => value !== item)
                  })
                }
              />
              {item}
            </label>
          ))}
        </fieldset>
        <label className="block text-sm">
          Task scope
          <select
            className="mt-1 min-h-11 w-full rounded-md border border-input bg-background px-3"
            value={input.scope.kind}
            onChange={(event) =>
              setInput({
                ...input,
                scope: {
                  kind: event.target.value as "all" | "lists",
                  list_ids: []
                }
              })
            }
          >
            <option value="all">All lists</option>
            <option value="lists">Selected lists</option>
          </select>
        </label>
        {input.scope.kind === "lists" && (
          <fieldset>
            <legend className="text-sm">Lists to share</legend>
            {lists.isPending && <p role="status">Loading lists…</p>}
            {lists.isError && (
              <p role="alert">
                Could not load lists.{" "}
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => void lists.refetch()}
                >
                  Retry lists
                </Button>
              </p>
            )}
            {lists.data?.length === 0 && (
              <p className="text-sm">
                Create a list first, or choose all lists.
              </p>
            )}
            {lists.data?.map((list) => (
              <label
                key={list.id}
                className="flex min-h-11 items-center gap-2 text-sm"
              >
                <input
                  type="checkbox"
                  checked={input.scope.list_ids.includes(list.id)}
                  onChange={(event) =>
                    setInput({
                      ...input,
                      scope: {
                        kind: "lists",
                        list_ids: event.target.checked
                          ? [...input.scope.list_ids, list.id]
                          : input.scope.list_ids.filter((id) => id !== list.id)
                      }
                    })
                  }
                />
                {list.name}
              </label>
            ))}
          </fieldset>
        )}
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={input.include_titles}
            onChange={(event) =>
              setInput({ ...input, include_titles: event.target.checked })
            }
          />
          Include task titles in shared events
        </label>
        <label className="flex min-h-11 items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={input.enabled}
            onChange={(event) =>
              setInput({ ...input, enabled: event.target.checked })
            }
          />
          Enable delivery to this destination
        </label>
        <div className="flex flex-wrap gap-2">
          <Button
            className="min-h-11"
            disabled={
              !input.events.length ||
              (input.scope.kind === "lists" && !input.scope.list_ids.length)
            }
            type="submit"
          >
            {busy ? "Saving webhook…" : "Save webhook"}
          </Button>
          <Button
            className="min-h-11"
            variant="outline"
            type="button"
            onClick={close}
          >
            Cancel
          </Button>
        </div>
      </fieldset>
      {error && (
        <p role="alert" className="break-words text-sm text-destructive">
          {error}
        </p>
      )}
    </form>
  )
}
function DeliveryHistory({ endpoint }: { endpoint: WebhookEndpoint }) {
  const deliveries = useWebhookDeliveries(endpoint.id)
  const action = useWebhookAction()
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium">Recent deliveries</h4>
      <Button
        className="min-h-11"
        variant="outline"
        onClick={() => void deliveries.refetch()}
      >
        Refresh deliveries
      </Button>
      {deliveries.isPending && <p role="status">Loading deliveries…</p>}
      {deliveries.isError && (
        <p role="alert">Could not load deliveries. Refresh to retry.</p>
      )}
      {deliveries.data?.length === 0 && (
        <p className="text-sm">
          No deliveries yet. Enable this webhook and send a test to check the
          destination.
        </p>
      )}
      <ul className="divide-y">
        {deliveries.data?.map((item) => (
          <li key={item.id} className="space-y-1 py-3 text-sm">
            <p className="break-words">
              {item.event_type} · {item.state} · {item.attempts} attempts
            </p>
            <p className="break-words text-xs text-muted-foreground">
              Created:{" "}
              {parseUTC(item.created_at)?.toLocaleString() ?? "Unknown"}
              {item.state === "pending" && item.next_attempt_at
                ? ` · Next attempt: ${parseUTC(item.next_attempt_at)?.toLocaleString() ?? "Unknown"}`
                : ""}
            </p>
            {item.last_error && (
              <p className="break-words text-destructive">{item.last_error}</p>
            )}
            {(item.state === "failed" ||
              (item.state === "pending" && item.last_error)) && (
              <Button
                className="min-h-11"
                variant="outline"
                aria-label={`Retry delivery ${item.id} to ${endpoint.name}`}
                disabled={!endpoint.enabled || action.isPending}
                onClick={() =>
                  action.mutate({
                    kind: "retry",
                    id: endpoint.id,
                    deliveryId: item.id
                  })
                }
              >
                Retry delivery
              </Button>
            )}
          </li>
        ))}
      </ul>
      {action.isPending && <p role="status">Retrying delivery…</p>}
      {action.isError && (
        <p role="alert" className="text-sm text-destructive">
          {action.error.message} Refresh deliveries and retry.
        </p>
      )}
    </div>
  )
}
function WebhookRow({ endpoint }: { endpoint: WebhookEndpoint }) {
  const [editing, setEditing] = useState(false)
  const editTrigger = useFormTrigger(editing)
  const headingId = useId()
  const [removing, setRemoving] = useState(false)
  const [history, setHistory] = useState(false)
  const action = useWebhookAction()
  return (
    <div
      role="group"
      aria-labelledby={headingId}
      className="min-w-0 space-y-3 border-t pt-4"
    >
      <div>
        <h3 id={headingId} className="break-words text-sm font-medium">
          {endpoint.name} · {endpoint.enabled ? "Enabled" : "Disabled"}
        </h3>
        <p className="break-all text-sm text-muted-foreground">
          {endpoint.url}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          className="min-h-11"
          variant="outline"
          disabled={action.isPending || editing}
          ref={editTrigger}
          aria-label={`Edit ${endpoint.name}`}
          onClick={() => setEditing(true)}
        >
          Edit
        </Button>
        <Button
          className="min-h-11"
          variant="outline"
          disabled={action.isPending || editing}
          aria-label={`${endpoint.enabled ? "Disable" : "Enable"} ${endpoint.name}`}
          onClick={() =>
            action.mutate({
              kind: "toggle",
              id: endpoint.id,
              enabled: !endpoint.enabled
            })
          }
        >
          {endpoint.enabled ? "Disable" : "Enable"}
        </Button>
        <Button
          className="min-h-11"
          variant="outline"
          disabled={action.isPending || !endpoint.enabled || editing}
          aria-label={`Send test to ${endpoint.name}`}
          onClick={() => action.mutate({ kind: "test", id: endpoint.id })}
        >
          Send test
        </Button>
        <Button
          className="min-h-11"
          variant="outline"
          aria-label={`${history ? "Hide" : "View"} deliveries for ${endpoint.name}`}
          aria-expanded={history}
          onClick={() => setHistory(!history)}
        >
          {history ? "Hide deliveries" : "View deliveries"}
        </Button>
        <Button
          className="min-h-11"
          variant="outline"
          disabled={action.isPending || editing}
          aria-label={`Remove ${endpoint.name}`}
          onClick={() => setRemoving(true)}
        >
          Remove
        </Button>
      </div>
      {removing && (
        <div className="space-y-2">
          <p className="text-sm">
            Remove {endpoint.name}? Pending deliveries will be cancelled.
            Previously received data stays with the destination.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              className="min-h-11"
              variant="destructive"
              disabled={action.isPending}
              aria-label={`Confirm removal of ${endpoint.name}`}
              onClick={() => action.mutate({ kind: "remove", id: endpoint.id })}
            >
              Confirm removal
            </Button>
            <Button
              className="min-h-11"
              variant="outline"
              aria-label={`Keep webhook ${endpoint.name}`}
              onClick={() => setRemoving(false)}
            >
              Keep webhook
            </Button>
          </div>
        </div>
      )}
      {editing && (
        <WebhookForm endpoint={endpoint} close={() => setEditing(false)} />
      )}
      {action.isPending && <p role="status">Updating webhook…</p>}
      {action.isSuccess && (
        <p role="status" className="text-sm">
          Request accepted. Check deliveries for the result.
        </p>
      )}
      {action.isError && (
        <p role="alert" className="break-words text-sm text-destructive">
          {action.error.message} Retry the action when the destination is ready.
        </p>
      )}
      {history && <DeliveryHistory endpoint={endpoint} />}
    </div>
  )
}
export function WebhookSettings() {
  const endpoints = useWebhooks()
  const [creating, setCreating] = useState(false)
  const addTrigger = useFormTrigger(creating)
  return (
    <section
      className="glass min-w-0 space-y-4 rounded-2xl p-5"
      aria-labelledby="webhook-settings-heading"
    >
      <h2
        id="webhook-settings-heading"
        className="flex items-center gap-2 text-sm font-semibold"
      >
        <Webhook className="size-4 text-primary" aria-hidden="true" />
        Outbound webhooks
      </h2>
      <p className="text-sm text-muted-foreground">
        Optional. Send selected task and time-block events to an automation
        service you choose. Journal works locally without webhooks.
      </p>
      <p className="text-sm text-muted-foreground">
        Share minimal event metadata by default. Task titles are shared only
        when you opt in; journal content stays local. Delivered means the
        destination accepted the request, instead of confirming calendar
        synchronization.
      </p>
      <p className="text-sm text-muted-foreground">
        Changing settings, disabling or removing a webhook cancels its pending
        deliveries. Previously received data stays with the destination. Journal
        must be running to deliver events.
      </p>
      {endpoints.isPending && <p role="status">Loading webhooks…</p>}
      {endpoints.isError && (
        <p role="alert">
          Could not load webhooks.{" "}
          <Button
            className="min-h-11"
            variant="outline"
            onClick={() => void endpoints.refetch()}
          >
            Retry webhooks
          </Button>
        </p>
      )}
      {endpoints.data?.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No webhooks configured. Add a destination when you are ready to share
          events.
        </p>
      )}
      {!creating ? (
        <Button
          className="min-h-11"
          variant="outline"
          ref={addTrigger}
          onClick={() => setCreating(true)}
        >
          Add webhook
        </Button>
      ) : (
        <WebhookForm close={() => setCreating(false)} />
      )}
      {endpoints.data?.map((endpoint) => (
        <WebhookRow key={endpoint.id} endpoint={endpoint} />
      ))}
    </section>
  )
}
