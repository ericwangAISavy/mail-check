import { useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Check, Palette } from "lucide-react"
import { api } from "@/lib/api"
import { useToast } from "@/components/common"

export type CalendarAccount = { id: number; label: string; email: string; calendar_color?: number | null }

/** Palette slots match the calendar's account-color-N styles (light and dark). */
export const CALENDAR_COLORS = ["Ocean", "Teal", "Violet", "Amber", "Rose", "Indigo", "Coral", "Lime"] as const

/** The automatic color (before any choice) stays exactly as it was. */
export const autoCalendarColor = (id: number) => Math.max(0, id - 1) % 6
export const calendarColorOf = (account: CalendarAccount) =>
  account.calendar_color != null && account.calendar_color >= 0 && account.calendar_color < CALENDAR_COLORS.length
    ? account.calendar_color : autoCalendarColor(account.id)

export default function CalendarColors({ accounts }: { accounts: CalendarAccount[] }) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState<number | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  const client = useQueryClient()
  const toast = useToast()
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => { if (!ref.current?.contains(event.target as Node)) setOpen(false) }
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false) }
    document.addEventListener("pointerdown", outside); document.addEventListener("keydown", escape)
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape) }
  }, [open])
  const choose = async (account: CalendarAccount, color: number | null) => {
    setSaving(account.id)
    try {
      await api.post(`/api/interviews/account-colors/${account.id}`, { color })
      await client.invalidateQueries({ queryKey: ["interviews"] })
    } catch (error) { toast(error instanceof Error ? error.message : "Could not change the color.", "error") }
    finally { setSaving(null) }
  }
  if (!accounts.length) return null
  return <div className="outlook-menu-anchor calendar-colors" ref={ref}>
    <button type="button" className="outlook-period" aria-expanded={open} aria-controls="calendar-colors-menu" onClick={() => setOpen(!open)}>
      <Palette size={14} aria-hidden="true" />Colors
    </button>
    {open && <div className="outlook-menu calendar-colors-menu" id="calendar-colors-menu" role="dialog" aria-label="Account colors">
      {accounts.map(account => {
        const current = calendarColorOf(account)
        return <div className="calendar-color-row" key={account.id}>
          <span className="calendar-color-account" title={account.email}>{account.label.includes("@") ? <><strong>{account.label.slice(0, account.label.indexOf("@"))}</strong><span>{account.label.slice(account.label.indexOf("@"))}</span></> : <strong>{account.label}</strong>}</span>
          <div className="calendar-swatches" role="radiogroup" aria-label={`Calendar color for ${account.label}`}>
            {CALENDAR_COLORS.map((name, index) => <button key={name} type="button" role="radio" aria-checked={current === index}
              aria-label={name} title={name} disabled={saving === account.id}
              className={`calendar-swatch swatch-${index}`} onClick={() => current !== index && void choose(account, index)}>
              {current === index && <Check size={12} strokeWidth={3} aria-hidden="true" />}
            </button>)}
          </div>
          {account.calendar_color != null
            ? <button type="button" className="calendar-color-reset" disabled={saving === account.id} onClick={() => void choose(account, null)}>Reset</button>
            : <span className="calendar-color-reset is-auto" aria-hidden="true">Auto</span>}
        </div>
      })}
    </div>}
  </div>
}
