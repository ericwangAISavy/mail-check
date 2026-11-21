import { useId, useState } from "react"
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"

/** Per day: application emails received, and the interview / rejection emails that came back. */
type Counts = { applications: number; interview: number; rejection: number }
type Period = "Day" | "Week" | "Month"
type Props = { quality: Record<string, Record<string, Counts>>; accounts: string[]; since?: string | null }
const rates = [
  { key: "interview", label: "Interview", noun: "interview emails", color: "var(--quality-interview)" },
  { key: "rejection", label: "Rejection", noun: "rejection emails", color: "var(--quality-rejection)" },
] as const
const percent = new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 })
const empty = (): Counts => ({ applications: 0, interview: 0, rejection: 0 })
const plural = (n: number, one: string, many = one + "s") => `${n.toLocaleString()} ${n === 1 ? one : many}`

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
  // A rate needs applications to compare against; without any it stays blank.
  const rows = Array.from(buckets, ([date, counts]) => ({
    date, counts,
    interview: counts.applications ? counts.interview / counts.applications * 100 : null,
    rejection: counts.applications ? counts.rejection / counts.applications * 100 : null,
  }))
  return { total, rows }
}

function AccountName({ label }: { label: string }) {
  const at = label.indexOf("@")
  return at > 0 ? <h3 title={label}><strong>{label.slice(0, at)}</strong><span>{label.slice(at)}</span></h3> : <h3 title={label}><strong>{label}</strong></h3>
}

type Row = ReturnType<typeof groupDays>["rows"][number]

function QualityCard({ label, dates, daily, period, style, formatDate }: {
  label: string; dates: string[]; daily: Record<string, Counts>; period: Period; style: "Line" | "Bar"; formatDate: (date: string) => string
}) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "")
  const { total, rows } = groupDays(dates, daily, period)
  const hasApplications = total.applications > 0
  const Chart = style === "Line" ? AreaChart : BarChart
  return <article className="quality-card" aria-label={label + " profile quality"}>
    <header><AccountName label={label} /><small>{plural(total.applications, "application")}</small></header>
    <div className="quality-rates">{rates.map(rate => <div key={rate.key} className="quality-rate" title={`${rate.label} emails ÷ application emails received`}>
      <span><i style={{ backgroundColor: rate.color }} />{rate.label} rate</span>
      <strong>{hasApplications ? percent.format(total[rate.key] / total.applications) : "—"}</strong>
      <small>{total[rate.key].toLocaleString()} / {total.applications.toLocaleString()} applications</small>
    </div>)}</div>
    {hasApplications ? <div className="quality-plot">
      <ResponsiveContainer width="100%" height="100%"><Chart accessibilityLayer data={rows} margin={{ top: 8, right: 10, left: 0, bottom: 0 }}>
        <defs>{rates.map(rate => <linearGradient key={rate.key} id={`${uid}-${rate.key}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" style={{ stopColor: rate.color }} stopOpacity={style === "Line" ? 0.28 : 0.95} />
          <stop offset="100%" style={{ stopColor: rate.color }} stopOpacity={style === "Line" ? 0 : 0.55} />
        </linearGradient>)}</defs>
        <CartesianGrid vertical={false} stroke="var(--border)" strokeOpacity={0.7} />
        <XAxis dataKey="date" tickFormatter={formatDate} minTickGap={28} tickLine={false} axisLine={false} />
        <YAxis width={40} domain={[0, (max: number) => Math.max(10, Math.ceil(max / 10) * 10)]} tickCount={4}
          tickFormatter={(value: number) => `${value}%`} tickLine={false} axisLine={false} />
        <Tooltip filterNull={false} cursor={{ stroke: "var(--border)" }} content={({ active, payload }) => {
          const row = payload?.[0]?.payload as Row | undefined
          if (!active || !row) return null
          return <div className="quality-tooltip"><strong>{period === "Week" ? "Week of " : ""}{formatDate(row.date)}</strong>
            {rates.map(rate => <div key={rate.key}><i style={{ backgroundColor: rate.color }} />
              <b>{row.counts.applications ? percent.format(row.counts[rate.key] / row.counts.applications) : "—"}</b>
              <span>{rate.label} · {row.counts[rate.key]} / {row.counts.applications}</span></div>)}</div>
        }} />
        {rates.map(rate => style === "Line"
          ? <Area key={rate.key} type="monotone" name={rate.label} dataKey={rate.key} stroke={rate.color} strokeWidth={2}
              fill={`url(#${uid}-${rate.key})`} dot={{ r: 2.5, strokeWidth: 0, fill: rate.color }} activeDot={{ r: 4.5, strokeWidth: 2, stroke: "var(--card)" }} isAnimationActive={false} />
          : <Bar key={rate.key} name={rate.label} dataKey={rate.key} fill={`url(#${uid}-${rate.key})`} maxBarSize={16}
              radius={[5, 5, 0, 0]} isAnimationActive={false} />)}
      </Chart></ResponsiveContainer>
    </div> : <p className="quality-empty">{total.interview + total.rejection > 0
      ? "Rates need application emails to compare against, and none were received yet."
      : "No application emails received yet."}</p>}
  </article>
}

export default function ProfileQuality({ quality, accounts, since }: Props) {
  const [period, setPeriod] = useState<Period>("Week")
  const [style, setStyle] = useState<"Line" | "Bar">("Line")
  const labels = [...new Set([...accounts, ...Object.keys(quality)])].sort()
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
  return <section className="profile-quality" aria-labelledby="profile-quality-title">
    <header><div><h2 id="profile-quality-title">Profile quality</h2>
      <p>Interview and rejection emails compared with the application emails each account received.</p>
      {since && <small className="quality-since" title="Interview and rejection emails are kept from this day on, so earlier applications are not compared with replies that were never recorded.">
        Counting from {new Intl.DateTimeFormat(undefined, { timeZone: "UTC", dateStyle: "medium" }).format(new Date(since + "T00:00:00Z"))}</small>}</div>
      <div className="quality-controls">
      <div className="quality-period" role="group" aria-label="Profile quality chart style">
        {(["Line", "Bar"] as const).map(value => <button key={value} aria-pressed={style === value} onClick={() => setStyle(value)}>{value}</button>)}
      </div>
      <div className="quality-period" role="group" aria-label="Profile quality grouping">
        {(["Day", "Week", "Month"] as const).map(value => <button key={value} aria-pressed={period === value} onClick={() => setPeriod(value)}>{value}</button>)}
      </div>
      </div>
    </header>
    {!labels.length && <p>No profile activity in this range.</p>}
    <div className="quality-grid">{labels.map(label => <QualityCard key={label} label={label} dates={dates} daily={quality[label] || {}}
      period={period} style={style} formatDate={formatDate} />)}</div>
  </section>
}
