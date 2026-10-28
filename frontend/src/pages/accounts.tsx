import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { KeyRound, LoaderCircle, Mail, Plus, ShieldCheck, Trash2, UserRound, Wifi } from "lucide-react"
import { api, request } from "@/lib/api"
import type { Account } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { EmptyState, Loading, PageHeading, Switch, useToast } from "@/components/common"

import OutlookDialog from "@/components/outlook-dialog"
import OutgoingDialog from "@/components/outgoing-dialog"
import BidderManagement from "@/components/bidder-management"

function AccountRow({ account, onRefresh, onReconnect }: { account: Account; onRefresh: () => void; onReconnect: () => void }) {
  const [outgoingOpen, setOutgoingOpen] = useState(false)
  const [busy, setBusy] = useState("")
  const toast = useToast()
  const change = async (action: string, url: string) => {
    setBusy(action)
    try {
      const result = await api.post<{ message?: string }>(url)
      toast(result.message || (action === "test" ? "Connection looks good." : "Account updated."), "success")
      onRefresh()
    } catch (error) { toast(error instanceof Error ? error.message : "Account action failed.", "error") }
    finally { setBusy("") }
  }
  const label = encodeURIComponent(account.label)
  return <><div className="account-row"><div className="account-icon">{account.provider === "outlook" ? <Mail size={19} /> : <UserRound size={19} />}</div><div className="account-info"><div className="account-name-line"><h3>{account.label}</h3><Badge variant={account.provider === "outlook" ? "default" : "outline"}>{account.provider === "outlook" ? "Microsoft" : "IMAP"}</Badge><Badge variant={account.enabled ? "muted" : "outline"}>{account.enabled ? "Active" : "Paused"}</Badge></div><p>{account.email}{account.provider === "imap" ? ` · ${account.imap_host} · ${account.folder}` : " · Personal Microsoft account"}</p></div><div className="account-actions"><span className="account-toggle-label">Include in checks</span><Switch disabled={Boolean(busy)} checked={account.enabled} label={`Include ${account.label} in checks`} onChange={(enabled) => void change("toggle", `/api/accounts/${label}/toggle?enabled=${enabled}`)} /><Button variant="outline" size="sm" disabled={Boolean(busy)} onClick={() => void change("test", `/api/accounts/${label}/test`)}>{busy === "test" ? <LoaderCircle className="spin" /> : <Wifi size={14} />}Test</Button>{account.provider === "imap" && <Button variant="outline" size="sm" onClick={()=>setOutgoingOpen(true)} disabled={Boolean(busy)}>Outgoing mail</Button>}{account.provider === "outlook" && <Button variant="outline" size="sm" onClick={onReconnect} disabled={Boolean(busy)}>Reconnect</Button>}<Button variant="ghost" size="icon" className="account-remove" title={`Remove ${account.label}`} disabled={Boolean(busy)} onClick={() => { if (window.confirm(`Remove ${account.label}? Its local message history will stay until normal retention cleanup.`)) void change("remove", `/api/accounts/${label}/delete`) }}><Trash2 size={15} /></Button></div></div><OutgoingDialog open={outgoingOpen} onOpenChange={setOutgoingOpen} label={account.label} onSaved={onRefresh}/></>
}

function AddImapDialog({ open, onOpenChange, refresh }: { open: boolean; onOpenChange: (open: boolean) => void; refresh: () => void }) {
  const toast = useToast()
  const [email, setEmail] = useState("")
  const manualServer = useRef(false)
  const [label, setLabel] = useState("")
  const [password, setPassword] = useState("")
  const [host, setHost] = useState("")
  const [port, setPort] = useState(993)
  const [folder, setFolder] = useState("INBOX")
  const [note, setNote] = useState("")
  const [pending, setPending] = useState(false)
  useEffect(() => {
    if (!open || !email.includes("@")) return
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const result = await request<{ preset: { host: string; port: number; note: string } | null }>(`/api/preset?email=${encodeURIComponent(email)}`, { signal: controller.signal })
        if (controller.signal.aborted) return
        if (!result.preset) { setNote("Add your provider’s IMAP hostname below."); return }
        if (!manualServer.current) { setHost(result.preset.host); setPort(result.preset.port) }
        setNote(result.preset.note)
        setLabel((current) => current || email.split("@")[0].replace(/[^a-z0-9_-]/gi, "-").slice(0, 28))
      } catch (error) {
        if (!controller.signal.aborted) setNote(error instanceof Error ? error.message : "Could not load provider details. Enter your server details below.")
      }
    }, 250)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [email, open])
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setPending(true)
    try {
      const result = await api.post<{ message: string }>("/api/accounts", { email, label, password, host, port, use_ssl: true, folder })
      toast(result.message || "Mailbox connected.", "success")
      setEmail(""); setLabel(""); setPassword(""); setHost(""); setPort(993); setFolder("INBOX"); setNote("")
      onOpenChange(false); refresh()
    } catch (error) { toast(error instanceof Error ? error.message : "Could not connect this mailbox.", "error") }
    finally { setPending(false) }
  }
  const close = (next: boolean) => { if (!next) setPassword(""); onOpenChange(next) }
  return <Dialog open={open} onOpenChange={close}><DialogContent><DialogHeader><DialogTitle>Connect a mailbox</DialogTitle><DialogDescription>Mail collection uses read-only IMAP. You can connect outgoing SMTP after setup to send replies. Your app password is saved only in your OS keyring.</DialogDescription></DialogHeader><form onSubmit={submit} className="form-stack"><label>Email address<input type="email" autoComplete="email" required value={email} onChange={(event) => { manualServer.current = false; setEmail(event.target.value) }} placeholder="you@gmail.com" /></label><label>Account label<input required maxLength={80} value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Personal" /></label><label>App password<input type="password" autoComplete="new-password" required value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Provider app password" /><small>Never paste your everyday mailbox password. Credentials are not sent to Ollama.</small></label><details className="advanced-field"><summary>Server details</summary><div className="settings-grid"><label>IMAP host<input required value={host} onChange={(event) => { manualServer.current = true; setHost(event.target.value) }} placeholder="imap.gmail.com" /></label><label>Port<input type="number" min={1} max={65535} value={port} onChange={(event) => { manualServer.current = true; setPort(Number(event.target.value)) }} /></label><label>Folder<input value={folder} onChange={(event) => setFolder(event.target.value)} /></label></div></details>{note && <p className="form-hint">{note}</p>}<div className="dialog-footer"><Button variant="outline" type="button" onClick={() => close(false)}>Cancel</Button><Button disabled={pending}>{pending && <LoaderCircle className="spin" />}Test &amp; connect</Button></div></form></DialogContent></Dialog>
}


export default function AccountsPage() {
  const [imapOpen, setImapOpen] = useState(false)
  const [outlookOpen, setOutlookOpen] = useState(false)
  const [reconnectLabel, setReconnectLabel] = useState<string>()
  const queryClient = useQueryClient()
  const { data, isPending, error } = useQuery({ queryKey: ["accounts"], queryFn: api.accounts })
  const refresh = useCallback(() => { void queryClient.invalidateQueries({ queryKey: ["accounts"] }); void queryClient.invalidateQueries({ queryKey: ["bidder-management"] }); void queryClient.invalidateQueries({ queryKey: ["bootstrap"] }); void queryClient.invalidateQueries({ queryKey: ["dashboard-accounts"] }) }, [queryClient])
  if (isPending) return <div className="page-wrap"><Loading /></div>
  return <div className="page-wrap accounts-page"><PageHeading title="Accounts" description="Connect the inboxes behind your next opportunity." action={<Button onClick={() => setImapOpen(true)}><Plus size={16} />Connect mailbox</Button>} />
    <div className="security-note"><ShieldCheck size={18} /><span><strong>You control outgoing mail.</strong> Mail checks never mark messages as read. Replies are sent only when you click Send.</span></div>
    {error && <p className="inline-error" role="alert">{error.message}</p>}
    {data?.accounts.length ? <><div className="section-title-line"><div><p className="eyebrow">CONNECTED INBOXES</p><h2>Your accounts</h2></div><span className="account-total">{data.accounts.length} total</span></div><Card className="account-card">{data.accounts.map((account) => <AccountRow key={account.id} account={account} onRefresh={refresh} onReconnect={()=>{setReconnectLabel(account.label);setOutlookOpen(true)}} />)}</Card></> : <EmptyState title="One inbox at a time" description="Connect a mailbox to begin building your private application queue." action={<Button onClick={() => setImapOpen(true)}><Plus size={16} />Connect your first mailbox</Button>} />}
    <BidderManagement />
    <div className="provider-heading"><div><p className="eyebrow">CONNECTION OPTIONS</p><h2>Choose your provider</h2></div><span>Credentials stay on your computer.</span></div>
    <div className="provider-grid"><button className="provider-card" onClick={() => setImapOpen(true)}><span className="provider-logo"><KeyRound /></span><span><strong>Gmail, Yahoo, iCloud &amp; more</strong><small>Connect with a secure app password over IMAP.</small></span><Plus size={17} className="provider-add" /></button><button className="provider-card" onClick={() => data?.outlook_ready ? (setReconnectLabel(undefined),setOutlookOpen(true)) : (window.location.href = "/settings#outlook")}><span className="provider-logo provider-microsoft">M</span><span><strong>Personal Outlook</strong><small>{data?.outlook_ready ? "Sign in with Microsoft. No password is stored." : "Add your Microsoft client ID in Settings first."}</small></span><Plus size={17} className="provider-add" /></button></div>
    <Card className="privacy-card"><ShieldCheck size={18} /><div><strong>Your mail stays yours.</strong><p>Messages and email bodies live in your local database. Only sender, subject, and the configured body excerpt go to your chosen Ollama model. Microsoft 365 work and school accounts are not supported.</p></div></Card>
    <AddImapDialog open={imapOpen} onOpenChange={setImapOpen} refresh={refresh} /><OutlookDialog accountLabel={reconnectLabel} open={outlookOpen} onOpenChange={setOutlookOpen} refresh={refresh} />
  </div>
}
