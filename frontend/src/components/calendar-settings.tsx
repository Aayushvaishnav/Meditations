import { useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { CalendarDays, LoaderCircle } from "lucide-react"
import { api } from "@/api/client"
import type { CalendarConnection, DiscoveredCalendar } from "@/api/types"
import { calendarKey, useCalendarConnections, useCalendarControl, useCalendarSetupPending } from "@/hooks/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { beginCalendarSetup } from "@/lib/calendar-setup-operation"
import { CalendarConnectionControls } from "./calendar-connection-controls"

const selectStyle = "mt-1 min-h-11 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm"

export function CalendarSettings() {
  const connections = useCalendarConnections()
  const qc = useQueryClient()
  const control = useCalendarControl()
  const [server, setServer] = useState("")
  const [target, setTarget] = useState("")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const passwordVersion = useRef(0)
  const contextVersion = useRef(0)
  useEffect(() => () => { contextVersion.current++ }, [])
  const [auth, setAuth] = useState<"basic" | "digest">("basic")
  const [calendars, setCalendars] = useState<DiscoveredCalendar[]>([])
  const [calendar, setCalendar] = useState("")
  const busy = useCalendarSetupPending()
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const locked = busy || control.isPending
  async function authenticate(connect: boolean) {
    const operation = beginCalendarSetup()
    if (operation.state === "busy") return
    const version = passwordVersion.current
    const context = contextVersion.current
    setError(""); setNotice("")
    try {
      let id = target
      if (!id) {
        const url = new URL(server)
        const draft = await api.post<CalendarConnection>("/calendar/connections", { server_url: server, calendar_url: `${url.origin}/` })
        id = draft.id
        if (contextVersion.current !== context) return
        setTarget(id)
      }
      const credentials = { username, password, auth_type: auth }
      if (connect) {
        await api.post(`/calendar/connections/${id}/connect`, { ...credentials, calendar_url: calendar })
        if (contextVersion.current !== context) return
        if (passwordVersion.current === version) setPassword("")
        setNotice("Credentials saved and connection verified. Check sync status below; only explicitly selected blocks can publish.")
        setCalendars([]); setCalendar("")
      } else {
        const found = await api.post<DiscoveredCalendar[]>(`/calendar/connections/${id}/discover`, credentials)
        if (contextVersion.current !== context) return
        setCalendars(found); setCalendar("")
        setNotice(found.some(item => item.writable && item.supports_vevent) ? "Choose a writable event calendar, then connect." : "No writable event calendars found. Check server permissions and retry discovery.")
      }
    } catch (cause) {
      if (contextVersion.current !== context) return
      setError(cause instanceof Error ? cause.message : "Calendar operation failed. Check the server and retry.")
      if (passwordVersion.current === version) setPassword("")
    } finally {
      operation.finish()
      void qc.invalidateQueries({ queryKey: calendarKey })
    }
  }
  return <section className="glass min-w-0 rounded-2xl p-5" aria-labelledby="calendar-settings-heading">
    <h2 id="calendar-settings-heading" className="flex items-center gap-2 text-sm font-semibold"><CalendarDays className="size-4 text-primary" aria-hidden="true" />Calendar synchronization</h2>
    <div className="mt-4 space-y-4">
      <p className="text-sm text-muted-foreground">Optional. Keep using Journal locally without an account or server. Connect a CalDAV server you manage to publish selected time blocks.</p>
      <p className="text-sm text-muted-foreground">Journal and your server must be running and reachable to sync. A localhost server is available only on this device. Journal does not install or start a server. OAuth-only sign-in is not supported.</p>
      {connections.isPending && <p role="status" className="text-sm">Loading calendar connections…</p>}
      {connections.isError && <div role="alert" className="text-sm text-destructive">Could not load connections. <Button className="min-h-11" variant="outline" onClick={() => void connections.refetch()}>Retry connections</Button></div>}
      <fieldset disabled={locked} className="min-w-0 space-y-3">
        <legend className="mb-2 text-sm font-medium">Set up or replace credentials</legend>
        <label className="block text-sm">Connection<select className={selectStyle} value={target} onChange={event => { contextVersion.current++; passwordVersion.current++; setTarget(event.target.value); setCalendars([]); setCalendar(""); setPassword(""); setNotice(""); setError("") }}><option value="">New server</option>{connections.data?.map(item => <option key={item.id} value={item.id}>{item.server_url}</option>)}</select></label>
        {!target && <label className="block text-sm">Server URL<Input className="mt-1 min-h-11" type="url" placeholder="https://calendar.example.org/" value={server} onChange={event => { setServer(event.target.value); setCalendars([]) }} /></label>}
        <div className="grid min-w-0 gap-3 sm:grid-cols-2">
          <label className="block min-w-0 text-sm">Username<Input className="mt-1 min-h-11" autoComplete="off" value={username} onChange={event => { contextVersion.current++; setUsername(event.target.value); setCalendars([]); setCalendar("") }} /></label>
          <label className="block min-w-0 text-sm">Password or app password<Input className="mt-1 min-h-11" type="password" autoComplete="new-password" value={password} onChange={event => { contextVersion.current++; passwordVersion.current++; setPassword(event.target.value); setCalendars([]); setCalendar("") }} /></label>
        </div>
        <label className="block text-sm">Authentication<select className={selectStyle} value={auth} onChange={event => { contextVersion.current++; setAuth(event.target.value as "basic" | "digest"); setCalendars([]); setCalendar("") }}><option value="basic">Basic</option><option value="digest">Digest</option></select></label>
        <p className="text-xs text-muted-foreground">Choose the method configured on your server. Use HTTPS, or HTTP only for loopback. Credentials are stored by the backend in your OS credential store, not in exports.</p>
        <Button className="min-h-11" variant="outline" disabled={!username || !password || (!target && !server)} onClick={() => void authenticate(false)}>Discover calendars</Button>
        {calendars.length > 0 && <><label className="block text-sm">Remote calendar<select className={selectStyle} value={calendar} onChange={event => setCalendar(event.target.value)}><option value="">Choose a writable event calendar</option>{calendars.map(item => <option key={item.url} value={item.url} disabled={!item.writable || !item.supports_vevent}>{item.display_name || item.url}{!item.writable || !item.supports_vevent ? " (unavailable)" : ""}</option>)}</select></label><Button className="min-h-11" disabled={!calendar || !username || !password} onClick={() => void authenticate(true)}>Connect and save credentials</Button></>}
      </fieldset>
      {busy && <p role="status" className="flex items-center gap-2 text-sm"><LoaderCircle aria-hidden="true" className="size-4 motion-safe:animate-spin" />Contacting calendar server…</p>}
      {notice && <p role="status" className="text-sm text-muted-foreground">{notice}</p>}
      {error && <p role="alert" className="text-sm text-destructive break-words">{error} Check the URL, authentication method and credentials, then retry.</p>}
      {connections.data?.map(connection => <CalendarConnectionControls key={connection.id} connection={connection} setupBusy={busy} />)}
    </div>
  </section>
}
