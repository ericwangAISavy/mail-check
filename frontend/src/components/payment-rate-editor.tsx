import { useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"

type BidderRate = {id:number;name:string;pay_per_bid?:string|null;adjustment_percent?:string}

export default function PaymentRateEditor({bidder,onClose}:{bidder:BidderRate;onClose:()=>void}) {
  const client=useQueryClient()
  const save=useMutation({
    mutationFn:(body:{pay_per_bid:string;adjustment_percent:string})=>api.post(`/api/payments/bidders/${bidder.id}/rate`,body),
    onSuccess:async()=>{
      await Promise.all([client.invalidateQueries({queryKey:["payments"]}),client.invalidateQueries({queryKey:["bidder-management"]})])
      onClose()
    },
  })
  return <Card className="payment-rate-entry">
    <h2>Set payment rate for {bidder.name}</h2>
    <p>A pay-per-bid rate is needed to calculate this bidder’s amounts. Enter the agreed rate; saved payments and manual amount overrides remain unchanged.</p>
    <form className="payment-inline-form" onSubmit={event=>{
      event.preventDefault()
      const values=new FormData(event.currentTarget)
      save.mutate({pay_per_bid:String(values.get("pay_per_bid")),adjustment_percent:String(values.get("adjustment_percent"))})
    }}>
      <label>Pay per bid (USD)<input name="pay_per_bid" type="number" min="0" max="100" step="0.000001" defaultValue={bidder.pay_per_bid??""} required disabled={save.isPending}/></label>
      <label>Adjustment (%)<input name="adjustment_percent" type="number" min="0" max="1000" step="0.0001" defaultValue={bidder.adjustment_percent??"20"} required disabled={save.isPending}/></label>
      <Button disabled={save.isPending}>{save.isPending?"Saving…":"Save rate"}</Button>
      <Button type="button" variant="ghost" disabled={save.isPending} onClick={onClose}>Cancel</Button>
    </form>
    {save.error&&<p role="alert" className="inline-error">{save.error.message}</p>}
  </Card>
}
