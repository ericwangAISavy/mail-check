import { ArrowDownUp, Clock3 } from "lucide-react"
import type { ReactNode } from "react"
import type { JobAgeOrder, QueueCounts, QueueFocus, QueueStatus } from "@/lib/sourcing"

const STATUSES: { id: QueueStatus; label: string; count: (c: QueueCounts) => number }[] = [
  { id: "todo", label: "To do", count: c => c.todo },
  { id: "completed", label: "Completed", count: c => c.completed },
  { id: "expired", label: "Expired", count: c => c.expired },
  { id: "all", label: "All", count: c => c.all },
]

/** The order a queue view runs in, in words. */
export function queueOrder(status: QueueStatus, reverse = false, ageOrder?: JobAgeOrder) {
  if (ageOrder) return ageOrder === "asc" ? "Oldest first" : "Newest first"
  const oldestFirst = (status === "todo") !== reverse
  return status === "todo" && !reverse ? "Priority" : oldestFirst ? "Oldest first" : "Newest first"
}

/** Status tabs, the To do breakdown and the order toggle for one profile sheet. Shared by
 * the admin editor and the bidder viewer so both read the same queue. */
export default function SourcingQueueBar({ counts, status, focus, reverse = false, ageOrder, onStatus, onFocus, onReverse, disabled = false, end, below }: {
  counts: QueueCounts; status: QueueStatus; focus: QueueFocus | null; reverse?: boolean; ageOrder?: JobAgeOrder
  onStatus: (status: QueueStatus) => void; onFocus: (focus: QueueFocus | null) => void; onReverse?: (reverse: boolean) => void
  disabled?: boolean
  /** Table-level controls at the right end of the bar (Filter). */
  end?: ReactNode
  /** Attached under the bar, e.g. the search and date panel. */
  below?: ReactNode
}) {
  const pill = (id: QueueFocus | null, label: string, value?: number) =>
    <button type="button" className={`sourcing-queue-pill${id === "expiring" ? " is-expiring" : ""}`} aria-pressed={focus === id} disabled={disabled || (id != null && !value && focus !== id)}
      onClick={() => onFocus(id)}>
      {id === "expiring" && <Clock3 size={13} aria-hidden="true" />}{label}{value != null && <span>{value.toLocaleString()}</span>}
    </button>
  // One bar: status, the To do breakdown (only meaningful there), then Filter and order.
  return <div className="sourcing-queue">
    <div className="sourcing-queue-bar">
      <div className="sourcing-queue-tabs" role="group" aria-label="Job status">
        {STATUSES.map(item => <button key={item.id} type="button" aria-pressed={status === item.id} disabled={disabled}
          className="sourcing-queue-tab" onClick={() => onStatus(item.id)}>
          {item.label} <span className="sourcing-queue-count">{item.count(counts).toLocaleString()}</span>
        </button>)}
      </div>
      {status === "todo" && <div className="sourcing-queue-pills" role="group" aria-label="To do breakdown">
        {pill(null, "All pending")}
        {pill("new", "New today", counts.new_today)}
        {pill("carryover", "Carryover", counts.carryover)}
        {pill("expiring", "Expiring soon", counts.expiring)}
      </div>}
      <div className="sourcing-queue-end">
        {end}
        {onReverse && <button type="button" className="sourcing-queue-order" disabled={disabled} aria-pressed={reverse}
          title={ageOrder ? "Restore default sorting" : `Order: ${status === "todo" && !reverse ? "oldest first, closest to expiring on top" : queueOrder(status, reverse).toLowerCase()}. Click to reverse.`} onClick={() => onReverse(!reverse)}>
          <ArrowDownUp size={14} aria-hidden="true" />{queueOrder(status, reverse, ageOrder)}
        </button>}
      </div>
    </div>
    {below}
  </div>
}
