import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, ArrowRight, Banknote, CalendarDays, CheckCircle2, Pencil, Plus, Trash2, UsersRound } from "lucide-react"
import { api, request } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Loading, PageHeading, useToast } from "@/components/common"
import "./payments.css"

type Assignment = { id: number; account_id: number; account_label: string; start_date: string; end_date: string | null }
type Payment = { amount_cents: number; application_count: number; paid_at: string; note: string }
type Bidder = { id: number; name: string; assignments: Assignment[]; daily: number[]; checked_daily?: number[]; total: number; payment: Payment | null }
type Report = { week_start: string; week_end: string; today: string; timezone: string; currency: string; dates: string[]; daily: number[]; checked_daily?: number[]; unassigned: number; bidders: Bidder[]; accounts: { id: number; label: string }[] }
const money = (cents: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100)
const shortDate = (day: string) => new Date(day + "T12:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
const moveWeek = (day: string, delta: number) => { const date = new Date(day + "T12:00:00Z"); date.setUTCDate(date.getUTCDate() + delta); return date.toISOString().slice(0, 10) }

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
  const bidders = data.bidders.filter(b => !selected || b.id === Number(selected))
  const total = bidders.reduce((sum, b) => sum + b.total, 0)
  const daily = data.dates.map((_, i) => bidders.reduce((sum, b) => sum + b.daily[i], 0))
  const checkedDaily = data.dates.map((_, i) => bidders.reduce((sum, b) => sum + (b.checked_daily?.[i] || 0), 0))
  const todayIndex = data.dates.indexOf(data.today)
  const closed = data.week_end < data.today
  const paymentBidder = data.bidders.find(b => b.id === paying)
  return <div className="page-wrap payments-page">
    <PageHeading title="Bidder payments" description="Application received confirmations, counted by bidder and assigned account." />
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
    {paymentBidder && !readOnly && <Card className="payment-entry"><h2>Record payment for {paymentBidder.name}</h2><p>{paymentBidder.total} confirmations · {shortDate(data.week_start)} – {shortDate(data.week_end)}. This records a payment you made; it does not transfer money.</p><form onSubmit={async e => { e.preventDefault(); const form = new FormData(e.currentTarget); try { await write(`/api/payments/bidders/${paymentBidder.id}/paid`, { week: data.week_start, expected_count: paymentBidder.total, amount: String(form.get("amount")), note: form.get("note") }) } catch { /* shown above */ } }}><label>Amount (USD)<input name="amount" type="number" min="0.01" max="1000000" step="0.01" required /></label><label>Reference or note (optional)<input name="note" maxLength={500} /></label><Button disabled={mutation.isPending}>Record as paid</Button><Button type="button" variant="ghost" onClick={() => setPaying(null)}>Cancel</Button></form></Card>}
    <Card className="payment-breakdown"><div className="payment-section-heading"><div><h2>Daily breakdown</h2><p>{closed ? "Completed week" : "Week in progress"} · Received confirmations / checked sourcing links</p></div><span>{bidders.length} bidders</span></div>
      {!data.bidders.length ? <div className="payment-empty"><UsersRound size={32} /><h3>No bidders yet</h3><p>{readOnly ? "An admin needs to add bidders and assign their accounts." : "Add your first bidder below, then assign the accounts they apply from."}</p></div> : <div className="payment-table-scroll"><table className="payment-table"><thead><tr><th scope="col">Bidder / accounts</th>{data.dates.map(day => <th scope="col" key={day} className={day === data.today ? "payment-today" : ""}><span>{new Date(day + "T12:00:00Z").toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" })}</span><small>{shortDate(day)}</small></th>)}<th scope="col">Week total</th><th scope="col">Payment</th></tr></thead><tbody>{bidders.map(b => {
        const accounts = b.assignments.filter(a => a.start_date <= data.week_end && (!a.end_date || a.end_date >= data.week_start))
        return <tr key={b.id}><th scope="row"><strong>{b.name}</strong><small className="payment-row-total">{b.total.toLocaleString()} this week</small><span>{accounts.map(a => a.account_label).join(", ") || "No accounts assigned this week"}</span></th>{b.daily.map((count, i) => <td key={data.dates[i]} className={data.dates[i] === data.today ? "payment-today" : ""}>{count.toLocaleString()} / {(b.checked_daily?.[i] || 0).toLocaleString()}</td>)}<td className="payment-total">{b.total.toLocaleString()}</td><td>{b.payment ? <div className="payment-paid"><span><CheckCircle2 size={14} />{money(b.payment.amount_cents)}</span><small>Paid · {b.payment.application_count} applications</small><small>{new Date(b.payment.paid_at).toLocaleDateString("en-US", { timeZone: data.timezone })}</small>{b.payment.application_count !== b.total && <small className="payment-warning">Count changed since payment</small>}{b.payment.note && <small>{b.payment.note}</small>}</div> : !closed ? <span className="payment-muted">In progress</span> : readOnly ? <span className="payment-muted">Not recorded</span> : <Button variant="outline" size="sm" onClick={() => { mutation.reset(); setPaying(b.id) }}>Record payment</Button>}</td></tr>
      })}</tbody><tfoot><tr><th scope="row">Total</th>{daily.map((count, i) => <td key={i}>{count.toLocaleString()} / {checkedDaily[i].toLocaleString()}</td>)}<td>{total.toLocaleString()}</td><td /></tr></tfoot></table></div>}
    </Card>
    {data.bidders.length > 0 && <p className="payment-mobile-hint">Swipe the table to see all days and payment status.</p>}
    {!readOnly && data.unassigned > 0 && <p className="payment-unassigned">{data.unassigned.toLocaleString()} confirmations this week have no bidder assignment. Assign their accounts with the correct dates below to include them.</p>}
    <p className="payment-count-note">Daily cells show received confirmations / checked job links for that day. Counts follow the latest “Application received” classification and the account assignment on the email’s received date. Missing dates use the first collection date. Unassigned accounts are excluded. Counts cover confirmations collected by mail-check; they are not a direct submission count.</p>
    {!readOnly && <details className="payment-management"><summary>Manage bidders and account assignments</summary><Card className="payment-admin-card"><h2>Add bidder</h2><form className="payment-inline-form" onSubmit={async e => { e.preventDefault(); const form = e.currentTarget; const values = new FormData(form); try { await write("/api/payments/bidders", { name: values.get("name") }); form.reset() } catch { /* shown above */ } }}><label>Bidder name<input name="name" required maxLength={100} placeholder="e.g. Alex" /></label><Button disabled={mutation.isPending}><Plus size={16} />Add bidder</Button></form></Card>
      {data.bidders.map(b => <BidderManager key={b.id} bidder={b} accounts={data.accounts} today={data.today} busy={mutation.isPending} write={write} />)}
    </details>}
  </div>
}

function BidderManager({ bidder, accounts, today, busy, write }: { bidder: Bidder; accounts: Report["accounts"]; today: string; busy: boolean; write: (url: string, body: unknown) => Promise<unknown> }) {
  const submit = (url: string, body: (form: FormData) => unknown) => async (e: FormEvent<HTMLFormElement>) => { e.preventDefault(); try { await write(url, body(new FormData(e.currentTarget))) } catch { /* page shows server error */ } }
  return <Card className="payment-admin-card"><h2>{bidder.name}</h2><form className="payment-inline-form" onSubmit={submit(`/api/payments/bidders/${bidder.id}`, form => ({ name: form.get("name") }))}><label>Name<input name="name" key={bidder.name} defaultValue={bidder.name} required maxLength={100} /></label><Button variant="outline" disabled={busy}>Save name</Button></form>
    <h3>Assigned accounts</h3>{!bidder.assignments.length && <p className="payment-muted">No accounts assigned.</p>}{bidder.assignments.map(a => <AssignmentRule key={a.id} assignment={a} accounts={accounts} busy={busy} write={write} />)}
    <form className="payment-inline-form payment-assign-form" onSubmit={submit(`/api/payments/bidders/${bidder.id}/assignments`, form => ({ account_id: Number(form.get("account")), start_date: form.get("start"), end_date: form.get("end") || null }))}><label>Account<select name="account" required defaultValue=""><option value="" disabled>Select account</option>{accounts.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}</select></label><label>First assigned day<input name="start" type="date" defaultValue={today} required /></label><label>Last day (optional)<input name="end" type="date" /></label><Button disabled={busy || !accounts.length}>Assign account</Button></form><p className="payment-muted">An account can belong to one bidder on any given day. To transfer it, set its last day here and assign it to the next bidder starting the following day.</p>
  </Card>
}


function AssignmentRule({ assignment: a, accounts, busy, write }: { assignment: Assignment; accounts: Report["accounts"]; busy: boolean; write: (url: string, body: unknown) => Promise<unknown> }) {
  const [editing, setEditing] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [error, setError] = useState("")
  const choices = accounts.some(account => account.id === a.account_id) ? accounts : [...accounts, { id: a.account_id, label: a.account_label + " (disconnected)" }]
  const cancel = () => { setEditing(false); setRemoving(false); setError("") }
  const remove = async () => {
    setError("")
    try { await write(`/api/payments/assignments/${a.id}/remove`, {}); setRemoving(false) }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not remove assignment.") }
  }
  return <div className={`payment-assignment ${editing || removing ? "payment-assignment-expanded" : ""}`}>
    <div><strong>{a.account_label}</strong><span>{a.start_date} → {a.end_date || "Ongoing"}</span></div>
    {!editing && !removing && <div className="payment-assignment-actions"><Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => { setEditing(true); setError("") }}><Pencil size={14} />Edit</Button><Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => { setRemoving(true); setError("") }}><Trash2 size={14} />Remove</Button></div>}
    {editing && <form className="payment-rule-editor" aria-label={`Edit assignment for ${a.account_label}`} onSubmit={async e => {
      e.preventDefault(); const form = new FormData(e.currentTarget); setError("")
      try { await write(`/api/payments/assignments/${a.id}`, { account_id: Number(form.get("account")), start_date: form.get("start"), end_date: form.get("end") || null }); setEditing(false) }
      catch (reason) { setError(reason instanceof Error ? reason.message : "Could not update assignment.") }
    }}><label>Assigned account<select name="account" defaultValue={a.account_id} required>{choices.map(account => <option key={account.id} value={account.id}>{account.label}</option>)}</select></label><label>First assigned day<input name="start" type="date" defaultValue={a.start_date} required /></label><label>Last day (optional)<input name="end" type="date" defaultValue={a.end_date || ""} /></label><div className="payment-assignment-actions"><Button size="sm" disabled={busy}>Save changes</Button><Button type="button" variant="ghost" size="sm" disabled={busy} onClick={cancel}>Cancel</Button></div><p className="payment-muted">Leave the last day empty for an ongoing assignment.</p></form>}
    {removing && <div className="payment-rule-remove"><p>Remove this assignment? Its confirmations will no longer count toward this bidder’s totals. Emails and payment records stay saved.</p><div className="payment-assignment-actions"><Button type="button" variant="destructive" size="sm" disabled={busy} onClick={() => void remove()}>Remove assignment</Button><Button type="button" variant="ghost" size="sm" disabled={busy} onClick={cancel}>Cancel</Button></div></div>}
    {error && <p className="inline-error payment-rule-error" role="alert">{error}</p>}
  </div>
}
