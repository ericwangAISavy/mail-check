import { useEffect, useState, type ReactNode } from "react"
import { Info } from "lucide-react"
import type { TriageData } from "@/lib/types"
import { parseStamp, timeAgo } from "@/lib/relative-time"

/** Real-time recovery checks run every 2 minutes; older than this is late. */
const DELAYED_AFTER_SECONDS = 5 * 60
const HINT = "Refresh Inbox reloads saved messages. New mail is collected automatically and appears here on its own; it may take a moment after it arrives. Hover the time for the exact update time."

type Tone = "live" | "busy" | "warn" | "off"

/** One compact, colour-coded line: a state pill, how fresh the Inbox is, and details on hover. */
export function InboxRefreshStatus({ schedule, unavailable = false }: { schedule: TriageData["check_schedule"]; unavailable?: boolean }) {
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") setNow(Date.now()) }, 1000)
    return () => window.clearInterval(timer)
  }, [])
  const live = schedule?.live
  // When every assigned mailbox was last collected (full check, real-time or live poll).
  const updated = parseStamp(live?.updated_at ?? live?.last_checked_at)
  const fresh = updated ? <time dateTime={updated.toISOString()} title={updated.toLocaleString()}>{timeAgo(updated, now)}</time> : null
  const updatedLine = fresh ? <> · Updated {fresh}</> : null
  const late = updated ? (now - updated.getTime()) / 1000 > DELAYED_AFTER_SECONDS : false

  let tone: Tone
  let pill: string
  let detail: ReactNode
  if (unavailable) {
    tone = "warn"; pill = "Offline"; detail = "Connection interrupted — retrying automatically"
  } else if (live?.enabled) {
    if (live.running) {
      tone = "busy"; pill = "Checking"; detail = <>Checking for new mail…{updatedLine}</>
    } else if (live.last_check_ok === false) {
      tone = "warn"; pill = "Retrying"; detail = <>Last check failed — retrying automatically{updatedLine}</>
    } else if (late) {
      tone = "warn"; pill = "Delayed"; detail = <>Updates are running late{updatedLine}</>
    } else if (schedule?.running) {
      tone = "busy"; pill = "Live"; detail = fresh ? <>Updated {fresh} · server is busy</> : "Server is busy — updates resume shortly"
    } else {
      tone = "live"; pill = "Live"; detail = fresh ? <>Updated {fresh}</> : "Waiting for the first update"
    }
  } else {
    tone = "off"; pill = "Off"
    detail = live?.disabled_reason || (!schedule ? "Update status unavailable" : !schedule.automatic ? "Automatic mail checks are off"
      : schedule.running ? "Server is processing updates" : "Mail updates automatically")
  }

  return <section className={`inbox-live-status tone-${tone}`} aria-label="Inbox update schedule">
    <span className="inbox-live-pill"><span className="inbox-live-dot" aria-hidden="true" />{pill}</span>
    <p role="status">{detail}</p>
    <span className="inbox-live-hint" role="img" aria-label={HINT} title={HINT}><Info size={14} aria-hidden="true" /></span>
  </section>
}
