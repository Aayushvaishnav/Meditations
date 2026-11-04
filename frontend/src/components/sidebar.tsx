import { useEffect, useMemo, useRef, useState } from "react"
import { BookOpen, Brain, CalendarClock, CalendarDays, CheckCircle2, Folder, Inbox, ListTodo, Menu, PanelLeftClose, PanelLeftOpen, Plus, Settings, TrendingUp, X } from "lucide-react"
import { useUi, type SmartView } from "@/stores/ui"
import { useCreateList, useDeleteList, useHealth, useLists, useTasks } from "@/hooks/api"
import { groupOf } from "@/lib/dates"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "@/components/ui/popover"
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { cn } from "cn"

const SMART_VIEWS: { id: SmartView; label: string; icon: typeof Inbox }[] = [
  { id: "today", label: "Today", icon: CalendarDays },
  { id: "overdue", label: "Overdue", icon: CalendarClock },
  { id: "upcoming", label: "Upcoming", icon: ListTodo },
  { id: "all", label: "All tasks", icon: Inbox },
  { id: "completed", label: "Completed", icon: CheckCircle2 },
]

function ScopeButton({ active, onClick, label, icon, count, collapsed = false }: {
  active: boolean; onClick: () => void; label: string; icon: React.ReactNode; count?: number; collapsed?: boolean
}) {
  const button = <button onClick={onClick} aria-label={label} aria-current={active ? "page" : undefined}
    className={cn("flex min-h-10 min-w-0 w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring", collapsed && "justify-center px-2",
      active ? "bg-primary/15 text-foreground ring-1 ring-primary/30" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground")}>
    {icon}
    {!collapsed && <><span className="min-w-0 truncate">{label}</span>{count !== undefined && count > 0 && <span className="ml-auto text-xs opacity-70">{count}</span>}</>}
  </button>
  return collapsed ? <Tooltip><TooltipTrigger render={button} /><TooltipContent side="right">{label}</TooltipContent></Tooltip> : button
}

function NewListButton() {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState("")
  const createList = useCreateList()
  if (!open) return <Button variant="ghost" className="w-full justify-start" onClick={() => setOpen(true)}><Plus />New list</Button>
  return <form className="space-y-2 p-1" onSubmit={(e) => {
    e.preventDefault()
    if (!name.trim()) return
    createList.mutate({ name: name.trim() }, { onSuccess: () => { setName(""); setOpen(false) } })
  }}>
    <Input autoFocus aria-label="List name" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); setOpen(false) } }} placeholder="List name…" />
    <div className="flex gap-2"><Button size="sm" type="submit" disabled={!name.trim() || createList.isPending}>Create list</Button><Button size="sm" variant="ghost" type="button" onClick={() => setOpen(false)}>Cancel</Button></div>
    {createList.isError && <p role="alert" className="text-sm text-destructive">Could not create list. Try again.</p>}
  </form>
}

function ListRow({ id, name, color, count, onNavigate }: { id: string; name: string; color: string; count: number; onNavigate: () => void }) {
  const section = useUi((s) => s.section)
  const scope = useUi((s) => s.scope)
  const setScope = useUi((s) => s.setScope)
  const deleteList = useDeleteList()
  const [confirming, setConfirming] = useState(false)
  return <div>
    <div className="flex items-center gap-1">
      <ScopeButton active={section === "tasks" && scope.kind === "list" && scope.id === id} onClick={() => { setScope({ kind: "list", id }); onNavigate() }} count={count} label={name}
        icon={<span aria-hidden="true" className="size-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />} />
      <Button variant="ghost" size="icon-sm" aria-label={`Delete list "${name}"`} onClick={() => setConfirming(!confirming)}><X className="text-muted-foreground" /></Button>
    </div>
    {confirming && <div className="space-y-2 rounded-lg bg-muted p-2 text-sm"><p>Delete {name}? Tasks will be kept.</p><div className="flex gap-2"><Button size="sm" variant="destructive" disabled={deleteList.isPending} onClick={() => deleteList.mutate(id)}>Delete list</Button><Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>Keep list</Button></div>{deleteList.isError && <p role="alert">Could not delete list. Try again.</p>}</div>}
  </div>
}

function Navigation({ collapsed, onNavigate }: { collapsed: boolean; onNavigate: () => void }) {
  const section = useUi((s) => s.section)
  const setSection = useUi((s) => s.setSection)
  const scope = useUi((s) => s.scope)
  const setScope = useUi((s) => s.setScope)
  const lists = useLists()
  const tasks = useTasks()
  const [listsOpen, setListsOpen] = useState(false)
  const counts = useMemo(() => {
    const all = tasks.data ?? []
    const open = all.filter((t) => t.status !== "completed" && t.status !== "canceled")
    return {
      smart: {
        today: open.filter((t) => ["overdue", "today"].includes(groupOf(t))).length,
        overdue: open.filter((t) => groupOf(t) === "overdue").length,
        upcoming: open.filter((t) => ["tomorrow", "upcoming"].includes(groupOf(t))).length,
        all: open.length,
        completed: all.filter((t) => t.status === "completed").length,
      } as Record<SmartView, number>,
      lists: open.reduce<Map<string, number>>((acc, t) => {
        if (t.list_id) acc.set(t.list_id, (acc.get(t.list_id) ?? 0) + 1)
        return acc
      }, new Map()),
    }
  }, [tasks.data])
  const listContents = <>
    {lists.isLoading ? Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-10 w-full" />) : (lists.data ?? []).map((l) => <ListRow key={l.id} {...l} count={counts.lists.get(l.id) ?? 0} onNavigate={() => { setListsOpen(false); onNavigate() }} />)}
    {lists.isError && <p role="alert" className="p-2 text-sm">Could not load lists. <button className="underline" onClick={() => void lists.refetch()}>Retry</button></p>}
    <NewListButton />
  </>
  return <>
    <nav aria-label="Main navigation" className="min-h-0 flex-1 space-y-1 overflow-y-auto overflow-x-hidden p-1">
      {([{ id: "journal", label: "Journal", icon: BookOpen }, { id: "second_brain", label: "Second brain", icon: Brain }, { id: "insights", label: "Insights", icon: TrendingUp }] as const).map(({ id, label, icon: Icon }) =>
        <ScopeButton key={id} active={section === id} label={label} collapsed={collapsed} icon={<Icon className="size-4 shrink-0" />} onClick={() => { setSection(id); onNavigate() }} />)}
      <div className="my-3 border-t border-border" />
      {SMART_VIEWS.map(({ id, label, icon: Icon }) => <ScopeButton key={id} active={section === "tasks" && scope.kind === "smart" && scope.id === id} label={label} collapsed={collapsed} icon={<Icon className="size-4 shrink-0" />} count={counts.smart[id]} onClick={() => { setScope({ kind: "smart", id }); onNavigate() }} />)}
      <div className="my-3 border-t border-border" />
      {collapsed ? <Popover open={listsOpen} onOpenChange={setListsOpen}>
        <PopoverTrigger render={<Button variant="ghost" className="min-h-10 w-full" aria-label="Lists" title="Lists" aria-current={section === "tasks" && scope.kind === "list" ? "page" : undefined} />}><Folder className="size-4" /></PopoverTrigger>
        <PopoverContent side="right" align="end" className="max-h-[80dvh] w-72 max-w-[calc(100vw-2rem)] overflow-y-auto"><PopoverTitle>Lists</PopoverTitle>{listContents}</PopoverContent>
      </Popover> : <section aria-label="Lists"><h2 className="px-3 py-2 text-sm font-medium text-muted-foreground">Lists</h2>{listContents}</section>}
    </nav>
    <footer className="shrink-0 border-t border-border pt-2"><ScopeButton active={section === "settings"} label="Settings" collapsed={collapsed} icon={<Settings className="size-4 shrink-0" />} onClick={() => { setSection("settings"); onNavigate() }} /></footer>
  </>
}

function ConnectionStatus() {
  const health = useHealth()
  const label = health.isError ? "API unreachable" : health.isLoading ? "Connecting to API" : "API connected"
  return <span role="status" aria-label={label} title={label} className={cn("size-2 shrink-0 rounded-full", health.isError ? "bg-destructive" : health.isLoading ? "bg-medium" : "bg-positive")} />
}

export function Sidebar() {
  const sidebar = useUi((s) => s.sidebar)
  const setSidebar = useUi((s) => s.setSidebar)
  const collapsed = sidebar === "collapsed"
  const [drawerOpen, setDrawerOpen] = useState(false)
  const desktopRef = useRef<HTMLElement>(null)
  const mobileTriggerRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const media = window.matchMedia("(min-width: 768px)")
    const onBreakpoint = () => {
      if (media.matches) setDrawerOpen(false)
      else if (desktopRef.current?.contains(document.activeElement)) mobileTriggerRef.current?.focus()
    }
    media.addEventListener("change", onBreakpoint)
    return () => media.removeEventListener("change", onBreakpoint)
  }, [])
  return <>
    <aside ref={desktopRef} aria-label="Sidebar" className={cn("glass hidden shrink-0 flex-col gap-3 border-r border-border p-2 md:flex", collapsed ? "w-16" : "w-60")}>
      <div className={cn("flex items-center gap-2 p-1", collapsed && "flex-col")}>
        {!collapsed && <><img src="/favicon.svg" alt="" draggable={false} className="size-7" /><span className="flex-1 text-sm font-semibold">Meditations</span></>}
        <ConnectionStatus />
        <Tooltip><TooltipTrigger render={<Button variant="ghost" size="icon-sm" aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!collapsed} onClick={() => setSidebar(collapsed ? "expanded" : "collapsed")} />}>{collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}</TooltipTrigger><TooltipContent side="right">{collapsed ? "Expand sidebar" : "Collapse sidebar"}</TooltipContent></Tooltip>
      </div>
      <Navigation collapsed={collapsed} onNavigate={() => {}} />
    </aside>
    <div className="flex shrink-0 items-center gap-3 border-b border-border px-3 py-2 md:hidden">
      <Dialog open={drawerOpen} onOpenChange={setDrawerOpen}>
        <DialogTrigger render={<Button variant="ghost" size="icon" ref={mobileTriggerRef} aria-label="Open navigation" aria-expanded={drawerOpen} />}><Menu /></DialogTrigger>
        <DialogContent finalFocus={() => window.matchMedia("(min-width: 768px)").matches ? desktopRef.current?.querySelector<HTMLButtonElement>("button[aria-expanded]") : mobileTriggerRef.current} className="inset-y-0 left-0 flex h-dvh w-72 max-w-[calc(100%-3rem)] translate-x-0 translate-y-0 flex-col rounded-none sm:max-w-72" aria-describedby={undefined}>
          <DialogTitle className="pr-8">Navigation</DialogTitle>
          <Navigation collapsed={false} onNavigate={() => setDrawerOpen(false)} />
        </DialogContent>
      </Dialog>
      <span className="flex-1 text-sm font-semibold">Meditations</span><ConnectionStatus />
    </div>
  </>
}
