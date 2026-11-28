import { isPageDate, usePageState } from "@/lib/page-state"
import { Fragment, lazy, Suspense, useEffect, useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Copy, Layers, Pencil, RefreshCw, SlidersHorizontal, UsersRound, Wallet } from "lucide-react"
import { api, request } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Loading, PageHeading, useToast } from "@/components/common"
import {copyPaymentReport,weeklyPaymentReport} from "@/lib/payment-report"
import PaymentRateEditor from "@/components/payment-rate-editor"
import { maskAccountLabel } from "@/lib/account-label"
import "./payments.css"

const BidderActivity = lazy(() => import("@/components/bidder-activity"))

type Assignment = { id: number; account_id: number; account_label: string; start_date: string; end_date: string | null }
type Payment = { revision?:number; amount_cents: number; application_count?: number; paid_at: string; note?: string }
type AccountBreakdown = {account_id:number|null;account_label:string;daily:number[];checked_daily:number[];total:number}
type DeductionRule = { minimum_daily: number; amount_cents: number }
type Bidder = { payment_visible?:boolean; below_minimum_daily?:boolean[]; gross_amount_cents?:number|null; deduction_daily?:number[]; deduction_total_cents?:number; account_breakdown?:AccountBreakdown[]; pay_per_bid?:string|null;adjustment_percent?:string;calculated_amount_cents?:number|null;payable_amount_cents?:number|null;amount_override_cents?:number|null;override_application_count?:number|null;wallet_network?:string; wallet_address?:string; id: number; name: string; assignments: Assignment[]; daily: number[]; checked_daily?: number[]; total: number; application_total?: number; payment: Payment | null }
type Report = { payment_visible?:boolean; other_work_visible?:boolean; deduction_rule?: DeductionRule; week_start: string; week_end: string; today: string; timezone: string; currency: string; dates: string[]; daily: number[]; checked_daily?: number[]; unassigned: number; unallocated_daily?: number[]; bidders: Bidder[]; accounts: { id: number; label: string }[] }
const applicationTotal = (bidder: Bidder) => (bidder.checked_daily || []).reduce((sum, count) => sum + count, 0)
const money = (cents: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100)
const shortDate = (day: string) => new Date(day + "T12:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
const moveWeek = (day: string, delta: number) => { const date = new Date(day + "T12:00:00Z"); date.setUTCDate(date.getUTCDate() + delta); return date.toISOString().slice(0, 10) }

function CountPair({ checked, replies, showReplies = true, deduction = 0, minimum = 0, belowMinimum = false, future = false }: { checked: number; replies: number; showReplies?: boolean; deduction?: number; minimum?: number; belowMinimum?: boolean; future?: boolean }) {
  // An upcoming day has no activity yet; say so instead of showing a zero.
  if (future && !checked && !replies) return <span className="payment-future" title="Upcoming day">—</span>
  return <span className="payment-count-pair"><span className={`payment-checked-count${belowMinimum ? " payment-below-minimum" : ""}`} title={belowMinimum ? minimum ? `Below daily minimum of ${minimum}: ${money(deduction)} deduction` : "Below daily minimum" : "Checked applications"}>{checked.toLocaleString()}</span>{showReplies && <>{" / "}<span className="payment-reply-count" title="Confirmed applications">{replies.toLocaleString()}</span></>}</span>
}

const effectiveRule = (rule?: DeductionRule): DeductionRule => rule ?? { minimum_daily: 0, amount_cents: 0 }
const sameRule = (a: DeductionRule, b: DeductionRule) => a.minimum_daily === b.minimum_daily && a.amount_cents === b.amount_cents

function DeductionRuleEditor({ rule, onSaved }: { rule?: DeductionRule; onSaved?: () => void }) {
  const [minimum, setMinimum] = useState(String(rule?.minimum_daily ?? 0))
  const [amount, setAmount] = useState(((rule?.amount_cents ?? 0) / 100).toFixed(2))
  const [base, setBase] = useState(() => effectiveRule(rule))
  const [dirty, setDirty] = useState(false)
  const client = useQueryClient()
  const toast = useToast()
  const changedElsewhere = !sameRule(base, effectiveRule(rule))
  const loadSaved = () => {
    setMinimum(String(rule?.minimum_daily ?? 0))
    setAmount(((rule?.amount_cents ?? 0) / 100).toFixed(2))
    setBase(effectiveRule(rule))
    setDirty(false)
  }
  // Only report changes trigger synchronization; completing a save must not reload old cached values.
  useEffect(() => { if (!dirty) loadSaved() }, [rule?.minimum_daily, rule?.amount_cents])
  const save = useMutation({
    mutationFn: (draft: { minimum_daily: number; deduction_amount: string; expected_rule: DeductionRule }) => api.post("/api/payments/deduction-rule", draft),
    onSuccess: async (_result, draft) => {
      setBase({ minimum_daily: draft.minimum_daily, amount_cents: Math.round(Number(draft.deduction_amount) * 100) })
      setDirty(false)
      await client.invalidateQueries({ queryKey: ["payments"] })
      toast("Daily deduction rule saved.", "success")
      onSaved?.()
    },
    onError: (error: Error) => toast(error.message, "error"),
  })
  return <div className="payment-deduction-rule"><h2>Daily deduction rule</h2>
    {dirty && changedElsewhere && <p role="alert">The deduction rule changed elsewhere. Load it before saving.</p>}
    <form onSubmit={event => { event.preventDefault(); if (!save.isPending && !changedElsewhere) save.mutate({ minimum_daily: Number(minimum), deduction_amount: amount, expected_rule: base }) }}><label>Minimum daily checked applications<input type="number" min="0" max="100000" step="1" required value={minimum} disabled={save.isPending} onChange={event => { setMinimum(event.target.value); setDirty(true) }} /></label><label>Daily deduction (USD)<input type="number" min="0" max="1000000" step="0.01" required value={amount} disabled={save.isPending} onChange={event => { setAmount(event.target.value); setDirty(true) }} /></label><Button disabled={save.isPending || changedElsewhere}>{save.isPending ? "Saving…" : "Save deduction rule"}</Button>
    {dirty && changedElsewhere && <Button type="button" variant="outline" disabled={save.isPending} onClick={() => { loadSaved(); save.reset() }}>Load saved rule</Button>}</form>{save.error && <p role="alert" className="inline-error">{save.error.message}</p>}</div>
}


/** The reporting week as a readable range; the native date input opens on click and stays
 * labelled "Week of" for keyboard and assistive-technology users. */
function WeekPicker({ value, label, disabled, onChange }: { value: string; label: string; disabled?: boolean; onChange: (value: string) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const open = () => { const el = input.current; if (!el || disabled) return; try { el.showPicker() } catch { el.focus() } }
  return <span className="bm-week">
    <button type="button" className="bm-week-button" disabled={disabled} onClick={open} aria-describedby="bm-week-input"><CalendarDays size={15} aria-hidden="true" /><span>{label}</span><ChevronDown size={14} aria-hidden="true" /></button>
    <input ref={input} id="bm-week-input" className="bm-week-input" type="date" min="1971-01-01" max="2100-12-31" aria-label="Week of" disabled={disabled} value={value} onChange={e => { if (e.target.value) onChange(e.target.value) }} />
  </span>
}

/** Deduction policy: one summary line under the metrics; the editor opens in a popover. */
function DeductionPolicy({ rule }: { rule?: DeductionRule }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (event: Event) => { if (event instanceof KeyboardEvent ? event.key === "Escape" : !root.current?.contains(event.target as Node)) setOpen(false) }
    document.addEventListener("pointerdown", close); document.addEventListener("keydown", close)
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", close) }
  }, [open])
  const current = effectiveRule(rule)
  const summary = current.minimum_daily > 0 || current.amount_cents > 0
    ? `Minimum ${current.minimum_daily.toLocaleString()} ${current.minimum_daily === 1 ? "application" : "applications"} · ${money(current.amount_cents)} per day`
    : "No daily minimum or deduction"
  return <div className="bm-policy" ref={root}>
    <SlidersHorizontal size={15} aria-hidden="true" /><strong>Deduction policy</strong><span>{summary}</span>
    <Button variant="ghost" size="sm" className="bm-policy-edit" aria-expanded={open} aria-controls="bm-policy-editor" onClick={() => setOpen(!open)}><Pencil size={14} aria-hidden="true" />Edit policy</Button>
    {open && <div className="bm-popover" id="bm-policy-editor" role="dialog" aria-label="Edit deduction policy"><DeductionRuleEditor rule={rule} onSaved={() => setOpen(false)} /></div>}
  </div>
}

function groupByAccount(bidders: Bidder[], start: string, end: string) {
  const groups: { accounts: Set<number>; labels: string[]; bidders: Bidder[] }[] = []
  for (const bidder of bidders) {
    const active = bidder.assignments.filter(a => a.start_date <= end && (!a.end_date || a.end_date >= start))
    const group = { accounts: new Set(active.map(a => a.account_id)), labels: active.map(a => a.account_label), bidders: [bidder] }
    // Merge shared-account groups, including bidders with several accounts.
    for (let i = groups.length - 1; i >= 0; i--) {
      if (![...groups[i].accounts].some(id => group.accounts.has(id))) continue
      const [shared] = groups.splice(i, 1)
      shared.accounts.forEach(id => group.accounts.add(id))
      group.labels.push(...shared.labels)
      group.bidders.push(...shared.bidders)
      i = groups.length // Revisit groups connected through the newly merged accounts.
    }
    groups.push(group)
  }
  const nameOrder = (a: Bidder, b: Bidder) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }) || a.id - b.id
  const accountKey = (group: typeof groups[number]) => group.labels.slice().sort((a, b) => a.localeCompare(b))[0] || ""
  groups.forEach(group => group.bidders.sort(nameOrder))
  groups.sort((a, b) => Number(!a.accounts.size) - Number(!b.accounts.size) || accountKey(a).localeCompare(accountKey(b)) || nameOrder(a.bidders[0], b.bidders[0]))
  return groups.flatMap(group => group.bidders)
}

export default function PaymentsPage({ readOnly = false }: { readOnly?: boolean }) {
  const [week, setWeek] = usePageState("payments", "week", "", value => value === "" || isPageDate(value))
  const [selected, setSelected] = usePageState("payments", "selected", "", value => value === "" || /^[1-9]\d*$/.test(value))
  const [expandedAccounts,setExpandedAccounts]=useState<Set<number>>(new Set())
  const [paying, setPaying] = useState<number | null>(null)
  const [paymentEditSession,setPaymentEditSession]=useState(0)
  const [editingRate,setEditingRate]=useState<number|null>(null)
  const [reviewedCount,setReviewedCount]=useState<number|null>(null)
  const [reviewedRevision,setReviewedRevision]=useState(0)
  const [reviewedCalculated,setReviewedCalculated]=useState<number|null>(null)
  const [reviewedRule,setReviewedRule]=useState<DeductionRule>(() => effectiveRule())
  const [reportPreview,setReportPreview]=useState<{text:string;issues:string[]}|null>(null)
  const [copyError,setCopyError]=useState("")
  const [copying,setCopying]=useState(false)
  const client = useQueryClient()
  const toast = useToast()
  const query = useQuery({ queryKey: ["payments", week], queryFn: ({ signal }) => request<Report>(`/api/payments?refresh=false${week ? `&week=${week}` : ""}`, { signal }), refetchInterval: 30_000 })
  useEffect(() => {
    if (selected && query.data && !query.data.bidders.some(bidder => String(bidder.id) === selected)) setSelected("")
  }, [query.data, selected])
  useEffect(()=>{setReportPreview(null);setCopyError("")},[week,query.data])
  const mutation = useMutation({ mutationFn: ({ url, body }: { url: string; body: unknown }) => api.post(url, body), onSuccess: async () => { setPaying(null); await client.invalidateQueries({ queryKey: ["payments"] }); toast("Saved.", "success") } })
  const refresh = useMutation({mutationFn: () => api.post<{changed?: number}>("/api/payments/refresh", {week: query.data!.week_start, mode: "refresh"}), onSuccess: async (result) => {
    await Promise.all(["payments", "sourcing-index", "sourcing-search", "dashboard"].map(key => client.invalidateQueries({queryKey: [key]})))
    window.dispatchEvent(new Event("mailcheck:check-completed"))
    const found = Number(result?.changed) || 0
    toast(found ? `Week refreshed · ${found.toLocaleString()} new ${found === 1 ? "check" : "checks"}.` : "Week refreshed · no new matches.", "success")
  }, onError: (error: Error) => toast(error.message, "error")})
  const write = (url: string, body: unknown) => mutation.mutateAsync({ url, body })
  if (query.isPending) return <Loading label="Loading application totals…" />
  if (query.error) return <div className="page-wrap"><PageHeading title="Bidder management" /><p role="alert" className="inline-error">{query.error.message}</p><Button onClick={() => void query.refetch()}>Try again</Button></div>
  const data = query.data!
  const showPayments = !readOnly || data.payment_visible === true
  const bidders = groupByAccount(data.bidders.filter(b => !selected || b.id === Number(selected)), data.week_start, data.week_end)
  const replyDaily = selected ? data.dates.map((_, i) => bidders.reduce((sum, b) => sum + b.daily[i], 0)) : data.daily
  const daily = data.dates.map((_, i) => bidders.reduce((sum, b) => sum + (b.checked_daily?.[i] || 0), 0))
  const total = daily.reduce((sum, count) => sum + count, 0)
  const unallocated = selected ? data.dates.map(() => 0) : data.unallocated_daily || data.dates.map(() => 0)
  const unallocatedTotal = unallocated.reduce((sum, count) => sum + count, 0)
  const todayIndex = data.dates.indexOf(data.today)
  const closed = data.week_end < data.today
  const paymentBidder = data.bidders.find(b => b.id === paying)
  const paymentRuleChanged = !sameRule(reviewedRule, effectiveRule(data.deduction_rule))
  const paymentCalculationChanged = (paymentBidder?.calculated_amount_cents ?? null) !== reviewedCalculated
  const rateBidder = data.bidders.find(b => b.id === editingRate)
  const copyWeekly=async()=>{
    const result=weeklyPaymentReport(groupByAccount(data.bidders,data.week_start,data.week_end))
    setReportPreview(result);setCopyError("")
    if(result.issues.length||!result.text)return
    setCopying(true)
    try{await copyPaymentReport(result.text);toast("Weekly payment report copied.","success")}catch(error){setCopyError(error instanceof Error?error.message:"Could not copy the report.")}finally{setCopying(false)}
  }
  const range = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }).formatRange(new Date(data.week_start + "T12:00:00Z"), new Date(data.week_end + "T12:00:00Z"))
  const changeWeek = (value: string) => { setWeek(value); setPaying(null) }
  const controls = <div className="bm-controls" role="group" aria-label="Reporting period and bidder">
    <Button variant="ghost" size="icon" aria-label="Previous week" disabled={refresh.isPending} onClick={() => changeWeek(moveWeek(data.week_start, -7))}><ChevronLeft size={17} /></Button>
    <WeekPicker value={data.week_start} label={range} disabled={refresh.isPending} onChange={changeWeek} />
    <Button variant="ghost" size="icon" aria-label="Next week" disabled={refresh.isPending} onClick={() => changeWeek(moveWeek(data.week_start, 7))}><ChevronRight size={17} /></Button>
    <Button variant="outline" size="sm" disabled={refresh.isPending} onClick={() => changeWeek("")}>This week</Button>
    <span className="bm-select"><select aria-label="Bidder" value={selected} onChange={e => setSelected(e.target.value)}><option value="">All bidders</option>{data.bidders.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></span>
    {!readOnly && <Button variant="outline" size="icon" className="bm-refresh" aria-label="Refresh this week" title="Match this week’s confirmation emails to unchecked links" disabled={refresh.isPending} onClick={() => refresh.mutate()}><RefreshCw size={16} className={refresh.isPending ? "spin" : ""} /></Button>}
    <span className="sr-only">Monday–Sunday · America/Chicago</span>
  </div>
  return <div className="page-wrap payments-page bm-page">
    <PageHeading title="Bidder management" description={showPayments ? "" : "Your checked application activity."} action={controls} />
    <section className="bm-summary" aria-label="This week at a glance">
      <div className="bm-metrics">
        <div className="bm-metric"><CalendarDays aria-hidden="true" /><div><span>{todayIndex >= 0 ? "Checked today" : "Selected week"}</span><strong>{(todayIndex >= 0 ? daily[todayIndex] : total).toLocaleString()}</strong><small>{todayIndex >= 0 ? new Date(data.today + "T12:00:00Z").toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric", timeZone: "UTC" }) : range}</small></div></div>
        <div className="bm-metric"><Layers aria-hidden="true" /><div><span>Checked applications this week</span><strong>{total.toLocaleString()}</strong><small>{shortDate(data.week_start)} – {shortDate(data.week_end)}</small></div></div>
        {showPayments && <div className="bm-metric"><Wallet aria-hidden="true" /><div><span>Payments recorded</span><strong>{money(bidders.reduce((sum, b) => sum + (b.payment?.amount_cents || 0), 0))}</strong><small>{bidders.filter(b => b.payment).length} of {bidders.length} bidders</small></div></div>}
      </div>
      {!readOnly && <DeductionPolicy rule={data.deduction_rule} />}
    </section>
    {mutation.error && <p role="alert" className="inline-error">{mutation.error.message}</p>}
    {rateBidder&&!readOnly&&<PaymentRateEditor key={rateBidder.id} bidder={rateBidder} onClose={()=>setEditingRate(null)}/>}
    {paymentBidder && !readOnly && <Card className="payment-entry"><h2>{paymentBidder.payment?"Edit payment":"Record payment"} for {paymentBidder.name}</h2><p>{applicationTotal(paymentBidder)} checked applications · {shortDate(data.week_start)} – {shortDate(data.week_end)}. {paymentBidder.payment?"Saving changes updates the recorded amount and count to this week’s current total. Previous values stay in edit history; the original payment date is kept.":""}</p>
      {paymentBidder.calculated_amount_cents!=null&&<p>Calculated: ${paymentBidder.pay_per_bid} × {applicationTotal(paymentBidder)} × {(1+Number(paymentBidder.adjustment_percent??20)/100).toLocaleString()} = {money(paymentBidder.gross_amount_cents ?? paymentBidder.calculated_amount_cents)}{(paymentBidder.deduction_total_cents ?? 0) > 0 && <> − {money(paymentBidder.deduction_total_cents!)} deductions = {money(paymentBidder.calculated_amount_cents)}{paymentBidder.deduction_total_cents! > (paymentBidder.gross_amount_cents ?? 0) ? " (minimum payment $0.00)" : ""}</>}</p>}
      {paymentBidder.payment?.application_count != null && paymentBidder.payment.application_count !== applicationTotal(paymentBidder) && <p>Recorded count: {paymentBidder.payment.application_count}; current checked total: {applicationTotal(paymentBidder)}. Saved payment unchanged.</p>}
      {paymentBidder.override_application_count != null && paymentBidder.override_application_count !== applicationTotal(paymentBidder) && <p>Saved amount reviewed at {paymentBidder.override_application_count} count; current checked total: {applicationTotal(paymentBidder)}.</p>}
      {reviewedCount!==null&&reviewedCount!==applicationTotal(paymentBidder)&&<p role="alert">Counts changed while editing. Close and reopen to review the updated amount.</p>}
      {paymentRuleChanged && <p role="alert">Deduction rule changed while editing. Close and reopen to review the updated amount.</p>}
      {!paymentRuleChanged && paymentCalculationChanged && <p role="alert">Calculated amount changed while editing. Close and reopen to review the updated amount.</p>}
      <form key={`${paymentBidder.id}:${data.week_start}:${paymentEditSession}`} onSubmit={async e=>{e.preventDefault();if(paymentRuleChanged||paymentCalculationChanged||mutation.isPending||reviewedCount!==null&&reviewedCount!==applicationTotal(paymentBidder))return;const form=new FormData(e.currentTarget);const intent=(e.nativeEvent as SubmitEvent).submitter?.getAttribute("value")||"paid";try{await write(`/api/payments/bidders/${paymentBidder.id}/${paymentBidder.payment?"paid/edit":intent==="save"?"amount":"paid"}`,{week:data.week_start,expected_count:reviewedCount??applicationTotal(paymentBidder),expected_rule:reviewedRule,expected_calculated_amount_cents:reviewedCalculated,amount:String(form.get("amount")),...(paymentBidder.payment?{expected_revision:reviewedRevision}:{}),...(intent==="paid"?{note:form.get("note")}: {})})}catch{/* shown above */}}}>
        <label>Amount (USD)<input name="amount" type="number" min="0" max="1000000" step="0.01" defaultValue={paymentBidder.payable_amount_cents!=null?(paymentBidder.payable_amount_cents/100).toFixed(2):""} required/></label>
        <label>Reference or note (optional)<input name="note" maxLength={500} defaultValue={paymentBidder.payment?.note||""}/></label>
        {!paymentBidder.payment&&<Button name="intent" value="save" variant="outline" disabled={mutation.isPending||paymentRuleChanged||paymentCalculationChanged||reviewedCount!==null&&reviewedCount!==applicationTotal(paymentBidder)}>Save amount</Button>}
        <Button name="intent" value="paid" disabled={mutation.isPending||paymentRuleChanged||paymentCalculationChanged||reviewedCount!==null&&reviewedCount!==applicationTotal(paymentBidder)}>{paymentBidder.payment?"Save changes":"Record as paid"}</Button>
        {!paymentBidder.payment&&paymentBidder.amount_override_cents!=null&&<Button type="button" variant="outline" disabled={mutation.isPending||paymentRuleChanged||paymentCalculationChanged} onClick={()=>void write(`/api/payments/bidders/${paymentBidder.id}/amount`,{week:data.week_start,expected_count:reviewedCount??applicationTotal(paymentBidder),expected_rule:reviewedRule,expected_calculated_amount_cents:reviewedCalculated,amount:null})}>Use calculated amount</Button>}
        {paymentBidder.payment&&paymentBidder.calculated_amount_cents!=null&&<Button type="button" variant="outline" onClick={event=>{const input=event.currentTarget.form?.elements.namedItem("amount") as HTMLInputElement|null;if(input)input.value=(paymentBidder.calculated_amount_cents!/100).toFixed(2)}}>Use calculated amount</Button>}
        <Button type="button" variant="ghost" onClick={()=>setPaying(null)}>Cancel</Button>
      </form></Card>}
    <Card className="payment-breakdown"><div className="payment-section-heading"><div><h2>Daily breakdown</h2><p>{closed ? "Completed week" : "Week in progress"} · {readOnly ? "Checked applications" : "Checked applications / confirmed applications"}</p></div><div className="payment-report-actions"><span>{bidders.length} bidders</span>{!readOnly&&<Button variant="outline" size="sm" disabled={!closed||copying||!data.bidders.length} title={closed ? "Copy final payment amounts for all bidders in this completed week" : "Available once this week ends — payments are final after Sunday"} onClick={()=>void copyWeekly()}><Copy size={15}/>{copying?"Copying…":"Copy weekly payment report"}</Button>}</div></div>
      {reportPreview&&!readOnly&&<div className="payment-report-preview"><h3>Payment report · {shortDate(data.week_start)} – {shortDate(data.week_end)}</h3>{reportPreview.issues.length>0&&<div role="alert"><p>Nothing copied. Complete these details first:</p><ul>{reportPreview.issues.map(issue=><li key={issue}>{issue}</li>)}</ul><a href="/accounts#bidder-management">Manage bidder wallets on Accounts</a></div>}{copyError&&<p role="alert">{copyError}</p>}{reportPreview.text&&<label>Weekly payment report<textarea aria-label="Weekly payment report" readOnly rows={Math.max(3,data.bidders.length+2)} value={reportPreview.text} onFocus={event=>event.currentTarget.select()}/></label>}<Button size="sm" variant="ghost" onClick={()=>{setReportPreview(null);setCopyError("")}}>Close report</Button></div>}
      {!data.bidders.length ? <div className="payment-empty"><UsersRound size={32} /><h3>No bidders yet</h3><p>{readOnly ? "An admin needs to add bidders and assign their accounts." : <a href="/accounts#bidder-management">Add bidders and assign their accounts on Accounts.</a>}</p></div> : <div className="payment-table-scroll"><table className="payment-table"><thead><tr><th scope="col">Bidder / accounts</th>{data.dates.map(day => <th scope="col" key={day} className={day === data.today ? "payment-today" : ""}><span>{new Date(day + "T12:00:00Z").toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" })}, {shortDate(day)}</span></th>)}<th scope="col">Week total</th>{showPayments && <th scope="col">Payment<small>Before / after deductions</small></th>}</tr></thead><tbody>{bidders.map(b => {
        const expanded=expandedAccounts.has(b.id)
        return <Fragment key={b.id}><tr><th scope="row">{b.account_breakdown?.length?<button className="payment-account-toggle" type="button" aria-label={`${expanded?"Hide":"Show"} accounts for ${b.name}`} aria-expanded={expanded} onClick={()=>setExpandedAccounts(previous=>{const next=new Set(previous);next.has(b.id)?next.delete(b.id):next.add(b.id);return next})}>{expanded?<ChevronDown size={15}/>:<ChevronRight size={15}/>}<strong>{b.name}</strong></button>:<strong>{b.name}</strong>}<small className="payment-row-total">{applicationTotal(b).toLocaleString()} checked this week</small></th>{b.daily.map((count, i) => <td key={data.dates[i]} className={data.dates[i] === data.today ? "payment-today" : ""}><CountPair showReplies={!readOnly} checked={b.checked_daily?.[i] || 0} replies={count} deduction={b.deduction_daily?.[i]} minimum={data.deduction_rule?.minimum_daily} belowMinimum={b.below_minimum_daily?.[i]} future={data.dates[i] > data.today} /></td>)}<td className="payment-total">{applicationTotal(b).toLocaleString()}</td>{showPayments && <td>{readOnly && b.payment_visible === false ? <span aria-label="Payment hidden">—</span> : <><span className="payment-amount-pair" aria-label="Before / after deductions"><span>{(b.gross_amount_cents ?? b.calculated_amount_cents)!=null?money((b.gross_amount_cents ?? b.calculated_amount_cents)!):b.pay_per_bid==null?"Rate not set":"Unavailable"}</span><span aria-hidden="true"> / </span>{readOnly?<span className="payment-confirmed">{b.calculated_amount_cents!=null?money(b.calculated_amount_cents):"Unavailable"}</span>:<button type="button" className="payment-confirmed payment-confirmed-edit" disabled={!closed} aria-label={`Edit confirmed payment for ${b.name}${b.calculated_amount_cents!=null?`, ${money(b.calculated_amount_cents!)}`:""}`} title={closed?"Click to edit the confirmed amount":"Editable after the week ends"} onClick={()=>{mutation.reset();setPaymentEditSession(session=>session+1);setReviewedCount(applicationTotal(b));setReviewedCalculated(b.calculated_amount_cents??null);setReviewedRule(effectiveRule(data.deduction_rule));setReviewedRevision(b.payment?.revision||0);setPaying(b.id)}}>{b.calculated_amount_cents!=null?money(b.calculated_amount_cents!):"Unavailable"}</button>}</span>{readOnly&&<div className="payment-recorded-status"><small>{b.payment?`Recorded paid: ${money(b.payment.amount_cents)}`:b.payable_amount_cents!=null&&b.payable_amount_cents!==b.calculated_amount_cents?`Saved amount: ${money(b.payable_amount_cents)} · Not recorded as paid`:"Not recorded as paid"}</small></div>}{b.calculated_amount_cents==null&&b.pay_per_bid==null&&<div className="payment-missing-rate">{readOnly?<small>Ask your admin to set a payment rate.</small>:<Button type="button" size="sm" variant="ghost" aria-label={`Set payment rate for ${b.name}`} onClick={()=>{setPaying(null);setEditingRate(b.id)}}>Set rate</Button>}</div>}</>}</td>}</tr>
          {expanded&&b.account_breakdown?.map(account=><tr className="payment-account-detail" key={account.account_id??"removed"} aria-label={`${b.name} · ${maskAccountLabel(account.account_label)}`}><th scope="row"><span>{maskAccountLabel(account.account_label)}</span></th>{account.daily.map((count,i)=><td key={data.dates[i]} className={data.dates[i]===data.today?"payment-today":""}><CountPair showReplies={!readOnly} checked={account.checked_daily[i] || 0} replies={count} future={data.dates[i] > data.today} /></td>)}<td className="payment-total">{account.total.toLocaleString()}</td>{showPayments && <td><small>{readOnly && b.payment_visible === false ? "—" : "Included in bidder payment"}</small></td>}</tr>)}
        </Fragment>
      })}
      {!readOnly && unallocatedTotal > 0 && <tr className="payment-unallocated"><th scope="row">Unallocated confirmed applications</th>{unallocated.map((count, i) => <td key={data.dates[i]}><CountPair showReplies={!readOnly} checked={0} replies={count} /></td>)}<td className="payment-total">0</td>{showPayments && <td>Awaiting checked links</td>}</tr>}
      </tbody><tfoot><tr><th scope="row">Total</th>{daily.map((count, i) => <td key={i} className={data.dates[i] === data.today ? "payment-today" : ""}><CountPair showReplies={!readOnly} checked={count} replies={replyDaily[i]} future={data.dates[i] > data.today} /></td>)}<td>{total.toLocaleString()}</td>{showPayments && <td />}</tr></tfoot></table></div>}
    </Card>
    {!readOnly && data.unassigned > 0 && <p className="payment-unassigned">{data.unassigned.toLocaleString()} confirmed applications this week have no bidder assignment. <a href="/accounts#bidder-management">Assign their accounts with the correct dates on Accounts</a> to include them.</p>}
    <Suspense fallback={<Loading label="Loading bidder activity…" />}>
      <BidderActivity visibilityKey={readOnly ? String(Boolean(data.other_work_visible)) : "admin"} allowAccounts={!readOnly || !data.other_work_visible} readOnly={readOnly} week={data.week_start} selected={selected} onSelect={setSelected} />
    </Suspense>

  </div>
}
