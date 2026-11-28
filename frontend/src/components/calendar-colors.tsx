import { useEffect, useId, useRef, useState, type CSSProperties, type KeyboardEvent } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Check, Palette, Pencil, RotateCcw, X } from "lucide-react"
import { api, getWorkspaceIdentityRevision } from "@/lib/api"
import type { CalendarAccount, InterviewData } from "@/lib/types"
import { useToast } from "@/components/common"

// The indices are stored by the server. Cyan replaces Ocean, Azure replaces Indigo, and Sage replaces Lime.
export const CALENDAR_COLORS = ["Cyan", "Teal", "Violet", "Amber", "Rose", "Azure", "Coral", "Sage"] as const
const paletteOrder = [5, 1, 2, 3, 4, 0, 6, 7]
const paletteDirection: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -1, ArrowDown: 1 }
export const autoCalendarColor = (id: number) => Math.max(0, id - 1) % 6
const validColor = (value?: number | null): value is number =>
  value != null && Number.isInteger(value) && value >= 0 && value < CALENDAR_COLORS.length
export const calendarColorOf = (account: CalendarAccount) =>
  validColor(account.calendar_color) ? account.calendar_color :
    validColor(account.calendar_default_color) ? account.calendar_default_color : autoCalendarColor(account.id)

function panelPosition(trigger: HTMLElement): CSSProperties {
  const rect = trigger.getBoundingClientRect()
  const width = Math.min(350, window.innerWidth - 24)
  const left = Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12))
  const below = window.innerHeight - rect.bottom - 20
  const above = rect.top - 20
  return below < 320 && above > below
    ? { width, left, bottom: window.innerHeight - rect.top + 8, maxHeight: above }
    : { width, left, top: rect.bottom + 8, maxHeight: below }
}

export default function CalendarColors({ accounts }: { accounts: CalendarAccount[] }) {
  const [position, setPosition] = useState<CSSProperties | null>(null)
  const [editing, setEditing] = useState<number | undefined>()
  const [pending, setPending] = useState<{ id: number; color: number | null } | null>(null)
  const saving = useRef(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const picker = useRef<HTMLDivElement>(null)
  const menuId = useId(), headingId = useId(), hintId = useId()
  const client = useQueryClient()
  const toast = useToast()
  const open = position !== null
  const account = accounts.find(item => item.id === editing) ?? accounts[0]

  useEffect(() => {
    if (!open) return
    panel.current?.querySelector<HTMLButtonElement>(".calendar-color-row[aria-pressed='true']")?.focus()
    const outside = (event: PointerEvent) => {
      const target = event.target as Node
      if (!panel.current?.contains(target) && !trigger.current?.contains(target)) setPosition(null)
    }
    const resize = () => { if (trigger.current) setPosition(panelPosition(trigger.current)) }
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return
      event.stopPropagation()
      setPosition(null)
      trigger.current?.focus()
    }
    document.addEventListener("pointerdown", outside)
    document.addEventListener("keydown", escape, true)
    window.addEventListener("resize", resize)
    window.addEventListener("scroll", resize, true)
    return () => {
      document.removeEventListener("pointerdown", outside)
      document.removeEventListener("keydown", escape, true)
      window.removeEventListener("resize", resize)
      window.removeEventListener("scroll", resize, true)
    }
  }, [open])

  if (!account) return null
  const close = () => { setPosition(null); trigger.current?.focus() }
  const displayed = (item: CalendarAccount) => pending?.id === item.id ? { ...item, calendar_color: pending.color } : item
  const current = calendarColorOf(displayed(account))
  const hasChoice = validColor(displayed(account).calendar_color)
  const choose = async (color: number | null) => {
    if (saving.current || color !== null && color === current) return
    saving.current = true
    setPending({ id: account.id, color })
    const identity = getWorkspaceIdentityRevision()
    const sameWorkspace = () => identity === getWorkspaceIdentityRevision()
    const queryKey = ["interviews", "list"]
    const update = (next?: number | null) => client.setQueriesData<InterviewData>({ queryKey }, old => old ? {
      ...old, accounts: old.accounts.map(item => item.id === account.id ? { ...item, calendar_color: next } : item),
    } : old)
    try {
      await client.cancelQueries({ queryKey })
      if (!sameWorkspace()) return
      update(color)
      await api.post(`/api/interviews/account-colors/${account.id}`, { color })
      void client.invalidateQueries({ queryKey })
    } catch (error) {
      if (sameWorkspace()) {
        update(account.calendar_color)
        toast(error instanceof Error ? error.message : "Could not change the color.", "error")
      }
    } finally {
      saving.current = false
      setPending(null)
    }
  }
  const selectWithKey = (event: KeyboardEvent<HTMLButtonElement>, color: number) => {
    const index = paletteOrder.indexOf(color)
    const movement = paletteDirection[event.key]
    if (movement === undefined && event.key !== "Home" && event.key !== "End") return
    event.preventDefault()
    if (saving.current) return
    const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? paletteOrder.length - 1
      : (index + movement! + paletteOrder.length) % paletteOrder.length
    const next = paletteOrder[nextIndex]
    picker.current?.querySelector<HTMLButtonElement>(`[data-swatch="${next}"]`)?.focus()
    void choose(next)
  }

  return <div className="outlook-menu-anchor calendar-colors">
    <button ref={trigger} type="button" className="outlook-period" aria-expanded={open}
      aria-haspopup="dialog" aria-controls={open ? menuId : undefined}
      onClick={event => setPosition(open ? null : panelPosition(event.currentTarget))}>
      <Palette size={14} aria-hidden="true" />Colors
    </button>
    {open && <div ref={panel} className="calendar-colors-menu" id={menuId} role="dialog"
      aria-labelledby={headingId} aria-describedby={hintId} style={position}>
      <header className="calendar-color-header">
        <h3 id={headingId}>Account colors</h3>
        <button type="button" className="calendar-color-close" onClick={close} aria-label="Close account colors"><X size={16} /></button>
        <p id={hintId}>Choose how applicant accounts appear on the interview calendar.</p>
      </header>
      <div className="calendar-color-accounts" role="group" aria-label="Applicant accounts">
        {accounts.map(item => <button key={item.id} type="button" className="calendar-color-row"
          aria-pressed={account.id === item.id} aria-label={`Edit color for ${item.label}`}
          onClick={() => setEditing(item.id)}>
          <span className={`calendar-color-chip account-color-${calendarColorOf(displayed(item))}`} aria-hidden="true" />
          <span className="calendar-color-account" title={item.label === item.email ? item.email : `${item.label} · ${item.email}`}>
            <strong>{item.label}</strong>
            {item.label.toLowerCase() !== item.email.toLowerCase() && <small>{item.email}</small>}
          </span>
          <Pencil className="calendar-color-edit" size={14} aria-hidden="true" />
        </button>)}
      </div>
      <div className="calendar-color-palette">
        <div className="calendar-palette-heading"><strong>Color palette</strong><span>{CALENDAR_COLORS[current]}</span></div>
        <div className="calendar-swatches" ref={picker} role="radiogroup" aria-label={`Calendar color for ${account.label}`}>
          {paletteOrder.map(index => {
            const name = CALENDAR_COLORS[index]
            return <button key={index} type="button" role="radio" aria-checked={current === index}
              aria-label={name} title={name} tabIndex={current === index ? 0 : -1} aria-disabled={!!pending}
              data-swatch={index} className={`calendar-swatch account-color-${index}`}
              onKeyDown={event => selectWithKey(event, index)} onClick={() => void choose(index)}>
              <span>{current === index && <Check size={14} strokeWidth={2.75} aria-hidden="true" />}</span>
            </button>
          })}
        </div>
        <button type="button" className="calendar-color-reset" disabled={!hasChoice || !!pending}
          onClick={() => void choose(null)}><RotateCcw size={13} aria-hidden="true" />Reset to default</button>
      </div>
    </div>}
  </div>
}
