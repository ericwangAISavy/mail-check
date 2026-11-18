import {useState} from 'react'
import {Card} from '@/components/ui/card'

type Health='healthy'|'degraded'|'unavailable'|'disabled'|'unknown'
type OperationalEvent={id:string;at:number;workspace:string;component:string;action:string;status:Health;job_id?:string}
const statuses:Health[]=['healthy','degraded','unavailable','disabled','unknown']
const labels:Record<string,string>={mail:'Mail collection',calendar:'Calendar collection',classify:'Classification',events:'Event publication'}
const clock=(at:number)=>new Date(at*1000).toLocaleString()
const time=(at:number)=>new Date(at*1000).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit',second:'2-digit'})

export default function MonitorEventHistory({events,names}:{events:OperationalEvent[];names:Map<string,string>}){
 const [selected,setSelected]=useState<string>()
 const ordered=events.filter(e=>Number.isFinite(e.at)).sort((a,b)=>a.at-b.at||a.id.localeCompare(b.id))
 const first=ordered[0]?.at??0,last=ordered.at(-1)?.at??first
 const start=first===last?first-30:first,end=first===last?last+30:last
 const lanes=[...new Set(ordered.map(e=>e.component))].sort()
 // Group visually adjacent events by component and status, retaining every ID.
 const groups=new Map<string,{key:string;slot:number;component:string;status:Health;events:OperationalEvent[]}>()
 for(const event of ordered){
  const slot=Math.min(39,Math.floor((event.at-start)/(end-start)*40))
  const key=`${event.component}:${event.status}:${slot}`
  const group=groups.get(key)??{key,slot,component:event.component,status:event.status,events:[]}
  group.events.push(event);groups.set(key,group)
 }
 const points=[...groups.values()]
 const active=points.find(p=>p.events.some(event=>event.id===selected))??points.at(-1)
 const height=lanes.length*96+62
 return <Card role="region" aria-label="Status history" className="monitor-history">
  <div className="monitor-history-heading"><div><h3>Status history</h3><p className="muted">{ordered.length} recorded events{ordered.length?` · ${clock(first)} – ${clock(last)}`:''}</p></div><span className="muted">Older → newer</span></div>
  <div className="monitor-history-legend" aria-label="Event status legend">{statuses.map(status=><span key={status} className={`monitor-${status}`}><i aria-hidden="true"/>{status}</span>)}</div>
  {!ordered.length?<p className="monitor-empty">No matching events.</p>:<>
   
   <div className="monitor-history-scroll"><svg viewBox={`0 0 1120 ${height}`} role="group" aria-label="Event timeline by component" className="monitor-history-graph">
    {lanes.map((lane,index)=><g key={lane}><text x="12" y={index*96+47} className="monitor-history-label">{labels[lane]??lane}</text><line x1="170" x2="1090" y1={index*96+48} y2={index*96+48} className="monitor-history-track"/></g>)}
    {[0,1,2,3,4].map(tick=>{const x=184+tick/4*880;return <g key={tick}><line x1={x} x2={x} y1="8" y2={height-43} className="monitor-history-grid"/><text x={x} y={height-16} textAnchor="middle" className="monitor-history-tick">{time(start+tick/4*(end-start))}</text></g>})}
    {points.map(point=>{
     const x=184+(point.slot+.5)/40*880,y=lanes.indexOf(point.component)*96+24+statuses.indexOf(point.status)*12
     const description=`${labels[point.component]??point.component}, ${point.status}, ${point.events.length} ${point.events.length===1?'event':'events'}, ${clock(point.events[0].at)}`
     return <g key={point.key} role="button" tabIndex={0} aria-label={description} aria-pressed={point.key===active?.key} className={`monitor-history-point monitor-${point.status}`} onClick={()=>setSelected(point.events[point.events.length-1].id)} onKeyDown={event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();setSelected(point.events[point.events.length-1].id)}}}>
      <title>{description}</title><circle cx={x} cy={y} r="13" className="monitor-history-hit"/><circle cx={x} cy={y} r={Math.min(10,4+Math.sqrt(point.events.length))} className="monitor-history-dot"/>{point.key===active?.key&&<circle cx={x} cy={y} r="12" className="monitor-history-ring"/>}
     </g>
    })}
   </svg></div>
   {active&&<div className="monitor-history-details"><h4>{labels[active.component]??active.component} · {active.events.length} {active.events.length===1?'event':'events'}</h4><ul>{[...active.events].reverse().map(event=><li key={event.id}><div><strong>{event.action.replaceAll('_',' ')}</strong><span className={`monitor-badge monitor-${event.status}`}><span aria-hidden="true"/>{event.status}</span></div><p>{names.get(event.workspace)??'Unknown workspace'} · <time dateTime={new Date(event.at*1000).toISOString()}>{clock(event.at)}</time></p><p>Job / change ID: <code>{event.job_id??'—'}</code></p></li>)}</ul></div>}
  </>}
 </Card>
}
