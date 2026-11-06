import { useState } from "react"
import { LoaderCircle } from "lucide-react"
import type { CalendarConnection, CalendarLinkView, TimeBlock } from "@/api/types"
import { useCalendarAllLinks, useCalendarControl, useCalendarLinks, useCalendarStatus, useTasks, useTimeBlocks } from "@/hooks/api"
import { Button } from "@/components/ui/button"
import { blockStartDay, blockTimeLabel } from "@/lib/time-blocks"
import { calendarLinkLabel, calendarSelectionLabel } from "@/lib/calendar-progress"
import { parseUTC } from "@/lib/date-values"

const selectStyle = "mt-1 min-h-11 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm"

function blockDescription(block: TimeBlock, title: string) {
  const interval = block.kind === "all_day"
    ? `${block.start_date} to ${block.end_date} (exclusive), all day`
    : `${blockStartDay(block)} · ${blockTimeLabel(block)} (local time; source zone ${block.timezone})`
  return `${title} · ${interval}`
}

function CalendarLinkRow({ link, description, locked, run }: {
  link: CalendarLinkView
  description: string
  locked: boolean
  run: (path: string) => void
}) {
  return (
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 border-t border-border py-2 text-sm">
      <div className="min-w-0 flex-1">
        <p className="break-words">{description}</p>
        <p className="text-muted-foreground">
          {calendarLinkLabel(link)}
        </p>
        {link.state === "conflict" && <p className="text-muted-foreground">Stop syncing to keep both copies without overwriting remote changes.</p>}
        {link.last_error && <p className="text-destructive break-words">{link.last_error}</p>}
      </div>
      {link.state !== "detached" && link.state !== "conflict" && link.desired_action !== "delete" && (
        <Button variant="outline" className="min-h-11" disabled={locked}
          onClick={() => run(`/blocks/${link.local_block_id}/opt-out`)}>
          Remove remote event
        </Button>
      )}
      {link.state !== "detached" && (
        <Button variant="outline" className="min-h-11" disabled={locked}
          onClick={() => run(`/links/${link.id}/detach`)}>
          Stop syncing; keep remote
        </Button>
      )}
    </div>
  )
}

export function CalendarConnectionControls({ connection, setupBusy }: { connection: CalendarConnection; setupBusy: boolean }) {
  const control = useCalendarControl()
  const status = useCalendarStatus(connection.id)
  const current = status.data?.connection ?? connection
  const links = useCalendarLinks(connection.id)
  const blocks = useTimeBlocks()
  const tasks = useTasks()
  const allLinks = useCalendarAllLinks()
  const describe = (block: TimeBlock) => blockDescription(block, tasks.data?.find(task => task.id === block.task_id)?.title ?? "Task unavailable")
  const [selected, setSelected] = useState("")
  const selectedLink = allLinks.data?.find(link => link.local_block_id === selected)
  const selectionBlocked = !!selectedLink && (selectedLink.connection_id !== connection.id || selectedLink.selection_state === "detached" || selectedLink.state === "conflict" || selectedLink.desired_action !== "delete")
  const locked = control.isPending || setupBusy
  const root = `/${connection.id}`
  const run = (path: string, body?: Record<string, unknown>, method?: "post" | "patch") => control.mutate({ path: root + path, body, method })
  return <div className="min-w-0 space-y-3 border-t border-border pt-4">
    <p className="break-all text-sm font-medium">{connection.calendar_url}</p>
    <div role="status" className="text-sm text-muted-foreground space-y-1">
      <p>{current.state === "authentication_required" ? "Authentication required. Replace credentials or verify to retry." : current.state === "connected" ? "Connection verified" : "Not verified. Verify after restarting Journal."} · {current.enabled ? "Sync enabled" : "Sync paused"}</p>
      {current.credential_state === "removal_pending" && <p>Credential removal incomplete. Retry Disconnect.</p>}
      {status.data && <><p>Outbound: {status.data.queued_count} queued · {status.data.conflict_count} conflicts · {status.data.error_count} errors</p><p>Last acknowledged remote change: {status.data.last_success_state === "never" ? "No events synced yet" : status.data.last_success_at ? parseUTC(status.data.last_success_at)?.toLocaleString() : "Earlier sync time unavailable"}</p></>}
    </div>
    <div className="flex flex-wrap gap-2">
      <Button className="min-h-11" variant="outline" disabled={locked || current.credential_state !== "present"} onClick={() => run("/verify")}>Verify connection</Button>
      <Button className="min-h-11" variant="outline" disabled={locked || (!current.enabled && current.state !== "connected")} onClick={() => run("/sync", { enabled: !current.enabled }, "patch")}>{current.enabled ? "Pause sync" : "Enable sync"}</Button>
      <Button className="min-h-11" variant="outline" disabled={locked || !current.enabled || current.state !== "connected"} onClick={() => run("/sync-now")}>Sync now</Button>
      <Button className="min-h-11" variant="outline" disabled={locked} onClick={() => run("/disconnect")}>Disconnect</Button>
    </div>
    <p className="text-xs text-muted-foreground">Disconnect keeps remote events. Enabling sync never selects blocks automatically.</p>
    <label className="block text-sm">Time block to publish
      <select className={selectStyle} value={selected} onChange={event => setSelected(event.target.value)}>
        <option value="">Choose a locally saved block</option>
        {blocks.data?.map(block => {
          const link = allLinks.data?.find(item => item.local_block_id === block.id)
          const blocked = !!link && (link.connection_id !== connection.id || link.selection_state === "detached" || link.state === "conflict" || link.desired_action !== "delete")
          return <option key={block.id} value={block.id} disabled={blocked}>
            {describe(block)} · {calendarSelectionLabel(link, connection.id)}
          </option>
        })}
      </select>
    </label>
    <Button className="min-h-11" variant="outline" disabled={!selected || selectionBlocked || !allLinks.isSuccess || locked || current.state !== "connected"} onClick={() => run(`/blocks/${selected}/opt-in`)}>Publish selected block</Button>
    <p className="text-xs text-muted-foreground">Remove remote event queues a deletion on the server. Stop syncing keeps its remote copy and resolves a conflict without overwriting either side.</p>
    <p className="text-xs text-muted-foreground">Local saves are immediate. Only selected blocks enter the remote queue; synced means the server acknowledged the change.</p>
    {links.data?.map(link => {
      const block = blocks.data?.find(item => item.id === link.local_block_id)
      return <CalendarLinkRow key={link.id} link={link} locked={locked} run={run}
        description={block ? describe(block) : "Locally deleted block"} />
    })}
    {control.isPending && <p role="status" className="flex items-center gap-2 text-sm"><LoaderCircle className="size-4 motion-safe:animate-spin" aria-hidden="true" />Updating calendar…</p>}
    {control.isError && <p role="alert" className="text-sm text-destructive">{control.error.message} Retry the action after checking the connection.</p>}
    {(status.isError || links.isError || blocks.isError || tasks.isError || allLinks.isError) && <div role="alert" className="text-sm text-destructive">Calendar details could not load. <Button variant="outline" className="min-h-11" onClick={() => { void status.refetch(); void links.refetch(); void blocks.refetch(); void tasks.refetch(); void allLinks.refetch() }}>Retry details</Button></div>}
  </div>
}

