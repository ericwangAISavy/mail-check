import { useEffect, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Activity, ChevronLeft, ChevronRight } from "lucide-react"
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { cumulativeActivity } from "@/lib/cumulative-activity"
import { request } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"

type Check = { at: string; new_checks: number; checked_total: number | null }
type Bidder = { id: number; name: string; hourly: number[]; daily: number[]; heatmap: number[][]; new_checks: number; active_half_hours: number; last_detected: string | null; latest_check: Check | null; previous_check: Check | null }
type TimelinePoint = { at: string; source: string; counts: Record<string, number> }
type Workday = {date: string; start: string; end: string; confirmations: TimelinePoint[]; account_confirmations: TimelinePoint[]; runs: TimelinePoint[]; account_runs: TimelinePoint[]}
type ActivityData = { workday?: Workday; dates: string[]; tracking_since: string | null; timezone: string; check_count?: number; bidders: Bidder[]; accounts?: Bidder[]; account_timeline?: TimelinePoint[]; confirmation_timeline?: TimelinePoint[]; account_confirmation_timeline?: TimelinePoint[]; timeline: TimelinePoint[] }
const colors = Array.from({length:7},(_,index)=>`var(--activity-color-${index})`)
function chartDate(value: unknown): Date | null {
  if (value === null || value === undefined || value === "" || (typeof value !== "string" && typeof value !== "number")) return null
  const stamp = typeof value === "number" ? value : /^\d{11,}$/.test(value) ? Number(value) : Date.parse(value)
  return Number.isFinite(stamp) && Number.isFinite(new Date(stamp).getTime()) ? new Date(stamp) : null
}
const exactTime = (value: unknown) => {const date = chartDate(value); return date ? new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit", timeZoneName: "short" }).format(date) : ""}
const time = (value: unknown) => {const date = chartDate(value); return date ? new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date) : ""}
const dayLabel = (value: unknown) => {if (value === "start") return "Start"; const date = chartDate(value); return date ? new Intl.DateTimeFormat("en-US", {month:"short",day:"numeric",timeZone:"UTC"}).format(date) : ""}
const axisHour = (value: unknown) => {const date = chartDate(value); return date ? new Intl.DateTimeFormat("en-US",{timeZone:"America/Chicago",hour:"numeric"}).format(date) : ""}
const hourLabel = (hour: number) => `${hour % 12 || 12}${hour < 12 ? "am" : "pm"}`
export default function BidderActivity({ week, selected, onSelect }: { week: string; selected: string; onSelect: (id: string) => void }) {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    const timer = globalThis.setInterval(() => setNow(Date.now()), 1000)
    return () => globalThis.clearInterval(timer)
  }, [])
  const [mode, setMode] = useState<"checks" | "days" | "confirmed">("confirmed")
  const [display, setDisplay] = useState<"cumulative" | "interval">("cumulative")
  const cumulative = display === "cumulative"
  const [day, setDay] = useState("")
  const [group, setGroup] = useState<"bidders" | "accounts">("bidders")
  const [account, setAccount] = useState("")
  useEffect(() => { setAccount(""); }, [week, selected])
  const scope = group === "accounts" ? selected : ""
  const query = useQuery({ queryKey: ["payments", "activity", week, scope, day], queryFn: () => request<ActivityData>(`/api/payments/activity?week=${week}${day ? `&day=${day}` : ""}${scope ? `&bidder=${scope}` : ""}`), refetchInterval: 30_000 })
  const data = query.data
  const valid = data && Array.isArray(data.timeline)
  const entities = valid ? group === "accounts" ? data.accounts || [] : data.bidders : []
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
  const total = bidders.reduce((sum, b) => sum + b.new_checks, 0)
  const hourly = Array.from({ length: 24 }, (_, hour) => bidders.reduce((sum, b) => sum + b.hourly[hour], 0))
  const ids = bidders.map(b=>String(b.id))
  const zero = Object.fromEntries(ids.map(id => [id, 0]))
  const rawTimeline = valid ? points.filter(point => chartDate(point.at)).slice().sort((a,b) => Date.parse(a.at)-Date.parse(b.at)) : []
  const plottedTimeline = (cumulative ? cumulativeActivity(rawTimeline, ids) : rawTimeline).map(point => ({at:point.at, stamp:Date.parse(point.at), source:point.source, ...point.counts}))
  const timeline = cumulative && window ? [{at:window.start, stamp:Date.parse(window.start), source:"Period start", ...zero}, ...plottedTimeline] : plottedTimeline
  const rawDaily = valid ? data.dates.map((day,i)=>({at:day,counts:Object.fromEntries(bidders.map(b=>[String(b.id),b.daily[i]]))})) : []
  const plottedDaily = (cumulative ? cumulativeActivity(rawDaily, ids) : rawDaily).map(point=>({at:point.at,...point.counts}))
  const daily = cumulative && plottedDaily.length ? [{at:"start", ...zero}, ...plottedDaily] : plottedDaily
  const chartData = mode === "days" ? daily : timeline
  const changeDot = (id: string, props: {cx?: number; cy?: number; index?: number; stroke?: string}) => {
    const {cx, cy, index, stroke} = props
    if (index === undefined || cx === undefined || cy === undefined) return <g />
    const values = chartData as Record<string, unknown>[]
    if (Number(values[index]?.[id] || 0) === Number(values[index - 1]?.[id] || 0)) return <g />
    return <circle cx={cx} cy={cy} r={mode === "checks" ? 3 : 2} stroke={stroke} fill="var(--card)" strokeWidth={2} />
  }
  const heatmap = valid ? data.dates.map((_, day) => Array.from({ length: 24 }, (_, hour) => bidders.reduce((sum, b) => sum + (b.heatmap[day]?.[hour] || 0), 0))) : []
  const maxHeat = Math.max(1, ...heatmap.flat())
  const tooltipLabel = (value: unknown, items: readonly {payload?: {at?: string; source?: string}}[]) => {
    const point = items?.[0]?.payload
    const stamp = point?.at ?? value
    const formatted = mode === "days" ? dayLabel(stamp) : exactTime(stamp)
    if (!formatted || mode === "days") return formatted
    return `${formatted} · ${mode === "checks" ? point?.source || "check" : "15-minute interval"}`
  }
  return <Card className="bidder-activity" aria-label="Bidder activity monitor">
    <div className="activity-heading"><div><p className="eyebrow"><Activity size={14} /> ACTIVITY MONITOR</p><h2>When confirmations arrive</h2><p>Matched confirmation receipt times in America/Chicago, not check-button times. Email arrival is a signal, not exact working hours.</p></div><span className="activity-live"><i />Updates after each check</span></div>
    {query.isPending ? <p role="status">Loading bidder activity…</p> : query.error ? <div role="alert">Could not load activity. <Button variant="outline" size="sm" onClick={() => void query.refetch()}>Retry activity</Button></div> : <>
      <div className="activity-group-controls" role="group" aria-label="Activity grouping"><Button size="sm" variant={group === "bidders" ? "secondary" : "outline"} aria-pressed={group === "bidders"} onClick={() => setGroup("bidders")}>By bidder</Button><Button size="sm" variant={group === "accounts" ? "secondary" : "outline"} aria-pressed={group === "accounts"} onClick={() => setGroup("accounts")}>By account</Button>{group === "accounts" && <span>Checked links across {selected ? "the selected bidder’s account tabs" : "all assigned bidders’ account tabs"}; shared-account counts may overlap.</span>}</div>
      <div className="activity-legend"><Button size="sm" variant={!selection ? "secondary" : "ghost"} onClick={() => choose("")}>All {group}</Button>{entities.map((b, i) => <button key={b.id} aria-pressed={selection === String(b.id)} onClick={() => choose(selection === String(b.id) ? "" : String(b.id))}><i style={{ background: colors[i % colors.length] }} />{b.name}</button>)}</div>
      <div className="activity-chart-heading"><h3>{cumulative ? mode === "days" ? "Cumulative weekly confirmations" : mode === "checks" ? "Cumulative links by check run" : "Cumulative confirmations in this workday" : mode === "days" ? "Daily confirmation totals" : mode === "checks" ? "New links by check run" : "Confirmations per interval"}</h3><div role="group" aria-label="Activity graph period"><Button size="sm" variant={mode === "confirmed" ? "secondary" : "ghost"} aria-pressed={mode === "confirmed"} onClick={() => setMode("confirmed")}>Confirmation time</Button><Button size="sm" variant={mode === "checks" ? "secondary" : "ghost"} aria-pressed={mode === "checks"} onClick={() => setMode("checks")}>Check runs</Button><Button size="sm" variant={mode === "days" ? "secondary" : "ghost"} aria-pressed={mode === "days"} onClick={() => setMode("days")}>By day</Button></div></div>
      <div className="activity-group-controls" role="group" aria-label="Graph display"><Button size="sm" variant={!cumulative ? "secondary" : "outline"} aria-pressed={!cumulative} onClick={()=>setDisplay("interval")}>Per interval</Button><Button size="sm" variant={cumulative ? "secondary" : "outline"} aria-pressed={cumulative} onClick={()=>setDisplay("cumulative")}>Cumulative</Button></div>
      {mode !== "days" && <div className="activity-workday-controls">
        <Button variant="outline" size="icon" disabled={!window} aria-label="Previous activity workday" onClick={() => moveDay(-1)}><ChevronLeft size={16}/></Button>
        <label>Workday <input type="date" aria-label="Activity workday" min="1971-01-01" max="2100-12-30" value={window?.date || day} onChange={e => {if(e.target.value) setDay(e.target.value)}} /></label>
        <Button variant="outline" size="icon" disabled={!window} aria-label="Next activity workday" onClick={() => moveDay(1)}><ChevronRight size={16}/></Button>
        <Button variant="outline" size="sm" onClick={() => {setDay(""); void query.refetch()}}>Current workday</Button>
        <span>{window ? `${time(window.start)} – ${time(window.end)}` : "6:00 AM – next 6:00 AM"} · America/Chicago</span>
      </div>}
      <p className="activity-mode-description">{!cumulative ? mode === "days" ? "Daily totals · each point shows that day’s count." : mode === "checks" ? `Every recorded run · ${points.length} checkpoints. Each point shows newly checked links for that run.` : "15-minute intervals · each point shows matched links received in that interval." : mode === "days" ? "Weekly running totals · each day adds to the previous total. The heatmap also covers the selected week." : mode === "checks" ? `Every recorded run · ${points.length} checkpoints in this workday. Lines show running totals; quiet runs stay flat. Hover for the exact time and cumulative counts.` : "15-minute intervals · running totals of matched links by confirmation receipt time. Quiet intervals stay flat; the last point shows each bidder or account’s workday total. The heatmap covers the selected week."}</p>
      {showNow && <p className="activity-now"><i />Now · {exactTime(now)}</p>}
      {valid && (mode === "days" ? total > 0 : (showNow || points.length > 0 && (mode === "checks" || points.some(p => bidders.some(b => p.counts[String(b.id)] > 0))))) ? <div className="activity-chart-scroll"><div className="activity-chart" aria-label={`${cumulative ? "Cumulative" : "Per interval"} ${mode === "days" ? "daily confirmations" : mode === "checks" ? "check runs in Chicago workday" : "confirmations in 15-minute intervals"}`}><ResponsiveContainer width="100%" height={260}><LineChart key={`${mode}-${display}`} data={chartData} margin={{ top: 10, right: 24, bottom: 12, left: -15 }}><CartesianGrid stroke="var(--border)" strokeDasharray="3 3" /><XAxis dataKey={mode === "days" ? "at" : "stamp"} type={mode === "days" ? "category" : "number"} scale={mode === "days" ? "auto" : "time"} domain={mode === "days" || !window ? undefined : [Date.parse(window.start),Date.parse(window.end)]} ticks={mode === "days" || !window ? undefined : Array.from({length:Math.round((Date.parse(window.end)-Date.parse(window.start))/3600000)+1},(_,i) => Date.parse(window.start)+i*3600000)} tickFormatter={value => mode === "days" ? dayLabel(value) : axisHour(value)} minTickGap={8} tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} /><YAxis domain={[0, "auto"]} allowDecimals={false} label={{value:cumulative ? "Cumulative links" : mode === "checks" ? "New links / run" : mode === "days" ? "Links / day" : "Links / 15 min",angle:-90,position:"insideLeft",offset:16,style:{fill:"var(--muted-foreground)",fontSize:10}}} tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} /><Tooltip labelFormatter={tooltipLabel} contentStyle={{ background: "var(--background)", borderColor: "var(--border)", borderRadius: 6 }} />{showNow && <ReferenceLine x={now} stroke="var(--primary)" strokeWidth={2} strokeDasharray="5 4" ifOverflow="hidden" label={{value:"Now",position:now < (Date.parse(window!.start)+Date.parse(window!.end))/2 ? "insideTopRight" : "insideTopLeft",fill:"var(--primary)",fontSize:12,fontWeight:700}} />}{bidders.map(b => <Line key={b.id} type="linear" dataKey={String(b.id)} name={b.name} stroke={colors[Math.max(0, entities.findIndex(row => row.id === b.id)) % colors.length]} strokeWidth={2} dot={props => changeDot(String(b.id), props)} activeDot={false} isAnimationActive={false} />)}</LineChart></ResponsiveContainer></div></div> : <div className="activity-empty"><Activity size={26} /><strong>{mode === "checks" ? "No check runs in this workday" : mode === "days" ? "No confirmation activity for this week" : "No confirmations in this workday"}</strong><span>{mode === "checks" ? "Auto-check or Check now will record a checkpoint here, including quiet runs." : "Use Refresh to match recent stored confirmations, or choose another workday. Checked rows without a matching message keep their status but have no inferred receipt time."}</span></div>}
      {mode === "checks" && points.length > 0 && <details className="activity-run-details"><summary>View all {points.length} check-run checkpoints</summary><div className="payment-table-scroll"><table className="activity-table"><thead><tr><th>Chicago time</th><th>Check source</th>{bidders.map(b => <th key={b.id}>{b.name}</th>)}</tr></thead><tbody>{points.map((point,i) => <tr key={i}><th>{exactTime(point.at)}</th><td>{point.source}</td>{bidders.map(b => <td key={b.id}>{point.counts[String(b.id)] || 0}</td>)}</tr>)}</tbody></table></div></details>}
      <div className="activity-chart-heading"><h3>Weekly confirmations by hour</h3><span>Low <i className="heat-key" /> High · Chicago time</span></div>
      <div className="activity-heatmap-scroll"><div className="activity-heatmap" role="img" aria-label="Hourly heatmap of newly detected checks"><span />{hourly.map((_, h) => <small key={h}>{h % 3 === 0 ? hourLabel(h) : ""}</small>)}{valid && data.dates.map((day, d) => <div className="heatmap-row" key={day}><span>{new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" })}</span>{heatmap[d].map((count, h) => <span className="heat-cell" key={h} tabIndex={count ? 0 : undefined} title={`${day}, ${hourLabel(h)}: ${count} matched checked links`} aria-label={`${day}, ${hourLabel(h)}: ${count} matched checked links`} style={{ background: count ? `color-mix(in srgb, var(--primary) ${20 + count / maxHeat * 70}%, var(--background))` : "var(--surface)" }} />)}</div>)}</div></div>
    </>}
  </Card>
}
