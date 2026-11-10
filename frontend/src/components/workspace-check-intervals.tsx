import { Crown, Users } from "lucide-react"
import { Button } from "@/components/ui/button"

type Props = { ownerMinutes:number; otherMinutes:number; enabled:boolean; onChange:(key:"interval_minutes"|"other_interval_minutes",value:number)=>void }
export function WorkspaceCheckIntervals({ownerMinutes,otherMinutes,enabled,onChange}:Props) {
  return <div className="workspace-check-settings">
    <div className="workspace-check-grid">{([
      {key:"interval_minutes",title:"Owner workspace",label:"Owner check interval · minutes",description:"The owner’s original workspace. Use 1–2 minutes for frequent updates.",value:ownerMinutes,presets:[1,2],Icon:Crown},
      {key:"other_interval_minutes",title:"Other admin workspaces",label:"Other admins check interval · minutes",description:"Applies to every other admin workspace. Use 5–10 minutes to reduce server load.",value:otherMinutes,presets:[5,10],Icon:Users},
    ] as const).map(({key,title,label,description,value,presets,Icon})=><section className="workspace-check-card" aria-label={title} key={key}>
      <div className="workspace-check-title"><Icon size={18} aria-hidden="true"/><h3>{title}</h3><span>{enabled && Number.isInteger(value) && value>=1 && value<=1440 ? `Every ${value} min` : enabled ? "Choose interval" : "Off"}</span></div>
      <p>{description}</p>
      <label className="setting-field"><span>{label}</span><input type="number" min="1" max="1440" step="1" aria-invalid={!Number.isInteger(value) || value<1 || value>1440} value={value} onChange={event=>onChange(key,Number(event.target.value))}/></label>
      {(!Number.isInteger(value) || value<1 || value>1440) && <p className="inline-error" role="alert">Enter a whole number from 1 to 1,440 minutes.</p>}
      <div className="workspace-check-presets" role="group" aria-label={`${title} quick intervals`}>{presets.map(minutes=><Button key={minutes} variant={value===minutes?"secondary":"outline"} size="sm" aria-pressed={value===minutes} onClick={()=>onChange(key,minutes)}>{minutes} min</Button>)}<small>1–1,440 minutes</small></div>
    </section>)}</div>
    <p className="form-hint workspace-check-live-note">Fast live checks for active bidder Inboxes remain separate. These intervals control scheduled mailbox checks.</p>
  </div>
}
