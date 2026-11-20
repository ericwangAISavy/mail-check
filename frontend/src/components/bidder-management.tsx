import { usePageState } from "@/lib/page-state"
import { BidderAccess } from "@/components/bidder-access"
import { useEffect, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Pencil, Plus, Trash2 } from "lucide-react"
import { api, request } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Loading, useToast } from "@/components/common"
import "@/pages/payments.css"
type Assignment = { id: number; account_id: number; account_label: string; start_date: string; end_date: string | null }
type Bidder = { id: number; name: string; wallet_network?:string; wallet_address?:string; pay_per_bid?:string|null; adjustment_percent?:string; assignments: Assignment[] }
type Report = { today: string; bidders: Bidder[]; accounts: { id: number; label: string }[] }

export default function BidderManagement({initiallyOpen=false,embedded=false}:{initiallyOpen?:boolean;embedded?:boolean}) {
  const [open, setOpen] = useState(() => embedded || initiallyOpen || window.location.hash === "#bidder-management")
  const [selectedBidder, setSelectedBidder] = usePageState<number>("/accounts", "expanded-bidder", -1, value => Number.isSafeInteger(value) && value >= -2)
  const [visited, setVisited] = useState<number[]>([])
  const client = useQueryClient()
  const toast = useToast()
  const query = useQuery({ queryKey: ["bidder-management"], queryFn: ({ signal }) => request<Report>("/api/payments/management", { signal }), enabled: open })
  const access=useQuery({queryKey:["bidder-access"],queryFn:({ signal }) =>request<{bidders:{bidder_id:number;enabled:boolean}[]}>("/api/auth/bidders/manage", { signal }),enabled:open})
  const mutation = useMutation({ mutationFn: ({ url, body }: { url: string; body: unknown }) => api.post(url, body), onSuccess: async () => {
    await Promise.all(["bootstrap", "applications-today", "bidder-access", "bidder-management", "payments", "dashboard-accounts", "dashboard", "sourcing-index", "sourcing-search", "login-bidders", "bidder-visibility"].map(key => client.invalidateQueries({ queryKey: [key] })))
    toast("Saved.", "success")
  } })
  const write = (url: string, body: unknown) => mutation.mutateAsync({ url, body })
  const data = query.data
  // One bidder is always shown; a stale or removed choice falls back to the first.
  const selected = data?.bidders.find(b => b.id === selectedBidder) ?? data?.bidders[0]
  useEffect(() => { if (selected) setVisited(ids => ids.includes(selected.id) ? ids : [...ids, selected.id]) }, [selected?.id])
  const content = <>
      {query.isPending && <Loading label="Loading bidders and assignments…" />}
      {query.error && <p role="alert" className="inline-error">{query.error.message} <Button onClick={() => void query.refetch()}>Try again</Button></p>}
      {access.error && <p role="alert" className="inline-error">Could not load bidder web access. <Button onClick={()=>void access.refetch()}>Try again</Button></p>}
      {mutation.error && <p role="alert" className="inline-error">{mutation.error.message}</p>}
      {data && <Card className="bidder-directory">
        <nav className="bidder-list" aria-label="Bidders">
          <div className="bidder-list-head"><strong>Bidders</strong><span>{data.bidders.length}</span></div>
          <ul>{data.bidders.map(b => {
            const active = b.assignments.filter(a => !a.end_date || a.end_date >= data.today).length
            return <li key={b.id}><button type="button" className="bidder-list-item" aria-label={b.name} aria-current={selected?.id === b.id ? "true" : undefined}
              aria-describedby={`bidder-summary-${b.id}`} onClick={() => setSelectedBidder(b.id)}>
              <span className="bidder-avatar" aria-hidden="true">{initials(b.name)}</span>
              <span className="bidder-list-text"><strong>{b.name}</strong><small id={`bidder-summary-${b.id}`}>{active} {active === 1 ? "account" : "accounts"}{b.pay_per_bid ? ` · $${b.pay_per_bid}/bid` : " · no rate"}</small></span>
            </button></li>
          })}</ul>
          {!data.bidders.length && <p className="payment-muted bidder-list-empty">No bidders yet.</p>}
          <form className="bidder-add" onSubmit={async e => { e.preventDefault(); const form = e.currentTarget; const values = new FormData(form); try { await write("/api/payments/bidders", { name: values.get("name") }); form.reset() } catch { /* shown above */ } }}>
            <input name="name" aria-label="Bidder name" required maxLength={100} placeholder="New bidder" />
            <Button size="sm" disabled={mutation.isPending}><Plus size={15} />Add bidder</Button>
          </form>
        </nav>
        <div className="bidder-detail">
          {data.bidders.filter(b => b.id === selected?.id || visited.includes(b.id)).map(b => <BidderManager key={b.id} hidden={b.id !== selected?.id}
            accessEnabled={!!access.data?.bidders.find(member=>member.bidder_id===b.id)?.enabled} accessReady={access.isSuccess}
            bidder={b} accounts={data.accounts} today={data.today} busy={mutation.isPending} write={write} />)}
          {!selected && <p className="payment-muted">Add a bidder to manage payment details and account assignments.</p>}
        </div>
      </Card>}
    </>
  return embedded ? <div className="payment-management bidder-management-content">{content}</div> : <details id="bidder-management" className="payment-management" open={open} onToggle={e => setOpen(e.currentTarget.open)}><summary>Manage bidders and account assignments</summary>{content}</details>
}

const initials = (name: string) => name.trim().split(/\s+/).slice(0, 2).map(part => part[0]?.toUpperCase() ?? "").join("") || "?"

function BidderManager({ hidden, bidder, accounts, today, busy, write,accessEnabled,accessReady }: { hidden: boolean; accessEnabled:boolean;accessReady:boolean;bidder: Bidder; accounts: Report["accounts"]; today: string; busy: boolean; write: (url: string, body: unknown) => Promise<unknown> }) {
  const [removing, setRemoving] = useState(false)
  const submit = (url: string, body: (form: FormData) => unknown) => async (e: FormEvent<HTMLFormElement>) => { e.preventDefault(); try { await write(url, body(new FormData(e.currentTarget))) } catch { /* page shows server error */ } }
  return <section id={`bidder-editor-${bidder.id}`} className="bidder-editor" hidden={hidden} aria-label={`${bidder.name} details`}>
    <header className="bidder-editor-head">
      <span className="bidder-avatar is-large" aria-hidden="true">{initials(bidder.name)}</span>
      <div><h3>{bidder.name}</h3><span className="payment-muted">{bidder.assignments.length} {bidder.assignments.length === 1 ? "assignment" : "assignments"}{bidder.wallet_address ? " · wallet saved" : ""}</span></div>
      <Button variant="ghost" size="sm" className="bidder-remove" disabled={busy} onClick={() => setRemoving(true)}><Trash2 size={14} />Remove bidder</Button>
    </header>
    {removing && <div className="payment-rule-remove"><p>Remove {bidder.name}? Their records stay saved.</p><div className="payment-assignment-actions"><Button variant="destructive" disabled={busy} onClick={async () => { try { await write(`/api/payments/bidders/${bidder.id}/remove`, {}) } catch { /* shown above */ } }}>Confirm removal</Button><Button variant="ghost" disabled={busy} onClick={() => setRemoving(false)}>Cancel</Button></div></div>}
    <div className="bidder-editor-group"><h4>Profile</h4>
      <form className="payment-inline-form" onSubmit={submit(`/api/payments/bidders/${bidder.id}`, form => ({ name: form.get("name") }))}><label>Name<input name="name" key={bidder.name} defaultValue={bidder.name} required maxLength={100} /></label><Button variant="outline" disabled={busy}>Save name</Button></form>
    </div>
    <div className="bidder-editor-group"><h4>Payment</h4>
      <form className="payment-inline-form" aria-label={`Payment rate for ${bidder.name}`} onSubmit={submit(`/api/payments/bidders/${bidder.id}/rate`,form=>({pay_per_bid:form.get("pay_per_bid"),adjustment_percent:form.get("adjustment_percent")}))}>
        <label>Pay per bid (USD)<input name="pay_per_bid" type="number" min="0" max="100" step="0.000001" key={bidder.pay_per_bid} defaultValue={bidder.pay_per_bid ?? ""} placeholder="0.05" required/></label>
        <label>Adjustment (%)<input name="adjustment_percent" type="number" min="0" max="1000" step="0.01" key={bidder.adjustment_percent} defaultValue={bidder.adjustment_percent ?? "20"} required/></label>
        <Button variant="outline" disabled={busy}>Save payment rate</Button>
      </form><p className="payment-muted">Weekly payment = pay per bid × checked applications × (1 + adjustment %).</p>
      <form className="payment-inline-form payment-wallet-form" aria-label={`Wallet for ${bidder.name}`} onSubmit={submit(`/api/payments/bidders/${bidder.id}/wallet`, form => ({ wallet_network:form.get("wallet_network"),wallet_address:form.get("wallet_address") }))}>
        <label>Payment network<input name="wallet_network" key={bidder.wallet_network} defaultValue={bidder.wallet_network || "USDT.BEP20"} placeholder="USDT.BEP20" maxLength={40}/></label>
        <label>Wallet address<input name="wallet_address" key={bidder.wallet_address} defaultValue={bidder.wallet_address || ""} placeholder="0x…" maxLength={128} autoComplete="off" spellCheck={false}/></label>
        <Button variant="outline" disabled={busy}>Save wallet</Button>
      </form>
    </div>
    {accessReady&&<div className="bidder-editor-group"><BidderAccess bidderId={bidder.id} name={bidder.name} enabled={accessEnabled} busy={busy} write={write}/></div>}
    <div className="bidder-editor-group"><h4>Assigned accounts</h4>{!bidder.assignments.length && <p className="payment-muted">No accounts assigned.</p>}{bidder.assignments.map(a => <AssignmentRule key={a.id} assignment={a} accounts={accounts} busy={busy} write={write} />)}
      <form className="payment-inline-form payment-assign-form" onSubmit={submit(`/api/payments/bidders/${bidder.id}/assignments`, form => ({ account_id: Number(form.get("account")), start_date: form.get("start"), end_date: form.get("end") || null }))}><label>Account<select name="account" required defaultValue=""><option value="" disabled>Select account</option>{accounts.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}</select></label><label>First assigned day<input name="start" type="date" defaultValue={today} required /></label><label>Last day (optional)<input name="end" type="date" /></label><Button disabled={busy || !accounts.length}>Assign account</Button></form>
    </div>
  </section>
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
    }}><label>Assigned account<select name="account" defaultValue={a.account_id} required>{choices.map(account => <option key={account.id} value={account.id}>{account.label}</option>)}</select></label><label>First assigned day<input name="start" type="date" defaultValue={a.start_date} required /></label><label>Last day (optional)<input name="end" type="date" defaultValue={a.end_date || ""} /></label><div className="payment-assignment-actions"><Button size="sm" disabled={busy}>Save changes</Button><Button type="button" variant="ghost" size="sm" disabled={busy} onClick={cancel}>Cancel</Button></div></form>}
    {removing && <div className="payment-rule-remove"><p>Remove this assignment?</p><div className="payment-assignment-actions"><Button type="button" variant="destructive" size="sm" disabled={busy} onClick={() => void remove()}>Remove assignment</Button><Button type="button" variant="ghost" size="sm" disabled={busy} onClick={cancel}>Cancel</Button></div></div>}
    {error && <p className="inline-error payment-rule-error" role="alert">{error}</p>}
  </div>
}
