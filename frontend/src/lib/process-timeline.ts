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
  const ticks: { date: Date; label: string; position: number }[] = []
  if (period === "daily") {
    for (let hour = 0; hour <= 24; hour += 4) {
      const date = new Date(start); date.setHours(hour)
      ticks.push({ date, label: hour === 24 ? "12 AM" : date.toLocaleTimeString(undefined, { hour: "numeric" }), position: (date.getTime() - start.getTime()) / (end.getTime() - start.getTime()) })
    }
  } else {
    const step = period === "weekly" ? 1 : period === "two-months" ? 10 : 5
    for (const date = new Date(start); date < end; date.setDate(date.getDate() + step)) {
      ticks.push({ date: new Date(date), label: date.toLocaleDateString(undefined, { month: "short", day: "numeric" }), position: (date.getTime() - start.getTime()) / (end.getTime() - start.getTime()) })
    }
  }
  return { start, end, ticks }
}

export function movePeriod(anchor: string, period: TimelinePeriod, direction: number) {
  const date = periodWindow(anchor, period).start
  if (period === "monthly" || period === "two-months") date.setMonth(date.getMonth() + direction * (period === "two-months" ? 2 : 1))
  else date.setDate(date.getDate() + direction * (period === "weekly" ? 7 : 1))
  return dateInput(date)
}

export function positionMilestones<T extends { id: string; occurred_at: string }>(milestones: T[], window: { start: Date; end: Date }) {
  const laneEnds: number[] = []
  return milestones.filter(m => new Date(m.occurred_at) >= window.start && new Date(m.occurred_at) < window.end)
    .sort((a, b) => new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime() || a.id.localeCompare(b.id))
    .map(milestone => {
      const position = (new Date(milestone.occurred_at).getTime() - window.start.getTime()) / (window.end.getTime() - window.start.getTime())
      let lane = laneEnds.findIndex(end => position - end >= .045)
      if (lane < 0) lane = laneEnds.length
      laneEnds[lane] = position
      return { milestone, position, lane }
    })
}
