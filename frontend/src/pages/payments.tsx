import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, ArrowRight, Banknote, CalendarDays, CheckCircle2, Copy, RefreshCw, UsersRound } from "lucide-react"
import { api, request } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Loading, PageHeading, useToast } from "@/components/common"
import {copyPaymentReport,weeklyPaymentReport} from "@/lib/payment-report"
import BidderActivity from "@/components/bidder-activity"
import "./payments.css"

type Assignment = { id: number; account_id: number; account_label: string; start_date: string; end_date: string | null }
type Payment = { revision?:number; amount_cents: number; application_count: number; paid_at: string; note: string }
type Bidder = { pay_per_bid?:string|null;adjustment_percent?:string;calculated_amount_cents?:number|null;payable_amount_cents?:number|null;amount_override_cents?:number|null;override_application_count?:number|null;wallet_network?:string; wallet_address?:string; id: number; name: string; assignments: Assignment[]; daily: number[]; checked_daily?: number[]; total: number; application_total?: number; payment: Payment | null }
type Report = { week_start: string; week_end: string; today: string; timezone: string; currency: string; dates: string[]; daily: number[]; checked_daily?: number[]; unassigned: number; unallocated_daily?: number[]; bidders: Bidder[]; accounts: { id: number; label: string }[] }
const applicationTotal = (bidder: Bidder) => bidder.daily.reduce((sum, count) => sum + count, 0)
const confirmedAmount = (bidder:Bidder) => bidder.payment?.amount_cents ?? bidder.amount_override_cents ?? bidder.calculated_amount_cents ?? bidder.payable_amount_cents
const money = (cents: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100)
const shortDate = (day: string) => new Date(day + "T12:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
const moveWeek = (day: string, delta: number) => { const date = new Date(day + "T12:00:00Z"); date.setUTCDate(date.getUTCDate() + delta); return date.toISOString().slice(0, 10) }

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
  const [week, setWeek] = useState("")
  const [selected, setSelected] = useState("")
  const [paying, setPaying] = useState<number | null>(null)
  const [reviewedCount,setReviewedCount]=useState<number|null>(null)
  const [reviewedRevision,setReviewedRevision]=useState(0)
  const [reportPreview,setReportPreview]=useState<{text:string;issues:string[]}|null>(null)
  const [copyError,setCopyError]=useState("")
  const [copying,setCopying]=useState(false)
  const client = useQueryClient()
  const toast = useToast()
  const query = useQuery({ queryKey: ["payments", week], queryFn: () => request<Report>(`/api/payments${week ? `?week=${week}` : ""}`), refetchInterval: 30_000 })
  useEffect(()=>{setReportPreview(null);setCopyError("")},[week,query.data])
  const mutation = useMutation({ mutationFn: ({ url, body }: { url: string; body: unknown }) => api.post(url, body), onSuccess: async () => { setPaying(null); await client.invalidateQueries({ queryKey: ["payments"] }); toast("Saved.", "success") } })
  const refresh = useMutation({mutationFn: (mode: "refresh" | "rebuild") => api.post("/api/payments/refresh", {week: query.data!.week_start, mode}), onSuccess: async () => {
    await Promise.all(["payments", "sourcing-index", "sourcing-search", "dashboard"].map(key => client.invalidateQueries({queryKey: [key]})))
    window.dispatchEvent(new Event("mailcheck:check-completed"))
    toast("Selected week refreshed. Confirmation estimates and checked applications recalculated.", "success")
  }, onError: (error: Error) => toast(error.message, "error")})
  const write = (url: string, body: unknown) => mutation.mutateAsync({ url, body })
  if (query.isPending) return <Loading label="Loading application totals…" />
  if (query.error) return <div className="page-wrap"><PageHeading title="Bidder management" /><p role="alert" className="inline-error">{query.error.message}</p><Button onClick={() => void query.refetch()}>Try again</Button></div>
  const data = query.data!
  const bidders = groupByAccount(data.bidders.filter(b => !selected || b.id === Number(selected)), data.week_start, data.week_end)
  const estimatedDaily = selected ? data.dates.map((_, i) => bidders.reduce((sum, b) => sum + b.daily[i], 0)) : data.daily
  const daily = data.dates.map((_, i) => bidders.reduce((sum, b) => sum + (b.checked_daily?.[i] || 0), 0))
  const total = estimatedDaily.reduce((sum, count) => sum + count, 0)
  const unallocated = selected ? data.dates.map(() => 0) : data.unallocated_daily || data.dates.map(() => 0)
  const unallocatedTotal = unallocated.reduce((sum, count) => sum + count, 0)
  const todayIndex = data.dates.indexOf(data.today)
  const closed = data.week_end < data.today
  const paymentBidder = data.bidders.find(b => b.id === paying)
  const copyWeekly=async()=>{
    const result=weeklyPaymentReport(groupByAccount(data.bidders,data.week_start,data.week_end))
    setReportPreview(result);setCopyError("")
    if(result.issues.length||!result.text)return
    setCopying(true)
    try{await copyPaymentReport(result.text);toast("Weekly payment report copied.","success")}catch(error){setCopyError(error instanceof Error?error.message:"Could not copy the report.")}finally{setCopying(false)}
  }
  return <div className="page-wrap payments-page">
    <PageHeading title="Bidder management" description="Weekly totals sum daily estimated confirmations across assigned accounts." action={!readOnly && <div className="payment-report-actions"><Button variant="outline" disabled={refresh.isPending} title="Update matches and totals for this week while preserving existing checks" onClick={() => refresh.mutate("refresh")}><RefreshCw size={16} className={refresh.isPending ? "spin" : ""} />Refresh this week</Button><Button variant="outline" disabled={refresh.isPending} title="Rebuild automatic matches for this week, removing stale automatic checks. Manual checks and saved payments are preserved." onClick={() => refresh.mutate("rebuild")}><RefreshCw size={16} className={refresh.isPending ? "spin" : ""} />Fully rebuild this week</Button></div>} />
    <Card className="payment-controls">
      <div className="payment-week"><Button variant="ghost" size="icon" aria-label="Previous week" disabled={refresh.isPending} onClick={() => { setWeek(moveWeek(data.week_start, -7)); setPaying(null) }}><ArrowLeft /></Button><label><span>Week of</span><input type="date" min="1971-01-01" max="2100-12-31" aria-label="Week of" disabled={refresh.isPending} value={data.week_start} onChange={e => { if (e.target.value) { setWeek(e.target.value); setPaying(null) } }} /></label><Button variant="ghost" size="icon" aria-label="Next week" disabled={refresh.isPending} onClick={() => { setWeek(moveWeek(data.week_start, 7)); setPaying(null) }}><ArrowRight /></Button><Button variant="outline" size="sm" disabled={refresh.isPending} onClick={() => { setWeek(""); setPaying(null) }}>This week</Button></div>
      <label className="payment-bidder-filter"><span>Bidder</span><select value={selected} onChange={e => setSelected(e.target.value)}><option value="">All bidders</option>{data.bidders.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>
      <span className="payment-timezone">Monday–Sunday · America/Chicago</span>
    </Card>
    <div className="payment-overview">
      <Card><CalendarDays aria-hidden="true" /><div><span>{todayIndex >= 0 ? "Today" : "Selected week"}</span><strong>{(todayIndex >= 0 ? estimatedDaily[todayIndex] : total).toLocaleString()}</strong><small>{todayIndex >= 0 ? shortDate(data.today) : `${shortDate(data.week_start)} – ${shortDate(data.week_end)}`}</small></div></Card>
      <Card><CheckCircle2 aria-hidden="true" /><div><span>Estimated confirmations this week</span><strong>{total.toLocaleString()}</strong><small>{shortDate(data.week_start)} – {shortDate(data.week_end)}</small></div></Card>
      <Card><Banknote aria-hidden="true" /><div><span>Payments recorded</span><strong>{money(bidders.reduce((sum, b) => sum + (b.payment?.amount_cents || 0), 0))}</strong><small>{bidders.filter(b => b.payment).length} of {bidders.length} bidders</small></div></Card>
    </div>
    {mutation.error && <p role="alert" className="inline-error">{mutation.error.message}</p>}
    {paymentBidder && !readOnly && <Card className="payment-entry"><h2>{paymentBidder.payment?"Edit payment":"Record payment"} for {paymentBidder.name}</h2><p>{applicationTotal(paymentBidder)} estimated confirmations · {shortDate(data.week_start)} – {shortDate(data.week_end)}. {paymentBidder.payment?"Saving changes updates the recorded amount and count to this week’s current total. Previous values stay in edit history; the original payment date is kept.":"Save an amount for the report, or record a payment you made. Neither action transfers money."}</p>
      {paymentBidder.calculated_amount_cents!=null&&<p>Calculated: ${paymentBidder.pay_per_bid} × {applicationTotal(paymentBidder)} × {(1+Number(paymentBidder.adjustment_percent??20)/100).toLocaleString()} = {money(paymentBidder.calculated_amount_cents)}</p>}
      {reviewedCount!==null&&reviewedCount!==applicationTotal(paymentBidder)&&<p role="alert">Counts changed while editing. Close and reopen to review the updated amount.</p>}
      <form key={`${paymentBidder.id}:${data.week_start}`} onSubmit={async e=>{e.preventDefault();const form=new FormData(e.currentTarget);const intent=(e.nativeEvent as SubmitEvent).submitter?.getAttribute("value")||"paid";try{await write(`/api/payments/bidders/${paymentBidder.id}/${paymentBidder.payment?"paid/edit":intent==="save"?"amount":"paid"}`,{week:data.week_start,expected_count:reviewedCount??applicationTotal(paymentBidder),amount:String(form.get("amount")),...(paymentBidder.payment?{expected_revision:reviewedRevision}:{}),...(intent==="paid"?{note:form.get("note")}: {})})}catch{/* shown above */}}}>
        <label>Amount (USD)<input name="amount" type="number" min="0" max="1000000" step="0.01" defaultValue={paymentBidder.payable_amount_cents!=null?(paymentBidder.payable_amount_cents/100).toFixed(2):""} required/></label>
        <label>Reference or note (optional)<input name="note" maxLength={500} defaultValue={paymentBidder.payment?.note||""}/></label>
        {!paymentBidder.payment&&<Button name="intent" value="save" variant="outline" disabled={mutation.isPending||reviewedCount!==null&&reviewedCount!==applicationTotal(paymentBidder)}>Save amount</Button>}
        <Button name="intent" value="paid" disabled={mutation.isPending||reviewedCount!==null&&reviewedCount!==applicationTotal(paymentBidder)}>{paymentBidder.payment?"Save changes":"Record as paid"}</Button>
        {!paymentBidder.payment&&paymentBidder.amount_override_cents!=null&&<Button type="button" variant="outline" disabled={mutation.isPending} onClick={()=>void write(`/api/payments/bidders/${paymentBidder.id}/amount`,{week:data.week_start,expected_count:reviewedCount??applicationTotal(paymentBidder),amount:null})}>Use calculated amount</Button>}
        {paymentBidder.payment&&paymentBidder.calculated_amount_cents!=null&&<Button type="button" variant="outline" onClick={event=>{const input=event.currentTarget.form?.elements.namedItem("amount") as HTMLInputElement|null;if(input)input.value=(paymentBidder.calculated_amount_cents!/100).toFixed(2)}}>Use calculated amount</Button>}
        <Button type="button" variant="ghost" onClick={()=>setPaying(null)}>Cancel</Button>
      </form></Card>}
    <Card className="payment-breakdown"><div className="payment-section-heading"><div><h2>Daily breakdown</h2><p>{closed ? "Completed week" : "Week in progress"} · Estimated confirmations / checked applications</p></div><div className="payment-report-actions"><span>{bidders.length} bidders</span>{!readOnly&&<Button variant="outline" size="sm" disabled={!closed||copying||!data.bidders.length} title="Copy final payment amounts for all bidders in the selected completed week" onClick={()=>void copyWeekly()}><Copy size={15}/>{copying?"Copying…":"Copy weekly payment report"}</Button>}</div></div>
      {reportPreview&&!readOnly&&<div className="payment-report-preview"><h3>Payment report · {shortDate(data.week_start)} – {shortDate(data.week_end)}</h3>{reportPreview.issues.length>0&&<div role="alert"><p>Nothing copied. Complete these details first:</p><ul>{reportPreview.issues.map(issue=><li key={issue}>{issue}</li>)}</ul><a href="/accounts#bidder-management">Manage bidder wallets on Accounts</a></div>}{copyError&&<p role="alert">{copyError}</p>}{reportPreview.text&&<label>Weekly payment report<textarea aria-label="Weekly payment report" readOnly rows={Math.max(3,data.bidders.length+2)} value={reportPreview.text} onFocus={event=>event.currentTarget.select()}/></label>}<Button size="sm" variant="ghost" onClick={()=>{setReportPreview(null);setCopyError("")}}>Close report</Button></div>}
      {!data.bidders.length ? <div className="payment-empty"><UsersRound size={32} /><h3>No bidders yet</h3><p>{readOnly ? "An admin needs to add bidders and assign their accounts." : <a href="/accounts#bidder-management">Add bidders and assign their accounts on Accounts.</a>}</p></div> : <div className="payment-table-scroll"><table className="payment-table"><thead><tr><th scope="col">Bidder / accounts</th>{data.dates.map(day => <th scope="col" key={day} className={day === data.today ? "payment-today" : ""}><span>{new Date(day + "T12:00:00Z").toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" })}</span><small>{shortDate(day)}</small></th>)}<th scope="col">Week total</th><th scope="col">Payment<small>Estimated / confirmed</small></th></tr></thead><tbody>{bidders.map(b => {
        const accounts = b.assignments.filter(a => a.start_date <= data.week_end && (!a.end_date || a.end_date >= data.week_start))
        return <tr key={b.id}><th scope="row"><strong>{b.name}</strong><small className="payment-row-total">{applicationTotal(b).toLocaleString()} estimated this week</small><span>{accounts.map(a => a.account_label).join(", ") || "No accounts assigned this week"}</span></th>{b.daily.map((count, i) => <td key={data.dates[i]} className={data.dates[i] === data.today ? "payment-today" : ""}>{count.toLocaleString()} / {(b.checked_daily?.[i] || 0).toLocaleString()}</td>)}<td className="payment-total">{applicationTotal(b).toLocaleString()}</td><td><span className="payment-amount-pair" aria-label="Estimated / confirmed payment"><span>{b.calculated_amount_cents!=null?money(b.calculated_amount_cents):"—"}</span><span aria-hidden="true"> / </span>{readOnly?<span className="payment-confirmed">{confirmedAmount(b)!=null?money(confirmedAmount(b)!):"—"}</span>:<button type="button" className="payment-confirmed payment-confirmed-edit" disabled={!closed} aria-label={`Edit confirmed payment for ${b.name}${confirmedAmount(b)!=null?`, ${money(confirmedAmount(b)!)}`:""}`} title={closed?"Click to edit the confirmed amount":"Editable after the week ends"} onClick={()=>{mutation.reset();setReviewedCount(applicationTotal(b));setReviewedRevision(b.payment?.revision||0);setPaying(b.id)}}>{confirmedAmount(b)!=null?money(confirmedAmount(b)!):"—"}</button>}</span></td></tr>
      })}
      {unallocatedTotal > 0 && <tr className="payment-unallocated"><th scope="row">Unallocated confirmations<span>Shared accounts with no matched completions that day</span></th>{unallocated.map((count, i) => <td key={data.dates[i]}>{count.toLocaleString()} / 0</td>)}<td className="payment-total">{unallocatedTotal.toLocaleString()}</td><td>Awaiting checked links</td></tr>}
      </tbody><tfoot><tr><th scope="row">Total</th>{daily.map((count, i) => <td key={i}>{estimatedDaily[i].toLocaleString()} / {count.toLocaleString()}</td>)}<td>{total.toLocaleString()}</td><td /></tr></tfoot></table></div>}
    </Card>
    {data.bidders.length > 0 && <p className="payment-mobile-hint">Swipe the table to see all days and payment status.</p>}
    {!readOnly && data.unassigned > 0 && <p className="payment-unassigned">{data.unassigned.toLocaleString()} confirmations this week have no bidder assignment. <a href="/accounts#bidder-management">Assign their accounts with the correct dates on Accounts</a> to include them.</p>}
    <BidderActivity week={data.week_start} selected={selected} onSelect={setSelected} />

  </div>
}
