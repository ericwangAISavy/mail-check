import { useEffect, useState } from "react"
import type { TriageData } from "@/lib/types"

function stamp(value: string | null | undefined) {
  if (!value) return null
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? date : null
}
const clock = (date: Date) => date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })

export function InboxRefreshStatus({ schedule, unavailable = false }: { schedule: TriageData["check_schedule"]; unavailable?: boolean }) {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") setNow(Date.now()) }, 1000)
    return () => window.clearInterval(timer)
  }, [])
  const live = schedule?.live
  const next = stamp(live?.enabled ? live.next_at : schedule?.next_at)
  const last = stamp(live?.last_checked_at)
  const seconds = next ? Math.max(0, Math.ceil((next.getTime() - now) / 1000)) : null
  const countdown = seconds === null ? "" : seconds > 0 ? ` (in ${seconds}s)` : " (due now)"
  const label = unavailable ? "Live inbox: connection interrupted; retrying automatically" : live?.enabled
    ? `Live inbox: checks for new mail about every ${live.interval_seconds} seconds${live.running ? "; checking for new mail…" : schedule?.running ? "; server is processing updates" : ""}`
    : live?.disabled_reason || (!schedule ? "Check schedule unavailable" : !schedule.automatic ? "Automatic mail checks are off" : schedule.running ? "Server is processing updates; mail checks resume afterward" : "Live check schedule unavailable")
  return <section className="inbox-live-status" aria-label="Inbox update schedule">
    <p role="status">{label}</p>
    {!unavailable && live?.enabled && !live.running && <p>{schedule?.running ? "Next live check: after the current server task finishes" : next ? <>Next live check: <time dateTime={next.toISOString()}>{clock(next)}</time> (your local time)<span aria-hidden="true">{countdown}</span></> : "Next live check: being scheduled"}</p>}
    {!unavailable && !live && schedule?.automatic && !schedule.running && next && <p>Next mail check: <time dateTime={next.toISOString()}>{clock(next)}</time> (your local time)</p>}
    {live?.enabled && live.last_check_ok === false && <p className="inbox-live-warning">The last live mail check failed. Retrying automatically.</p>}
    {live?.enabled && last && <p>Last successful live check: <time dateTime={last.toISOString()}>{last.toLocaleString()}</time> (your local time)</p>}
    <p className="inbox-live-hint">Refresh Inbox reloads saved messages; live checks collect new mail. New messages may take a moment to appear after a check.</p>
  </section>
}
