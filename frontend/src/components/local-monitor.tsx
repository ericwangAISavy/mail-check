import {useEffect,useState} from "react"
import {AlertTriangle,CheckCircle2} from "lucide-react"
import {useQuery} from "@tanstack/react-query"
import {request} from "@/lib/api"
import {MonitoringView} from "@/pages/system-monitoring"
import {Button} from '@/components/ui/button'
import {version} from '../../package.json'

type Status={origin:string;checked_at:number|null;outage_since?:number|null;snapshot_stale:boolean;failed_services?:string[];problem_services?:{id:string;status:string;name?:string;workspace_name?:string;reason?:string}[];logs:string[]}

function newerBuild(candidate:unknown){
 if(typeof candidate!=='string'||!/^\d+\.\d+\.\d+$/.test(candidate))return false
 const next=candidate.split('.').map(Number),current=version.split('.').map(Number)
 for(let index=0;index<3;index++)if(next[index]!==current[index])return next[index]>current[index]
 return false
}

export default function LocalMonitor(){
 const [log,setLog]=useState("")
 const [now,setNow]=useState(Date.now)
 useEffect(()=>{const timer=window.setInterval(()=>setNow(Date.now()),5000);return()=>window.clearInterval(timer)},[])
 const status=useQuery({queryKey:["local-monitor-status"],queryFn:({signal})=>request<Status>("/api/status",{signal}),refetchInterval:5000,refetchIntervalInBackground:true,retry:false,staleTime:0})
 const build=useQuery({queryKey:['local-monitor-build'],queryFn:({signal})=>request<{version:string}>('/assets/build-info.json',{signal,cache:'no-store'}),refetchInterval:30000,refetchIntervalInBackground:true,retry:false})
 const stale=!!status.data?.checked_at&&now/1000-status.data.checked_at>20
 const down=status.data?.origin==="unavailable"
 const unknown=status.data?.origin==="unknown"&&!!status.data.checked_at
 const failed=status.data?.failed_services||[]
 const problems=status.data?.problem_services||[]
 const critical=status.isError||stale||down||unknown||failed.length>0
 const warning=status.data?.origin==="busy"||problems.length>0
 const title=status.isError?"Monitoring connection lost":stale||unknown?"Health checks are not updating":down?"OfferPath is down":failed.length?"Service failure detected":status.data?.origin==="busy"?"OfferPath is overloaded":problems.length?"Service health needs attention":status.data?.origin==="ready"?"Local gateway is available":"Checking OfferPath…"
 useEffect(()=>{
  const previous=document.title
  document.title=critical?"ALERT · "+title:warning?"WARNING · "+title:"OfferPath · System monitoring"
  return()=>{document.title=previous}
 },[critical,warning,title])
 const logs=status.data?.logs||[]
 const selected=logs.includes(log)?log:failed.map(id=>id+".log").find(name=>logs.includes(name))||(logs.includes("origin-supervisor.log")?"origin-supervisor.log":logs[0])
 const tail=useQuery({queryKey:["local-monitor-log",selected],queryFn:({signal})=>request<{text:string}>(`/api/log?name=${encodeURIComponent(selected!)}`,{signal}),enabled:!!selected,refetchInterval:5000})
 return <>
  <div className="page-wrap local-monitor-status">
   <span className="monitor-ui-version muted">UI v{version}</span>
   {newerBuild(build.data?.version)&&<div role="status" className="monitor-update-note"><div><strong>Monitoring update available</strong><p>v{build.data?.version} is installed. Reload to use the latest monitoring page.</p></div><Button variant="outline" size="sm" onClick={()=>window.location.reload()}>Reload monitoring</Button></div>}
   <div role={critical||warning?"alert":"status"} className={`monitor-availability ${critical?"is-critical":warning?"is-warning":"is-healthy"}`}>
    {critical||warning?<AlertTriangle size={26} aria-hidden="true"/>:<CheckCircle2 size={24} aria-hidden="true"/>}
    <div><strong>{title}</strong>
     {critical&&<p>{down&&!stale&&!status.isError?"The application is not responding to local health checks. Automatic recovery should be running. Check origin-supervisor.log below.":failed.length?"One or more services failed their independent checks. Select the affected service log below for runtime errors.":"Current application availability cannot be confirmed. Check the monitoring process and server logs."}</p>}
     {failed.length>0&&<p>Affected services: {failed.join(", ")}</p>}
     {problems.length>0&&<p>Checks needing attention: {problems.map(item=>`${item.workspace_name?item.workspace_name+': ':''}${item.name||item.id} (${item.status}${item.reason?': '+item.reason.replaceAll('_',' '):''})`).join(", ")}. Expand Evidence below.</p>}
     {down&&status.data?.outage_since&&<p>Outage detected {new Date(status.data.outage_since*1000).toLocaleString()}</p>}
     {status.data?.snapshot_stale&&<p>Service tiles and charts show last known data.</p>}
    </div>
   </div>
  </div>
  <MonitoringView owner independent/>
  <section className="page-wrap local-monitor-logs" aria-label="Server logs">
   <h2>Server logs</h2>
   <select aria-label="Log file" value={selected||""} onChange={event=>setLog(event.target.value)}>
    {logs.map(name=><option key={name} value={name}>{name}</option>)}
   </select>
   <pre>{tail.isError?"Log unavailable":tail.data?.text||"Waiting for logs…"}</pre>
  </section>
 </>
}
