import { useState } from "react"
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"

/** Per day: application emails received, and the interview / rejection emails that came back. */
type Counts = { applications: number; interview: number; rejection: number }
type Period = "Day" | "Week" | "Month"
type Metric = "interview" | "rejection"
type Props = { quality: Record<string, Record<string, Counts>>; accounts: string[]; since?: string | null }

/** Palette slots available for account lines; further accounts are listed but not plotted. */
const SERIES = 8
const metrics = [
  { key: "interview", label: "Interview rate", short: "Interview" },
  { key: "rejection", label: "Rejection rate", short: "Rejection" },
] as const
const percent = new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 })
const empty = (): Counts => ({ applications: 0, interview: 0, rejection: 0 })
const colorOf = (index: number) => index < SERIES ? `var(--quality-series-${index})` : "var(--muted-foreground)"
const rate = (counts: Counts, metric: Metric) => counts.applications ? counts[metric] / counts.applications : null

function groupDays(dates: string[], daily: Record<string, Counts>, period: Period) {
  const buckets = new Map<string, Counts>()
  const total = empty()
  for (const day of dates) {
    let key = day
    if (period === "Month") key = day.slice(0, 7) + "-01"
    if (period === "Week") {
      const monday = new Date(day + "T00:00:00Z")
      monday.setUTCDate(monday.getUTCDate() - (monday.getUTCDay() + 6) % 7)
      key = monday.toISOString().slice(0, 10)
    }
    const bucket = buckets.get(key) || empty()
    const counts = daily[day]
    if (counts) {
      for (const metric of ["applications", "interview", "rejection"] as const) {
        bucket[metric] += counts[metric]
        total[metric] += counts[metric]
      }
    }
    buckets.set(key, bucket)
  }
  return { total, rows: Array.from(buckets, ([date, counts]) => ({ date, counts })) }
}

function AccountName({ label }: { label: string }) {
  const at = label.indexOf("@")
  return at > 0 ? <span className="quality-name" title={label}><strong>{label.slice(0, at)}</strong><span>{label.slice(at)}</span></span>
    : <span className="quality-name" title={label}><strong>{label}</strong></span>
}

export default function ProfileQuality({ quality, accounts, since }: Props) {
  const [period, setPeriod] = useState<Period>("Week")
  const [style, setStyle] = useState<"Line" | "Bar">("Line")
  const [metric, setMetric] = useState<Metric>("interview")
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set())
  // Account order (and so line color) follows the account list; a new account is added at the end and never repaints the others.
  const labels = [...new Set([...accounts, ...Object.keys(quality).sort()])]
  const storedDates = Object.values(quality).flatMap(days => Object.keys(days)).sort()
  const dates: string[] = []
  if (storedDates.length) {
    const day = new Date(storedDates[0] + "T00:00:00Z")
    const end = storedDates[storedDates.length - 1]
    while (day.toISOString().slice(0, 10) <= end) {
      dates.push(day.toISOString().slice(0, 10))
      day.setUTCDate(day.getUTCDate() + 1)
    }
  }
  const dateFormat = new Intl.DateTimeFormat(undefined, period === "Month"
    ? { timeZone: "UTC", month: "short", year: "numeric" } : { timeZone: "UTC", month: "short", day: "numeric" })
  const formatDate = (date: string) => dateFormat.format(new Date(date + "T00:00:00Z"))

  const grouped = labels.map(label => groupDays(dates, quality[label] || {}, period))
  const overall = grouped.reduce((sum, group) => {
    for (const key of ["applications", "interview", "rejection"] as const) sum[key] += group.total[key]
    return sum
  }, empty())
  // An account is drawn when it has applications to compare against and is not switched off.
  const drawn = labels.map((label, index) => index < SERIES && grouped[index].total.applications > 0 && !hidden.has(label))
  const rows = (grouped[0]?.rows ?? []).map((bucket, at) => {
    const row: Record<string, unknown> = { date: bucket.date, counts: grouped.map(group => group.rows[at].counts) }
    labels.forEach((_, index) => {
      const counts = grouped[index].rows[at].counts
      // Multiply first: 3 / 10 * 100 is 30.000000000000004, 3 * 100 / 10 is exactly 30.
      row[`s${index}`] = drawn[index] && counts.applications ? counts[metric] * 100 / counts.applications : null
    })
    return row
  })
  const lastPoint = labels.map((_, index) => rows.reduce((last, row, at) => row[`s${index}`] == null ? last : at, -1))
  // Fit the axis to typical values so one thin week (few applications, several replies) cannot flatten every line.
  const plotted = rows.flatMap(row => labels.flatMap((_, index) => typeof row[`s${index}`] === "number" ? [row[`s${index}`] as number] : [])).sort((a, b) => a - b)
  const niceTop = (value: number) => Math.max(20, Math.ceil(value / 20) * 20)       // 20, 40, 60 ... so the mid tick is a round number too
  const peak = plotted.length ? plotted[plotted.length - 1] : 0
  const typicalTop = niceTop((plotted.length ? plotted[Math.floor((plotted.length - 1) * 0.9)] : 0) * 1.3)
  const clipped = peak > typicalTop * 1.5
  const axisTop = clipped ? typicalTop : niceTop(peak)
  const anyApplications = overall.applications > 0
  const toggle = (label: string) => setHidden(current => {
    const next = new Set(current)
    if (!next.delete(label)) next.add(label)
    return next
  })
  const active = metrics.find(item => item.key === metric)!
  const Chart = style === "Line" ? LineChart : BarChart

  return <section className="profile-quality" aria-labelledby="profile-quality-title">
    <header><div><h2 id="profile-quality-title">Profile quality</h2>
      <p>Interview and rejection emails compared with the application emails each account received.</p>
      {since && <small className="quality-since" title="Interview and rejection emails are kept from this day on, so earlier applications are not compared with replies that were never recorded.">
        Counting from {new Intl.DateTimeFormat(undefined, { timeZone: "UTC", dateStyle: "medium" }).format(new Date(since + "T00:00:00Z"))}</small>}</div>
      <div className="quality-controls">
        <div className="quality-period" role="group" aria-label="Profile quality metric">
          {metrics.map(item => <button key={item.key} aria-pressed={metric === item.key} onClick={() => setMetric(item.key)}>{item.label}</button>)}
        </div>
        <div className="quality-period" role="group" aria-label="Profile quality chart style">
          {(["Line", "Bar"] as const).map(value => <button key={value} aria-pressed={style === value} onClick={() => setStyle(value)}>{value}</button>)}
        </div>
        <div className="quality-period" role="group" aria-label="Profile quality grouping">
          {(["Day", "Week", "Month"] as const).map(value => <button key={value} aria-pressed={period === value} onClick={() => setPeriod(value)}>{value}</button>)}
        </div>
      </div>
    </header>
    {!labels.length ? <p>No profile activity in this range.</p> : <div className="quality-panel">
      <div className="quality-plot">
        {drawn.some(Boolean) ? <ResponsiveContainer width="100%" height="100%"><Chart accessibilityLayer data={rows} margin={{ top: 10, right: 14, left: 0, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" strokeOpacity={0.7} />
          <XAxis dataKey="date" tickFormatter={formatDate} minTickGap={28} tickLine={false} axisLine={false} />
          <YAxis width={44} domain={[0, axisTop]} allowDataOverflow ticks={[0, axisTop / 2, axisTop]}
            tickFormatter={(value: number) => `${value}%`} tickLine={false} axisLine={false} />
          <Tooltip filterNull={false} cursor={{ stroke: "var(--border)" }} content={({ active: on, payload }) => {
            const row = payload?.[0]?.payload as { date: string; counts: Counts[] } | undefined
            if (!on || !row) return null
            const entries = labels.map((label, index) => ({ label, index, counts: row.counts[index] }))
              .filter(entry => drawn[entry.index] && entry.counts.applications > 0)
              .sort((a, b) => (rate(b.counts, metric) ?? 0) - (rate(a.counts, metric) ?? 0))
            return <div className="quality-tooltip"><strong>{period === "Week" ? "Week of " : ""}{formatDate(row.date)}</strong>
              {entries.map(entry => <div key={entry.label}><i style={{ backgroundColor: colorOf(entry.index) }} />
                <b>{percent.format(rate(entry.counts, metric) ?? 0)}</b>
                <span>{entry.label} · {entry.counts[metric]} / {entry.counts.applications}</span></div>)}
              {!entries.length && <span>No applications this {period.toLowerCase()}</span>}</div>
          }} />
          {labels.map((label, index) => !drawn[index] ? null : style === "Line"
            ? <Line key={label} name={label} dataKey={`s${index}`} stroke={colorOf(index)} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"
                dot={(props: { cx?: number; cy?: number; index?: number; value?: unknown }) => props.index === lastPoint[index] && props.value != null
                  ? <circle key={`end-${index}`} cx={props.cx} cy={props.cy} r={4} fill={colorOf(index)} stroke="var(--card)" strokeWidth={2} />
                  : <g key={`dot-${index}-${props.index}`} />}
                activeDot={{ r: 5, stroke: "var(--card)", strokeWidth: 2 }} isAnimationActive={false} />
            : <Bar key={label} name={label} dataKey={`s${index}`} fill={colorOf(index)} maxBarSize={14} radius={[4, 4, 0, 0]} isAnimationActive={false} />)}
        </Chart></ResponsiveContainer>
        : <p className="quality-empty">{!anyApplications
          ? (overall.interview + overall.rejection > 0
            ? "Rates need application emails to compare against, and none were received yet."
            : "No application emails received yet.")
          : "Every account is switched off. Choose one in the table below."}</p>}
      </div>
      {clipped && <small className="quality-clip">A few points are above {axisTop}% and run off the chart. Hover to see the exact value.</small>}
      <div className="quality-table-wrap"><table className="quality-table">
        <caption className="sr-only">{active.label} by account. Select an account to show or hide its line.</caption>
        <thead><tr><th scope="col">Account</th><th scope="col">Applications</th>
          {metrics.map(item => <th key={item.key} scope="col" className={metric === item.key ? "is-active" : undefined}>{item.label}</th>)}</tr></thead>
        <tbody>{labels.map((label, index) => {
          const total = grouped[index].total
          const plottable = index < SERIES && total.applications > 0
          return <tr key={label} className={plottable && hidden.has(label) ? "is-hidden" : undefined}>
            <th scope="row"><button type="button" aria-pressed={plottable && !hidden.has(label)} disabled={!plottable}
              title={plottable ? "Show or hide this account on the chart" : total.applications ? "More accounts than chart colors" : "No application emails yet"}
              onClick={() => toggle(label)}><i style={{ backgroundColor: plottable ? colorOf(index) : "transparent" }} /><AccountName label={label} /></button></th>
            <td>{total.applications.toLocaleString()}</td>
            {metrics.map(item => <td key={item.key} className={metric === item.key ? "is-active" : undefined}>
              {total.applications ? <><strong>{percent.format(total[item.key] / total.applications)}</strong><small>{total[item.key].toLocaleString()} / {total.applications.toLocaleString()}</small></>
                : <><strong>—</strong><small>{total[item.key].toLocaleString()} / 0</small></>}</td>)}
          </tr>
        })}</tbody>
        <tfoot><tr><th scope="row"><span className="quality-name"><strong>All accounts</strong></span></th>
          <td>{overall.applications.toLocaleString()}</td>
          {metrics.map(item => <td key={item.key} className={metric === item.key ? "is-active" : undefined}>
            {overall.applications ? <><strong>{percent.format(overall[item.key] / overall.applications)}</strong><small>{overall[item.key].toLocaleString()} / {overall.applications.toLocaleString()}</small></>
              : <><strong>—</strong><small>{overall[item.key].toLocaleString()} / 0</small></>}</td>)}
        </tr></tfoot>
      </table></div>
    </div>}
  </section>
}
