import { isPageDate, usePageState } from "@/lib/page-state"
import { useEffect, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Activity, CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Clock3, Globe } from "lucide-react"
import { Area, CartesianGrid, ComposedChart, Customized, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { maskAccountLabel } from "@/lib/account-label"
import { cumulativeActivity } from "@/lib/cumulative-activity"
import { request } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { BidderChartTooltip } from "./bidder-chart-tooltip"

type Check = { at: string; new_checks: number; checked_total: number | null }
type Bidder = { id: number; name: string; hourly: number[]; daily: number[]; checked_daily?:number[]; without_time_daily?:number[]; heatmap: number[][]; new_checks: number; active_half_hours: number; last_detected: string | null; latest_check: Check | null; previous_check: Check | null }
type TimelinePoint = { at: string; source: string; counts: Record<string, number> }
type DayTotal = {checked:number;timed:number;without_time:number}
type Workday = {totals?:Record<string,DayTotal>;account_totals?:Record<string,DayTotal>;date: string; start: string; end: string; confirmations: TimelinePoint[]; account_confirmations: TimelinePoint[]; runs: TimelinePoint[]; account_runs: TimelinePoint[]}
type ActivityData = { workday?: Workday; dates: string[]; tracking_since: string | null; timezone: string; check_count?: number; bidders: Bidder[]; accounts?: Bidder[]; account_timeline?: TimelinePoint[]; confirmation_timeline?: TimelinePoint[]; account_confirmation_timeline?: TimelinePoint[]; timeline: TimelinePoint[] }
const colors = Array.from({length:7},(_,index)=>`var(--activity-color-${index})`)
function chartDate(value: unknown): Date | null {
  if (value === null || value === undefined || value === "" || (typeof value !== "string" && typeof value !== "number")) return null
  const stamp = typeof value === "number" ? value : /^\d{11,}$/.test(value) ? Number(value) : Date.parse(value)
  return Number.isFinite(stamp) && Number.isFinite(new Date(stamp).getTime()) ? new Date(stamp) : null
}
const exactTime = (value: unknown) => {const date = chartDate(value); return date ? new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit", timeZoneName: "short" }).format(date) : ""}
const dayLabel = (value: unknown) => {if (value === "start") return "Start"; const date = chartDate(value); return date ? new Intl.DateTimeFormat("en-US", {month:"short",day:"numeric",timeZone:"UTC"}).format(date) : ""}
const axisHour = (value: unknown) => {const date = chartDate(value); return date ? new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",hour:"numeric"}).format(date) : ""}
const hourLabel = (hour: number) => `${hour % 12 || 12}${hour < 12 ? "am" : "pm"}`
export default function BidderActivity({ week, selected, onSelect,readOnly=false,allowAccounts=true,visibilityKey="default" }: { visibilityKey?:string;allowAccounts?:boolean;readOnly?:boolean;week: string; selected: string; onSelect: (id: string) => void }) {
  const chart = useRef<HTMLDivElement>(null)
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    const timer = globalThis.setInterval(() => setNow(Date.now()), 1000)
    return () => globalThis.clearInterval(timer)
  }, [])
  const [mode, setMode] = usePageState<"checks" | "days" | "confirmed">("/payments", "activity-mode", "confirmed", value => ["checks", "days", "confirmed"].includes(value))
  const [display, setDisplay] = usePageState<"cumulative" | "interval">("/payments", "activity-display", "cumulative", value => ["cumulative", "interval"].includes(value))
  const cumulative = display === "cumulative"
  const [day, setDay] = usePageState("/payments", "activity-day", "", value => isPageDate(value, true))
  const previousWeek = useRef(week)
  useEffect(() => {
    if (previousWeek.current !== week || day && (day < week || day > new Date(new Date(week + "T12:00:00Z").getTime() + 6 * 86400000).toISOString().slice(0, 10))) setDay("")
    previousWeek.current = week
  }, [week])
  const [selectedGroup, setGroup] = usePageState<"bidders" | "accounts">("/payments", "activity-group", "bidders", value => ["bidders", "accounts"].includes(value))
  const group = allowAccounts ? selectedGroup : "bidders"
  const [account, setAccount] = usePageState("/payments", "activity-account", "", value => value === "" || /^[1-9]\d*$/.test(value))
  const previousAccountContext = useRef(`${week}:${selected}`)
  useEffect(() => {
    const context = `${week}:${selected}`
    if (previousAccountContext.current !== context) setAccount("")
    previousAccountContext.current = context
  }, [week, selected])
  const scope = group === "accounts" ? selected : ""
  const query = useQuery({ queryKey: ["payments", "activity", week, scope, day, visibilityKey], queryFn: ({ signal }) => request<ActivityData>(`/api/payments/activity?week=${week}${day ? `&day=${day}` : ""}${scope ? `&bidder=${scope}` : ""}`, { signal }), refetchInterval: 30_000 })
  const data = query.data
  const valid = data && Array.isArray(data.timeline)
  const entities = valid ? group === "accounts" ? (data.accounts || []).map(account => ({ ...account, name: maskAccountLabel(account.name) })) : data.bidders : []
  const selection = group === "accounts" ? account : selected
  const choose = (id: string) => group === "accounts" ? setAccount(id) : onSelect(id)
  const bidders = entities.filter(b => !selection || b.id === Number(selection))
  const window = valid ? data.workday : undefined
  const showNow = mode !== "days" && !!window && now >= Date.parse(window.start) && now < Date.parse(window.end)
  const points = window ? mode === "checks"
    ? group === "accounts" ? window.account_runs : window.runs
    : group === "accounts" ? window.account_confirmations : window.confirmations : []
  const moveDay = (offset: number) => {
    const value = new Date(`${window?.date || day}T12:00:00Z`)
    value.setUTCDate(value.getUTCDate() + offset)
    setDay(value.toISOString().slice(0,10))
  }
  const total = bidders.reduce((sum, b) => sum + (mode==="days"?(b.checked_daily || b.daily).reduce((a,n)=>a+n,0):b.new_checks), 0)
  const summaries = group==="accounts"?window?.account_totals:window?.totals
  const selectedTotal = bidders.reduce((sum,b)=>{const item=summaries?.[String(b.id)];return {checked:sum.checked+(item?.checked || 0),timed:sum.timed+(item?.timed || 0),without_time:sum.without_time+(item?.without_time || 0)}},{checked:0,timed:0,without_time:0})
  const ids = bidders.map(b=>String(b.id))
  const zero = Object.fromEntries(ids.map(id => [id, 0]))
  const rawTimeline = valid ? points.filter(point => chartDate(point.at)).slice().sort((a,b) => Date.parse(a.at)-Date.parse(b.at)) : []
  const plottedTimeline = (cumulative ? cumulativeActivity(rawTimeline, ids) : rawTimeline).map(point => ({at:point.at, stamp:Date.parse(point.at), source:point.source, ...point.counts}))
  const timeline = cumulative && window ? [{at:window.start, stamp:Date.parse(window.start), source:"Period start", ...zero}, ...plottedTimeline] : plottedTimeline
  const rawDaily = valid ? data.dates.map((day,i)=>({at:day,counts:Object.fromEntries(bidders.map(b=>[String(b.id),(b.checked_daily || b.daily)[i] || 0]))})) : []
  const plottedDaily = (cumulative ? cumulativeActivity(rawDaily, ids) : rawDaily).map(point=>({at:point.at,...point.counts}))
  // Upcoming days have not happened: their values are left empty so lines end at today.
  const chicagoToday = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Chicago", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(now))
  const pastDaily = plottedDaily.map(point => point.at > chicagoToday ? { at: point.at, ...Object.fromEntries(ids.map(id => [id, null])) } : point)
  const daily = cumulative && pastDaily.length ? [{at:"start", ...zero}, ...pastDaily] : pastDaily
  const chartData = mode === "days" ? daily : timeline
  const heatmap = valid ? data.dates.map((_, day) => Array.from({ length: 24 }, (_, hour) => bidders.reduce((sum, b) => sum + (b.heatmap[day]?.[hour] || 0), 0))) : []
  const maxHeat = Math.max(1, ...heatmap.flat())
  const tooltipLabel = (value: unknown, items: readonly {payload?: {at?: string; source?: string}}[]) => {
    const point = items?.[0]?.payload
    const stamp = point?.at ?? value
    const formatted = mode === "days" ? dayLabel(stamp) : exactTime(stamp)
    if (!formatted || mode === "days") return formatted
    return `${formatted} · ${mode === "checks" ? point?.source || "check" : "15-minute interval"}`
  }
  const zoneName = (() => { try { return new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", timeZoneName: "short" }).formatToParts(new Date(now)).find(part => part.type === "timeZoneName")?.value || "" } catch { return "" } })()
  const kpi = mode === "confirmed" && summaries ? selectedTotal.checked : total
  const kpiLabel = mode === "days" ? "Checked applications this week" : mode === "checks" ? "Links found by check runs" : "Checked applications"
  // Cumulative lines hold their value until now, so the live edge reads as "so far today".
  // Nothing is drawn past the present: lines stop at "now" (holding their value up to it).
  const observed = mode !== "days" && showNow ? (chartData as Record<string, unknown>[]).filter(point => !(Number(point.stamp) > now)) : chartData as Record<string, unknown>[]
  const lastPoint = observed[observed.length - 1]
  const series = mode !== "days" && cumulative && showNow && lastPoint && Number(lastPoint.stamp) < now
    ? [...observed, { ...lastPoint, at: new Date(now).toISOString(), stamp: now, source: "Now" }]
    : observed
  const colorOf = (id: number) => colors[Math.max(0, entities.findIndex(row => row.id === id)) % colors.length]
  // Each line's latest point gets a small marker and its name + value beside it ("Nifemi 38").
  // Markers register here while the chart draws; EndLabels then lays the names out together.
  const ends: Record<string, EndPoint> = {}
  const endpoint = (id: string, color: string, name: string) => (props: { cx?: number; cy?: number; index?: number }) => {
    const { cx, cy, index } = props
    const rows = series as Record<string, unknown>[]
    let last = rows.length - 1
    while (last > 0 && rows[last]?.[id] == null) last--
    if (index !== last || cx === undefined || cy === undefined) return <g key={`${id}-${index}`} />
    ends[id] = { cx, cy, value: Number(rows[index]?.[id] || 0), color, name }
    return <circle key={`${id}-end`} className="bm-endpoint" cx={cx} cy={cy} r={3} fill={color} stroke="var(--card)" strokeWidth={1.5} />
  }
  const nowLabel = (props: { viewBox?: { x?: number } }) => <text className="bm-now-label" x={props.viewBox?.x ?? 0} y={12} textAnchor="middle" fontSize={11} fontWeight={600} fill="var(--primary)">{`Now · ${new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", hour: "numeric", minute: "2-digit" }).format(new Date(now))}`}</text>
  const hasChart = valid && (mode === "days" ? total > 0 : (showNow || points.length > 0 && (mode === "checks" || points.some(p => bidders.some(b => p.counts[String(b.id)] > 0)))))
  return <section className="bidder-activity bm-analytics" aria-label="Bidder activity monitor">
    <header className="bm-analytics-head">
      <div className="bm-analytics-title"><h2>Confirmation analytics</h2><p>Track application confirmations throughout the day</p></div>
      <div className="bm-analytics-filters">
        {allowAccounts && <span className="bm-select"><select aria-label="Activity grouping" value={group} onChange={e => setGroup(e.target.value as "bidders" | "accounts")}><option value="bidders">By bidder</option><option value="accounts">By account</option></select></span>}
        <span className="bm-select"><select aria-label={group === "accounts" ? "Activity account" : "Activity bidder"} value={selection} onChange={e => choose(e.target.value)}><option value="">All {group}</option>{entities.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></span>
      </div>
    </header>
    {query.isPending ? <p role="status" className="inline-loading">Loading bidder activity…</p> : query.error ? <div role="alert">Could not load activity. <Button variant="outline" size="sm" onClick={() => void query.refetch()}>Retry activity</Button></div> : <>
      {group === "accounts" && <p className="bm-note">Checked links across {selected ? "the selected bidder’s account tabs" : "all assigned bidders’ account tabs"}; shared-account counts may overlap.</p>}
      <div className="bm-analytics-top">
        <div className="bm-analytics-summary">
          <div className="bm-segment" role="group" aria-label="Activity graph period">
            <button type="button" aria-pressed={mode === "confirmed"} onClick={() => setMode("confirmed")}>Confirmation time</button>
            <button type="button" aria-pressed={mode === "checks"} onClick={() => setMode("checks")}>Check runs</button>
            <button type="button" aria-pressed={mode === "days"} onClick={() => setMode("days")}>By day</button>
          </div>
          <div className="bm-kpi-row">
            <div className="bm-kpi">
              <strong>{kpi.toLocaleString()}</strong>
              <div><span>{kpiLabel}</span>{mode === "confirmed" && summaries && <small role="status" aria-label="Receipt time reconciliation">{selectedTotal.timed.toLocaleString()} with receipt time · {selectedTotal.without_time.toLocaleString()} without{selectedTotal.without_time > 0 ? " (shown in By day; times are never guessed)" : ""}</small>}</div>
            </div>
            <div className="bm-analytics-nav">
              {mode !== "days" && <>
                <Button variant="ghost" size="icon" disabled={!window} aria-label="Previous activity day" onClick={() => moveDay(-1)}><ChevronLeft size={16} /></Button>
                <DayPicker value={window?.date || day} onChange={setDay} />
                <Button variant="ghost" size="icon" disabled={!window} aria-label="Next activity day" onClick={() => moveDay(1)}><ChevronRight size={16} /></Button>
                <Button variant="ghost" size="sm" onClick={() => { setDay(""); if (!readOnly) void query.refetch() }}>Today</Button>
              </>}
              <span className="bm-select"><select aria-label="Graph display" value={display} onChange={e => setDisplay(e.target.value as "cumulative" | "interval")}><option value="cumulative">Cumulative</option><option value="interval">Per interval</option></select></span>
            </div>
          </div>
          <div className="activity-legend" role="group" aria-label={`Show one of the ${group}`}>{entities.map((b, i) => <button key={b.id} type="button" aria-pressed={selection === String(b.id)} onClick={() => choose(selection === String(b.id) ? "" : String(b.id))}><i style={{ background: colors[i % colors.length] }} />{b.name}</button>)}</div>
        </div>
        <WeeklyHeatmap dates={valid ? data.dates : []} heatmap={heatmap} max={maxHeat} now={now} />
      </div>
      {showNow && <span className="sr-only">Now · {exactTime(now)}</span>}
      {hasChart ? <div className="activity-chart-scroll"><div ref={chart} className="activity-chart" role="group" aria-label={`${cumulative ? "Cumulative" : "Per interval"} ${mode === "days" ? "daily checked applications" : mode === "checks" ? "check runs in Chicago calendar day" : "confirmations in 15-minute intervals"}`}><ResponsiveContainer width="100%" height={280}><ComposedChart key={`${mode}-${display}`} data={series} margin={{ top: 22, right: 120, bottom: 0, left: 0 }}>
        <defs>
          {bidders.map(b => <linearGradient key={b.id} id={`bm-fill-${b.id}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={colorOf(b.id)} stopOpacity={0.12} /><stop offset="100%" stopColor={colorOf(b.id)} stopOpacity={0} /></linearGradient>)}
        </defs>
        <CartesianGrid vertical={false} stroke="var(--border)" strokeOpacity={0.55} />
        <XAxis dataKey={mode === "days" ? "at" : "stamp"} type={mode === "days" ? "category" : "number"} scale={mode === "days" ? "auto" : "time"} domain={mode === "days" || !window ? undefined : [Date.parse(window.start), Date.parse(window.end)]} ticks={mode === "days" || !window ? undefined : Array.from({ length: Math.round((Date.parse(window.end) - Date.parse(window.start)) / 10800000) + 1 }, (_, i) => Date.parse(window.start) + i * 10800000)} tickFormatter={value => mode === "days" ? dayLabel(value) : axisHour(value)} minTickGap={12} axisLine={false} tickLine={false} tickMargin={10} tick={{ fill: "var(--muted-foreground)", fontSize: 11.5 }} />
        <YAxis domain={[0, "auto"]} allowDecimals={false} width={48} axisLine={false} tickLine={false} tickMargin={6} label={{ value: mode === "days" ? cumulative ? "Cumulative applications" : "Applications per day" : mode === "checks" ? cumulative ? "Cumulative links" : "New links per run" : cumulative ? "Cumulative confirmations" : "Confirmations per 15 min", angle: -90, position: "insideLeft", offset: 12, style: { fill: "var(--muted-foreground)", fontSize: 11, textAnchor: "middle" } }} tick={{ fill: "var(--muted-foreground)", fontSize: 11.5 }} />
        <Tooltip<number, string> labelFormatter={tooltipLabel} cursor={{ stroke: "var(--border)", strokeWidth: 1 }} content={props => <BidderChartTooltip {...props} chart={chart} title={tooltipLabel(props.label, props.payload ?? [])} />} />
        {showNow && <ReferenceLine x={now} stroke="color-mix(in srgb, var(--primary) 70%, transparent)" strokeWidth={1} strokeDasharray="3 4" ifOverflow="hidden" label={nowLabel} />}
        {bidders.map(b => <Area key={b.id} type="monotone" dataKey={String(b.id)} name={b.name} stroke={colorOf(b.id)} strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" fill={cumulative ? `url(#bm-fill-${b.id})` : "transparent"} dot={endpoint(String(b.id), colorOf(b.id), b.name)} activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }} isAnimationActive={false} connectNulls={false} />)}
        <Customized component={(props: { width?: number; offset?: { top?: number; height?: number } }) => <EndLabels ends={ends} width={props.width ?? 0} top={props.offset?.top ?? 0} bottom={(props.offset?.top ?? 0) + (props.offset?.height ?? 0)} />} />
      </ComposedChart></ResponsiveContainer></div></div> : <div className="activity-empty"><Activity size={26} /><strong>{mode === "checks" ? "No check runs in this day" : mode === "days" ? "No checked applications for this week" : "No confirmations in this day"}</strong><span>{mode === "checks" ? "No check runs yet." : "No matched confirmations for this day."}</span></div>}
      {mode === "checks" && points.length > 0 && <details className="activity-run-details"><summary>View all {points.length} check-run checkpoints</summary><div className="payment-table-scroll"><table className="activity-table"><thead><tr><th>Chicago time</th><th>Check source</th>{bidders.map(b => <th key={b.id}>{b.name}</th>)}</tr></thead><tbody>{points.map((point, i) => <tr key={i}><th>{exactTime(point.at)}</th><td>{point.source}</td>{bidders.map(b => <td key={b.id}>{point.counts[String(b.id)] || 0}</td>)}</tr>)}</tbody></table></div></details>}
      <footer className="bm-analytics-foot"><span><Clock3 size={14} aria-hidden="true" />{mode === "days" ? "Checked applications per day" : mode === "checks" ? "Check run time" : "Confirmation receipt time"}</span><span><Globe size={14} aria-hidden="true" />America/Chicago{zoneName ? ` (${zoneName})` : ""}</span></footer>
    </>}
  </section>
}

/** The activity day as a readable date; the native date input opens on click. */
function DayPicker({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const label = value ? new Date(value + "T12:00:00Z").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" }) : "Today"
  return <span className="bm-week">
    <button type="button" className="bm-week-button" onClick={() => { const el = input.current; if (!el) return; try { el.showPicker() } catch { el.focus() } }}><CalendarDays size={15} aria-hidden="true" /><span>{label}</span><ChevronDown size={14} aria-hidden="true" /></button>
    <input ref={input} className="bm-week-input" type="date" aria-label="Activity day" min="1971-01-01" max="2100-12-30" value={value} onChange={e => { if (e.target.value) onChange(e.target.value) }} />
  </span>
}

/** Weekly activity: a compact 7 × 24 map of confirmation receipt hours (Chicago time).
 * Zero, upcoming hours and data are drawn differently; every cell keeps its exact count. */
function WeeklyHeatmap({ dates, heatmap, max, now }: { dates: string[]; heatmap: number[][]; max: number; now: number }) {
  const [wide, setWide] = useState(() => typeof globalThis.matchMedia !== "function" || globalThis.matchMedia("(min-width: 1100px)").matches)
  useEffect(() => {
    if (typeof globalThis.matchMedia !== "function") return
    const query = globalThis.matchMedia("(min-width: 1100px)"), update = () => setWide(query.matches)
    query.addEventListener?.("change", update); return () => query.removeEventListener?.("change", update)
  }, [])
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "America/Chicago", year: "numeric", month: "2-digit", day: "2-digit", hour: "numeric", hourCycle: "h23" }).formatToParts(new Date(now))
  const get = (type: string) => parts.find(part => part.type === type)?.value || ""
  const today = `${get("year")}-${get("month")}-${get("day")}`, hourNow = Number(get("hour"))
  const range = dates.length ? new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" }).formatRange(new Date(dates[0] + "T12:00:00Z"), new Date(dates[dates.length - 1] + "T12:00:00Z")) : ""
  return <details className="bm-heatmap" open={wide || undefined}>
    <summary><strong>Weekly activity</strong><span>{range}</span><span className="bm-heat-key" aria-hidden="true">Low<i /><i /><i /><i />High</span></summary>
    <div className="bm-heat-grid" role="group" aria-label="Hourly heatmap of confirmation receipt times">
      <span />{Array.from({ length: 24 }, (_, h) => <small key={h}>{h % 3 === 0 ? hourLabel(h) : ""}</small>)}
      {dates.map((day, d) => <div className="heatmap-row" key={day} style={{ display: "contents" }}>
        <span>{new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" })}</span>
        {(heatmap[d] || []).map((count, h) => {
          const upcoming = day > today || day === today && h > hourNow
          const level = count ? Math.min(4, Math.ceil(count / max * 4)) : 0
          return <span className={`heat-cell level-${level}${upcoming ? " is-upcoming" : ""}`} role="img" key={h} tabIndex={count ? 0 : undefined} title={`${day}, ${hourLabel(h)}: ${count} matched checked links${upcoming ? " (upcoming)" : ""}`} aria-label={`${day}, ${hourLabel(h)}: ${count} matched checked links`} />
        })}
      </div>)}
    </div>
  </details>
}

type EndPoint = { cx: number; cy: number; value: number; color: string; name: string }
/** Names beside each line's latest point ("Nifemi 38"). Labels are placed together: sorted by
 * height, nudged apart to a 16px minimum, kept inside the plot, flipped left near the right edge,
 * and joined to their point by a faint connector only when moved. When several lines sit at
 * zero, their overlapping zero labels are left out (legend and tooltip still name them). */
function EndLabels({ ends, width, top, bottom }: { ends: Record<string, EndPoint>; width: number; top: number; bottom: number }) {
  let items = Object.entries(ends).map(([id, end]) => ({ id, ...end }))
  if (items.filter(item => item.value === 0).length > 1) items = items.filter(item => item.value !== 0)
  const gap = 16
  const placed = items.sort((a, b) => a.cy - b.cy).map(item => ({ ...item, y: item.cy }))
  for (let i = 1; i < placed.length; i++) placed[i].y = Math.max(placed[i].y, placed[i - 1].y + gap)
  for (let i = placed.length - 1; i >= 0; i--) placed[i].y = Math.min(placed[i].y, i === placed.length - 1 ? bottom - 4 : placed[i + 1].y - gap)
  for (const item of placed) item.y = Math.max(item.y, top + 6)
  return <g className="bm-end-labels" aria-hidden="true">{placed.map(item => {
    const value = item.value.toLocaleString(), estimate = 10 + (item.name.length + value.length + 1) * 6.8
    const flip = item.cx + 10 + estimate > width
    const x = flip ? item.cx - 10 : item.cx + 10
    const ink = `color-mix(in srgb, ${item.color} 70%, var(--foreground))`
    return <g key={item.id}>
      {Math.abs(item.y - item.cy) > 3 && <line x1={flip ? item.cx - 4 : item.cx + 4} y1={item.cy} x2={flip ? x + 3 : x - 3} y2={item.y} stroke={item.color} strokeOpacity={0.45} strokeWidth={1} />}
      <text x={x} y={item.y + 4} textAnchor={flip ? "end" : "start"} fontSize={12.5} fill={ink}><tspan fontWeight={500}>{item.name}</tspan><tspan dx={5} fontWeight={650}>{value}</tspan></text>
    </g>
  })}</g>
}
