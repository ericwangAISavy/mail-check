import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, ArrowRight, ArrowUpRight, Building2, CalendarDays, Flag, Mail, Pin, PinOff, Search, X } from "lucide-react"
import { request } from "@/lib/api"
import type { InterviewProcess, ProcessMilestone } from "@/lib/types"
import { dateInput, movePeriod, periodWindow, positionMilestones, inPeriod, milestoneTiming, needsFollowUp, type TimelinePeriod } from "@/lib/process-timeline"
import { InterviewDetails } from "@/components/interview-details"
import { MessageDetails } from "@/components/message-details"
import { Dialog } from "@/components/ui/dialog"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Loading, PageHeading } from "@/components/common"
import "./interview-processes.css"

const dateTime = (value: string) => new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
const processTone = (organization: string | null) => [...(organization || "unassigned")].reduce((hash, letter) => Math.imul(hash ^ letter.charCodeAt(0), 16777619) >>> 0, 2166136261) % 5
const periods: [TimelinePeriod, string][] = [["daily", "Daily"], ["weekly", "Weekly"], ["two-weeks", "Two weeks"], ["monthly", "Monthly"], ["two-months", "Two months"]]
type Preview = { milestone: ProcessMilestone; trigger: HTMLButtonElement; timing: ReturnType<typeof milestoneTiming> }

export default function InterviewProcessesPage() {
  const [search, setSearch] = useState("")
  const [anchor, setAnchor] = useState(() => dateInput(new Date(Date.now())))
  const [period, setPeriod] = useState<TimelinePeriod>("weekly")
  const [active, setActive] = useState<Preview | null>(null)
  const [detail, setDetail] = useState<Pick<Preview, "milestone" | "trigger"> | null>(null)
  const suppressFocus = useRef(false)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const client = useQueryClient()
  const query = useQuery({ queryKey: ["interviews", "processes"], queryFn: () => request<{ processes: InterviewProcess[] }>("/api/interview-processes"), refetchInterval: 30_000 })
  const pin = useMutation({
    mutationFn: ({ organization, pinned }: { organization: string | null; pinned: boolean }) => request("/api/interview-processes/pin", { method: "POST", body: JSON.stringify({ organization, pinned }) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["interviews", "processes"] }),
  })
  const keepPreview = () => { if (closeTimer.current) clearTimeout(closeTimer.current) }
  const hidePreview = () => { keepPreview(); closeTimer.current = setTimeout(() => setActive(null), 180) }
  const showPreview = (milestone: ProcessMilestone, trigger: HTMLButtonElement) => { if (suppressFocus.current || detail) return; keepPreview(); setActive({ milestone, trigger, timing: milestoneTiming(milestone, window) }) }
  const closePreview = () => { keepPreview(); setActive(null) }
  const openDetails = (milestone: ProcessMilestone, trigger: HTMLButtonElement) => {
    keepPreview()
    setActive(null)
    setDetail({ milestone, trigger })
  }
  const restoreMilestoneFocus = (event: Event) => {
    event.preventDefault()
    suppressFocus.current = true
    detail?.trigger.focus({ preventScroll: true })
    requestAnimationFrame(() => { suppressFocus.current = false })
  }
  useEffect(() => { setActive(null) }, [anchor, period, search])
  useEffect(() => () => { if (closeTimer.current) clearTimeout(closeTimer.current) }, [])
  const window = periodWindow(anchor, period)
  const processes = query.data?.processes || []
  const now = Math.max(Date.now(), query.dataUpdatedAt)
  const needle = search.trim().toLowerCase()
  const rows = processes.filter(process => !needle || (process.organization || "Unassigned").toLowerCase().includes(needle) || process.milestones.some(m => m.organization_domains.some(domain => domain.includes(needle))))
    .filter(process => process.milestones.some(milestone => inPeriod(milestone, window)))
    .map(process => {
      const followUp = needsFollowUp(process.milestones, now, process.events)
      return { process, followUp, layout: positionMilestones(process.milestones, followUp).map(item => ({ ...item, timing: milestoneTiming(item.milestone, window, now) })), matchingCount: process.milestones.filter(milestone => inPeriod(milestone, window)).length }
    })
    .sort((a, b) => Number(b.process.pinned) - Number(a.process.pinned))
  const endDay = new Date(window.end); endDay.setDate(endDay.getDate() - 1)
  const rangeLabel = period === "daily" ? window.start.toLocaleDateString(undefined, { dateStyle: "long" }) : `${window.start.toLocaleDateString(undefined, { month: "short", day: "numeric" })} – ${endDay.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`
  return <div className="page-wrap processes-page">
    <PageHeading title="Interview processes" description="Every conversation, one step at a time." action={<Link className="process-calendar-link" to="/interviews"><CalendarDays size={16} />Open Interview calendar<ArrowUpRight size={15} /></Link>} />
    <Card className="timeline-controls">
      <div className="timeline-periods" role="group" aria-label="Timeline period">{periods.map(([value, label]) => <button type="button" key={value} aria-pressed={period === value} onClick={() => setPeriod(value)}>{label}</button>)}</div>
      <div className="timeline-date-controls"><Button variant="ghost" size="icon" aria-label="Previous period" onClick={() => setAnchor(movePeriod(anchor, period, -1))}><ArrowLeft size={16} /></Button><label><span className="sr-only">Timeline date</span><input aria-label="Timeline date" type="date" min="1971-01-01" max="2100-12-31" value={anchor} onChange={event => { if (event.target.value && event.target.validity.valid) setAnchor(event.target.value) }} /></label><Button variant="ghost" size="icon" aria-label="Next period" onClick={() => setAnchor(movePeriod(anchor, period, 1))}><ArrowRight size={16} /></Button><Button variant="outline" size="sm" onClick={() => setAnchor(dateInput(new Date(Date.now())))}>Today</Button></div>
    </Card>
    <div className="timeline-toolbar"><label className="process-search"><Search size={16} aria-hidden="true" /><span className="sr-only">Find organization</span><input type="search" placeholder="Find organization…" value={search} onChange={event => setSearch(event.target.value)} /></label><div className="timeline-legend"><span><CalendarDays size={13} />Meeting</span><span><Mail size={13} />Message</span><span className="legend-past">Past / outside window</span><span className="legend-present">In window</span><span className="legend-future">Upcoming after window</span></div></div>
    <div className="timeline-range"><h2>{rangeLabel}</h2><span>{rows.length} {rows.length === 1 ? "process" : "processes"} · Full history for matching processes</span></div>
    {pin.error && <p role="alert" className="inline-error">{pin.error.message}</p>}
    {query.isPending ? <Loading label="Loading interview processes…" /> : query.error ? <div className="process-empty"><p role="alert" className="inline-error">{query.error.message}</p><Button variant="outline" onClick={() => void query.refetch()}>Try again</Button></div> : processes.length === 0 ? <Card className="process-empty"><Building2 size={30} /><h2>No interview processes yet</h2><p>Use Check now on Interview to collect calendar events.</p></Card> : <>
      <div className="process-groups">{rows.map(({ process, layout, matchingCount, followUp }) => <Card className={`process-timeline-card process-tone-${processTone(process.organization)}${process.pinned ? " is-pinned" : ""}`} key={process.organization || "unassigned"}>
        <div className="process-row-heading"><div className="process-identity"><Building2 size={18} aria-hidden="true" /><h2>{process.organization || "Unassigned"}</h2>{process.pinned && <span className="pinned-label">Pinned</span>}{followUp && <span className="process-follow-up-label">Follow up</span>}<span className="process-milestone-count">{layout.length} milestones · {matchingCount} in window</span></div><button type="button" className="process-pin" aria-label={`${process.pinned ? "Unpin" : "Pin"} ${process.organization || "Unassigned"}`} aria-pressed={process.pinned} disabled={pin.isPending} onClick={() => pin.mutate({ organization: process.organization, pinned: !process.pinned })}>{process.pinned ? <PinOff size={16} /> : <Pin size={16} />}</button></div>
        {layout.length ? <div className="timeline-scroll" tabIndex={0} role="region" aria-label={`${process.organization || "Unassigned"} timeline`}><div className="timeline-canvas">
          <div className="timeline-track" style={{ minWidth: Math.max(0, (layout.length - 1 + Number(followUp)) * 48) }}>
            {layout.length + Number(followUp) > 1 && <div className="timeline-line" aria-hidden="true" />}
            {layout.map(({ milestone, position, timing }) => <button key={milestone.id} type="button" className={`timeline-milestone milestone-${milestone.kind} milestone-${milestone.status.toLowerCase().replaceAll(" ", "-")} milestone-${timing.tone}`} style={{ left: `${position * 100}%` }} aria-label={`${milestone.kind === "event" ? "Event" : "Email"}: ${milestone.title}, ${dateTime(milestone.occurred_at)} · ${timing.label}`} aria-haspopup="dialog" aria-expanded={active?.milestone.id === milestone.id} onMouseEnter={event => showPreview(milestone, event.currentTarget)} onMouseLeave={hidePreview} onFocus={event => showPreview(milestone, event.currentTarget)} onBlur={hidePreview} onClick={event => openDetails(milestone, event.currentTarget)}>{milestone.kind === "event" ? <CalendarDays size={12} aria-hidden="true" /> : <Mail size={12} aria-hidden="true" />}</button>)}
            {followUp && <span className="timeline-milestone milestone-follow-up" style={{ left: "100%" }} role="status" aria-label={`Follow up needed for ${process.organization || "Unassigned"}`} title="Follow up needed — all saved activity has finished"><Flag size={13} aria-hidden="true" /></span>}
          </div>
        </div></div> : <p className="timeline-no-milestones">No milestones saved.</p>}
      </Card>)}</div>
      {!rows.length && <Card className="process-empty"><CalendarDays size={26} /><h3>No milestones in this period</h3><p>Choose another date or a wider time window. Matching processes show their complete history.</p></Card>}
    </>}
    {active && !detail && <MilestonePreview active={active} onClose={closePreview} onEnter={keepPreview} onLeave={hidePreview} onOpen={() => openDetails(active.milestone, active.trigger)} />}
    <Dialog open={detail !== null} onOpenChange={open => { if (!open) setDetail(null) }}>{detail && (detail.milestone.kind === "event" ? <InterviewDetails key={detail.milestone.id} id={Number(detail.milestone.id.split(":")[1])} onCloseAutoFocus={restoreMilestoneFocus} /> : <MessageDetails key={detail.milestone.id} id={Number(detail.milestone.id.split(":")[1])} onCloseAutoFocus={restoreMilestoneFocus} />)}</Dialog>
  </div>
}

function MilestonePreview({ active, onClose, onEnter, onLeave, onOpen }: { active: Preview; onClose: () => void; onEnter: () => void; onLeave: () => void; onOpen: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState({ left: 12, top: 12 })
  const milestone = active.milestone
  useLayoutEffect(() => {
    const place = () => {
      const rect = active.trigger.getBoundingClientRect(), panel = ref.current!
      const width = panel.offsetWidth, height = panel.offsetHeight
      const left = Math.min(Math.max(12, rect.left + rect.width / 2 - width / 2), window.innerWidth - width - 12)
      const top = rect.bottom + height + 14 < window.innerHeight ? rect.bottom + 10 : Math.max(12, rect.top - height - 10)
      setPosition({ left, top })
    }
    place()
    window.addEventListener("resize", place)
    window.addEventListener("scroll", place, true)
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true) }
  }, [active])
  useEffect(() => {
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") onClose() }
    const outside = (event: PointerEvent) => { if (!ref.current?.contains(event.target as Node) && !active.trigger.contains(event.target as Node)) onClose() }
    document.addEventListener("keydown", key); document.addEventListener("pointerdown", outside)
    return () => { document.removeEventListener("keydown", key); document.removeEventListener("pointerdown", outside) }
  }, [active, onClose])
  return createPortal(<div ref={ref} tabIndex={-1} role="dialog" aria-label="Milestone preview" className="milestone-preview" style={position} onMouseEnter={onEnter} onMouseLeave={onLeave} onFocus={onEnter} onBlur={onLeave}>
    <div className="milestone-preview-top"><span>{milestone.kind === "event" ? <CalendarDays size={14} /> : <Mail size={14} />}{milestone.kind === "event" ? "Calendar event" : "Email"}{milestone.status !== "Email" && <span className="milestone-preview-status">{milestone.status}</span>}</span><button type="button" aria-label="Close preview" onClick={onClose}><X size={15} /></button></div>
    <h3>{milestone.title}</h3><p className={`milestone-timing milestone-timing-${active.timing.tone}`}>{active.timing.label}</p><time dateTime={milestone.occurred_at}>{dateTime(milestone.occurred_at)}</time>
    {milestone.summary && <p className="milestone-summary">{milestone.summary}</p>}
    <p className="milestone-sender">{milestone.sender || "Sender unknown"}{milestone.account_labels.length ? ` · ${milestone.account_labels.join(", ")}` : ""}</p>
    {milestone.assignment_reason && <p className="milestone-assignment">{milestone.assignment_reason}{milestone.organization_domains.length > 0 && <span>{milestone.organization_domains.join(", ")}</span>}</p>}
    <button type="button" className="milestone-detail-action" onClick={onOpen}>{milestone.kind === "event" ? "View event" : "View message"}<ArrowUpRight size={14} /></button>
  </div>, document.body)
}
