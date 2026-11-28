export type Counts = { eligible: number; interview: number; rejection: number; answered: number }
export type Profile = { id: number; label: string; color_slot?: number; duplicates: number; unmatched: { interview: number; rejection: number }; daily: Record<string, { applications: number; windows: Record<string, Counts> }> }
export type Outcomes = { version: number; history_since: string | null; timezone: string; mature_through: Record<string, string>; accounts: Profile[] }
export type Period = "Day" | "Week" | "Month"
export type Point = { date: string; from: string; through: string; counts: Counts[] } & Record<`s${number}`, number | null>
export const empty = (): Counts => ({ eligible: 0, interview: 0, rejection: 0, answered: 0 })
export const shift = (day: string, n: number) => { const d = new Date(day + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }
export function sum(profile: Profile, horizon: number, start: string, end: string) {
  const result = empty()
  for (const [day, bucket] of Object.entries(profile.daily)) if (day >= start && day <= end) {
    const counts = bucket.windows[String(horizon)]
    if (counts) for (const key of Object.keys(result) as (keyof Counts)[]) result[key] += counts[key]
  }
  return result
}
export function interval(hits: number, n: number): [number, number] | null {
  if (!n) return null
  const z = 1.96, p = hits / n, d = 1 + z * z / n
  const center = (p + z * z / (2 * n)) / d
  const margin = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
  return [Math.max(0, center - margin) * 100, Math.min(1, center + margin) * 100]
}
function bucket(day: string, period: Period) {
  if (period === "Month") return day.slice(0, 7) + "-01"
  if (period === "Week") return shift(day, -(new Date(day + "T00:00:00Z").getUTCDay() + 6) % 7)
  return day
}
export function points(data: Outcomes, horizon: number, period: Period, rolling: boolean, metric: "interview" | "rejection", small: boolean): Point[] {
  const end = data.mature_through[String(horizon)]
  const dates = data.accounts.flatMap(p => Object.keys(p.daily)).filter(d => d <= end && (!data.history_since || d >= data.history_since))
  if (!dates.length) return []
  const start = dates.sort()[0]
  // Prefix sums keep years of history linear to prepare, rather than rescanning
  // every application day for each plotted day and account.
  const prepared = data.accounts.map(profile => {
    const days = Object.keys(profile.daily).sort()
    const totals: Counts[] = [empty()]
    for (const day of days) {
      const c = profile.daily[day].windows[String(horizon)] || empty()
      const previous = totals[totals.length - 1]
      totals.push(Object.fromEntries(Object.keys(previous).map(k => [k, previous[k as keyof Counts] + c[k as keyof Counts]])) as Counts)
    }
    const upper = (day: string) => {
      let lo = 0, hi = days.length
      while (lo < hi) { const mid = (lo + hi) >>> 1; if (days[mid] <= day) lo = mid + 1; else hi = mid }
      return lo
    }
    return (from: string, through: string): Counts => {
      const a = totals[upper(shift(from, -1))], b = totals[upper(through)]
      return Object.fromEntries(Object.keys(a).map(k => [k, b[k as keyof Counts] - a[k as keyof Counts]])) as Counts
    }
  })
  const periods = new Map<string, { start: string; end: string }>()
  for (let day = start; day <= end; day = shift(day, 1)) {
    const key = bucket(day, period)
    const previous = periods.get(key)
    periods.set(key, { start: previous?.start || day, end: day })
  }
  return [...periods].map(([date, span]) => {
    const from = rolling ? shift(span.end, -27) : span.start
    const counts = prepared.map(total => total(from, span.end))
    return { date, from, through: span.end, counts, ...Object.fromEntries(counts.map((c, i) => [`s${i}`, c.eligible && (small || c.eligible >= 20) ? 100 * c[metric] / c.eligible : null])) } as Point
  })
}
