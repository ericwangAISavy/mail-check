// Types and display helpers for /api/dashboard/metrics. Definitions live in docs/METRICS.md;
// the server computes every value, the client only formats it.

export type Change = { absolute: number; percent: number | null } | null
export type TrendPoint = { week: string; value: number | null; partial: boolean }
type Summary = { previous_full: number | null; average: number | null; average_weeks: number; trend: TrendPoint[]; change: Change }
export type ApplicationSummary = Summary & { current: number; previous_comparable: number | null }
export type InterviewSummary = Summary & { scheduled: number; so_far: number; previous_so_far: number | null }
export type RateValue = { value: number; hits: number; base: number } | null
export type ProfileMetric = "interviews" | "applications" | "rejections" | "interview_rate" | "rejection_rate"
export type Bucket = { start: string; partial: boolean; replies_partial?: boolean }
export type ProfileSeries = {
  id: number; label: string; email: string; color: number
  points: { interviews: (number | null)[]; applications: (number | null)[]; rejections: (number | null)[]; interview_rate: RateValue[]; rejection_rate: RateValue[] }
}
export type RateAvailability = { available: boolean; reason: string | null; emails: number; matched: number; share: number | null }
export type BidderPoint = { carryover: number; new: number; available: number; completed: number; expired: number; remaining: number; completion_rate: number | null; checked: number } | null
export type WorkloadPoint = { new: number | null; checked: number | null; backlog: number | null; expired: number | null }
export type Grain = "daily" | "weekly"
export type AttentionItem = { id: string; severity: "critical" | "warning" | "info"; count: number; href: string; label: string; detail: string }
export type DashboardMetrics = {
  as_of: string; timezone: string; today: string
  range: { weeks: number | null; start: string; end: string }
  summaries: { week_start: string; week_end: string; applications: ApplicationSummary; interviews: InterviewSummary }
  profiles: { weeks: Bucket[]; series: ProfileSeries[]; rates: Record<"interview_rate" | "rejection_rate", RateAvailability>; cohort_days: number; mature_through: string; replies_since: string | null }
  bidders: Record<Grain, { buckets: Bucket[]; series: { id: number; name: string; points: BidderPoint[] }[]; workload: WorkloadPoint[] }> & { history_since: string | null }
  attention: AttentionItem[]
  payments: { week_start: string; week_end: string; currency: string; gross_cents: number; deductions_cents: number; net_payable_cents: number; recorded_cents: number; outstanding_cents: number | null; reconciled: boolean; week_ended: boolean; missing_rates: string[]; checked: number; bidders: number }
}

export const count = (value: number | null | undefined) => value == null ? "N/A" : value.toLocaleString("en-US", { maximumFractionDigits: 0 })
export const average = (value: number | null | undefined) => value == null ? "N/A" : value.toLocaleString("en-US", { maximumFractionDigits: value < 100 && value % 1 ? 1 : 0 })
export const percent = (value: number | null | undefined) => value == null ? "N/A" : `${(value * 100).toFixed(value > 0 && value < 0.1 ? 1 : 0)}%`
export const money = (cents: number | null | undefined, currency = "USD") => cents == null ? "N/A" : new Intl.NumberFormat("en-US", { style: "currency", currency }).format(cents / 100)

export const signed = (value: number) => `${value > 0 ? "+" : value < 0 ? "−" : "±"}${Math.abs(value).toLocaleString("en-US")}`
/** "+460 (+69.4%)"; the percentage is left out when the previous value was zero. */
export function changeText(change: Change): string | null {
  if (!change) return null
  if (change.percent == null) return signed(change.absolute)
  return `${signed(change.absolute)} (${signed(change.percent)}%)`
}

export const dayLabel = (iso: string, withWeekday = false) => {
  const day = new Date(`${iso}T00:00:00Z`)
  return Number.isNaN(day.getTime()) ? "" : new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", ...(withWeekday ? { weekday: "short" } : {}), timeZone: "UTC" }).format(day)
}
export const rangeLabel = (start: string, end: string) => start === end ? dayLabel(start) : `${dayLabel(start)} – ${dayLabel(end)}`

const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1)
/** Short, recognisable names for accounts labelled by email address ("eric.wang@…" → "Eric").
 * Repeats are numbered, shortest address first, so each alias stays unique; the full
 * address is always shown in tooltips. */
export function accountAliases(accounts: { id: number; label: string }[]): Record<number, string> {
  const used = new Map<string, number>(), out: Record<number, string> = {}
  for (const account of [...accounts].sort((a, b) => a.label.length - b.label.length || a.label.localeCompare(b.label))) {
    let base = account.label
    if (base.includes("@")) {
      const local = base.split("@")[0]
      base = capital((local.split(/[._+\-\d]+|(?<=[a-z])(?=[A-Z])/).find(Boolean) || local).toLowerCase())
    }
    const seen = (used.get(base) || 0) + 1
    used.set(base, seen)
    out[account.id] = seen > 1 ? `${base} ${seen}` : base
  }
  return out
}
