import { useEffect, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Activity, Clock3, TrendingUp } from "lucide-react"
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { request } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"

type Check = { at: string; new_checks: number; checked_total: number | null }
type Bidder = { id: number; name: string; hourly: number[]; daily: number[]; heatmap: number[][]; new_checks: number; active_half_hours: number; last_detected: string | null; latest_check: Check | null; previous_check: Check | null }
type TimelinePoint = { at: string; source: string; counts: Record<string, number> }
type ActivityData = { dates: string[]; tracking_since: string | null; timezone: string; check_count?: number; bidders: Bidder[]; accounts?: Bidder[]; account_timeline?: TimelinePoint[]; timeline: TimelinePoint[] }
const colors = ["#00cfff", "#a78bfa", "#34d399", "#fbbf24", "#f472b6", "#60a5fa", "#fb923c"]
const time = (stamp: string) => new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(new Date(stamp))
const hourLabel = (hour: number) => `${hour % 12 || 12}${hour < 12 ? "am" : "pm"}`
export default function BidderActivity({ week, selected, onSelect }: { week: string; selected: string; onSelect: (id: string) => void }) {
  const [mode, setMode] = useState<"checks" | "days">("checks")
  const [group, setGroup] = useState<"bidders" | "accounts">("bidders")
  const [account, setAccount] = useState("")
  useEffect(() => { setAccount(""); }, [week, selected])
  const scope = group === "accounts" ? selected : ""
  const query = useQuery({ queryKey: ["payments", "activity", week, scope], queryFn: () => request<ActivityData>(`/api/payments/activity?week=${week}${scope ? `&bidder=${scope}` : ""}`), refetchInterval: 30_000 })
  const data = query.data
  const valid = data && Array.isArray(data.timeline)
  const entities = valid ? group === "accounts" ? data.accounts || [] : data.bidders : []
  const selection = group === "accounts" ? account : selected
  const choose = (id: string) => group === "accounts" ? setAccount(id) : onSelect(id)
  const bidders = entities.filter(b => !selection || b.id === Number(selection))
  const points = valid ? group === "accounts" ? data.account_timeline || [] : data.timeline : []
  const total = bidders.reduce((sum, b) => sum + b.new_checks, 0)
  const hourly = Array.from({ length: 24 }, (_, hour) => bidders.reduce((sum, b) => sum + b.hourly[hour], 0))
  const peak = hourly.indexOf(Math.max(...hourly))
  const timeline = valid ? points.map(point => ({ at: point.at, ...point.counts })) : []
  const daily = valid ? data.dates.map((day, i) => ({ at: day, ...Object.fromEntries(bidders.map(b => [String(b.id), b.daily[i]])) })) : []
  const heatmap = valid ? data.dates.map((_, day) => Array.from({ length: 24 }, (_, hour) => bidders.reduce((sum, b) => sum + (b.heatmap[day]?.[hour] || 0), 0))) : []
  const maxHeat = Math.max(1, ...heatmap.flat())
  const label = (value: string) => mode === "checks" ? time(value) : new Date(`${value}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
  return <Card className="bidder-activity" aria-label="Bidder activity monitor">
    <div className="activity-heading"><div><p className="eyebrow"><Activity size={14} /> ACTIVITY MONITOR</p><h2>When activity is detected</h2><p>Newly checked links observed in America/Chicago. Detection times show activity signals, not exact working hours.</p></div><span className="activity-live"><i />Updates after each check</span></div>
    {query.isPending ? <p role="status">Loading bidder activity…</p> : query.error ? <div role="alert">Could not load activity. <Button variant="outline" size="sm" onClick={() => void query.refetch()}>Retry activity</Button></div> : <>
      <div className="activity-group-controls" role="group" aria-label="Activity grouping"><Button size="sm" variant={group === "bidders" ? "secondary" : "outline"} aria-pressed={group === "bidders"} onClick={() => setGroup("bidders")}>By bidder</Button><Button size="sm" variant={group === "accounts" ? "secondary" : "outline"} aria-pressed={group === "accounts"} onClick={() => setGroup("accounts")}>By account</Button>{group === "accounts" && <span>Checked links across {selected ? "the selected bidder’s account tabs" : "all assigned bidders’ account tabs"}; shared-account counts may overlap.</span>}</div>
      <div className="activity-legend"><Button size="sm" variant={!selection ? "secondary" : "ghost"} onClick={() => choose("")}>All {group}</Button>{entities.map((b, i) => <button key={b.id} aria-pressed={selection === String(b.id)} onClick={() => choose(selection === String(b.id) ? "" : String(b.id))}><i style={{ background: colors[i % colors.length] }} />{b.name}</button>)}</div>
      <div className="activity-metrics"><div><Activity size={18} /><span>New links detected<strong>{total.toLocaleString()}</strong></span></div><div><Clock3 size={18} /><span>Busiest detection hour<strong>{total ? `${hourLabel(peak)}–${hourLabel((peak + 1) % 24)}` : "Awaiting activity"}</strong></span></div><div><TrendingUp size={18} /><span>Checks recorded<strong>{valid ? data.check_count ?? data.timeline.length : 0}</strong></span></div></div>
      <div className="activity-chart-heading"><h3>Activity over time</h3><div role="group" aria-label="Activity graph period"><Button size="sm" variant={mode === "checks" ? "secondary" : "ghost"} aria-pressed={mode === "checks"} onClick={() => setMode("checks")}>Each check</Button><Button size="sm" variant={mode === "days" ? "secondary" : "ghost"} aria-pressed={mode === "days"} onClick={() => setMode("days")}>By day</Button></div></div>
      {valid && (points.length > 0 || total > 0) ? <div className="activity-chart" aria-label="Newly checked links over time"><ResponsiveContainer width="100%" height={240}><LineChart data={mode === "checks" ? timeline : daily} margin={{ top: 10, right: 16, bottom: 12, left: -15 }}><CartesianGrid stroke="var(--border)" strokeDasharray="3 3" /><XAxis dataKey="at" tickFormatter={label} minTickGap={55} tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} /><YAxis allowDecimals={false} tick={{ fill: "var(--muted-foreground)", fontSize: 11 }} /><Tooltip labelFormatter={value => label(String(value))} contentStyle={{ background: "var(--background)", borderColor: "var(--border)", borderRadius: 6 }} />{bidders.map(b => <Line key={b.id} type="linear" dataKey={String(b.id)} name={b.name} stroke={colors[Math.max(0, entities.findIndex(row => row.id === b.id)) % colors.length]} strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />)}</LineChart></ResponsiveContainer></div> : <div className="activity-empty"><Activity size={26} /><strong>Activity history starts here</strong><span>Run Check now or wait for auto-check. Newly checked links will appear here; existing checks are kept as an untimed baseline.</span></div>}
      <div className="activity-chart-heading"><h3>Activity by hour</h3><span>Low <i className="heat-key" /> High · Chicago time</span></div>
      <div className="activity-heatmap-scroll"><div className="activity-heatmap" role="img" aria-label="Hourly heatmap of newly detected checks"><span />{hourly.map((_, h) => <small key={h}>{h % 3 === 0 ? hourLabel(h) : ""}</small>)}{valid && data.dates.map((day, d) => <div className="heatmap-row" key={day}><span>{new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" })}</span>{heatmap[d].map((count, h) => <span className="heat-cell" key={h} tabIndex={count ? 0 : undefined} title={`${day}, ${hourLabel(h)}: ${count} newly checked links`} aria-label={`${day}, ${hourLabel(h)}: ${count} newly checked links`} style={{ background: count ? `color-mix(in srgb, var(--primary) ${20 + count / maxHeat * 70}%, var(--background))` : "var(--surface)" }} />)}</div>)}</div></div>
      <div className="payment-table-scroll"><table className="activity-table"><thead><tr><th>{group === "accounts" ? "Account" : "Bidder"}</th><th>New links detected</th><th>Active 30-min windows</th><th>Last activity</th><th>Latest / previous check</th></tr></thead><tbody>{bidders.map(b => {
        const latest = b.latest_check?.new_checks, previous = b.previous_check?.new_checks
        const change = latest === undefined || previous === undefined ? "Building history" : previous === 0 ? latest > 0 ? "Activity increased" : "No new checks" : `${latest >= previous ? "+" : ""}${Math.round((latest - previous) / previous * 100)}%`
        const trend = latest !== undefined && previous !== undefined ? latest > previous ? "activity-rise" : latest < previous ? "activity-drop" : "" : ""
        return <tr key={b.id}><th><i style={{ background: colors[Math.max(0, entities.findIndex(row => row.id === b.id)) % colors.length] }} />{b.name}</th><td>{b.new_checks}</td><td>{b.active_half_hours}</td><td>{b.last_detected ? time(b.last_detected) : "No activity detected"}</td><td><strong className={trend}>{latest ?? "—"} / {previous ?? "—"}</strong><small>{change}</small></td></tr>
      })}</tbody></table></div>
      <p className="activity-footnote">Chart dates are detection dates; payment counts stay on the original sourcing date. The per-check chart shows the latest 240 checks; By day covers the full week. Batch email delivery and check frequency affect the pattern. Active windows are not hours worked. {valid && data.tracking_since ? `Tracking started ${time(data.tracking_since)}.` : "Tracking begins with this update."}</p>
    </>}
  </Card>
}
