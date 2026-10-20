import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Pencil, Plus, Trash2 } from "lucide-react"
import { api, request } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Loading, useToast } from "@/components/common"
import "@/pages/payments.css"
type Assignment = { id: number; account_id: number; account_label: string; start_date: string; end_date: string | null }
type Bidder = { id: number; name: string; assignments: Assignment[] }
type Report = { today: string; bidders: Bidder[]; accounts: { id: number; label: string }[] }

export default function BidderManagement() {
  const [open, setOpen] = useState(() => window.location.hash === "#bidder-management")
  const client = useQueryClient()
  const toast = useToast()
  const query = useQuery({ queryKey: ["bidder-management"], queryFn: () => request<Report>("/api/payments"), enabled: open })
  const mutation = useMutation({ mutationFn: ({ url, body }: { url: string; body: unknown }) => api.post(url, body), onSuccess: async () => {
    await Promise.all(["bidder-management", "payments", "dashboard-accounts", "dashboard", "sourcing-index", "sourcing-search", "login-bidders"].map(key => client.invalidateQueries({ queryKey: [key] })))
    toast("Saved.", "success")
  } })
  const write = (url: string, body: unknown) => mutation.mutateAsync({ url, body })
  const data = query.data
  return (
    <details id="bidder-management" className="payment-management" open={open} onToggle={e => setOpen(e.currentTarget.open)}><summary>Manage bidders and account assignments</summary>
      {query.isPending && <Loading label="Loading bidders and assignments…" />}
      {query.error && <p role="alert" className="inline-error">{query.error.message} <Button onClick={() => void query.refetch()}>Try again</Button></p>}
      {mutation.error && <p role="alert" className="inline-error">{mutation.error.message}</p>}
      {data && <><Card className="payment-admin-card"><h2>Add bidder</h2><form className="payment-inline-form" onSubmit={async e => { e.preventDefault(); const form = e.currentTarget; const values = new FormData(form); try { await write("/api/payments/bidders", { name: values.get("name") }); form.reset() } catch { /* shown above */ } }}><label>Bidder name<input name="name" required maxLength={100} placeholder="e.g. Alex" /></label><Button disabled={mutation.isPending}><Plus size={16} />Add bidder</Button></form></Card>
      {data.bidders.map(b => <BidderManager key={b.id} bidder={b} accounts={data.accounts} today={data.today} busy={mutation.isPending} write={write} />)}
    </>}
    </details>
  )
}

function BidderManager({ bidder, accounts, today, busy, write }: { bidder: Bidder; accounts: Report["accounts"]; today: string; busy: boolean; write: (url: string, body: unknown) => Promise<unknown> }) {
  const [removing, setRemoving] = useState(false)
  const submit = (url: string, body: (form: FormData) => unknown) => async (e: FormEvent<HTMLFormElement>) => { e.preventDefault(); try { await write(url, body(new FormData(e.currentTarget))) } catch { /* page shows server error */ } }
  return <Card className="payment-admin-card"><div className="payment-section-heading"><h2>{bidder.name}</h2><Button variant="destructive" size="sm" disabled={busy} onClick={() => setRemoving(true)}><Trash2 size={14} />Remove bidder</Button></div>
    {removing && <div className="payment-rule-remove"><p>Remove {bidder.name}? Their sign-in will be disabled and their documents will be archived. Existing documents and payment records will stay saved.</p><div className="payment-assignment-actions"><Button variant="destructive" disabled={busy} onClick={async () => { try { await write(`/api/payments/bidders/${bidder.id}/remove`, {}) } catch { /* shown above */ } }}>Confirm removal</Button><Button variant="ghost" disabled={busy} onClick={() => setRemoving(false)}>Cancel</Button></div></div>}
    <form className="payment-inline-form" onSubmit={submit(`/api/payments/bidders/${bidder.id}`, form => ({ name: form.get("name") }))}><label>Name<input name="name" key={bidder.name} defaultValue={bidder.name} required maxLength={100} /></label><Button variant="outline" disabled={busy}>Save name</Button></form>
    <h3>Assigned accounts</h3>{!bidder.assignments.length && <p className="payment-muted">No accounts assigned.</p>}{bidder.assignments.map(a => <AssignmentRule key={a.id} assignment={a} accounts={accounts} busy={busy} write={write} />)}
    <form className="payment-inline-form payment-assign-form" onSubmit={submit(`/api/payments/bidders/${bidder.id}/assignments`, form => ({ account_id: Number(form.get("account")), start_date: form.get("start"), end_date: form.get("end") || null }))}><label>Account<select name="account" required defaultValue=""><option value="" disabled>Select account</option>{accounts.map(a => <option key={a.id} value={a.id}>{a.label}</option>)}</select></label><label>First assigned day<input name="start" type="date" defaultValue={today} required /></label><label>Last day (optional)<input name="end" type="date" /></label><Button disabled={busy || !accounts.length}>Assign account</Button></form><p className="payment-muted">An account can be assigned to several bidders on the same day. Each bidder’s received application totals include that account during their assigned dates; checked sourcing links stay with the bidder who owns the document.</p>
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
