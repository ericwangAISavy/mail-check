import { useQuery } from "@tanstack/react-query"
import { ExternalLink } from "lucide-react"
import { request } from "@/lib/api"
import type { Message } from "@/lib/types"
import { EmailContent } from "@/components/email-content"
import { Loading } from "@/components/common"
import { DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import "@/pages/interviews.css"

export function MessageDetails({ id, onCloseAutoFocus }: { id: number; onCloseAutoFocus?: (event: Event) => void }) {
  const query = useQuery({ queryKey: ["reader", id], queryFn: () => request<{ message: Message; body_html: string; original_html?: string | null }>(`/api/messages/${id}`), staleTime: 60_000 })
  const message = query.data?.message
  return <DialogContent className="interview-dialog process-message-dialog" onCloseAutoFocus={onCloseAutoFocus}>
    <DialogHeader><DialogTitle>{message?.subject || "Message details"}</DialogTitle><DialogDescription>Saved message details and full content.</DialogDescription></DialogHeader>
    {query.isPending ? <Loading label="Opening message…" /> : query.error ? <p role="alert" className="inline-error">{query.error.message}</p> : message && <>
      <dl className="interview-details"><div><dt>From</dt><dd>{message.from_name && <strong>{message.from_name}<br /></strong>}{message.from_addr}</dd></div><div><dt>Mailbox</dt><dd>{message.account_label}</dd></div><div><dt>Received</dt><dd>{message.date_utc ? new Date(message.date_utc).toLocaleString() : message.date_display}</dd></div></dl>
      {message.summary && <div className="process-message-summary"><h3>Summary</h3><p>{message.summary}</p></div>}
      <section className="process-message-content" aria-label="Full message content">{query.data?.original_html ? <EmailContent html={query.data.original_html} /> : <div className="email-body" dangerouslySetInnerHTML={{ __html: query.data?.body_html || "<p>No message body was stored.</p>" }} />}</section>
      {message.open_url && <a className="interview-meeting-link" href={message.open_url} target="_blank" rel="noopener noreferrer">{message.open_label || "Open original email"}<ExternalLink size={14} /></a>}
    </>}
  </DialogContent>
}
