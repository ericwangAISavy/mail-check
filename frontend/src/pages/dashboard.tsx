import { lazy, Suspense, useMemo } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { AlertTriangle, ArrowDownRight, ArrowRight, ArrowUpRight, CalendarDays, CheckCircle2, FileText, Layers, LoaderCircle, Minus, RefreshCw, RotateCcw, TrendingUp, Users, Wallet } from "lucide-react"
import { api } from "@/lib/api"
import type { Bootstrap } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { EmptyState, Loading, useToast } from "@/components/common"
import { usePageState } from "@/lib/page-state"
import type { Series } from "@/components/dashboard-charts"
import {
  accountAliases, average, changeText, count, dayLabel, money, percent, rangeLabel,
  type Bucket, type Change, type DashboardMetrics, type Grain, type ProfileMetric, type TrendPoint,
} from "@/lib/dashboard-metrics"

const TrendChart = lazy(() => import("@/components/dashboard-charts").then(module => ({ default: module.TrendChart })))
const RANGES = [4, 8, 12]
const DEFAULT_WEEKS = 8
const bidderColor = (index: number) => `var(--activity-color-${index % 7})`

function Sparkline({ points, tone }: { points: TrendPoint[]; tone: string }) {
  const width = 220, height = 64, max = Math.max(1, ...points.map(p => p.value ?? 0))
  const xy = points.map((p, i): [number, number] | null => p.value == null ? null : [4 + (i / Math.max(1, points.length - 1)) * (width - 8), height - 6 - (p.value / max) * (height - 14)]).filter((p): p is [number, number] => p !== null)
  if (xy.length < 2) return <span />
  // Horizontal control points keep each curve segment between its two values.
  const path = (list: [number, number][]) => list.map(([x, y], i) => { if (!i) return `M${x},${y}`; const [px, py] = list[i - 1], mid = (px + x) / 2; return `C${mid},${py} ${mid},${y} ${x},${y}` }).join("")
  const dashed = points[points.length - 1].partial && points[points.length - 1].value != null
  const solid = dashed ? xy.slice(0, -1) : xy
  const [lx, ly] = xy[xy.length - 1]
  return <svg className={`od-spark ${tone}`} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={`Weekly totals: ${points.map(p => `${dayLabel(p.week)} ${p.value ?? "no records"}`).join(", ")}`}>
    <path className="od-spark-fill" d={`${path(xy)}L${lx},${height}L${xy[0][0]},${height}Z`} />
    <path className="od-spark-line" d={path(solid)} />
    {dashed && <path className="od-spark-line is-dashed" d={path(xy.slice(-2))} />}
    <circle cx={lx} cy={ly} r={3} />
  </svg>
}

function Delta({ change, versus }: { change: Change; versus: string }) {
  const text = changeText(change)
  if (!text) return <span className="od-delta is-none">No comparable history</span>
  const direction = change!.absolute > 0 ? "up" : change!.absolute < 0 ? "down" : "flat"
  const Icon = direction === "up" ? ArrowUpRight : direction === "down" ? ArrowDownRight : Minus
  return <><span className={`od-delta is-${direction}`}><Icon size={13} aria-hidden="true" />{text}</span><span className="od-versus">{versus}</span></>
}

function WeeklySummary({ data }: { data: DashboardMetrics }) {
  const { applications: apps, interviews: meetings, week_start, week_end } = data.summaries
  const averageText = (value: number | null, weeks: number) => value == null ? "Weekly average N/A" : `${weeks}-week average ${average(value)}`
  return <div className="od-summaries">
    <section className="od-card od-summary" aria-labelledby="od-apps-title">
      <span className="od-icon is-apps" aria-hidden="true"><FileText size={20} /></span>
      <div className="od-summary-body">
        <h2 id="od-apps-title">Applications this week<small>Week to date · {rangeLabel(week_start, week_end)}</small></h2>
        <p className="od-figure"><strong>{count(apps.current)}</strong><Delta change={apps.change} versus={`vs ${count(apps.previous_comparable)} by this time last week`} /></p>
        <p className="od-context"><span>Last week {count(apps.previous_full)}</span><span>{averageText(apps.average, apps.average_weeks)}</span></p>
      </div>
      <Sparkline points={apps.trend} tone="is-apps" />
    </section>
    <section className="od-card od-summary" aria-labelledby="od-meet-title">
      <span className="od-icon is-meet" aria-hidden="true"><CalendarDays size={20} /></span>
      <div className="od-summary-body">
        <h2 id="od-meet-title">Interviews this week<small>Calendar events, Mon–Sun, including upcoming</small></h2>
        <p className="od-figure"><strong>{count(meetings.scheduled)}</strong><Delta change={meetings.change} versus="vs last week’s full schedule" /></p>
        <p className="od-context"><span title={meetings.previous_so_far == null ? undefined : `${count(meetings.previous_so_far)} had started by this time last week`}>{count(meetings.so_far)} started so far</span><span>Last week {count(meetings.previous_full)}</span><span>{averageText(meetings.average, meetings.average_weeks)}</span></p>
      </div>
      <Sparkline points={meetings.trend} tone="is-meet" />
    </section>
  </div>
}

type Tab = "profiles" | "bidders" | "workload"
type BidderMetric = "completion_rate" | "checked" | "expired" | "remaining" | "available"
type WorkloadKey = "new" | "checked" | "backlog" | "expired"
const TABS: [Tab, string, typeof TrendingUp][] = [["profiles", "Profile quality", TrendingUp], ["bidders", "Bidder productivity", Users], ["workload", "Workload", Layers]]
const PROFILE_METRICS: [ProfileMetric, string, string, string][] = [
  ["interviews", "Interviews", "Weekly interview performance", "Calendar interview events by profile, by the week they take place"],
  ["applications", "Applications", "Weekly applications", "Unique confirmed applications by profile"],
  ["rejections", "Rejections", "Weekly rejections", "Unique rejections by profile, by the week the email arrived"],
  ["interview_rate", "Interview conversion", "Application to interview conversion", "Share of each week’s applications that reached an interview"],
  ["rejection_rate", "Rejection rate", "Application rejection rate", "Share of each week’s applications that were rejected"],
]
const BIDDER_METRICS: [BidderMetric, string, string, string][] = [
  ["completion_rate", "Completion rate", "Bidder completion rate", "Completed ÷ available links (opening backlog plus newly available, each counted once)"],
  ["checked", "Checked", "Checked applications", "Credited applications, counted the same way as Bidder management"],
  ["expired", "Expired", "Expired links", "Available links that reached the 7-day limit unchecked"],
  ["remaining", "Remaining", "Remaining workload", "Links still open at the end of each period"],
  ["available", "Available", "Available workload", "Opening backlog plus newly available links"],
]
const WORKLOAD: [WorkloadKey, string, string][] = [["new", "New links", "var(--od-new)"], ["checked", "Checked", "var(--od-checked)"], ["backlog", "Backlog", "var(--od-backlog)"], ["expired", "Expired", "var(--od-expired)"]]

function Segment<K extends string>({ label, value, options, onChange }: { label: string; value: K; options: { key: K; text: string; disabled?: string | null }[]; onChange: (key: K) => void }) {
  return <div className="od-segment" role="group" aria-label={label}>{options.map(o => <button key={o.key} type="button" aria-pressed={value === o.key} className={o.disabled ? "is-unavailable" : undefined} title={o.disabled || undefined} onClick={() => onChange(o.key)}>{o.text}</button>)}</div>
}

function Workspace({ data }: { data: DashboardMetrics }) {
  const [tab, setTab] = usePageState<Tab>("dashboard", "tab", "profiles", v => TABS.some(t => t[0] === v))
  const [profileMetric, setProfileMetric] = usePageState<ProfileMetric>("dashboard", "profile-metric", "interviews", v => PROFILE_METRICS.some(m => m[0] === v))
  const [bidderMetric, setBidderMetric] = usePageState<BidderMetric>("dashboard", "bidder-metric", "completion_rate", v => BIDDER_METRICS.some(m => m[0] === v))
  const [grain, setGrain] = usePageState<Grain>("dashboard", "grain", "weekly", v => v === "daily" || v === "weekly")
  const [showNew, setShowNew] = usePageState("dashboard", "new-links", true)
  const [showChecked, setShowChecked] = usePageState("dashboard", "checked", true)
  const [showBacklog, setShowBacklog] = usePageState("dashboard", "backlog", false)
  const [showExpired, setShowExpired] = usePageState("dashboard", "expired", false)
  const [showData, setShowData] = usePageState("dashboard", "data", false)
  const visible: Record<WorkloadKey, [boolean, (v: boolean) => void]> = { new: [showNew, setShowNew], checked: [showChecked, setShowChecked], backlog: [showBacklog, setShowBacklog], expired: [showExpired, setShowExpired] }

  const profiles = data.profiles, work = data.bidders[grain]
  const aliases = useMemo(() => accountAliases(profiles.series), [profiles.series])
  const rateMetric = profileMetric === "interview_rate" || profileMetric === "rejection_rate" ? profileMetric : null
  const unavailable = tab === "profiles" && rateMetric && !profiles.rates[rateMetric].available ? profiles.rates[rateMetric].reason : null

  let title: string, subtitle: string, series: Series[], percentage = false, buckets: Bucket[] = work.buckets, activeGrain: Grain = grain, note: ((i: number) => string | null) | undefined
  if (tab === "profiles") {
    const meta = PROFILE_METRICS.find(m => m[0] === profileMetric)!
    title = meta[2]; subtitle = meta[3]; percentage = !!rateMetric; buckets = profiles.weeks; activeGrain = "weekly"
    series = profiles.series.map((p, index) => {
      const raw: (number | null | { value: number; hits: number; base: number })[] = p.points[profileMetric]
      // Accounts that share a calendar colour keep its hue; repeats are shaded so lines stay distinct.
      const repeat = profiles.series.slice(0, index).some(other => other.color === p.color)
      return { key: `p${p.id}`, name: aliases[p.id], full: p.label, color: repeat ? "color-mix(in srgb,var(--calendar-accent) 45%,var(--foreground))" : "var(--calendar-accent)", className: `account-color-${p.color}`,
        values: raw.map(v => v == null ? null : typeof v === "number" ? v : v.value),
        details: raw.map(v => v && typeof v === "object" ? `${v.hits.toLocaleString()} of ${v.base.toLocaleString()} applications` : null) }
    })
    note = index => {
      const week = profiles.weeks[index]
      if (profileMetric === "interviews" && week.partial) return "Includes interviews still ahead this week."
      if (profileMetric === "rejections" && week.replies_partial && profiles.replies_since) return `Rejection emails are recorded from ${dayLabel(profiles.replies_since)}; this week is incomplete.`
      if (rateMetric) return `${profiles.cohort_days}-day follow-up; applications confirmed through ${dayLabel(profiles.mature_through)}.`
      return null
    }
  } else if (tab === "bidders") {
    const meta = BIDDER_METRICS.find(m => m[0] === bidderMetric)!
    title = meta[2]; subtitle = meta[3]; percentage = bidderMetric === "completion_rate"
    series = work.series.map((b, index) => ({ key: `b${b.id}`, name: b.name, full: b.name, color: bidderColor(index),
      values: b.points.map(p => p == null ? null : p[bidderMetric]),
      details: b.points.map(p => p && percentage && p.available ? `${p.completed.toLocaleString()} of ${p.available.toLocaleString()} available links` : null) }))
  } else {
    title = "Workload supply and output"; subtitle = "New links added against checked applications; backlog is what remains open at each period’s end"
    series = WORKLOAD.filter(([key]) => visible[key][0]).map(([key, name, color]) => ({ key, name, full: name, color, values: work.workload.map(p => p[key]) }))
    note = () => "Checked can exceed new links when earlier backlog is completed."
  }
  const format = percentage ? (v: number) => percent(v) : (v: number) => v.toLocaleString("en-US")
  const since = data.bidders.history_since
  const history = tab !== "profiles" && since && since > data.range.start ? ` Sourcing history starts ${dayLabel(since)}; earlier periods are blank.` : ""

  return <section className="od-card od-workspace" aria-label="Analytics">
    <div className="od-tabs" role="tablist" aria-label="Analytics view">{TABS.map(([key, text, Icon]) => <button key={key} type="button" role="tab" id={`od-tab-${key}`} aria-selected={tab === key} aria-controls="od-panel" tabIndex={tab === key ? 0 : -1}
      onClick={() => setTab(key)} onKeyDown={event => {
        const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0
        if (!step) return
        event.preventDefault()
        const next = TABS[(TABS.findIndex(t => t[0] === key) + step + TABS.length) % TABS.length][0]
        setTab(next); document.getElementById(`od-tab-${next}`)?.focus()
      }}><Icon size={16} aria-hidden="true" />{text}</button>)}</div>
    <div role="tabpanel" id="od-panel" aria-labelledby={`od-tab-${tab}`}>
      <header className="od-chart-head">
        <div className="od-chart-title"><h2>{title}</h2><p>{subtitle}</p></div>
        <div className="od-chart-tools">
          {tab === "profiles" && <Segment label="Profile metric" value={profileMetric} onChange={setProfileMetric} options={PROFILE_METRICS.map(m => ({ key: m[0], text: m[1], disabled: m[0] === "interview_rate" || m[0] === "rejection_rate" ? profiles.rates[m[0]].reason : null }))} />}
          {tab === "bidders" && <Segment label="Bidder metric" value={bidderMetric} onChange={setBidderMetric} options={BIDDER_METRICS.map(m => ({ key: m[0], text: m[1] }))} />}
          {tab === "workload" && <div className="od-toggles" role="group" aria-label="Visible series">{WORKLOAD.map(([key, text, color]) => <button key={key} type="button" aria-pressed={visible[key][0]} onClick={() => visible[key][1](!visible[key][0])}><i style={{ background: color }} aria-hidden="true" />{text}</button>)}</div>}
          {tab !== "profiles" && <Segment label="Aggregation" value={grain} onChange={setGrain} options={[{ key: "daily", text: "Daily" }, { key: "weekly", text: "Weekly" }]} />}
          <Button variant="ghost" size="sm" aria-expanded={showData} onClick={() => setShowData(value => !value)}>{showData ? "Hide data" : "View data"}</Button>
        </div>
      </header>
      <div className="od-plot">
        {unavailable ? <div className="od-unavailable" role="status"><strong>N/A — not reliable enough to chart</strong><p>{unavailable}</p></div>
          : <Suspense fallback={<Loading label="Loading chart…" />}><TrendChart key={`${tab}-${activeGrain}`} label={title} buckets={buckets} series={series} grain={activeGrain} format={format} percentage={percentage} note={note} /></Suspense>}
      </div>
      {!unavailable && <p className="od-chart-note"><i aria-hidden="true" />Dashed: {activeGrain === "weekly" ? "current week, still in progress" : "today, still in progress"}. Select a line’s name to isolate it.{history}</p>}
      {showData && !unavailable && <div className="od-data"><table aria-label={`${title} data`}><thead><tr><th scope="col">{activeGrain === "weekly" ? "Week of" : "Day"}</th>{series.map(s => <th scope="col" key={s.key} title={s.full}>{s.name}</th>)}</tr></thead>
        <tbody>{buckets.map((bucket, i) => <tr key={bucket.start}><th scope="row">{dayLabel(bucket.start)}{bucket.partial ? " (in progress)" : ""}</th>{series.map(s => <td key={s.key} title={s.details?.[i] || undefined}>{s.values[i] == null ? "—" : format(s.values[i] as number)}</td>)}</tr>)}</tbody></table></div>}
    </div>
  </section>
}

function Payments({ data }: { data: DashboardMetrics["payments"] }) {
  const items: [string, number][] = [["Gross", data.gross_cents], ["Deductions", data.deductions_cents], ["Net payable", data.net_payable_cents], ["Recorded", data.recorded_cents]]
  if (data.outstanding_cents != null) items.push(["Outstanding", data.outstanding_cents])
  return <section className="od-card od-strip" aria-labelledby="od-pay-title">
    <span className="od-icon is-pay" aria-hidden="true"><Wallet size={18} /></span>
    <div className="od-strip-title"><h2 id="od-pay-title">Payments</h2><p>Week {rangeLabel(data.week_start, data.week_end)}</p>
      <Link className="od-link" to="/payments">View breakdown<ArrowRight size={13} aria-hidden="true" /></Link></div>
    <dl>{items.map(([label, cents]) => <div key={label} className={label === "Net payable" ? "is-lead" : undefined}><dt>{label}</dt><dd>{money(cents, data.currency)}</dd></div>)}</dl>
    {data.missing_rates.length > 0 && <p className="od-strip-note">Missing pay rate: {data.missing_rates.join(", ")}</p>}
  </section>
}

function Attention({ items }: { items: DashboardMetrics["attention"] }) {
  return <section className="od-card od-strip" aria-labelledby="od-attention-title">
    <span className={`od-icon ${items.length ? "is-warn" : "is-clear"}`} aria-hidden="true">{items.length ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}</span>
    <div className="od-strip-title"><h2 id="od-attention-title">Needs attention</h2>{!items.length && <p role="status">Nothing needs attention.</p>}</div>
    {items.length > 0 && <ul>{items.map(item => <li key={item.id}><Link to={item.href} title={item.detail} className={`is-${item.severity}`}><strong>{item.count.toLocaleString()}</strong><span>{item.label}</span></Link></li>)}</ul>}
  </section>
}

export default function DashboardPage({ readOnly = false }: { bootstrap?: Bootstrap; readOnly?: boolean }) {
  const [search, setSearch] = useSearchParams()
  const toast = useToast()
  const custom = search.has("start") || search.has("end")
  const weeks = RANGES.includes(Number(search.get("weeks"))) ? Number(search.get("weeks")) : DEFAULT_WEEKS
  const params = useMemo(() => {
    const value = new URLSearchParams()
    if (custom) { for (const key of ["start", "end"]) if (search.get(key)) value.set(key, search.get(key)!) }
    else value.set("weeks", String(weeks))
    for (const key of ["account", "bidder"]) if (search.get(key) && !(key === "bidder" && readOnly)) value.set(key, search.get(key)!)
    return value
  }, [search, custom, weeks, readOnly])
  const incomplete = custom && (!search.get("start") || !search.get("end"))
  const query = useQuery({ queryKey: ["dashboard-metrics", params.toString()], queryFn: ({ signal }) => api.dashboardMetrics(params, signal), enabled: !incomplete, placeholderData: previous => previous })
  const { data: scope } = useQuery({ queryKey: ["dashboard-accounts"], queryFn: ({ signal }) => api.dashboardAccounts(signal) })
  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(search)
    for (const [key, value] of Object.entries(changes)) { if (value !== null) next.set(key, value); else next.delete(key) }
    setSearch(next)
  }
  const chooseRange = (value: string) => value === "custom"
    ? update({ weeks: null, start: query.data?.range.start || "", end: query.data?.today || "" })
    : update({ weeks: Number(value) === DEFAULT_WEEKS ? null : value, start: null, end: null })
  const filtered = custom || search.has("weeks") || !!search.get("account") || (!readOnly && !!search.get("bidder"))
  const refresh = async () => {
    const result = await query.refetch()
    if (result.error) toast(result.error.message || "Could not refresh the dashboard.", "error")
  }
  const data = query.data
  if (query.error && !data) return <div className="page-wrap"><EmptyState title="Dashboard is unavailable" description={query.error instanceof Error ? query.error.message : "Try loading the dashboard again."} action={<div className="flex flex-wrap justify-center gap-2"><Button onClick={() => void query.refetch()}>Try again</Button>{filtered && <Button variant="outline" onClick={() => setSearch(new URLSearchParams())}>Reset filters</Button>}</div>} /></div>
  const updated = data ? new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", timeZone: data.timezone }).format(new Date(data.as_of)) : ""
  return <div className="page-wrap od-page">
    <header className="od-head">
      <div className="od-title"><h1>Dashboard</h1>{data && <p>Chicago time · updated {updated}</p>}</div>
      <div className="od-filters" role="group" aria-label="Dashboard filters">
        <span className="od-select"><select aria-label="Account" value={search.get("account") || ""} onChange={e => update({ account: e.target.value || null })}><option value="">All accounts</option>{scope?.accounts.map(a => <option key={a.label} value={a.label}>{a.label}</option>)}</select></span>
        {!readOnly && <span className="od-select"><select aria-label="Bidder" value={search.get("bidder") || ""} onChange={e => update({ bidder: e.target.value || null })}><option value="">All bidders</option>{scope?.bidders?.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></span>}
        <span className="od-select"><select aria-label="Graph range" title="Range shown in the analytics graph" value={custom ? "custom" : String(weeks)} onChange={e => chooseRange(e.target.value)}>{RANGES.map(n => <option key={n} value={n}>Last {n} weeks</option>)}<option value="custom">Custom range</option></select></span>
        {custom && <>
          <input className="od-date" type="date" aria-label="From" value={search.get("start") || ""} max={search.get("end") || undefined} onChange={e => update({ start: e.target.value })} />
          <input className="od-date" type="date" aria-label="Through" value={search.get("end") || ""} min={search.get("start") || undefined} onChange={e => update({ end: e.target.value })} />
        </>}
        <Button variant="ghost" size="icon" aria-label="Refresh dashboard" title="Refresh" disabled={query.isFetching} onClick={() => void refresh()}>{query.isFetching ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />}</Button>
        {filtered && <Button variant="ghost" size="sm" onClick={() => setSearch(new URLSearchParams())}><RotateCcw size={14} />Reset</Button>}
      </div>
    </header>
    {query.error && data && <p role="alert" className="inline-error">Could not update this view: {query.error.message}. Showing the last loaded results.</p>}
    {incomplete ? <p className="od-empty">Choose a start and end date.</p> : !data ? <Loading label="Calculating dashboard metrics…" /> : <>
      <WeeklySummary data={data} />
      <Workspace data={data} />
      <div className="od-footer-row"><Payments data={data.payments} /><Attention items={data.attention} /></div>
    </>}
  </div>
}
