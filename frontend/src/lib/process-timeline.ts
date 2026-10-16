export type TimelinePeriod = "daily" | "weekly" | "monthly" | "two-months"
export const dateInput = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`
const fromInput = (value: string) => { const [y, m, d] = value.split("-").map(Number); return new Date(y, m - 1, d) }

export function periodWindow(anchor: string, period: TimelinePeriod) {
  const start = fromInput(anchor)
  if (period === "weekly") start.setDate(start.getDate() - (start.getDay() + 6) % 7)
  if (period === "monthly" || period === "two-months") start.setDate(1)
  const end = new Date(start)
  if (period === "monthly" || period === "two-months") end.setMonth(end.getMonth() + (period === "two-months" ? 2 : 1))
  else end.setDate(end.getDate() + (period === "weekly" ? 7 : 1))
  return { start, end }
}

export function movePeriod(anchor: string, period: TimelinePeriod, direction: number) {
  const date = periodWindow(anchor, period).start
  if (period === "monthly" || period === "two-months") date.setMonth(date.getMonth() + direction * (period === "two-months" ? 2 : 1))
  else date.setDate(date.getDate() + direction * (period === "weekly" ? 7 : 1))
  return dateInput(date)
}

export function positionMilestones<T extends { id: string; occurred_at: string }>(milestones: T[], window: { start: Date; end: Date }) {
  const ordered = milestones.filter(m => new Date(m.occurred_at) >= window.start && new Date(m.occurred_at) < window.end)
    .sort((a, b) => new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime() || a.id.localeCompare(b.id))
  return ordered.map((milestone, index) => ({ milestone, position: ordered.length > 1 ? index / (ordered.length - 1) : 0 }))
}
