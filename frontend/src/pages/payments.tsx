import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, ArrowRight, Banknote, CalendarDays, CheckCircle2, UsersRound } from "lucide-react"
import { api, request } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Loading, PageHeading, useToast } from "@/components/common"
import BidderActivity from "@/components/bidder-activity"
import "./payments.css"

type Assignment = { id: number; account_id: number; account_label: string; start_date: string; end_date: string | null }
type Payment = { amount_cents: number; application_count: number; paid_at: string; note: string }
type Bidder = { id: number; name: string; assignments: Assignment[]; daily: number[]; checked_daily?: number[]; total: number; application_total?: number; payment: Payment | null }
type Report = { week_start: string; week_end: string; today: string; timezone: string; currency: string; dates: string[]; daily: number[]; checked_daily?: number[]; unassigned: number; unallocated_daily?: number[]; bidders: Bidder[]; accounts: { id: number; label: string }[] }
const applicationTotal = (bidder: Bidder) => bidder.application_total ?? bidder.checked_daily?.reduce((sum, count) => sum + count, 0) ?? 0
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
  const client = useQueryClient()
  const toast = useToast()
  const query = useQuery({ queryKey: ["payments", week], queryFn: () => request<Report>(`/api/payments${week ? `?week=${week}` : ""}`), refetchInterval: 30_000 })
  const mutation = useMutation({ mutationFn: ({ url, body }: { url: string; body: unknown }) => api.post(url, body), onSuccess: async () => { setPaying(null); await client.invalidateQueries({ queryKey: ["payments"] }); toast("Saved.", "success") } })
  const write = (url: string, body: unknown) => mutation.mutateAsync({ url, body })
  if (query.isPending) return <Loading label="Loading application totals…" />
  if (query.error) return <div className="page-wrap"><PageHeading title="Bidder payments" /><p role="alert" className="inline-error">{query.error.message}</p><Button onClick={() => void query.refetch()}>Try again</Button></div>
  const data = query.data!
  const bidders = groupByAccount(data.bidders.filter(b => !selected || b.id === Number(selected)), data.week_start, data.week_end)
  const estimatedDaily = selected ? data.dates.map((_, i) => bidders.reduce((sum, b) => sum + b.daily[i], 0)) : data.daily
  const daily = data.dates.map((_, i) => bidders.reduce((sum, b) => sum + (b.checked_daily?.[i] || 0), 0))
  const total = daily.reduce((sum, count) => sum + count, 0)
  const unallocated = selected ? data.dates.map(() => 0) : data.unallocated_daily || data.dates.map(() => 0)
  const unallocatedTotal = unallocated.reduce((sum, count) => sum + count, 0)
  const todayIndex = data.dates.indexOf(data.today)
  const closed = data.week_end < data.today
  const paymentBidder = data.bidders.find(b => b.id === paying)
  return <div className="page-wrap payments-page">
    <PageHeading title="Bidder payments" description="Applications counted from checked sourcing links across assigned accounts." />
    <Card className="payment-controls">
      <div className="payment-week"><Button variant="ghost" size="icon" aria-label="Previous week" onClick={() => { setWeek(moveWeek(data.week_start, -7)); setPaying(null) }}><ArrowLeft /></Button><label><span>Week of</span><input type="date" min="1971-01-01" max="2100-12-31" aria-label="Week of" value={data.week_start} onChange={e => { if (e.target.value) { setWeek(e.target.value); setPaying(null) } }} /></label><Button variant="ghost" size="icon" aria-label="Next week" onClick={() => { setWeek(moveWeek(data.week_start, 7)); setPaying(null) }}><ArrowRight /></Button><Button variant="outline" size="sm" onClick={() => { setWeek(""); setPaying(null) }}>This week</Button></div>
      <label className="payment-bidder-filter"><span>Bidder</span><select value={selected} onChange={e => setSelected(e.target.value)}><option value="">All bidders</option>{data.bidders.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></label>
      <span className="payment-timezone">Monday–Sunday · America/Chicago</span>
    </Card>
    <div className="payment-overview">
      <Card><CalendarDays aria-hidden="true" /><div><span>{todayIndex >= 0 ? "Today" : "Selected week"}</span><strong>{(todayIndex >= 0 ? daily[todayIndex] : total).toLocaleString()}</strong><small>{todayIndex >= 0 ? shortDate(data.today) : `${shortDate(data.week_start)} – ${shortDate(data.week_end)}`}</small></div></Card>
      <Card><CheckCircle2 aria-hidden="true" /><div><span>Applications this week</span><strong>{total.toLocaleString()}</strong><small>{shortDate(data.week_start)} – {shortDate(data.week_end)}</small></div></Card>
      <Card><Banknote aria-hidden="true" /><div><span>Payments recorded</span><strong>{money(bidders.reduce((sum, b) => sum + (b.payment?.amount_cents || 0), 0))}</strong><small>{bidders.filter(b => b.payment).length} of {bidders.length} bidders</small></div></Card>
    </div>
    {mutation.error && <p role="alert" className="inline-error">{mutation.error.message}</p>}
    {paymentBidder && !readOnly && <Card className="payment-entry"><h2>Record payment for {paymentBidder.name}</h2><p>{applicationTotal(paymentBidder)} checked applications · {shortDate(data.week_start)} – {shortDate(data.week_end)}. This records a payment you made; it does not transfer money.</p><form onSubmit={async e => { e.preventDefault(); const form = new FormData(e.currentTarget); try { await write(`/api/payments/bidders/${paymentBidder.id}/paid`, { week: data.week_start, expected_count: applicationTotal(paymentBidder), amount: String(form.get("amount")), note: form.get("note") }) } catch { /* shown above */ } }}><label>Amount (USD)<input name="amount" type="number" min="0.01" max="1000000" step="0.01" required /></label><label>Reference or note (optional)<input name="note" maxLength={500} /></label><Button disabled={mutation.isPending}>Record as paid</Button><Button type="button" variant="ghost" onClick={() => setPaying(null)}>Cancel</Button></form></Card>}
    <Card className="payment-breakdown"><div className="payment-section-heading"><div><h2>Daily breakdown</h2><p>{closed ? "Completed week" : "Week in progress"} · Checked applications / estimated confirmations</p></div><span>{bidders.length} bidders</span></div>
      {!data.bidders.length ? <div className="payment-empty"><UsersRound size={32} /><h3>No bidders yet</h3><p>{readOnly ? "An admin needs to add bidders and assign their accounts." : <a href="/accounts#bidder-management">Add bidders and assign their accounts on Accounts.</a>}</p></div> : <div className="payment-table-scroll"><table className="payment-table"><thead><tr><th scope="col">Bidder / accounts</th>{data.dates.map(day => <th scope="col" key={day} className={day === data.today ? "payment-today" : ""}><span>{new Date(day + "T12:00:00Z").toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" })}</span><small>{shortDate(day)}</small></th>)}<th scope="col">Week total</th><th scope="col">Payment</th></tr></thead><tbody>{bidders.map(b => {
        const accounts = b.assignments.filter(a => a.start_date <= data.week_end && (!a.end_date || a.end_date >= data.week_start))
        return <tr key={b.id}><th scope="row"><strong>{b.name}</strong><small className="payment-row-total">{applicationTotal(b).toLocaleString()} checked this week</small><span>{accounts.map(a => a.account_label).join(", ") || "No accounts assigned this week"}</span></th>{b.daily.map((count, i) => <td key={data.dates[i]} className={data.dates[i] === data.today ? "payment-today" : ""}>{(b.checked_daily?.[i] || 0).toLocaleString()} / {count.toLocaleString()}</td>)}<td className="payment-total">{applicationTotal(b).toLocaleString()}</td><td>{b.payment ? <div className="payment-paid"><span><CheckCircle2 size={14} />{money(b.payment.amount_cents)}</span><small>Paid · {b.payment.application_count} applications at recording</small><small>{new Date(b.payment.paid_at).toLocaleDateString("en-US", { timeZone: data.timezone })}</small>{b.payment.application_count !== applicationTotal(b) && <small className="payment-warning">Count changed since payment</small>}{b.payment.note && <small>{b.payment.note}</small>}</div> : !closed ? <span className="payment-muted">In progress</span> : readOnly ? <span className="payment-muted">Not recorded</span> : <Button variant="outline" size="sm" onClick={() => { mutation.reset(); setPaying(b.id) }}>Record payment</Button>}</td></tr>
      })}
      {unallocatedTotal > 0 && <tr className="payment-unallocated"><th scope="row">Unallocated confirmations<span>Shared accounts with no checked links that day</span></th>{unallocated.map((count, i) => <td key={data.dates[i]}>0 / {count.toLocaleString()}</td>)}<td className="payment-total">0</td><td>Awaiting checked links</td></tr>}
      </tbody><tfoot><tr><th scope="row">Total</th>{daily.map((count, i) => <td key={i}>{count.toLocaleString()} / {estimatedDaily[i].toLocaleString()}</td>)}<td>{total.toLocaleString()}</td><td /></tr></tfoot></table></div>}
    </Card>
    {data.bidders.length > 0 && <p className="payment-mobile-hint">Swipe the table to see all days and payment status.</p>}
    {!readOnly && data.unassigned > 0 && <p className="payment-unassigned">{data.unassigned.toLocaleString()} confirmations this week have no bidder assignment. <a href="/accounts#bidder-management">Assign their accounts with the correct dates on Accounts</a> to include them.</p>}
    <BidderActivity week={data.week_start} selected={selected} onSelect={setSelected} />
    <p className="payment-count-note">Daily cells show checked applications / estimated received confirmations. The first number sums checked job-link rows on that bidder’s sourcing date across accounts assigned to them on that date. Cards, weekly totals, and new payment records use this checked count. Confirmation emails check matching rows from their received day back six days, using company, role when present, and account. Checks never clear automatically. The second number remains a proportional receipt estimate for reference. Shared receipts with no checked links remain unallocated. Existing payment records remain saved.</p>

  </div>
}
