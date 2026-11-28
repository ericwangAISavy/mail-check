import { useEffect, useId, useRef, useState, type MouseEvent, type Ref } from "react"
import { createPortal } from "react-dom"
import { NavLink } from "react-router-dom"
import {
  BarChart3, BriefcaseBusiness, CalendarDays, Inbox, Link2, Mails, PanelLeftClose,
  PanelLeftOpen, Settings, ShieldCheck, UsersRound, Workflow, X, type LucideIcon,
} from "lucide-react"
import { OfferPathMark } from "./offerpath-mark"
import ReleaseHistory from "./release-history"

type Destination = { to: string; label: string; icon: LucideIcon; access?: "admin" | "bidder" | "owner" | "job-links" }
const groups: { id: string; label: string; destinations: Destination[] }[] = [
  { id: "workspace", label: "Workspace", destinations: [
    { to: "/", label: "Triage", icon: Inbox, access: "admin" },
    { to: "/inbox", label: "Inbox", icon: Inbox, access: "bidder" },
    { to: "/dashboard", label: "Dashboard", icon: BarChart3 },
  ] },
  { id: "interviews", label: "Interviews", destinations: [
    { to: "/interviews", label: "Interview", icon: CalendarDays, access: "admin" },
    { to: "/interview-processes", label: "Interview pipeline", icon: Workflow, access: "admin" },
  ] },
  { id: "jobs", label: "Jobs", destinations: [
    { to: "/sourcing", label: "Job sourcing", icon: BriefcaseBusiness },
    { to: "/job-links", label: "Job links", icon: Link2, access: "job-links" },
  ] },
  { id: "management", label: "Management", destinations: [
    { to: "/payments", label: "Bidder management", icon: UsersRound },
    { to: "/accounts", label: "Accounts", icon: Mails, access: "admin" },
  ] },
  { id: "administration", label: "Administration", destinations: [
    { to: "/settings", label: "Settings", icon: Settings },
    { to: "/admin-management", label: "Admin management", icon: ShieldCheck, access: "owner" },
  ] },
]

export function workspaceNavigationLabel(path: string) {
  const destination = path === "/interview-processes/legacy" ? "/interview-processes" : path.replace(/\/$/, "") || "/"
  return groups.flatMap(group => group.destinations).find(item => item.to === destination)?.label ?? "Triage"
}

type SidebarProps = {
  panelRef: Ref<HTMLElement>
  admin: boolean
  owner: boolean
  canViewJobLinks: boolean
  drawer: boolean
  open: boolean
  collapsed: boolean
  pendingPath: string | null
  actionable: number
  fresh: number
  onNavigate: (event: MouseEvent<HTMLAnchorElement>, path: string) => void
  onPreload: (path: string) => void
  onToggle: () => void
  onClose: () => void
}

const compactCount = (count: number) => count > 9999 ? "9999+" : String(count)

export default function WorkspaceSidebar({
  panelRef, admin, owner, canViewJobLinks, drawer, open, collapsed, pendingPath, actionable, fresh,
  onNavigate, onPreload, onToggle, onClose,
}: SidebarProps) {
  const rail = collapsed && !drawer
  const access = { admin, bidder: !admin, owner: admin && owner, "job-links": canViewJobLinks }
  const labelId = useId()
  const queueId = useId()
  const queueDescription = actionable > 0
    ? `${actionable.toLocaleString()} in queue${fresh > 0 ? `, ${fresh.toLocaleString()} new since your last visit` : ""}`
    : ""
  const [tip, setTip] = useState<{ label: string; detail?: string; left: number; top: number }>()
  const dismiss = useRef<number | undefined>(undefined)
  const hideTip = () => {
    window.clearTimeout(dismiss.current)
    setTip(undefined)
  }
  const showTip = (link: HTMLAnchorElement, label: string, detail?: string) => {
    if (!rail) return
    window.clearTimeout(dismiss.current)
    const { right, top, height } = link.getBoundingClientRect()
    setTip({ label, detail, left: right + 10, top: top + height / 2 })
  }
  const scheduleTipDismissal = () => {
    window.clearTimeout(dismiss.current)
    dismiss.current = window.setTimeout(() => setTip(undefined), 100)
  }

  useEffect(() => {
    if (!tip) return
    const dismissTip = () => { window.clearTimeout(dismiss.current); setTip(undefined) }
    const keyboard = (event: KeyboardEvent) => { if (event.key === "Escape") dismissTip() }
    window.addEventListener("resize", dismissTip)
    window.addEventListener("keydown", keyboard)
    return () => {
      window.clearTimeout(dismiss.current)
      window.removeEventListener("resize", dismissTip)
      window.removeEventListener("keydown", keyboard)
    }
  }, [tip])

  return <aside ref={panelRef} id="workspace-navigation" className={`sidebar workspace-sidebar${open ? " mobile-open" : ""}`}
    data-navigation-mode={drawer ? "drawer" : rail ? "rail" : "expanded"}
    inert={drawer && !open} role={open ? "dialog" : undefined} aria-modal={open ? true : undefined} aria-label={open ? "Navigation" : undefined}>
    {drawer && <div className="sidebar-drawer-header">
      <div className="sidebar-drawer-brand"><OfferPathMark size={25} /><span>Offer<span>Path</span></span></div>
      <button type="button" className="sidebar-control" aria-label="Close navigation" onClick={onClose}><X size={18} aria-hidden="true" /></button>
    </div>}
    <nav className="side-nav" aria-label="Main navigation" onScroll={hideTip}>
      {groups.map(group => {
        const destinations = group.destinations.filter(item => !item.access || access[item.access])
        if (!destinations.length) return null
        const headingId = `${labelId}-${group.id}`
        return <div className={`sidebar-group${group.id === "administration" ? " sidebar-administration" : ""}`} key={group.id} role="group" aria-labelledby={headingId}>
          <div id={headingId} className="sidebar-group-label">{group.label}</div>
          <ul className="sidebar-group-links">
            {destinations.map(({ to, label, icon: Icon }) => {
              const counts = to === "/" && queueDescription
              return <li key={to}><NavLink to={to} end={to === "/"}
                className={({ isActive }) => `side-link${isActive ? " active" : ""}${pendingPath === to ? " is-pending" : ""}`}
                aria-describedby={counts ? queueId : undefined}
                title={!rail && counts ? queueDescription : undefined}
                onClick={event => { hideTip(); onNavigate(event, to) }}
                onPointerEnter={event => { onPreload(to); showTip(event.currentTarget, label, counts || undefined) }}
                onPointerLeave={event => { if (rail && !event.currentTarget.matches(":focus-visible")) scheduleTipDismissal() }}
                onFocus={event => { onPreload(to); if (event.currentTarget.matches(":focus-visible")) showTip(event.currentTarget, label, counts || undefined) }}
                onBlur={hideTip} onPointerDown={() => onPreload(to)}>
                <Icon size={17} strokeWidth={1.75} aria-hidden="true" />
                <span className="sidebar-link-label">{label}</span>
                {counts && <span className="nav-badges" data-fresh={fresh > 0} aria-hidden="true">
                  {fresh > 0 && <span className="nav-new">{compactCount(fresh)} new</span>}
                  <span className="nav-count">{compactCount(actionable)}</span>
                </span>}
              </NavLink></li>
            })}
          </ul>
        </div>
      })}
      {queueDescription && <span id={queueId} hidden>{queueDescription}</span>}
    </nav>
    <div className="sidebar-footer">
      {!drawer && <button type="button" className="sidebar-control sidebar-collapse" aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
        title={collapsed ? "Expand navigation" : "Collapse navigation"} aria-expanded={!collapsed} aria-controls="workspace-navigation"
        onClick={() => { hideTip(); onToggle() }}>
        {collapsed ? <PanelLeftOpen size={17} aria-hidden="true" /> : <PanelLeftClose size={17} aria-hidden="true" />}
      </button>}
      <ReleaseHistory />
    </div>
    {rail && tip && createPortal(<div className="sidebar-tooltip" aria-hidden="true" style={{ left: tip.left, top: tip.top }}
      onPointerEnter={() => window.clearTimeout(dismiss.current)} onPointerLeave={scheduleTipDismissal}>
      <span>{tip.label}</span>{tip.detail && <small>{tip.detail}</small>}
    </div>, document.body)}
  </aside>
}
