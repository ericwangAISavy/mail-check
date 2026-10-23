import type { InterviewEvent } from "./types"

export type CalendarView = "workweek" | "week" | "month" | "day"
export const HOUR_HEIGHT = 80
export const dayKey = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`
export const startOfDay = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate())
export const shiftDays = (date: Date, count: number) => new Date(date.getFullYear(), date.getMonth(), date.getDate() + count)
export const startOfWeek = (date: Date) => shiftDays(date, -((date.getDay() + 6) % 7))
export function parseDay(value: string | null) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const [year, month, day] = value.split("-").map(Number)
  const result = new Date(year, month - 1, day)
  return dayKey(result) === value ? result : null
}
export function viewDays(date: Date, view: CalendarView) {
  const first = view === "month" ? startOfWeek(new Date(date.getFullYear(), date.getMonth(), 1)) : view === "day" ? startOfDay(date) : startOfWeek(date)
  return Array.from({ length: view === "month" ? 42 : view === "workweek" ? 5 : view === "week" ? 7 : 1 }, (_, index) => shiftDays(first, index))
}
export function fallsOnDay(event: InterviewEvent, day: Date) {
  if (!event.start_at) return false
  const start = new Date(event.start_at), end = event.end_at ? new Date(event.end_at) : start
  return Number.isFinite(start.getTime()) && start < shiftDays(day, 1) && (end > day || dayKey(start) === dayKey(day))
}
export function calendarCounts(events: InterviewEvent[], days: Date[]) {
  const counts = {total:0,intro:0,tech:0,unknown:0}
  const seen = new Set<number>()
  for (const event of events) {
    if (seen.has(event.id) || event.status === "Cancelled" || !days.some(day => fallsOnDay(event,day))) continue
    seen.add(event.id); counts.total++
    const duration = event.start_at && event.end_at ? new Date(event.end_at).getTime()-new Date(event.start_at).getTime() : NaN
    if (!Number.isFinite(duration) || duration<=0) counts.unknown++
    else if (duration<=30*60_000) counts.intro++
    else counts.tech++
  }
  return counts
}

export type TimePlacement = { event: InterviewEvent; start: number; end: number; lane: number; lanes: number; continuesBefore: boolean; continuesAfter: boolean; unknownEnd: boolean }
export function placeEvents(events: InterviewEvent[], day: Date): TimePlacement[] {
  const nextDay = shiftDays(day, 1)
  const minute = (value: Date) => value.getHours() * 60 + value.getMinutes() + value.getSeconds() / 60
  const placements = events.filter(event => fallsOnDay(event, day)).map(event => {
    const start = new Date(event.start_at!)
    const finish = event.end_at ? new Date(event.end_at) : null
    const knownEnd = finish && Number.isFinite(finish.getTime()) && finish > start ? finish : null
    const from = start < day ? 0 : minute(start)
    let until = knownEnd ? knownEnd >= nextDay ? 1440 : minute(knownEnd) : from + 20
    // On a DST fold the clock can move backwards while real time advances.
    // Preserve the displayed real start/end labels and give the block its elapsed height.
    if (knownEnd && until <= from) until = from + (knownEnd.getTime() - Math.max(start.getTime(), day.getTime())) / 60000
    return { event, start: from, end: Math.min(1440, Math.max(from + 15, until)), lane: 0, lanes: 1, continuesBefore: start < day, continuesAfter: !!knownEnd && knownEnd > nextDay, unknownEnd: !knownEnd }
  }).sort((a, b) => a.start - b.start || b.end - a.end || a.event.id - b.event.id)
  let group: TimePlacement[] = [], laneEnds: number[] = [], groupEnd = -1
  const finishGroup = () => { for (const placement of group) placement.lanes = laneEnds.length; group = []; laneEnds = [] }
  for (const placement of placements) {
    if (placement.start >= groupEnd) { finishGroup(); groupEnd = -1 }
    let lane = laneEnds.findIndex(end => end <= placement.start)
    if (lane < 0) lane = laneEnds.length
    placement.lane = lane
    laneEnds[lane] = placement.end
    groupEnd = Math.max(groupEnd, placement.end)
    group.push(placement)
  }
  finishGroup()
  return placements
}

const escapeICal = (value: string) => value.replace(/\\/g, "\\\\").replace(/\r?\n|\r/g, "\\n").replace(/;/g, "\\;").replace(/,/g, "\\,")
const stamp = (value: string) => new Date(value).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z")
// RFC 5545 folds at 75 octets, without splitting UTF-8 code points.
function fold(line: string) {
  let result = "", part = "", count = 0
  for (const char of line) {
    const bytes = new TextEncoder().encode(char).length
    if (count + bytes > 75) { result += part + "\r\n"; part = " "; count = 1 }
    part += char; count += bytes
  }
  return result + part
}
export function exportInterviews(events: InterviewEvent[], now = new Date()) {
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Mailcheck//Interview Calendar//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
  for (const event of events) {
    if (!event.start_at || !Number.isFinite(new Date(event.start_at).getTime())) continue
    lines.push("BEGIN:VEVENT", `UID:${escapeICal(`mailcheck-interview-${event.id}@local`)}`, `DTSTAMP:${stamp(now.toISOString())}`, `DTSTART:${stamp(event.start_at)}`)
    if (event.end_at && new Date(event.end_at) > new Date(event.start_at)) lines.push(`DTEND:${stamp(event.end_at)}`)
    lines.push(`SUMMARY:${escapeICal([event.company || "Unknown company", event.role, event.stage].filter(Boolean).join(" · "))}`)
    if (event.location) lines.push(`LOCATION:${escapeICal(event.location)}`)
    if (event.meeting_url) lines.push(`URL:${event.meeting_url.replace(/[\r\n]/g, "")}`)
    lines.push(`DESCRIPTION:${escapeICal([event.meeting_platform, event.meeting_url, event.notes, !event.end_at ? "End time unknown" : null].filter(Boolean).join("\n"))}`)
    lines.push(`STATUS:${event.status === "Cancelled" ? "CANCELLED" : event.needs_review ? "TENTATIVE" : "CONFIRMED"}`, "END:VEVENT")
  }
  return [...lines, "END:VCALENDAR"].map(fold).join("\r\n") + "\r\n"
}
