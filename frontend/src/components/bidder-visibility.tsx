import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api, request } from "@/lib/api"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"

type VisibilityData = { bidders: Member[] }

const readVisibility = () => request<VisibilityData>("/api/payments/visibility")

type Member = {
  id: number
  name: string
  payment_visible: boolean | number
  other_work_visible: boolean | number
  visibility_revision: number
}

function VisibilityRow({ member }: { member: Member }) {
  const client = useQueryClient()
  const [payment, setPayment] = useState(Boolean(member.payment_visible))
  const [others, setOthers] = useState(Boolean(member.other_work_visible))
  const [dirty, setDirty] = useState(false)
  const [revision, setRevision] = useState(member.visibility_revision)
  useEffect(() => {
    if (!dirty) {
      setPayment(Boolean(member.payment_visible))
      setOthers(Boolean(member.other_work_visible))
      setRevision(member.visibility_revision)
    }
  }, [member.payment_visible, member.other_work_visible, member.visibility_revision, dirty])
  const save = useMutation({
    mutationFn: () => api.post(`/api/payments/bidders/${member.id}/visibility`, {
      payment_visible: payment, other_work_visible: others, expected_revision: revision,
    }),
    onSuccess: async () => {
      // The successful compare-and-swap confirms this revision even if the
      // subsequent read fails. Never reset the form to an older cached policy.
      client.setQueryData<VisibilityData>(["bidder-visibility"], previous => previous && ({
        bidders: previous.bidders.map(row => row.id === member.id ? {
          ...row, payment_visible: payment, other_work_visible: others, visibility_revision: revision + 1,
        } : row),
      }))
      setDirty(false)
      await Promise.all([
        client.invalidateQueries({ queryKey: ["bidder-visibility"] }),
        client.invalidateQueries({ queryKey: ["payments"] }),
      ])
    },
  })
  const reload = useMutation({
    mutationFn: readVisibility,
    onSuccess: data => {
      client.setQueryData(["bidder-visibility"], data)
      setDirty(false)
      save.reset()
    },
  })
  const busy = save.isPending || reload.isPending

  return <tr>
    <th scope="row">{member.name}</th>
    <td><input type="checkbox" aria-label={`Payment visible for ${member.name}`} checked={payment} disabled={busy} onChange={event => { setPayment(event.target.checked); setDirty(true) }} /></td>
    <td><input type="checkbox" aria-label={`Other bidders work visible for ${member.name}`} checked={others} disabled={busy} onChange={event => { setOthers(event.target.checked); setDirty(true) }} /></td>
    <td><Button size="sm" disabled={!dirty || busy} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save visibility"}</Button>
      {save.error && <div role="alert"><p>{save.error.message}</p><Button variant="outline" size="sm" disabled={busy} onClick={() => reload.mutate()}>Reload saved options</Button>{reload.error && <p>{reload.error.message}</p>}</div>}
    </td>
  </tr>
}

export default function BidderVisibility({ embedded = false }: { embedded?: boolean }) {
  const query = useQuery({ queryKey: ["bidder-visibility"], queryFn: readVisibility })
  return <Card className="bidder-visibility-panel">
    {!embedded && <h2>Bidder visibility</h2>}
    <p>Choose what each bidder can see. Other bidders’ work shows checked counts only; their payments and accounts stay private. Dashboard graphs always use the signed-in bidder’s assigned accounts.</p>
    {query.isPending ? <p>Loading visibility options…</p> : query.error && !query.data ? <div role="alert"><p>{query.error.message}</p><Button variant="outline" size="sm" onClick={() => void query.refetch()}>Try again</Button></div> : <div className="table-scroll">
      {query.error && <p role="alert">Could not refresh visibility options. Showing the last loaded settings.</p>}
      <table><thead><tr><th>Bidder</th><th>Payment visible</th><th>Other bidders’ work visible</th><th>Save</th></tr></thead>
        <tbody>{query.data?.bidders.map(member => <VisibilityRow key={member.id} member={member} />)}</tbody>
      </table>
      {!query.data?.bidders.length && <p>Add bidders above to set visibility.</p>}
    </div>}
  </Card>
}
