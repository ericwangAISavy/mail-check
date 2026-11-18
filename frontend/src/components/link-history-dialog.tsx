import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { LoaderCircle } from 'lucide-react'
import { api, request } from '@/lib/api'
import { operationId } from '@/lib/operation-id'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useToast } from '@/components/common'

type BidderHistory = { id: number; name: string; deleted: boolean; link_count: number }
type Preview = { link_count: number; checked_count: number; preview_token: string }

export default function LinkHistoryDialog({ accountId, accountLabel, onClose }: {
  accountId: number; accountLabel: string; onClose: () => void
}) {
  const client = useQueryClient()
  const toast = useToast()
  const [bidderId, setBidderId] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [preview, setPreview] = useState<Preview | null>(null)
  const [operation, setOperation] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const url = `/api/accounts/${accountId}/link-history`
  const history = useQuery({
    queryKey: ['link-history', accountId],
    queryFn: ({ signal }) => request<{ bidders: BidderHistory[] }>(url, { signal }),
    retry: false,
  })
  const selected = history.data?.bidders.find(bidder => String(bidder.id) === bidderId)
  const scope = { bidder_id: Number(bidderId), start: start || null, end: end || null }
  const review = async () => {
    setBusy(true)
    setError('')
    try {
      const result = await api.post<Preview>(`${url}/preview`, scope)
      setPreview(result)
      setOperation(operationId())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not preview link history.')
    } finally { setBusy(false) }
  }
  const clear = async () => {
    if (!preview || busy) return
    setBusy(true)
    setError('')
    try {
      const result = await api.post<{ deleted: number }>(`${url}/clear`, {
        ...scope, preview_token: preview.preview_token, operation,
      })
      const keys = new Set(['link-history', 'sourcing', 'sourcing-index', 'sourcing-search', 'sourcing-viewer',
        'sourcing-delete-preview', 'payments', 'bidder-activity', 'dashboard', 'dashboard-accounts', 'applications-today'])
      await client.invalidateQueries({ predicate: query => keys.has(String(query.queryKey[0])) })
      toast(`${result.deleted} sourcing link(s) removed.`, 'success')
      onClose()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not clear link history.')
    } finally { setBusy(false) }
  }
  return <Dialog open onOpenChange={open => { if (!open && !busy) onClose() }}>
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Clear link history</DialogTitle>
        <DialogDescription>Review sourcing links saved under {accountLabel}, including history from deleted bidders.</DialogDescription>
      </DialogHeader>
      {history.isPending ? <p>Loading link history…</p> : history.isError ?
        <p role="alert">Could not load link history. <Button variant="outline" onClick={() => void history.refetch()}>Retry</Button></p> :
        !history.data?.bidders.length ? <p>No sourcing link history for this account.</p> :
          <div className="form-stack">
            <label>Bidder<select value={bidderId} disabled={busy || !!preview} onChange={event => setBidderId(event.target.value)}>
              <option value="">Choose a bidder</option>
              {history.data.bidders.map(bidder => <option key={bidder.id} value={bidder.id}>
                {bidder.name}{bidder.deleted ? ' (Deleted)' : ''} · {bidder.link_count} links
              </option>)}
            </select></label>
            <div className="link-history-dates">
              <label>From<input type="date" value={start} max={end || undefined} disabled={busy || !!preview} onChange={event => setStart(event.target.value)} /></label>
              <label>Through<input type="date" value={end} min={start || undefined} disabled={busy || !!preview} onChange={event => setEnd(event.target.value)} /></label>
            </div>
            <p className="form-hint">Leave dates empty to include all links.</p>
            {preview && <div className="link-history-preview" role="status">
              <strong>{preview.link_count} link(s) selected for {selected?.name}</strong>
              <p>{preview.checked_count} checked link(s). Removing checked rows can change calculated application and payment totals. Saved payment records are retained.</p>
              <p>Deletion is permanent.</p>
            </div>}
            {error && <p className="inline-error" role="alert">{error}</p>}
            <div className="dialog-footer">
              {preview && <Button variant="outline" disabled={busy} onClick={() => { setPreview(null); setError('') }}>Change selection</Button>}
              <Button variant="outline" disabled={busy} onClick={onClose}>Cancel</Button>
              {preview ? <Button variant="destructive" disabled={busy || !preview.link_count} onClick={() => void clear()}>
                {busy && <LoaderCircle className="spin" />}Delete {preview.link_count} links
              </Button> : <Button disabled={busy || !bidderId || !!(start && end && start > end)} onClick={() => void review()}>
                {busy && <LoaderCircle className="spin" />}Review deletion
              </Button>}
            </div>
          </div>}
    </DialogContent>
  </Dialog>
}
