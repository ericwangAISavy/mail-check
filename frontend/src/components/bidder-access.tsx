import { useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"

export function BidderAccess({bidderId,name,enabled,busy,write}:{bidderId:number;name:string;enabled:boolean;busy:boolean;write:(url:string,body:unknown)=>Promise<unknown>}) {
  const [password,setPassword]=useState("")
  const [saving,setSaving]=useState(false)
  const save=async(event:FormEvent<HTMLFormElement>)=>{
    event.preventDefault();setSaving(true)
    try{await write(`/api/auth/bidders/${bidderId}/password`,{password,enabled:true});setPassword("")}
    catch{/* Parent displays the error. */}finally{setSaving(false)}
  }
  return <section className="bidder-access" aria-label={`Web access for ${name}`}>
    <div className="payment-section-heading"><h3>Bidder web access</h3><span className="payment-muted">{enabled?"Enabled · Read only":"Not enabled"}</span></div>
    <p className="payment-muted">Sign in as {name} + your admin username. This bidder can view your whole team’s Dashboard and Bidder management, plus their own Job sourcing, without editing or refreshing data.</p>
    <form className="payment-inline-form" onSubmit={event=>void save(event)}>
      <label>{enabled?"New bidder password":"Bidder password"}<input type="password" name="bidder_password" autoComplete="new-password" minLength={12} maxLength={256} required value={password} onChange={event=>setPassword(event.target.value)}/></label>
      <Button variant="outline" disabled={busy||saving}>{enabled?"Reset bidder password":"Enable bidder access"}</Button>
      {enabled&&<Button type="button" variant="ghost" disabled={busy||saving} onClick={async()=>{try{await write(`/api/auth/bidders/${bidderId}/password`,{enabled:false});setPassword("")}catch{/* Parent displays the error. */}}}>Disable bidder access</Button>}
    </form><small className="payment-muted">Use 12–256 characters. Resetting or disabling access signs out this bidder on every device.</small>
  </section>
}
