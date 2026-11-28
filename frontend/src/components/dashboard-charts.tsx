import { useState } from "react"
import { CartesianGrid, ComposedChart, Customized, Line, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipProps } from "recharts"
import { dayLabel, signed, type Bucket } from "@/lib/dashboard-metrics"

export type Series = {
  key: string
  /** Short name drawn beside the line's latest point. */
  name: string
  /** Full identity for the tooltip. */
  full: string
  color: string
  /** Sets the account color variables the color refers to. */
  className?: string
  values: (number | null)[]
  /** Numerator and denominator or similar context per bucket. */
  details?: (string | null)[]
}

type End = { cx: number; cy: number }

function ChartTip({ index, buckets, series, grain, format, percentage, note }: {
  index: number; buckets: Bucket[]; series: Series[]; grain: "daily" | "weekly"; format: (v: number) => string; percentage: boolean; note?: (index: number) => string | null
}) {
  const bucket = buckets[index]
  if (!bucket) return null
  const rows = series.filter(s => s.values[index] != null).sort((a, b) => (b.values[index] as number) - (a.values[index] as number))
  const extra = note?.(index)
  return <div className="od-tip" role="tooltip">
    <div className="od-tip-title">{grain === "weekly" ? `Week of ${dayLabel(bucket.start)}` : dayLabel(bucket.start, true)}{bucket.partial ? " · in progress" : ""}</div>
    {rows.map(s => {
      const value = s.values[index] as number, previous = index > 0 ? s.values[index - 1] : null
      const delta = previous == null || bucket.partial ? null : value - previous
      return <div className={`od-tip-row ${s.className || ""}`} key={s.key}>
        <i style={{ background: s.color }} />
        <span>{s.full}{s.details?.[index] ? <small>{s.details[index]}</small> : null}</span>
        <strong>{format(value)}</strong>
        <em>{delta == null ? "" : percentage ? `${signed(Math.round(delta * 1000) / 10)} pp` : signed(delta)}</em>
      </div>
    })}
    {rows.length === 0 && <p>No records for this period.</p>}
    {extra && <p>{extra}</p>}
  </div>
}

/** Names beside each line's latest point, spread apart so they never overlap and joined by a
 * faint connector when moved. Selecting a name isolates its line. */
function EndLabels({ ends, series, width, top, bottom, focus, onFocus }: {
  ends: Record<string, End>; series: Series[]; width: number; top: number; bottom: number; focus: string | null; onFocus: (key: string) => void
}) {
  const items = series.filter(s => ends[s.key]).map(s => ({ ...s, ...ends[s.key] })).sort((a, b) => a.cy - b.cy).map(item => ({ ...item, y: item.cy }))
  const gap = Math.min(18, Math.max(12, (bottom - top) / Math.max(1, items.length)))
  for (let i = 1; i < items.length; i++) items[i].y = Math.max(items[i].y, items[i - 1].y + gap)
  for (let i = items.length - 1; i >= 0; i--) items[i].y = Math.min(items[i].y, i === items.length - 1 ? bottom - 2 : items[i + 1].y - gap)
  for (const item of items) item.y = Math.max(item.y, top + 4)
  const right = items.reduce((max, item) => Math.max(max, item.cx), 0)
  return <g className="od-end-labels">{items.map(item => {
    const x = Math.min(right + 14, width - 40)
    const dimmed = focus !== null && focus !== item.key
    return <g key={item.key} className={`od-end ${item.className || ""}`} role="button" tabIndex={0} aria-pressed={focus === item.key} aria-label={`Show only ${item.full}`} opacity={dimmed ? 0.35 : 1}
      onClick={() => onFocus(item.key)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onFocus(item.key) } }}>
      <title>{item.full}</title>
      {(Math.abs(item.y - item.cy) > 3 || x - item.cx > 20) && <line x1={item.cx + 5} y1={item.cy} x2={x - 4} y2={item.y} stroke={item.color} strokeOpacity={0.4} strokeWidth={1} />}
      <text x={x} y={item.y + 4} fontSize={12.5} fontWeight={600} fill={item.color}>{item.name}</text>
    </g>
  })}</g>
}

/** Multi-series monotone trend lines. Missing records leave gaps, the unfinished final
 * period is dashed, and only the latest (or an isolated) point carries a permanent marker. */
export function TrendChart({ buckets, series, grain, format, percentage = false, label, note }: {
  buckets: Bucket[]; series: Series[]; grain: "daily" | "weekly"; format: (v: number) => string; percentage?: boolean; label: string; note?: (index: number) => string | null
}) {
  const [selected, setSelected] = useState<string | null>(null)
  const focus = series.some(s => s.key === selected) ? selected : null
  const partialAt = buckets.findIndex(b => b.partial)
  const rows = buckets.map((bucket, index) => {
    const row: Record<string, string | number | null> = { start: bucket.start }
    for (const s of series) {
      row[`s:${s.key}`] = partialAt >= 0 && index >= partialAt ? null : s.values[index] ?? null
      row[`d:${s.key}`] = partialAt >= 0 && index >= partialAt - 1 ? s.values[index] ?? null : null
    }
    return row
  })
  const lastIndex: Record<string, number> = Object.fromEntries(series.map(s => { let i = s.values.length - 1; while (i >= 0 && s.values[i] == null) i--; return [s.key, i] }))
  // Markers register while the lines draw; EndLabels then lays the names out together.
  const ends: Record<string, End> = {}
  const marker = (s: Series, part: "s" | "d") => (props: { cx?: number; cy?: number; index?: number }) => {
    const { cx, cy, index } = props
    const empty = <g key={`${part}-${s.key}-${index}`} />
    if (cx == null || cy == null || index === undefined || s.values[index] == null) return empty
    const last = index === lastIndex[s.key]
    const isolated = s.values[index - 1] == null && s.values[index + 1] == null
    if (!last && !isolated) return empty
    if (last) ends[s.key] = { cx, cy }
    return <circle key={`${part}-${s.key}-${index}`} className={s.className} cx={cx} cy={cy} r={3.5} fill={s.color} stroke="var(--card)" strokeWidth={1.5} opacity={focus && focus !== s.key ? 0.2 : 1} />
  }
  if (!series.some(s => s.values.some(v => v != null))) return <p className="od-chart-empty">No records are available for this selection.</p>
  return <div className="od-chart" role="group" aria-label={label}>
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={rows} margin={{ top: 12, right: 112, bottom: 0, left: -6 }}>
        <CartesianGrid vertical={false} stroke="var(--border)" strokeOpacity={0.55} />
        <XAxis dataKey="start" tickFormatter={(v: string) => dayLabel(v)} tick={{ fontSize: 12, fill: "var(--muted-foreground)" }} tickLine={false} axisLine={{ stroke: "var(--border)" }} minTickGap={20} tickMargin={8} />
        <YAxis allowDecimals={percentage} domain={percentage ? [0, (max: number) => Math.min(1, Math.max(0.1, Math.ceil(max * 10) / 10))] : [0, "auto"]} tickFormatter={(v: number) => percentage ? `${Math.round(v * 100)}%` : v.toLocaleString("en-US")} tick={{ fontSize: 12, fill: "var(--muted-foreground)" }} tickLine={false} axisLine={false} width={52} />
        <Tooltip isAnimationActive={false} cursor={{ stroke: "var(--muted-foreground)", strokeOpacity: 0.45, strokeWidth: 1 }}
          content={(props: TooltipProps<number, string>) => props.active ? <ChartTip index={buckets.findIndex(b => b.start === props.label)} buckets={buckets} series={focus ? series.filter(s => s.key === focus) : series} grain={grain} format={format} percentage={percentage} note={note} /> : null} />
        {series.flatMap(s => (["s", "d"] as const).map(part => <Line key={`${part}:${s.key}`} className={s.className} type="monotone" dataKey={`${part}:${s.key}`} name={s.name}
          stroke={s.color} strokeWidth={focus === s.key ? 2.75 : 2.25} strokeOpacity={focus && focus !== s.key ? 0.15 : 1} strokeLinecap="round" strokeDasharray={part === "d" ? "5 5" : undefined}

          dot={part === (partialAt >= 0 && lastIndex[s.key] >= partialAt ? "d" : "s") ? marker(s, part) : false}
          activeDot={focus && focus !== s.key ? false : { r: 4.5, strokeWidth: 2, stroke: "var(--card)", fill: s.color, className: s.className }} connectNulls={false} isAnimationActive={false} />))}
        <Customized component={(props: { width?: number; offset?: { top?: number; height?: number } }) => <EndLabels ends={ends} series={series} width={props.width ?? 0} top={props.offset?.top ?? 0} bottom={(props.offset?.top ?? 0) + (props.offset?.height ?? 0)} focus={focus} onFocus={key => setSelected(current => current === key ? null : key)} />} />
      </ComposedChart>
    </ResponsiveContainer>
  </div>
}
