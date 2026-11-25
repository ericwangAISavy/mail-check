import {useEffect,useMemo,useState} from "react"
import {useSearchParams} from "react-router-dom"
import {useQuery,useQueryClient} from "@tanstack/react-query"
import {Copy,FileSpreadsheet,RefreshCw,Search} from "lucide-react"
import {ApiError,request} from "@/lib/api"
import {chicagoDay,serializeTSV,type Snapshot} from "@/lib/sourcing"
import {SheetGrid} from "@/components/sourcing-grid"
import {copyPaymentReport as copyText} from "@/lib/payment-report"
import {Button} from "@/components/ui/button"
import {Loading,useToast} from "@/components/common"
import "./sourcing.css"

type Job={id:string;company:string;role:string;link:string}
type Results={items:Job[];next_cursor:string|null;incomplete:boolean;incomplete_reason?:'own_links_unavailable'}
const PAGE_SIZES=[100,200,300,400,500]
const deniedAccess=(error:unknown)=>error instanceof ApiError&&(error.status===401||error.status===403)
const queryFlag=(params:URLSearchParams,name:string,fallback:boolean)=>{
 const value=params.get(name)?.toLowerCase()
 if(value&&['true','1','yes','on','t','y'].includes(value))return true
 if(value&&['false','0','no','off','f','n'].includes(value))return false
 return fallback
}

export default function JobLinks(){
 const client=useQueryClient()
 const [params,setParams]=useSearchParams()
 const keyword=params.get("q")||""
 const legacyDay=params.get('day')||''
 const startDate=params.get('start_date')??legacyDay
 const endDate=params.get('end_date')??legacyDay
 const excludeMyLinks=queryFlag(params,'exclude_my_links',true)
 const excludeOnePage=queryFlag(params,'exclude_one_page',false)
 const rangeError=startDate&&endDate&&startDate>endDate?'The end date must be on or after the start date.':''
 const requestedLimit=Number(params.get('limit')||100)
 const limit=PAGE_SIZES.includes(requestedLimit)?requestedLimit:100
 const [draft,setDraft]=useState(keyword),[cursors,setCursors]=useState([""]),[selected,setSelected]=useState<Set<string>>(new Set()),[copying,setCopying]=useState(false)
 const toast=useToast()
 const cursor=cursors[cursors.length-1]
 useEffect(()=>{setDraft(keyword)},[keyword])
 useEffect(()=>{setCursors([""]);setSelected(new Set())},[keyword,startDate,endDate,limit,excludeMyLinks,excludeOnePage])
 const changeFilter=(name:string,enabled:boolean)=>{
  setCursors(['']);setSelected(new Set())
  const next=new URLSearchParams(params);next.set(name,String(enabled));setParams(next)
 }
 const changeRange=(start:string,end:string)=>{
  setCursors(['']);setSelected(new Set())
  const next=new URLSearchParams(params)
  next.delete('day')
  if(start)next.set('start_date',start);else next.delete('start_date')
  if(end)next.set('end_date',end);else next.delete('end_date')
  setParams(next)
 }
 const query=useQuery({queryKey:["job-links",keyword,startDate,endDate,limit,excludeMyLinks,excludeOnePage,cursor],queryFn:({signal})=>request<Results>(`/api/job-links?${new URLSearchParams({q:keyword,cursor,start_date:startDate,end_date:endDate,limit:String(limit),exclude_my_links:String(excludeMyLinks),exclude_one_page:String(excludeOnePage)})}`,{signal}),enabled:!rangeError,retry:(count,error)=>!deniedAccess(error)&&count<1})
 const denied=deniedAccess(query.error)
 useEffect(()=>{
  if(!denied)return
  setSelected(new Set())
  client.removeQueries({queryKey:['job-links'],type:'inactive'})
  void client.invalidateQueries({queryKey:['auth']})
 },[denied,client])
 const rows=query.isError||rangeError?[]:query.data?.items||[]
 const chosen=rows.filter(row=>selected.has(row.id))
 const snapshot=useMemo<Snapshot>(()=>{
  const columns:Snapshot['columns']=[{id:'company',title:'Company',kind:'company',width:220},{id:'role',title:'Role',kind:'role',width:220},{id:'link',title:'Job link',kind:'link',width:220}]
  const cell=(value:string)=>({value,display:value,formula:false,link:'',version:1,style:{wrap:false}})
  return {id:0,title:'Job links',revision:'1',structure_revision:1,refreshed_at:0,columns,
   row_ids:['',...rows.map(row=>row.id)],rows:[columns.map(col=>cell(col.title)),...rows.map(row=>[cell(row.company),cell(row.role),cell(row.link)])],
   properties:{gridProperties:{rowCount:rows.length+1,columnCount:3}}}
 },[rows])
 const copy=async(text:string)=>{
  setCopying(true)
  try{await copyText(text);toast("Copied.","success")}
  catch{toast("Could not copy. Focus the sheet and press Ctrl/Cmd+C to copy the selected rows.","error")}
  finally{setCopying(false)}
 }
 return <div className="sourcing-page job-links-page">
  <div className="sourcing-toolbar">
   <FileSpreadsheet size={22}/><strong>Job links</strong>
   <div className="sourcing-toolbar-days"><div className="sheet-days job-links-date-range" role="group" aria-label="Job date range">
    <Button size="sm" variant="ghost" aria-pressed={!startDate&&!endDate} onClick={()=>changeRange('','')}>All dates</Button>
    <label>From<input type="date" value={startDate} max={endDate||undefined} onChange={event=>changeRange(event.target.value,endDate)} aria-invalid={!!rangeError} aria-describedby={rangeError?'job-links-range-error':undefined}/></label>
    <label>To<input type="date" value={endDate} min={startDate||undefined} onChange={event=>changeRange(startDate,event.target.value)} aria-invalid={!!rangeError} aria-describedby={rangeError?'job-links-range-error':undefined}/></label>
    <Button size="sm" variant="ghost" aria-pressed={startDate===chicagoDay()&&endDate===chicagoDay()} onClick={()=>changeRange(chicagoDay(),chicagoDay())}>Today</Button>
   </div></div>
   <form className="sourcing-search job-links-search" onSubmit={event=>{event.preventDefault();setCursors([""]);setSelected(new Set());const next=new URLSearchParams(params);if(draft.trim())next.set('q',draft.trim());else next.delete('q');setParams(next);}}>
    <Search size={16} aria-hidden="true"/>
    <input aria-label="Search job links" value={draft} onChange={event=>setDraft(event.target.value)} maxLength={200} placeholder="Company, role or job link"/>
   </form>
   <Button variant="outline" size="sm" disabled={!!rangeError||query.isFetching} aria-label="Refresh job links" onClick={()=>void query.refetch()}><RefreshCw size={15}/></Button>
  </div>
  <section className="sheet-editor">
   <div className="sheet-edit-toolbar">
    <span>{rows.length} links{chosen.length?` · ${chosen.length} selected`:''}</span>
    <Button variant="outline" size="sm" title="Copy selected URLs, one per line" disabled={!chosen.length||copying||query.isFetching} onClick={()=>void copy(chosen.map(row=>row.link).join('\n'))}><Copy size={15}/>Copy links</Button>
    <Button variant="outline" size="sm" disabled={!chosen.length||copying||query.isFetching} onClick={()=>void copy(serializeTSV(chosen.map(row=>[row.company,row.role,row.link])))}><Copy size={15}/>Copy selected rows</Button>
    <div className="job-links-filters" role="group" aria-label="Job link filters">
     <label title="Hide links already saved in this workspace, including copies from other workspaces"><input type="checkbox" checked={excludeMyLinks} onChange={event=>changeFilter('exclude_my_links',event.target.checked)}/>Exclude my links</label>
     <label title="Hide Greenhouse and Ashby application links"><input type="checkbox" checked={excludeOnePage} onChange={event=>changeFilter('exclude_one_page',event.target.checked)}/>Exclude one-page links</label>
    </div>
   </div>
   {!query.isError&&!rangeError&&query.data?.incomplete&&<div role="alert" className="inline-error">{excludeMyLinks&&query.data.incomplete_reason==='own_links_unavailable'?<>Your saved links could not be checked, so Exclude my links could not be applied. Refresh to retry, or include your links to search the library.<Button className="ml-2" variant="outline" size="sm" onClick={()=>changeFilter('exclude_my_links',false)}>Include my links</Button></>:<>Some saved links are temporarily unavailable. Refresh to search the complete library.</>}</div>}
   {rangeError?<p role="alert" id="job-links-range-error" className="inline-error">{rangeError}</p>:query.isPending?<Loading label="Loading job links…"/>:query.isError?<p role="alert" className="inline-error">{query.error.message}</p>:<>
    <SheetGrid snapshot={snapshot} changes={[]} onChange={()=>{}} disabled ariaLabel="Shared job links"
     onSelection={selection=>setSelected(new Set(selection.rows.map(row=>rows[row-1]?.id).filter((id):id is string=>!!id)))}/>
    {!rows.length&&!query.data?.incomplete&&<p className="sourcing-viewer-message">No matching job links.</p>}
   </>}
   <div className="sourcing-viewer-pagination">
    <Button variant="outline" size="sm" disabled={cursors.length===1||query.isFetching} onClick={()=>{setSelected(new Set());setCursors(cursors.slice(0,-1))}}>Previous</Button>
    <span>Page {cursors.length}</span>
    <Button variant="outline" size="sm" disabled={!query.data?.next_cursor||query.isFetching} onClick={()=>{setSelected(new Set());setCursors([...cursors,query.data!.next_cursor!])}}>Next</Button>
    <label className="job-links-page-size">Items per page
     <select value={limit} onChange={event=>{setCursors(['']);setSelected(new Set());const next=new URLSearchParams(params);next.set('limit',event.target.value);setParams(next);}}>
      {PAGE_SIZES.map(size=><option key={size} value={size}>{size}</option>)}
     </select>
    </label>
   </div>
  </section>
 </div>
}
