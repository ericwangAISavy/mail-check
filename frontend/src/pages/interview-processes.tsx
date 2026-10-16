import { useState } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ArrowUpRight, Building2, CalendarDays, Search } from "lucide-react"
import { request } from "@/lib/api"
import type { InterviewProcess } from "@/lib/types"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Loading, PageHeading } from "@/components/common"
import "./interview-processes.css"

const dateTime = (value: string | null) => value ? new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "Time unknown"

export default function InterviewProcessesPage() {
  const [search, setSearch] = useState("")
  // The shared interview key refreshes this view when collection or corrections finish.
  const query = useQuery({ queryKey: ["interviews", "processes"], queryFn: () => request<{ processes: InterviewProcess[] }>("/api/interview-processes"), refetchInterval: 30_000 })
  const processes = query.data?.processes || []
  const needle = search.trim().toLowerCase()
  const visible = processes.filter(process => !needle || (process.organization || "Unassigned").toLowerCase().includes(needle) || process.events.some(event => event.organization_domains.some(domain => domain.includes(needle))))
  const unassigned = processes.find(process => !process.organization)?.event_count || 0
  return <div className="page-wrap processes-page">
    <PageHeading title="Interview processes" description="Follow each organization’s interview history, from the first booking to the next conversation." action={<Link className="process-calendar-link" to="/interviews"><CalendarDays size={16} />Open Interview calendar<ArrowUpRight size={15} /></Link>} />
    <p className="process-explanation">Use Check now on Interview to collect new calendar events. Events join the same organization by participant or organizer email domain. Multiple eligible domains stay Unassigned.</p>
    {query.isPending ? <Loading label="Loading interview processes…" /> : query.error ? <div className="process-empty"><p role="alert" className="inline-error">{query.error.message}</p><Button variant="outline" onClick={() => void query.refetch()}>Try again</Button></div> : <>
      <div className="process-overview" aria-label="Process totals">
        <Card><span>Organizations</span><strong>{processes.filter(process => process.organization).length}</strong></Card>
        <Card><span>Calendar events</span><strong>{processes.reduce((count, process) => count + process.event_count, 0)}</strong></Card>
        <Card><span>With upcoming interviews</span><strong>{processes.filter(process => process.organization && process.next_interview).length}</strong></Card>
        <Card><span>Unassigned events</span><strong>{unassigned}</strong></Card>
      </div>
      {processes.length === 0 ? <Card className="process-empty"><Building2 size={30} /><h2>No interview processes yet</h2><p>Collect events from your Interview calendar to start tracking organizations here.</p></Card> : <>
        <label className="process-search"><Search size={17} aria-hidden="true" /><span className="sr-only">Find organization</span><input type="search" placeholder="Find an organization or domain…" value={search} onChange={event => setSearch(event.target.value)} /></label>
        <div className="process-groups">{visible.map(process => <ProcessCard key={process.organization || "unassigned"} process={process} />)}</div>
        {!visible.length && <p className="process-empty">No matching organizations. Try another domain.</p>}
      </>}
    </>}
  </div>
}

function ProcessCard({ process }: { process: InterviewProcess }) {
  const name = process.organization || "Unassigned"
  return <Card className={`process-card${process.organization ? "" : " process-unassigned"}`}>
    <div className="process-card-heading"><div className="process-identity"><span className="process-icon"><Building2 size={20} aria-hidden="true" /></span><div><h2>{name}</h2><p>{process.event_count} {process.event_count === 1 ? "event" : "events"}{!process.organization && " · Organization needs review"}</p></div></div>
      <div className="process-next"><span>Next interview</span><strong>{process.next_interview ? dateTime(process.next_interview.start_at) : "No upcoming interview"}</strong></div>
    </div>
    <details className="process-history" open><summary>Event history <span>Earliest first · Times in your timezone</span></summary>
      <ol>{process.events.map(event => <li key={event.id}>
        <div className="process-event-time"><time dateTime={event.start_at || undefined}>{dateTime(event.start_at)}</time><span className={`process-status process-status-${event.display_status.toLowerCase().replaceAll(" ", "-")}`}>{event.display_status}</span></div>
        <div className="process-event-body"><h3>{event.company || event.stage}{event.role ? ` · ${event.role}` : ""}</h3><p>{event.company && event.stage !== "Other" ? `${event.stage} · ` : ""}{event.organizer_email || "Organizer unknown"}{event.account_labels?.length ? ` · ${event.account_labels.join(", ")}` : ""}</p>
          {event.assignment_reason && <div className="process-assignment"><strong>{event.assignment_reason}</strong>{event.organization_domains.length > 0 && <span>{event.organization_domains.join(", ")}</span>}</div>}
        </div>
        <Link className="process-event-link" to={`/interviews?event=${event.id}`} aria-label={`View event ${event.id}: ${event.stage}`}>View event<ArrowUpRight size={14} /></Link>
      </li>)}</ol>
    </details>
  </Card>
}
