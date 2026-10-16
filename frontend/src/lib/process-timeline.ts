export type TimelinePeriod = "all" | "daily" | "weekly" | "two-weeks" | "monthly" | "two-months"
export const dateInput = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`
const fromInput = (value: string) => { const [y, m, d] = value.split("-").map(Number); return new Date(y, m - 1, d) }

export function periodWindow(anchor: string, period: TimelinePeriod) {
  if (period === "all") return { start: new Date(-8640000000000000), end: new Date(8640000000000000), all: true }
  const start = fromInput(anchor)
  if (period === "weekly" || period === "two-weeks") start.setDate(start.getDate() - (start.getDay() + 6) % 7)
  if (period === "monthly" || period === "two-months") start.setDate(1)
  const end = new Date(start)
  if (period === "monthly" || period === "two-months") end.setMonth(end.getMonth() + (period === "two-months" ? 2 : 1))
  else end.setDate(end.getDate() + (period === "two-weeks" ? 14 : period === "weekly" ? 7 : 1))
  return { start, end }
}

export function movePeriod(anchor: string, period: TimelinePeriod, direction: number) {
  if (period === "all") return anchor
  const date = periodWindow(anchor, period).start
  if (period === "monthly" || period === "two-months") date.setMonth(date.getMonth() + direction * (period === "two-months" ? 2 : 1))
  else date.setDate(date.getDate() + direction * (period === "two-weeks" ? 14 : period === "weekly" ? 7 : 1))
  return dateInput(date)
}

export function positionMilestones<T extends { id: string; occurred_at: string }>(milestones: T[], followUp = false) {
  const ordered = [...milestones]
    .sort((a, b) => new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime() || a.id.localeCompare(b.id))
  const segments = ordered.length - 1 + Number(followUp)
  return ordered.map((milestone, index) => ({ milestone, position: segments > 0 ? index / segments : 0 }))
}

export function needsFollowUp(milestones: { id: string; occurred_at: string }[], now = Date.now(), events: { id: number; end_at: string | null }[] = []) {
  const endings = new Map(events.map(event => [`event:${event.id}`, event.end_at]))
  return milestones.length > 0 && milestones.every(milestone => {
    const start = new Date(milestone.occurred_at).getTime()
    const end = endings.get(milestone.id)
    return start <= now && (!end || new Date(end).getTime() <= now)
  })
}

export function inPeriod(milestone: { occurred_at: string }, window: { start: Date; end: Date }) {
  const date = new Date(milestone.occurred_at)
  return date >= window.start && date < window.end
}

export function milestoneTiming(milestone: { occurred_at: string; kind: string; status: string }, window: { start: Date; end: Date; all?: boolean }, now = Date.now()) {
  const date = new Date(milestone.occurred_at)
  if (window.all) {
    if (milestone.kind === "event" && ["Scheduled", "Rescheduled"].includes(milestone.status) && date.getTime() > now) return { tone: "future", label: "Upcoming booking" }
    return { tone: date.getTime() > now ? "present" : "past", label: date.getTime() > now ? "Upcoming milestone" : "Past milestone" }
  }
  if (date < window.start) return { tone: "past", label: "Before selected window" }
  if (date < window.end) return { tone: "present", label: "In selected window" }
  if (milestone.kind === "event" && ["Scheduled", "Rescheduled"].includes(milestone.status) && date.getTime() > now) {
    return { tone: "future", label: "Upcoming booking after selected window" }
  }
  return { tone: "past", label: "After selected window" }
}
