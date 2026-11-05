import { useEffect, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api, request } from "@/lib/api"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"

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
      await Promise.all([
        client.invalidateQueries({ queryKey: ["bidder-visibility"] }),
        client.invalidateQueries({ queryKey: ["payments"] }),
      ])
      setDirty(false)
    },
  })
  return <tr>
    <th scope="row">{member.name}</th>
    <td><input type="checkbox" aria-label={`Payment visible for ${member.name}`} checked={payment} disabled={save.isPending} onChange={event => { setPayment(event.target.checked); setDirty(true) }} /></td>
    <td><input type="checkbox" aria-label={`Other bidders work visible for ${member.name}`} checked={others} disabled={save.isPending} onChange={event => { setOthers(event.target.checked); setDirty(true) }} /></td>
    <td><Button size="sm" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>{save.isPending ? "Saving…" : "Save visibility"}</Button>
      {save.error && <div role="alert"><p>{save.error.message}</p><Button variant="outline" size="sm" onClick={() => { setDirty(false); save.reset(); void client.invalidateQueries({ queryKey: ["bidder-visibility"] }) }}>Reload saved options</Button></div>}
    </td>
  </tr>
}

export default function BidderVisibility() {
  const query = useQuery({ queryKey: ["bidder-visibility"], queryFn: () => request<{ bidders: Member[] }>("/api/payments/visibility") })
  return <Card className="bidder-visibility-panel">
    <h2>Bidder visibility</h2>
    <p>Choose what each bidder can see. Other bidders’ work shows checked counts only; their payments and accounts stay private. Dashboard graphs always use the signed-in bidder’s assigned accounts.</p>
    {query.isPending ? <p>Loading visibility options…</p> : query.error ? <div role="alert"><p>{query.error.message}</p><Button variant="outline" size="sm" onClick={() => void query.refetch()}>Try again</Button></div> : <div className="table-scroll">
      <table><thead><tr><th>Bidder</th><th>Payment visible</th><th>Other bidders’ work visible</th><th>Save</th></tr></thead>
        <tbody>{query.data?.bidders.map(member => <VisibilityRow key={member.id} member={member} />)}</tbody>
      </table>
      {!query.data?.bidders.length && <p>Add bidders above to set visibility.</p>}
    </div>}
  </Card>
}
