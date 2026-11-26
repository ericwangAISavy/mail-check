import { useMemo, useState } from "react"
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { interval, points, shift, sum, type Point, type Outcomes, type Period } from "@/lib/profile-outcomes"

type Metric = "interview" | "rejection"
const metrics = [{ key: "interview", label: "Interview rate" }, { key: "rejection", label: "Rejection rate" }] as const
const pct = (v: number) => `${v.toFixed(1)}%`
const confidence = (hits: number, n: number) => { const ci = interval(hits, n); return ci ? `${pct(ci[0])}–${pct(ci[1])}` : "—" }
const color = (index: number) => `var(--quality-series-${index % 8})`
const label = (day: string) => new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", timeZone: "UTC" }).format(new Date(day + "T00:00:00Z"))
export default function ProfileQuality({ outcomes }: { outcomes?: Outcomes }) {
  const [period, setPeriod] = useState<Period>("Week")
  const [style, setStyle] = useState<"Line" | "Bar">("Line")
  const [metric, setMetric] = useState<Metric>("interview")
  const [horizon, setHorizon] = useState(14)
  const [rolling, setRolling] = useState(true)
  const [small, setSmall] = useState(false)
  const [details, setDetails] = useState(false)
  const [hidden, setHidden] = useState<ReadonlySet<number>>(new Set())
  const rows = useMemo(() => outcomes ? points(outcomes, horizon, period, rolling, metric, small) : [], [outcomes, horizon, period, rolling, metric, small])
  const end = outcomes?.mature_through[String(horizon)] || ""
  const Chart = style === "Line" ? LineChart : BarChart
  const accounts = outcomes?.accounts || []
  const unmatched = accounts.reduce((n, p) => n + p.unmatched.interview + p.unmatched.rejection, 0)
  const visible = rows.some(row => accounts.some((p, i) => !hidden.has(p.id) && (row as Record<string, unknown>)[`s${i}`] != null))
  return <section className="profile-quality" aria-labelledby="profile-quality-title">
    <header><div className="quality-heading"><h2 id="profile-quality-title">Profile quality</h2><span className="quality-context" title="Unique confirmed applications with matched recruiting outcomes">{horizon}-day outcomes</span></div>
      <div className="quality-controls">
        <div className="quality-period" role="group" aria-label="Profile quality metric">{metrics.map(m => <button key={m.key} aria-pressed={metric === m.key} onClick={() => setMetric(m.key)} aria-label={m.label}>{m.key === "interview" ? "Interview" : "Rejection"}</button>)}</div>
        <div className="quality-period" role="group" aria-label="Profile quality chart style">{(["Line", "Bar"] as const).map(v => <button key={v} aria-pressed={style === v} onClick={() => setStyle(v)}>{v}</button>)}</div>
        <div className="quality-period" role="group" aria-label="Profile quality grouping">{(["Day", "Week", "Month"] as const).map(v => <button key={v} aria-pressed={period === v} onClick={() => setPeriod(v)}>{v}</button>)}</div>
      </div>
    </header>
    {!outcomes ? <p>Application outcome analysis is unavailable. Refresh after the server update.</p> : <div className="quality-panel">
      <div className="quality-analysis-controls">
        <div className="quality-period" role="group" aria-label="Trend calculation"><button aria-pressed={rolling} onClick={() => setRolling(true)}>28-day trend</button><button aria-pressed={!rolling} onClick={() => setRolling(false)}>Per period</button></div>
        <label>Response <select aria-label="Response window" value={horizon} onChange={e => setHorizon(Number(e.target.value))}>{[7, 14, 30].map(h => <option key={h} value={h}>{h} days</option>)}</select></label>
        <span className="quality-context" title="Only application cohorts with a complete response window are included">Observed through {label(end)}</span>
        <details className="quality-options"><summary>Options</summary><div>
          <label><input type="checkbox" checked={small} onChange={e => setSmall(e.target.checked)} /> Show samples below 20</label>
          <label><input type="checkbox" checked={details} onChange={e => setDetails(e.target.checked)} /> Show counting details and confidence ranges</label>
        </div></details>
      </div>
      <div className={`quality-plot ${visible ? "" : "is-empty"}`}>{visible ? <ResponsiveContainer width="100%" height="100%"><Chart accessibilityLayer data={rows} margin={{ top: 12, right: 14, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--border)" strokeOpacity={0.7} />
        <XAxis dataKey="date" tickFormatter={label} minTickGap={28} tickLine={false} axisLine={false} />
        <YAxis width={44} domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={(v: number) => `${v}%`} tickLine={false} axisLine={false} />
        <Tooltip content={({ active, payload }) => {
          const row = payload?.[0]?.payload as Point | undefined
          if (!active || !row) return null
          return <div className="quality-tooltip"><strong>{label(row.from)} – {label(row.through)}</strong>{accounts.map((p, i) => {
            const c = row.counts[i]
            return hidden.has(p.id) || row[`s${i}`] == null ? null : <div key={p.id}><i style={{ background: color(p.color_slot ?? i) }} /><span>{p.label}: <b>{pct(100 * c[metric] / c.eligible)}</b> ({c[metric]} / {c.eligible})<br />95% interval {confidence(c[metric], c.eligible)}{c.eligible < 20 ? " · Small sample" : ""}</span></div>
          })}</div>
        }} />
        {accounts.map((p, i) => hidden.has(p.id) ? null : style === "Line"
          ? <Line key={p.id} name={p.label} dataKey={`s${i}`} type="linear" connectNulls={false} stroke={color(p.color_slot ?? i)} strokeDasharray={(p.color_slot ?? i) >= 8 ? "5 3" : undefined} strokeWidth={2} dot={{ r: 2 }} isAnimationActive={false} />
          : <Bar key={p.id} name={p.label} dataKey={`s${i}`} fill={color(p.color_slot ?? i)} maxBarSize={14} radius={[3, 3, 0, 0]} isAnimationActive={false} />)}
      </Chart></ResponsiveContainer> : <p className="quality-empty">No visible cohort has enough observed applications. Choose a shorter response window, show small samples, or enable an account below.</p>}</div>
      <div className="quality-table-wrap"><table className="quality-table">
        <caption className="quality-caption"><span>Latest 28 mature days: {label(shift(end, -27))} - {label(end)}</span><span>Click an account to toggle its chart</span></caption>
        <thead><tr><th>Account</th><th title="All tracked confirmations / recent confirmations still gathering responses">Tracked / recent</th><th title="Mature applications in the latest 28-day cohort window">Sample</th><th>Interview</th><th>Rejection</th><th>Interview trend</th></tr></thead>
        <tbody>{accounts.map((p, i) => {
          const c = sum(p, horizon, shift(end, -27), end), previous = sum(p, horizon, shift(end, -55), shift(end, -28))
          const ci = interval(c.interview, c.eligible), before = interval(previous.interview, previous.eligible)
          const trend = c.eligible < 20 ? "Small sample" : previous.eligible < 20 ? "Building baseline" : ci && before && ci[0] > before[1] ? "Higher conversion" : ci && before && ci[1] < before[0] ? "Lower conversion" : "No clear change"
          const total = Object.values(p.daily).reduce((n, d) => n + d.applications, 0)
          const recent = Object.entries(p.daily).reduce((n, [day, d]) => n + (day > end ? d.applications : 0), 0)
          return <tr key={p.id} className={hidden.has(p.id) ? "is-hidden" : undefined}>
            <th scope="row"><button title={p.label} aria-pressed={!hidden.has(p.id)} onClick={() => setHidden(old => { const next = new Set(old); if (next.has(p.id)) next.delete(p.id); else next.add(p.id); return next })}><i style={{ backgroundColor: color(p.color_slot ?? i) }} /><span className="quality-account-label">{p.label}</span></button></th>
            <td title={`${p.duplicates} duplicate confirmations excluded`}>{total.toLocaleString()} / {recent.toLocaleString()}{details && <small className="quality-detail">{p.duplicates} duplicate confirmations excluded</small>}</td>
            <td title={`${c.answered} applications received an outcome`}>{c.eligible.toLocaleString()}{details && <small className="quality-detail">{c.answered} received an outcome</small>}</td>
            {metrics.map(m => <td key={m.key} className={metric === m.key ? "is-active" : undefined} title={`95% confidence range: ${confidence(c[m.key], c.eligible)}`}><div className="quality-rate"><strong>{c.eligible ? pct(100 * c[m.key] / c.eligible) : "\u2014"}</strong><small>{c[m.key]} / {c.eligible}</small></div>{details && <small className="quality-detail">95% {confidence(c[m.key], c.eligible)}</small>}</td>)}
            <td><span className={`quality-trend ${trend === "Higher conversion" ? "is-up" : trend === "Lower conversion" ? "is-down" : ""}`}>{trend}</span></td>
          </tr>
        })}</tbody>
      </table></div>
      <details className="quality-data"><summary>Method &amp; data quality · {unmatched} unlinked outcome emails excluded</summary><p>{rolling ? "Each graph point combines 28 application days, weighted by application volume." : "Each graph point represents that calendar period."} Recent applications are still gathering responses. Recruiting outcomes reflect resume, role fit and market conditions; they are not a resume score.</p><p>Applications are deduplicated within each profile and calendar day. Outcomes must match a preceding application; ambiguous matches are excluded. Repeat messages count once. Interview and rejection can both occur for one application, so the two rates do not sum to 100%. Confidence intervals describe sampling uncertainty, not missing data.</p><p>History observed from {outcomes.history_since || "available records"} · {outcomes.timezone}. Missing historical mail can reduce measured conversion. Profiles use the same response window. Recent applications do not lower the trend. A shorter window reports faster responses, not eventual success.</p></details>
    </div>}
  </section>
}
