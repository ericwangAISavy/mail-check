import { useEffect, useState } from "react";
import { Clock3 } from "lucide-react";
import { serverNow } from "@/lib/api";
import { QUEUE_LIFETIME_MS } from "@/lib/sourcing";

const minute = 60_000;
const hour = 60 * minute;
const day = 24 * hour;
const timestamp = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/Chicago", year: "numeric", month: "short", day: "numeric",
  hour: "numeric", minute: "2-digit", second: "2-digit", timeZoneName: "short",
});

export function useSourcingAgeClock(enabled = true) {
  const [now, setNow] = useState(serverNow);
  useEffect(() => {
    if (!enabled) return;
    const update = () => setNow(serverNow());
    update();
    const timer = window.setInterval(update, minute);
    return () => window.clearInterval(timer);
  }, [enabled]);
  return now;
}

export function SourcingJobAge({ added, now, expiring }: { added: number | null; now: number; expiring: boolean }) {
  const elapsed = added == null ? 0 : Math.max(0, now - added);
  const label = elapsed >= day ? `${Math.floor(elapsed / day)}d`
    : elapsed >= hour ? `${Math.floor(elapsed / hour)}h`
    : elapsed >= minute ? `${Math.floor(elapsed / minute)}m` : "Now";
  const description = added == null ? "Availability timestamp unavailable" : `Added ${timestamp.format(added)}`;
  const expires = added == null ? NaN : added + QUEUE_LIFETIME_MS;
  const expiry = expiring && Number.isFinite(new Date(expires).getTime()) ? `Expires ${timestamp.format(expires)}` : null;
  const details = expiry ? `${description} · ${expiry}` : description;
  return <span className={`sourcing-job-age${expiring ? " is-expiring" : ""}`} title={details}>
    {expiring && <Clock3 size={12} role="img" aria-label="Expiring soon" />}
    {added == null ? <span aria-hidden="true">—</span> : <time dateTime={new Date(added).toISOString()}>{label}</time>}
    <span className="sr-only">{details}</span>
  </span>;
}
