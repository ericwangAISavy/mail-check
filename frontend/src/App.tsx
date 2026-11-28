import { readBrowserPreference, writeBrowserPreference } from "@/lib/browser-preferences"
import { getAppearance, setMode, subscribeAppearance } from "@/lib/appearance"
import { PageQueryBoundary } from "@/lib/page-state"
import WorkspaceSidebar, { workspaceNavigationLabel } from "@/components/workspace-sidebar"
import ChangePassword from "@/components/change-password"
import { OfferPathMark } from "@/components/offerpath-mark"
import { lazy, Suspense, useCallback, useContext, useEffect, useRef, useState, useSyncExternalStore, type MouseEvent } from "react"
import { Navigate, NavLink, Route, Routes, UNSAFE_DataRouterContext, useLocation, useNavigate } from "react-router-dom"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Activity, ChevronRight, CircleHelp, LoaderCircle, Moon, PanelLeftOpen, Plus, Sun } from "lucide-react"
import { api, request } from "@/lib/api"
import { parseStamp, timeAgo } from "@/lib/relative-time"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Loading, PageHeading, ToastProvider, useToast } from "@/components/common"
import type { Bootstrap } from "@/lib/types"
import { AuthGate, useAuth } from "@/components/auth"
import { useRealtimeUpdates } from "@/lib/realtime"
import { bidderAlertScope, useBidderAlertPreferences, useBidderMailAlerts } from "@/lib/bidder-mail-alerts"

// Each page's code downloads on demand. Navigation can start that download
// early (hover, focus, press) so a click rarely waits for the network.
const pageImports = {
  triage: () => import("@/pages/triage"),
  sourcing: () => import("@/pages/sourcing"),
  jobLinks: () => import("@/pages/job-links"),
  dashboard: () => import("@/pages/dashboard"),
  payments: () => import("@/pages/payments"),
  interviews: () => import("@/pages/interviews"),
  interviewPipeline: () => import("@/pages/interview-pipeline"),
  interviewProcesses: () => import("@/pages/interview-processes"),
  accounts: () => import("@/pages/accounts"),
  adminManagement: () => import("@/pages/admin-management"),
  settings: () => import("@/pages/settings"),
}
const routeImports: Record<string, () => Promise<unknown>> = {
  "/": pageImports.triage, "/inbox": pageImports.triage, "/sourcing": pageImports.sourcing,
  "/job-links": pageImports.jobLinks,
  "/dashboard": pageImports.dashboard, "/payments": pageImports.payments, "/interviews": pageImports.interviews,
  "/interview-processes": pageImports.interviewPipeline, "/interview-processes/legacy": pageImports.interviewProcesses,
  "/accounts": pageImports.accounts,
  "/admin-management": pageImports.adminManagement, "/settings": pageImports.settings,
}
/** Start downloading a page's code; failures are left to the real navigation. */
function preloadRoute(path: string) { void routeImports[path]?.().catch(() => undefined) }
const TriagePage = lazy(pageImports.triage)
const SourcingPage = lazy(pageImports.sourcing)
const JobLinks = lazy(pageImports.jobLinks)
const DashboardPage = lazy(pageImports.dashboard)
const PaymentsPage = lazy(pageImports.payments)
const InterviewsPage = lazy(pageImports.interviews)
const InterviewPipelinePage = lazy(pageImports.interviewPipeline)
const InterviewProcessesPage = lazy(pageImports.interviewProcesses)
const AccountsPage = lazy(pageImports.accounts)
const AdminManagement = lazy(pageImports.adminManagement)
const SettingsPage = lazy(pageImports.settings)
const PersonalSettingsPage = lazy(() => pageImports.settings().then(module => ({ default: module.PersonalSettingsPage })))

function ThemeControl() {
  const theme = useSyncExternalStore(subscribeAppearance, getAppearance).mode
  const rotate = () => { setMode(theme === "system" ? "light" : theme === "light" ? "dark" : "system") }
  const Icon = theme === "dark" ? Moon : theme === "light" ? Sun : Activity
  return <Button variant="ghost" size="icon" aria-label={`Color theme: ${theme}. Change theme`} title={`Theme: ${theme}`} onClick={rotate}><Icon size={18} /></Button>
}


/** "Updated 2 min ago" for the latest mail collection, ticking locally between polls.
 * Kept as its own component so only this text re-renders each second. */
function Freshness({ updatedAt }: { updatedAt: string }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  const date = parseStamp(updatedAt)
  if (!date) return null
  return <time className="tabular status-updated" dateTime={date.toISOString()} title={date.toLocaleString()} aria-live="off">{timeAgo(date, now)}</time>
}

/** The header auto-check toggle is hidden; automatic checks stay configurable in Settings. */
const SHOW_AUTO_CHECK_TOGGLE = false

function JobStatus({ bootstrap }: { bootstrap: Bootstrap }) {
  const {session}=useAuth()
  const canManageSettings=!session?.workspace_id || !!session.is_owner
  const calendarOnly = ["/interviews", "/interview-processes", "/interview-processes/legacy"].includes(useLocation().pathname)
  const queryClient = useQueryClient()
  const toast = useToast()
  const [status, setStatusValue] = useState<Awaited<ReturnType<typeof api.status>> | null>(null)
  const [receivedAt, setReceivedAt] = useState(() => Date.now())
  const setStatus = useCallback((next: Awaited<ReturnType<typeof api.status>>) => { setStatusValue(next); setReceivedAt(Date.now()) }, [])
  const seen = useRef<number | null>(null)
  const fastPollUntil = useRef(0)
  const pollNow = useRef<() => void>(() => undefined)
  // When the countdown reaches zero the server is about to start a check:
  // poll quickly for a few seconds instead of waiting out the idle interval.
  const onDue = useCallback(() => {
    if (Date.now() < fastPollUntil.current) return // the fast loop is already polling
    fastPollUntil.current = Date.now() + 10_000
    pollNow.current()
  }, [])
  useEffect(() => {
    let stopped = false
    let timer = 0
    let polling = false
    let latestRunning = false
    const controller = new AbortController()
    const poll = async () => {
      if (stopped || polling) return
      polling = true
      window.clearTimeout(timer)
      try {
        const current = await api.status(controller.signal)
        if (stopped) return
        latestRunning = current.running
        setStatus(current)
        if (seen.current === null) seen.current = current.completion_id
        else if (seen.current !== current.completion_id) {
          seen.current = current.completion_id
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: ["accounts"] }),
            queryClient.invalidateQueries({ queryKey: ["triage"] }),
            queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
            queryClient.invalidateQueries({ queryKey: ["payments"] }),
            queryClient.invalidateQueries({ queryKey: ["bootstrap"] }),
            queryClient.invalidateQueries({ queryKey: ["reader"] }),
            queryClient.invalidateQueries({ queryKey: ["interviews"] }),
            queryClient.invalidateQueries({ queryKey: ["pipeline"] }),
          ])
          if (stopped) return
          window.dispatchEvent(new Event("mailcheck:check-completed"))
          if (!current.background) toast(current.message || (current.ok ? "Check complete." : "Check finished with an issue."), current.ok ? "success" : "error")
          for (const item of current.background ? [] : current.interview_changes || []) {
            const label = item.status === "Cancelled" ? "Meeting cancelled" : item.status === "Rescheduled" ? "Meeting rescheduled" : "Meeting added"
            toast(`${label} · ${item.company || "Company unknown"}${item.start_at ? " · " + new Date(item.start_at).toLocaleString() : " · Needs review"}`, "info")
          }
          try {
            const pref = readBrowserPreference("mailcheck.notify") === "on" && typeof Notification !== "undefined" && Notification.permission === "granted"
            if (pref) {
              const pending = await request<{ items: { pk: number; title: string; who: string; summary: string; url: string }[] }>("/api/notifications", { signal: controller.signal })
              if (stopped) return
              const shown: number[] = []
              for (const item of pending.items) {
                try {
                  const alert = new Notification(`${item.title} · ${item.who}`, { body: item.summary, tag: String(item.pk) })
                  alert.onclick = () => { window.open(item.url, "_blank", "noopener"); }
                  shown.push(item.pk)
                } catch { /* Do not acknowledge a notification the browser rejected. */ }
              }
              if (shown.length) await api.post("/api/notifications/ack", shown)
            }
          } catch { /* Notification permissions and browser settings are optional. */ }
        }
      } catch { if (!stopped) setStatusValue(null) }
      polling = false
      if (!stopped) timer = window.setTimeout(poll, latestRunning ? 1000 : Date.now() < fastPollUntil.current ? 2000 : 30000)
    }
    const focus = () => { window.clearTimeout(timer); void poll() }
    const checkStarted = () => { fastPollUntil.current = Date.now() + 10_000; focus() }
    window.addEventListener("mailcheck:check-started", checkStarted)
    pollNow.current = focus
    void poll()
    window.addEventListener("focus", focus)
    window.addEventListener("mailcheck:settings-updated", focus)
    return () => { window.removeEventListener("mailcheck:check-started", checkStarted); stopped = true; controller.abort(); window.clearTimeout(timer); window.removeEventListener("focus", focus); window.removeEventListener("mailcheck:settings-updated", focus) }
  }, [queryClient, toast, setStatus])

  const runCheck = async () => {
    try {
      await api.startCheck(calendarOnly ? "calendar" : "mail")
      toast(calendarOnly ? "Calendar collection started." : "Email check started. Your inbox stays read-only.", "info")
      pollNow.current()
    } catch (error) { toast(error instanceof Error ? error.message : "Could not start the check.", "error") }
  }
  const toggle = async () => {
    const enable = !status?.auto
    try {
      const result = await api.post<{ message?: string }>(`/api/autocheck?enabled=${enable}`)
      setStatus(await api.status())
      toast(result.message || (enable ? "Automatic checks are on." : "Automatic checks are off."), "success")
    } catch (error) { toast(error instanceof Error ? error.message : "Could not update the schedule.", "error") }
  }
  const scheduled = Boolean(status?.auto && status.next_in != null)
  // No visible countdown: poll quickly when a scheduled check is due, so the
  // bar switches to "Checking mail…" promptly.
  useEffect(() => {
    if (status?.running || !scheduled || status?.next_in == null) return
    const timer = window.setTimeout(onDue, Math.max(0, status.next_in) * 1000)
    return () => window.clearTimeout(timer)
  }, [status?.running, status?.next_in, scheduled, receivedAt, onDue])
  const elapsed = status?.running && status.stage_elapsed != null && status.stage_elapsed >= 5 ? status.stage_elapsed : null
  return <div className="top-actions">
    <span className={`connection-status ${status?.running ? "is-running" : ""}`}>
      {status?.running ? <LoaderCircle className="spin" size={15} /> : <span className="status-dot" />}
      {/* Keep changing text in its own element: translators may replace text
          nodes, so removing a bare text sibling can crash React reconciliation.
          Only this message is a live region; the ticking digits are not, or a
          screen reader would announce every second. */}
      <span className="status-text" aria-live="polite" title={status?.message || undefined}>{!status ? "Status unavailable" : status.running ? status.message || "Checking mail…" : status.updated_at ? "Updated" : "All systems ready"}</span>
      {elapsed != null && <small className="tabular status-elapsed">{elapsed}s</small>}
      {!status?.running && status?.updated_at && <Freshness updatedAt={status.updated_at} />}
    </span>
    {SHOW_AUTO_CHECK_TOGGLE && <button className={`schedule-button ${status?.auto ? "is-on" : ""}`} type="button" aria-pressed={Boolean(status?.auto)} aria-label={status?.auto ? "Auto-check on" : "Auto-check off"} onClick={toggle} disabled={!canManageSettings} title={!canManageSettings ? "Automatic checking is managed by the owner." : status?.auto ? `Checking automatically every ${status.interval_minutes ?? "?"} min. Click to turn off.` : "Turn on automatic checks"}><span className="sched-long">{status?.auto ? "Auto-check on" : "Auto-check off"}</span><span className="sched-short">{status?.auto ? "Auto on" : "Auto off"}</span></button>}
    <Button onClick={runCheck} disabled={status?.running || !bootstrap.readiness.accounts || (!calendarOnly && !bootstrap.readiness.model)}>{status?.running ? <LoaderCircle className="spin" /> : <Plus />}<span>{status?.running ? "Checking" : "Check now"}</span></Button>
  </div>
}

function DailyApplicationCount({count}:{count?:number}) {
  const daily=useQuery({queryKey:["applications-today"],queryFn:({ signal }) => api.applicationsToday(signal),enabled:count===undefined,retry:false,staleTime:30000,refetchInterval:60000,refetchOnWindowFocus:true})
  const value=count ?? daily.data?.applications_today
  const label=value===undefined ? daily.isError ? "Today's application count unavailable" : "Loading today's application count" : `${value} checked applications today`
  return <span className="header-application-count" title="Checked applications today · Chicago" aria-label={label}><strong>{value===undefined?"—":value.toLocaleString()}</strong><span>today</span></span>
}

function Workspace({ bootstrap }: { bootstrap: Bootstrap }) {
  const { role, signOut, session } = useAuth()
  const admin = role === "admin"
  const canManageSettings = admin && (!session?.workspace_id || !!session.is_owner)
  const canViewJobLinks = admin && (canManageSettings || session?.job_links_access === true)
  const toast = useToast()
  const [collapsed, setCollapsed] = useState(readBrowserPreference("mailcheck.sidebar") === "collapsed")
  const [mobileNav, setMobileNav] = useState(false)
  const [compactNav,setCompactNav]=useState(()=>window.matchMedia('(max-width: 1023px)').matches)
  const mobileNavTrigger=useRef<HTMLButtonElement>(null),mobileNavPanel=useRef<HTMLElement>(null)
  useEffect(()=>{
    const media=window.matchMedia('(max-width: 1023px)')
    const update=()=>{setCompactNav(media.matches);if(!media.matches)setMobileNav(false)}
    media.addEventListener('change',update)
    return()=>media.removeEventListener('change',update)
  },[])
  useEffect(()=>{
    if(!mobileNav)return
    const controls=()=>Array.from(mobileNavPanel.current?.querySelectorAll<HTMLElement>('a[href],button:not(:disabled),[tabindex="0"]')||[]).filter(element=>getComputedStyle(element).display!=='none'&&getComputedStyle(element).visibility!=='hidden')
    controls()[0]?.focus()
    const keyboard=(event:KeyboardEvent)=>{
      const dialog = document.activeElement?.closest('[role="dialog"]')
      if (event.defaultPrevented || dialog && dialog !== mobileNavPanel.current) return
      if(event.key==='Escape'){event.preventDefault();setMobileNav(false);return}
      if(event.key!=='Tab')return
      const items=controls(),first=items[0],last=items[items.length-1]
      if(!first||!last)return
      if(!mobileNavPanel.current?.contains(document.activeElement)||event.shiftKey&&document.activeElement===first||!event.shiftKey&&document.activeElement===last){event.preventDefault();(event.shiftKey?last:first).focus()}
    }
    document.addEventListener('keydown',keyboard)
    return()=>{document.removeEventListener('keydown',keyboard);if(mobileNavTrigger.current&&getComputedStyle(mobileNavTrigger.current).display!=='none')mobileNavTrigger.current.focus()}
  },[mobileNav])
  const location = useLocation()
  const navigate = useNavigate()
  useEffect(() => { setMobileNav(false) }, [location.pathname])
  // A navigation renders as a transition: React keeps the old page until the new
  // one is ready. Reflect the click immediately instead of looking unresponsive.
  const [pendingPath, setPendingPath] = useState<string | null>(null)
  useEffect(() => { setPendingPath(null) }, [location.pathname])
  useEffect(() => {
    if (!pendingPath) return
    const timer = window.setTimeout(() => setPendingPath(null), 20000)
    return () => window.clearTimeout(timer)
  }, [pendingPath])
  // A blocked navigation (for example unsaved Sourcing edits) never changes the
  // location, so drop the optimistic highlight as soon as a blocker holds it.
  const dataRouter = useContext(UNSAFE_DataRouterContext)?.router
  useEffect(() => dataRouter?.subscribe((state) => {
    if ([...state.blockers.values()].some((blocker) => blocker.state === "blocked")) setPendingPath(null)
  }), [dataRouter])
  // "New" = actionable queue items stored after the newest message this person had seen on
  // Triage (remembered per workspace and user in this browser). A first visit sets the baseline.
  const seenKey = `offerpath:triage-seen:${session?.workspace_id || "default"}:${session?.username || ""}`
  const readSeen = useCallback(() => { try { const value = localStorage.getItem(seenKey); return value == null || !/^\d+$/.test(value) ? null : Number(value) } catch { return null } }, [seenKey])
  const [seen, setSeen] = useState<number | null>(readSeen)
  useEffect(() => { setSeen(readSeen()) }, [readSeen])
  const queue = useQuery({
    queryKey: ["bootstrap", "queue-counts", seen],
    queryFn: ({signal}) => request<{actionable: number; latest?: number; new?: number}>(`/api/queue-counts${seen != null ? `?seen=${seen}` : ""}`, {signal}),
    enabled: admin && !["/settings", "/admin-management", "/job-links"].includes(location.pathname),
    refetchInterval: 60_000,
    placeholderData: previous => previous,
  })
  const actionable = bootstrap.counts.actionable ?? queue.data?.actionable ?? 0
  const latestSeen = queue.data?.latest
  const onTriage = location.pathname === "/"
  useEffect(() => {
    if (latestSeen == null || !(seen == null || onTriage && latestSeen !== seen)) return
    try { localStorage.setItem(seenKey, String(latestSeen)) } catch { /* this visit only */ }
    setSeen(latestSeen)
  }, [latestSeen, onTriage, seen, seenKey])
  const fresh = !onTriage && seen != null ? queue.data?.new ?? 0 : 0
  // The queue size in the tab title is visible from other tabs and the taskbar.
  useEffect(() => { document.title = actionable > 0 ? `(${actionable}) OfferPath` : "OfferPath" }, [actionable])
  const toggleSidebar = () => { const next = !collapsed; setCollapsed(next); writeBrowserPreference("mailcheck.sidebar", next ? "collapsed" : "expanded") }
  const navigateSidebar = (event: MouseEvent<HTMLAnchorElement>, path: string) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    if (location.pathname.replace(/\/$/, "") === path.replace(/\/$/, "")) event.preventDefault()
    else setPendingPath(path)
    setMobileNav(false)
  }

  return <div data-offerpath-workspace className={`app-frame ${collapsed ? "sidebar-collapsed" : ""}`}>
    <header className="topbar app-header">
      <div className="brand-header"><button className="brand-lockup" onClick={() => { const home = admin ? "/" : "/dashboard"; if (location.pathname !== home) navigate(home) }} aria-label="OfferPath home"><span className="brand-mark"><OfferPathMark size={28} /></span><span className="brand-word">Offer<span>Path</span></span></button></div>
      <div className="top-left"><Button variant="ghost" size="icon" className="mobile-menu" ref={mobileNavTrigger} aria-expanded={mobileNav} aria-controls="workspace-navigation" onClick={() => setMobileNav(true)} aria-label="Open navigation"><PanelLeftOpen /></Button><div className="crumb"><span>Workspace</span><ChevronRight size={14} /><strong>{workspaceNavigationLabel(pendingPath ?? location.pathname)}</strong></div>{(admin || !location.pathname.startsWith("/payments")) && <DailyApplicationCount count={bootstrap.counts.applications_today}/>}</div>
      <div className="top-right"><ThemeControl /><span className="signed-in-role">{!admin ? (session?.bidder_name ? `${session.bidder_name} · Bidder` : "Bidder") : session?.is_owner ? "Owner" : "Admin"}</span>{admin && !canManageSettings && <ChangePassword />}<Button variant="ghost" size="sm" onClick={() => void signOut().catch((error) => toast(error instanceof Error ? error.message : "Could not sign out.", "error"))}>Sign out</Button>{admin && location.pathname !== "/admin-management" && location.pathname !== "/job-links" && <JobStatus bootstrap={bootstrap} />}</div>
      {pendingPath && <div className="route-progress" role="progressbar" aria-label="Opening page" />}
    </header>
    {mobileNav && <div className="mobile-scrim" aria-hidden="true" onClick={() => setMobileNav(false)} />}
    <WorkspaceSidebar panelRef={mobileNavPanel} admin={admin} owner={!!session?.is_owner} canViewJobLinks={canViewJobLinks}
      drawer={compactNav || mobileNav} open={mobileNav} collapsed={collapsed} pendingPath={pendingPath}
      actionable={actionable} fresh={fresh} onNavigate={navigateSidebar} onPreload={preloadRoute}
      onToggle={toggleSidebar} onClose={() => setMobileNav(false)} />

    <section className={`app-content ${["/sourcing","/job-links"].includes(location.pathname) ? "sourcing-workspace" : ""}`}>
      {session?.workspace_id && <div className="workspace-banner"><span>Workspace: <strong>{session.workspace_name}</strong></span><span>{session.is_owner ? session.workspace_id === "legacy" ? "Owner’s original workspace" : "Owner access · another admin’s workspace" : session.username}</span>{session.is_owner && <NavLink to="/admin-management">Manage admins / switch workspace</NavLink>}</div>}
      {admin && location.pathname !== "/admin-management" && location.pathname !== "/sourcing" && location.pathname !== "/job-links" && location.pathname !== "/settings" && (!bootstrap.readiness.accounts) ? <div className="setup-ribbon"><span><CircleHelp size={17} />Your workspace is almost ready.</span><span>Connect an email account</span><Button variant="outline" size="sm" onClick={() => navigate("/accounts")}>Finish setup <ChevronRight size={15} /></Button></div> : null}
      <main className="page-content"><PageQueryBoundary><Suspense fallback={<Loading />}><Routes>
        <Route path="/" element={admin ? <TriagePage bootstrap={bootstrap} canManageSettings={canManageSettings} /> : <Navigate to="/dashboard" replace />} />
        <Route path="/followups" element={admin ? <Navigate to="/interview-processes" replace /> : <Navigate to="/dashboard" replace />} />
        <Route path="/inbox" element={admin ? <Navigate to="/" replace /> : <TriagePage bootstrap={bootstrap} canManageSettings={false} bidderInbox />} />
        <Route path="/dashboard" element={<DashboardPage bootstrap={bootstrap} readOnly={!admin} />} />
        <Route path="/interviews" element={admin ? <InterviewsPage bootstrap={bootstrap} /> : <Navigate to="/dashboard" replace />} />
        <Route path="/interview-processes" element={admin ? <InterviewPipelinePage /> : <Navigate to="/dashboard" replace />} />
        <Route path="/interview-processes/legacy" element={admin ? <InterviewProcessesPage /> : <Navigate to="/dashboard" replace />} />
        <Route path="/sourcing" element={<SourcingPage />} />
        <Route path="/job-links" element={canViewJobLinks ? <JobLinks/> : admin ? <div className="page-wrap"><PageHeading title="Job links access required" description="Ask the owner to enable Job links access for your admin account."/></div> : <Navigate to="/dashboard" replace/>} />
        <Route path="/payments" element={<PaymentsPage readOnly={!admin} />} />
        <Route path="/accounts" element={admin ? <AccountsPage canManageSettings={canManageSettings} /> : <Navigate to="/dashboard" replace />} />
        <Route path="/admin-management" element={session?.is_owner ? <AdminManagement /> : <Navigate to="/" replace />} />
        <Route path="/settings" element={canManageSettings ? <SettingsPage bootstrap={bootstrap} /> : <PersonalSettingsPage />} />
        <Route path="/login" element={<Navigate to={admin ? "/" : "/dashboard"} replace />} />
        <Route path="*" element={admin ? <UnknownRoute /> : <Navigate to="/dashboard" replace />} />
      </Routes></Suspense></PageQueryBoundary></main>
      <footer className="app-footer"><span><span className="footer-dot" />{admin ? "Admin workspace" : "Bidder workspace"}</span><span>Unread stays unread. Always.</span></footer>
    </section>
  </div>
}

function UnknownRoute() {
  const navigate = useNavigate()
  return <div className="page-wrap"><PageHeading title="That page moved" /><Card className="recovery-card"><p>Return to your triage workspace to continue.</p><Button onClick={() => navigate("/")}>Back to triage</Button></Card></div>
}

function Recovery({ message, retry, retrying }: { message: string; retry: () => void; retrying: boolean }) {
  const configurationError = /^The saved configuration at /i.test(message)
  const {session}=useAuth()
  const canManageSettings=!session?.workspace_id || !!session.is_owner
  const navigate = useNavigate()
  return <main className="recovery-page"><div className="brand-mark"><OfferPathMark size={30} /></div><p className="eyebrow">SAFE RECOVERY</p><h1>{configurationError ? "Check your local settings" : "Workspace temporarily unavailable"}</h1><p className="recovery-description">{configurationError ? "Settings need an update before OfferPath can open." : "OfferPath could not load your workspace. Try connecting again shortly."}</p><Card className="recovery-card"><pre>{message}</pre><Button onClick={retry} disabled={retrying}>Retry connection</Button>{canManageSettings ? <Button variant="outline" onClick={() => navigate("/settings")}>Try settings</Button> : <p>Ask the owner to review the shared Settings.</p>}</Card></main>
}

function BidderMailAlertMonitor({ scope, preferences }: { scope: string; preferences: number }) {
  useBidderMailAlerts(scope, preferences)
  return null
}

function ReadyApp() {
  useRealtimeUpdates()
  const path=useLocation().pathname
  const controlPage = path === "/admin-management" || path === "/job-links"
  const settingsRecovery=path==="/settings"
  const { data, isPending, error, refetch, isFetching } = useQuery({ queryKey: ["bootstrap"], queryFn: ({ signal }) => api.bootstrap(signal), retry: false, refetchInterval: 60_000, enabled: !controlPage })
  if (controlPage || settingsRecovery) return <Workspace bootstrap={settingsRecovery && data ? data : {readiness:{model:false,accounts:false,privacy_ack:true,outlook:false},counts:{},taxonomy:[],presets:[],last_run:"",account_count:0}} />
  if (isPending) return <div role="status" className="loading-state" data-offerpath-bootstrap>Connecting to your workspace…</div>
  if (!data && error) return <Recovery message={error.message} retry={() => void refetch()} retrying={isFetching} />
  // Keep the workspace at a stable position so refresh failures cannot discard
  // page state or unsaved input. A failed background read still has usable data.
  return <><Workspace bootstrap={data!} />{error && <div role="status" className="fixed bottom-4 right-4 z-50 max-w-md rounded-xl border border-border bg-card p-4 shadow-lg"><p>Workspace updates are temporarily unavailable.</p><Button onClick={() => void refetch()} disabled={isFetching}>Retry connection</Button></div>}</>
}

function SignedInApp() {
  const { session } = useAuth()
  const scope = bidderAlertScope(session)
  const preferences = useBidderAlertPreferences(scope)
  return <>{preferences !== 0 && <BidderMailAlertMonitor key={scope} scope={scope} preferences={preferences} />}<ReadyApp /></>
}

export default function App() { return <ToastProvider><AuthGate><SignedInApp /></AuthGate></ToastProvider> }
