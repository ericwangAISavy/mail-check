import { Clock3 } from "lucide-react"
import type { QueueCounts, QueueFocus, QueueStatus } from "@/lib/sourcing"

const STATUSES: { id: QueueStatus; label: string; count: (c: QueueCounts) => number }[] = [
  { id: "todo", label: "To do", count: c => c.todo },
  { id: "completed", label: "Completed", count: c => c.completed },
  { id: "expired", label: "Expired", count: c => c.expired },
  { id: "all", label: "All", count: c => c.all },
]

/** Status tabs and the To do breakdown for one profile sheet. Shared by the admin
 * editor and the bidder viewer so both read the same queue. */
export default function SourcingQueueBar({ counts, status, focus, onStatus, onFocus, disabled = false }: {
  counts: QueueCounts; status: QueueStatus; focus: QueueFocus | null
  onStatus: (status: QueueStatus) => void; onFocus: (focus: QueueFocus | null) => void; disabled?: boolean
}) {
  const metric = (id: QueueFocus, label: string, value: number) =>
    <button type="button" className={`sourcing-queue-metric is-${id}`} aria-pressed={status === "todo" && focus === id} disabled={disabled || (!value && focus !== id)}
      onClick={() => { onStatus("todo"); onFocus(focus === id && status === "todo" ? null : id) }}>
      {id === "expiring" && <Clock3 size={13} aria-hidden="true" />}{label} <strong>{value}</strong>
    </button>
  return <div className="sourcing-queue">
    <div className="sourcing-queue-tabs" role="group" aria-label="Job status">
      {STATUSES.map(item => <button key={item.id} type="button" aria-pressed={status === item.id} disabled={disabled}
        className="sourcing-queue-tab" onClick={() => { onStatus(item.id); onFocus(null) }}>
        {item.label} <span className="sourcing-queue-count">{item.count(counts)}</span>
      </button>)}
    </div>
    <div className="sourcing-queue-metrics" aria-label="To do breakdown">
      {metric("new", "New today", counts.new_today)}
      {metric("carryover", "Carryover", counts.carryover)}
      {metric("expiring", "Expiring soon", counts.expiring)}
    </div>
  </div>
}
