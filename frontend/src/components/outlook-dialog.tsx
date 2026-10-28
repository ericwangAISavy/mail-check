import {useEffect,useState,type FormEvent} from "react"
import {ExternalLink,LoaderCircle} from "lucide-react"
import {api,request} from "@/lib/api"
import {Button} from "@/components/ui/button"
import {Dialog,DialogContent,DialogDescription,DialogHeader,DialogTitle} from "@/components/ui/dialog"
import {useToast} from "@/components/common"
export default function OutlookDialog({ open, onOpenChange, refresh, accountLabel }: { open: boolean; onOpenChange: (open: boolean) => void; refresh: () => void; accountLabel?: string }) {
  const [label, setLabel] = useState("")
  const [flow, setFlow] = useState<{ user_code: string; verification_uri: string } | null>(null)
  const [message, setMessage] = useState("")
  const [pending, setPending] = useState(false)
  const toast = useToast()
  useEffect(() => { if(open) { setLabel(accountLabel || ""); setMessage("") } },[open,accountLabel])
  useEffect(() => {
    if (!open || !flow) return
    let cancelled = false
    let timer = 0
    const poll = async () => {
      try {
        const status = await request<{ state: string; message: string }>("/api/outlook/status")
        if (cancelled) return
        if (status.state === "connected") { setMessage(status.message); setFlow(null); refresh(); toast(status.message || "Outlook connected.", "success"); onOpenChange(false); return }
        if (status.state === "failed") { setMessage(status.message); setFlow(null); return }
      } catch (error) { if (!cancelled) setMessage(error instanceof Error ? error.message : "Sign-in status is unavailable. Retrying…") }
      if (!cancelled) timer = window.setTimeout(poll, 2000)
    }
    void poll()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [flow, open, onOpenChange, refresh, toast])
  const cancel = async () => { try { await api.post("/api/outlook/cancel"); setFlow(null); onOpenChange(false) } catch (error) { toast(error instanceof Error ? error.message : "Could not cancel sign-in. Try again.", "error") } }
  const start = async (event: FormEvent) => {
    event.preventDefault(); setPending(true); setMessage("")
    try {
      const response = await api.post<{ user_code: string; verification_uri: string }>("/api/outlook/start", { label, reconnect: Boolean(accountLabel) })
      setFlow(response); window.open(response.verification_uri, "_blank", "noopener,noreferrer")
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not start Microsoft sign-in.") }
    finally { setPending(false) }
  }
  return <Dialog open={open} onOpenChange={(next) => { if (!next && flow) void cancel(); else onOpenChange(next) }}><DialogContent><DialogHeader><DialogTitle>{accountLabel ? "Reconnect Outlook.com" : "Connect Outlook.com"}</DialogTitle><DialogDescription>Sign in with Microsoft’s device code. OfferPath requests Mail.Read to read mail, Mail.Send to send your replies, and read-only Calendars.Read for meeting bookings.</DialogDescription></DialogHeader>{flow ? <div className="outlook-code">{message && <p role="alert" className="inline-error">{message}</p>}<p>Open the Microsoft sign-in page and enter this code:</p><strong>{flow.user_code}</strong><a href={flow.verification_uri} target="_blank" rel="noreferrer">Open Microsoft sign-in <ExternalLink size={14} /></a><p className="form-hint">This dialog checks for completion automatically.</p><div className="dialog-footer"><Button variant="outline" onClick={() => void cancel()}>Cancel sign-in</Button></div></div> : <form className="form-stack" onSubmit={start}><label>Account label<input autoFocus value={label} readOnly={Boolean(accountLabel)} onChange={(event) => setLabel(event.target.value)} required placeholder="Personal Outlook" /></label>{message && <p role="alert" className="inline-error">{message}</p>}<div className="dialog-footer"><Button variant="outline" type="button" onClick={() => onOpenChange(false)}>Cancel</Button><Button disabled={pending}>{pending && <LoaderCircle className="spin" />}Continue with Microsoft</Button></div></form>}</DialogContent></Dialog>
}
