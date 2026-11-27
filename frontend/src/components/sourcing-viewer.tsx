import {usePageState} from "@/lib/page-state"
import {useEffect,useMemo,useRef,useState} from "react"
import {useQuery} from "@tanstack/react-query"
import {Copy} from "lucide-react"
import {chicagoDayStart,jobSite,nextQueueBoundary,queueCounts,readSourcingSheet,rowLifecycle,serializeTSV,type QueueCounts,type QueueFocus,type QueueStatus,type Snapshot,type Tab} from "@/lib/sourcing"
import {serverNow} from "@/lib/api"
import {copyPaymentReport as copyText} from "@/lib/payment-report"
import {Button} from "@/components/ui/button"
import SourcingDays from "./sourcing-days"
import SourcingQueueBar from "./sourcing-queue"

/** Deliberately separate from the editor: no mutation, draft or autosave hooks. */
export default function SourcingViewer({tab,highlightId,highlightRow,initialDay,onDayChange,onQueueCounts}:{tab:Tab;highlightId?:string;highlightRow?:number;initialDay?:string;onDayChange?:(day:string)=>void;onQueueCounts?:(counts:QueueCounts)=>void}) {
 // The same work queue as the editor: To do across all days; the day only filters history.
 const [day,setDay]=useState(initialDay??""),[page,setPage]=usePageState("/sourcing",`tab:${tab.id}:viewer-page`,0,value=>Number.isSafeInteger(value)&&value>=0)
 const [message,setMessage]=useState(""),[copying,setCopying]=useState(false)
 const resolved=useRef("")
 const query=useQuery({queryKey:["sourcing-viewer",tab.id],queryFn:({ signal }) =>readSourcingSheet(tab.id, signal),staleTime:Infinity,refetchOnWindowFocus:false,refetchOnReconnect:false})
 const snapshot=query.data
 const [status,setStatus]=useState<QueueStatus>(initialDay?"all":"todo"),[focus,setFocus]=useState<QueueFocus|null>(null),[now,setNow]=useState(()=>serverNow())
 const dayStart=useMemo(()=>chicagoDayStart(now),[now])
 const counts=useMemo(()=>snapshot?queueCounts(snapshot,[],now,dayStart):null,[snapshot,now,dayStart])
 const reportCounts=useRef(onQueueCounts);reportCounts.current=onQueueCounts
 useEffect(()=>{if(counts)reportCounts.current?.(counts)},[counts])
 useEffect(()=>{setNow(serverNow())},[snapshot])
 useEffect(()=>{
  if(!snapshot)return
  const timer=window.setTimeout(()=>setNow(serverNow()),Math.max(1000,Math.min(nextQueueBoundary(snapshot,[],now,dayStart)-serverNow()+250,2**31-1)))
  return()=>window.clearTimeout(timer)
 },[snapshot,now,dayStart])
 useEffect(()=>{onDayChange?.(day);setMessage("")},[day,onDayChange])
 useEffect(()=>{
  if(!snapshot)return
  const target=highlightId? snapshot.row_ids.indexOf(highlightId):highlightRow
  const key=highlightId||String(highlightRow??"")
  if(key&&key!==resolved.current&&target!=null&&target>0){
   resolved.current=key;setDay("");setStatus("all");setFocus(null)
   const order=queueRows(snapshot,"all",null,"",serverNow(),chicagoDayStart(serverNow()))
   setPage(Math.max(0,Math.floor(order.findIndex(row=>row.index===target)/100)))
  }
 },[snapshot,highlightId,highlightRow])
 const rows=useMemo(()=>snapshot?queueRows(snapshot,status,focus,day,now,dayStart):[],[snapshot,status,focus,day,now,dayStart])
 const expiring=useMemo(()=>new Set(rows.filter(row=>row.expiring).map(row=>row.index)),[rows])
 const pages=Math.max(1,Math.ceil(rows.length/100)),currentPage=Math.min(page,pages-1)
 const copy=async(text:string)=>{
  setCopying(true);setMessage("")
  try{await copyText(text);setMessage("Copied to clipboard.")}catch{setMessage("Automatic copy is unavailable. Select the text in the table and copy it manually.")}finally{setCopying(false)}
 }
 const text=(cell:Snapshot["rows"][number][number]|undefined)=>String(cell?.display??cell?.value??"")
 return <section className="sheet-editor sourcing-viewer" aria-label="Read-only job sourcing">
  <SourcingDays allowAll day={day} onChange={value=>{setDay(value);setStatus(value?"all":"todo");setFocus(null);setPage(0)}} disabled={query.isPending} snapshot={snapshot||null} canAssign={false} onAssign={()=>{}} readOnly/>
  {counts&&<SourcingQueueBar counts={counts} status={status} focus={focus} onStatus={value=>{setStatus(value);setPage(0)}} onFocus={value=>{setFocus(value);setPage(0)}}/>}
  <div className="sheet-edit-toolbar"><span className="payment-muted">Read only · Select text or copy jobs</span><Button variant="outline" size="sm" disabled={!rows.length||copying} onClick={()=>void copy(serializeTSV([snapshot!.columns.map((col,index)=>text(snapshot!.rows[0]?.[index])||col.title),...rows.map(row=>row.cells.map(text))]))}><Copy size={15}/>Copy these jobs</Button></div>
  {message&&<p role="status" className="sourcing-viewer-message">{message}</p>}
  {query.isPending?<p role="status" className="inline-loading">Loading saved jobs…</p>:query.error?<p role="alert">{query.error.message}</p>:!rows.length?<p className="sourcing-viewer-message">{status==="todo"&&!focus&&!day?"Nothing to do. New jobs appear here as soon as they are added.":"No jobs match this view."}</p>:<>
   <div className="sourcing-viewer-scroll"><table className="sourcing-viewer-table"><thead><tr><th scope="col">#</th>{snapshot!.columns.map((col,index)=><th scope="col" key={col.id}>{text(snapshot!.rows[0]?.[index])||col.title}</th>)}</tr></thead><tbody>{rows.slice(currentPage*100,(currentPage+1)*100).map(({cells,index},offset)=><tr key={snapshot!.row_ids[index]} className={snapshot!.row_ids[index]===highlightId?"sourcing-viewer-highlight":undefined}><th scope="row">{currentPage*100+offset+1}</th>{cells.map((cell,col)=>{
    const value=text(cell),isLink=snapshot!.columns[col]?.kind==="link"&&/^https?:\/\//i.test(String(cell.value))
    return <td key={snapshot!.columns[col]?.id||col} style={{fontWeight:cell.style?.bold?700:undefined,fontStyle:cell.style?.italic?"italic":undefined,textAlign:cell.style?.align}}>{snapshot!.columns[col]?.kind==="company"&&expiring.has(index)?<span className="sheet-company-cell"><span>{value}</span><span className="sheet-expiring">Expiring soon</span></span>:snapshot!.columns[col]?.kind==="check"?<span aria-label={String(cell.value)==="true"?"Checked":"Not checked"}>{String(cell.value)==="true"?"✓":"—"}</span>:isLink?<div className="sourcing-viewer-link"><a href={String(cell.value)} target="_blank" rel="noopener noreferrer" title={String(cell.value)}>{jobSite(value)}</a><Button variant="ghost" size="icon" aria-label={`Copy job link ${currentPage*100+offset+1}`} disabled={copying} onClick={()=>void copy(String(cell.value))}><Copy size={14}/></Button></div>:value}</td>
   })}</tr>)}</tbody></table></div>
   {pages>1&&<div className="sourcing-viewer-pagination"><Button variant="outline" size="sm" disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}>Previous rows</Button><span>Page {currentPage+1} of {pages} · {rows.length} jobs</span><Button variant="outline" size="sm" disabled={currentPage>=pages-1} onClick={()=>setPage(currentPage+1)}>Next rows</Button></div>}
  </>}
 </section>
}

/** Rows for one queue view, ordered like the editor: To do oldest first, history newest first. */
function queueRows(snapshot:Snapshot,status:QueueStatus,focus:QueueFocus|null,day:string,now:number,dayStart:number){
 const value=(r:number,c:number)=>String(snapshot.rows[r]?.[c]?.value??"")
 return snapshot.rows.map((cells,index)=>({cells,index,life:index>0?rowLifecycle(snapshot,index,value,now,dayStart):null}))
  .filter(({index,life})=>{
   if(!life||!life.job)return false
   if(day&&(snapshot.row_dates?.[index]||"undated")!==day)return false
   const todo=!life.done&&!life.expired
   const inStatus=status==="all"||(status==="todo"?todo:status==="completed"?life.done:life.expired)
   return inStatus&&(!focus||todo&&(focus==="expiring"?life.expiring:focus==="new"?life.isNew:!life.isNew))
  })
  .sort((a,b)=>(status==="todo"?a.life!.created-b.life!.created:b.life!.created-a.life!.created)||a.index-b.index)
  .map(({cells,index,life})=>({cells,index,expiring:life!.expiring}))
}
