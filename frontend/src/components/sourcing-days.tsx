import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { chicagoDay, offsetDay, type Snapshot } from "@/lib/sourcing";

export default function SourcingDays({
  day,
  onChange,
  disabled,
  snapshot,
  onAssign,
  canAssign,
  readOnly=false,
}: {
  day: string;
  onChange: (day: string) => void;
  disabled: boolean;
  snapshot: Snapshot | null;
  onAssign: () => void;
  canAssign: boolean;
  readOnly?:boolean;
}) {
  const counts = new Map<string, number>();
  snapshot?.rows.slice(1).forEach((row, index) => {
    if (row.some((cell, col) => snapshot.columns[col]?.kind !== "check" && String(cell.value).trim())) {
      const date = snapshot.row_dates?.[index + 1] || "undated";
      counts.set(date, (counts.get(date) || 0) + 1);
    }
  });
  return (
    <div className="sheet-days" aria-label="Daily jobs">
      <CalendarDays size={15} />
      <Button
        size="icon"
        variant="ghost"
        aria-label="Previous day"
        disabled={disabled || day === "undated"}
        onClick={() => onChange(offsetDay(day, -1))}
      >
        <ChevronLeft size={16} />
      </Button>
      <input
        type="date"
        aria-label="Job date"
        value={day === "undated" ? "" : day}
        disabled={disabled}
        onChange={(e) => {
          if (e.target.value && e.target.value.length === 10)
            onChange(e.target.value);
        }}
      />
      <Button
        size="icon"
        variant="ghost"
        aria-label="Next day"
        disabled={disabled || day === "undated"}
        onClick={() => onChange(offsetDay(day, 1))}
      >
        <ChevronRight size={16} />
      </Button>
      <Button
        size="sm"
        variant="ghost"
        disabled={disabled}
        aria-pressed={day === chicagoDay()}
        onClick={() => onChange(chicagoDay())}
      >
        Today
      </Button>
      <Button
        size="sm"
        variant="ghost"
        disabled={disabled}
        aria-pressed={day === "undated"}
        onClick={() => onChange("undated")}
      >
        Undated{counts.get("undated") ? ` (${counts.get("undated")})` : ""}
      </Button>
      <select
        aria-label="Saved job days"
        value=""
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="" disabled>
          History
        </option>
        {[...counts.keys()]
          .filter((d) => d !== "undated")
          .sort()
          .reverse()
          .map((d) => (
            <option key={d} value={d}>
              {d} · {counts.get(d)} jobs
            </option>
          ))}
      </select>
      <span className="sheet-day-count">
        {counts.get(day) || 0} jobs · Chicago
      </span>
      {!readOnly && <Button
        className="sheet-assign-date"
        size="sm"
        variant="ghost"
        disabled={disabled || !canAssign}
        onClick={onAssign}
      >
        Assign date
      </Button>}
    </div>
  );
}
