import {usePageState} from "@/lib/page-state"
import {useEffect,useId,useMemo,useRef,useState,type ReactNode} from "react"
import {useQuery,useQueryClient} from "@tanstack/react-query"
import {ArrowDown,ArrowDownUp,ArrowUp,Copy,ExternalLink} from "lucide-react"
import {addedColumnIndex,chicagoDayStart,compareJobAge,jobAddedAt,jobSite,nextQueueBoundary,queueCounts,readSourcingSheet,rowLifecycle,serializeTSV,type JobAgeOrder,type QueueCounts,type QueueFocus,type QueueStatus,type Snapshot,type Tab} from "@/lib/sourcing"
import {request,serverNow} from "@/lib/api"
import {useAuth} from "@/components/auth"
import {copyPaymentReport as copyText} from "@/lib/payment-report"
import {Button} from "@/components/ui/button"
import SourcingDays from "./sourcing-days"
import SourcingQueueBar from "./sourcing-queue"
import {SourcingJobAge,useSourcingAgeClock} from "./sourcing-job-age"

/** Bidders view saved jobs and record link visits independently of sheet edits. */
export default function SourcingViewer({tab,highlightId,highlightRow,initialDay,onDayChange,onQueueCounts,queueEnd,filterBar}:{tab:Tab;queueEnd?:ReactNode;filterBar?:{open:boolean;content:ReactNode};highlightId?:string;highlightRow?:number;initialDay?:string;onDayChange?:(day:string)=>void;onQueueCounts?:(counts:QueueCounts)=>void}) {
 // The same work queue as the editor: To do across all days; the day only filters history.
 const [day,setDay]=useState(initialDay??""),[page,setPage]=usePageState("/sourcing",`tab:${tab.id}:viewer-page`,0,value=>Number.isSafeInteger(value)&&value>=0)
 const [message,setMessage]=useState(""),[copying,setCopying]=useState(false)
 const [opening,setOpening]=useState(() => new Map<string,number>())
 const [openError,setOpenError]=useState(false)
 const openedDescription=useId()
 const {session}=useAuth()
 const client=useQueryClient()
 const queryKey=["sourcing-viewer",session?.workspace_id,session?.bidder_id,tab.account_id,tab.id] as const
 const resolved=useRef("")
 const query=useQuery({
  queryKey,
  queryFn:async({signal})=>{
   const sheet=await readSourcingSheet(tab.id,signal)
   const cached=client.getQueryData<Snapshot>(queryKey)
   if(!cached?.opened_row_ids?.length)return sheet
   // A read can miss a concurrent click. Retain it only for the same job instance.
   const saved=new Set(cached.opened_row_ids)
   const knownJobs=new Map(cached.row_ids.flatMap((id,index)=>saved.has(id)?[[id,cached.row_created?.[index]] as const]:[]))
   const openedIds=new Set(sheet.opened_row_ids)
   sheet.row_ids.forEach((id,index)=>{
    if(knownJobs.has(id)&&knownJobs.get(id)===sheet.row_created?.[index])openedIds.add(id)
   })
   return {...sheet,opened_row_ids:[...openedIds]}
  },
  staleTime:30_000,
  refetchOnWindowFocus:false,
  refetchOnReconnect:false,
 })
 const snapshot=query.data
 const ageNow=useSourcingAgeClock(!!snapshot)
 const [ageOrder,setAgeOrder]=useState<JobAgeOrder>()
 const AgeSortIcon=ageOrder === "asc" ? ArrowUp : ageOrder === "desc" ? ArrowDown : ArrowDownUp
 const displayColumns=useMemo(()=>{
  if(!snapshot)return []
  const indices:(number|null)[]=snapshot.columns.map((_,index)=>index)
  indices.splice(addedColumnIndex(snapshot.columns),0,null)
  return indices
 },[snapshot?.columns])
 const opened=useMemo(()=>new Set(snapshot?.opened_row_ids),[snapshot?.opened_row_ids])
 const [status,setStatus]=useState<QueueStatus>(initialDay?"all":"todo"),[focus,setFocus]=useState<QueueFocus|null>(null),[reverse,setReverse]=useState(false),[now,setNow]=useState(()=>serverNow())
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
   resolved.current=key;setDay("");setStatus("all");setFocus(null);setAgeOrder(undefined)
   const order=queueRows(snapshot,"all",null,"",serverNow(),chicagoDayStart(serverNow()))
   setPage(Math.max(0,Math.floor(order.findIndex(row=>row.index===target)/100)))
  }
 },[snapshot,highlightId,highlightRow])
 const rows=useMemo(()=>snapshot?queueRows(snapshot,status,focus,day,now,dayStart,reverse,ageOrder):[],[snapshot,status,focus,day,now,dayStart,reverse,ageOrder])
 const pages=Math.max(1,Math.ceil(rows.length/100)),currentPage=Math.min(page,pages-1)
 const copy=async(text:string)=>{
  setCopying(true);setMessage("")
  try{await copyText(text);setMessage("Copied to clipboard.")}catch{setMessage("Automatic copy is unavailable. Select the text in the table and copy it manually.")}finally{setCopying(false)}
 }
 const openJob=async(rowId:string,createdAt:number|null|undefined)=>{
  if(tab.account_id===null||createdAt==null||opened.has(rowId)||opening.get(rowId)===createdAt)return
  setOpenError(false)
  setOpening(jobs=>new Map(jobs).set(rowId,createdAt))
  try{
   await request(`/api/sourcing/tabs/${tab.id}/opened`,{
    method:"POST",body:JSON.stringify({row_id:rowId,job_created_at:createdAt}),keepalive:true,
   })
   client.setQueryData<Snapshot>(queryKey,sheet=>sheet?.row_created?.[sheet.row_ids.indexOf(rowId)]===createdAt?{
    ...sheet,opened_row_ids:[...new Set([...sheet.opened_row_ids??[],rowId])],
   }:sheet)
  }catch{
   setOpenError(true)
  }finally{
   setOpening(jobs=>{
    if(jobs.get(rowId)!==createdAt)return jobs
    const next=new Map(jobs)
    next.delete(rowId)
    return next
   })
  }
 }
 const text=(cell:Snapshot["rows"][number][number]|undefined)=>String(cell?.display??cell?.value??"")
 return <section className="sheet-editor sourcing-viewer" aria-label="Read-only job sourcing">
  {counts&&<SourcingQueueBar counts={counts} status={status} focus={focus} reverse={reverse} ageOrder={ageOrder} onStatus={value=>{setStatus(value);setFocus(null);setReverse(false);setAgeOrder(undefined);setPage(0)}} onFocus={value=>{setFocus(value);setPage(0)}} onReverse={value=>{setReverse(ageOrder?false:value);setAgeOrder(undefined);setPage(0)}} end={<><Button variant="ghost" size="sm" className="sourcing-copy-jobs" disabled={!rows.length||copying} onClick={()=>void copy(serializeTSV([snapshot!.columns.map((col,index)=>text(snapshot!.rows[0]?.[index])||col.title),...rows.map(row=>row.cells.map(text))]))}><Copy size={14}/>Copy these jobs</Button>{queueEnd}</>} below={<div className="sourcing-filter-panel" id="sourcing-tools" hidden={filterBar?!filterBar.open:false}>{filterBar?.content}<SourcingDays allowAll day={day} onChange={value=>{setDay(value);setStatus(value?"all":"todo");setFocus(null);setPage(0)}} disabled={query.isPending} snapshot={snapshot||null} canAssign={false} onAssign={()=>{}} readOnly/></div>}/>}
  {message&&<p role="status" className="sourcing-viewer-message">{message}</p>}
  {openError&&<p role="status" className="sourcing-viewer-message">OfferPath couldn’t remember an opened link. Opening it again will retry.</p>}
  <span className="sr-only" id={openedDescription}>Opened previously</span>
  {query.isPending?<p role="status" className="inline-loading">Loading saved jobs…</p>:!snapshot&&query.error?<p role="alert">{query.error.message}</p>:!rows.length?<p className="sourcing-viewer-message">{status==="todo"&&!focus&&!day?"Nothing to do. New jobs appear here as soon as they are added.":"No jobs match this view."}</p>:<>
   <div className="sourcing-viewer-scroll" role="region" aria-label="Job table" tabIndex={0}><table className="sourcing-viewer-table">
   <colgroup><col className="sheet-number-col" />{displayColumns.map(col => col == null ? <col key="added" className="sheet-added-col" />
     : <col key={snapshot!.columns[col].id} className={`sheet-${snapshot!.columns[col].kind}-col`} />)}</colgroup>
   <thead><tr><th scope="col">#</th>{displayColumns.map(col => col == null
    ? <th scope="col" key="added" className="sheet-added-col" aria-sort={ageOrder === "asc" ? "ascending" : ageOrder === "desc" ? "descending" : "none"}>
      <button type="button" className="sheet-age-sort" onClick={()=>{setAgeOrder(ageOrder === "asc" ? "desc" : ageOrder === "desc" ? undefined : "asc");setPage(0)}}>Added<AgeSortIcon size={11} aria-hidden="true" /></button>
    </th>
    : <th scope="col" key={snapshot!.columns[col].id} className={`sheet-${snapshot!.columns[col].kind}-col`}>{text(snapshot!.rows[0]?.[col])||snapshot!.columns[col].title}</th>)}</tr></thead>
   <tbody>{rows.slice(currentPage*100,(currentPage+1)*100).map(({cells,index,expiring},offset)=>{
    const rowId=snapshot!.row_ids[index],createdAt=snapshot!.row_created?.[index]
    const isOpened=opened.has(rowId)||(createdAt!=null&&opening.get(rowId)===createdAt)
    return <tr key={rowId} data-opened={isOpened||undefined} className={rowId===highlightId?"sourcing-viewer-highlight":undefined}><th scope="row">{currentPage*100+offset+1}</th>{displayColumns.map(col=>{
    if(col==null)return <td key="added" className="sheet-added-col"><SourcingJobAge added={jobAddedAt(snapshot!,index)} now={ageNow} expiring={expiring}/></td>
    const cell=cells[col],definition=snapshot!.columns[col]
    const value=text(cell),url=String(cell?.value??""),isLink=definition.kind==="link"&&/^https?:\/\//i.test(url)
    return <td key={definition.id} className={`sheet-${definition.kind}-col`} style={{fontWeight:cell?.style?.bold?700:undefined,fontStyle:cell?.style?.italic?"italic":undefined,textAlign:cell?.style?.align}}>{definition.kind==="check"?<span aria-label={url==="true"?"Checked":"Not checked"}>{url==="true"?"✓":"—"}</span>:isLink?<div className="sourcing-viewer-link">
     <a href={url} target="_blank" rel="noopener noreferrer" title={`${jobSite(value)} · ${url}`} className="sheet-link-site" aria-label={url} aria-describedby={isOpened?openedDescription:undefined} onClick={()=>void openJob(rowId,createdAt)} onAuxClick={event=>{if(event.button===1)void openJob(rowId,createdAt)}}><ExternalLink size={15} aria-hidden="true"/></a>
     <Button variant="ghost" size="icon" aria-label={`Copy job link ${currentPage*100+offset+1}`} disabled={copying} onClick={()=>void copy(url)}><Copy size={14}/></Button>
    </div>:<span className="sheet-job-text" title={value}>{value}</span>}</td>
   })}</tr>})}</tbody></table></div>
   {pages>1&&<div className="sourcing-viewer-pagination"><Button variant="outline" size="sm" disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}>Previous rows</Button><span>Page {currentPage+1} of {pages} · {rows.length} jobs</span><Button variant="outline" size="sm" disabled={currentPage>=pages-1} onClick={()=>setPage(currentPage+1)}>Next rows</Button></div>}
  </>}
 </section>
}

/** Rows for one queue view, ordered like the editor: To do oldest first, history newest first. */
function queueRows(snapshot:Snapshot,status:QueueStatus,focus:QueueFocus|null,day:string,now:number,dayStart:number,reverse=false,ageOrder?:JobAgeOrder){
 const value=(r:number,c:number)=>String(snapshot.rows[r]?.[c]?.value??"")
 return snapshot.rows.map((cells,index)=>({cells,index,life:index>0?rowLifecycle(snapshot,index,value,now,dayStart):null}))
  .filter(({index,life})=>{
   if(!life||!life.job)return false
   if(day&&(snapshot.row_dates?.[index]||"undated")!==day)return false
   const todo=!life.done&&!life.expired
   const inStatus=status==="all"||(status==="todo"?todo:status==="completed"?life.done:life.expired)
   return inStatus&&(!focus||todo&&(focus==="expiring"?life.expiring:focus==="new"?life.isNew:!life.isNew))
  })
  .sort((a,b)=>ageOrder?compareJobAge(snapshot,a.index,b.index,ageOrder):((status==="todo")!==reverse?a.life!.created-b.life!.created:b.life!.created-a.life!.created)||a.index-b.index)
  .map(({cells,index,life})=>({cells,index,expiring:life!.expiring}))
}
