import {useEffect,useMemo,useState} from "react"
import {useSearchParams} from "react-router-dom"
import {useQuery} from "@tanstack/react-query"
import {Copy,FileSpreadsheet,RefreshCw,Search} from "lucide-react"
import {request} from "@/lib/api"
import {serializeTSV,type Snapshot} from "@/lib/sourcing"
import {SheetGrid} from "@/components/sourcing-grid"
import SourcingDays from "@/components/sourcing-days"
import {copyPaymentReport as copyText} from "@/lib/payment-report"
import {Button} from "@/components/ui/button"
import {Loading,useToast} from "@/components/common"
import "./sourcing.css"

type Job={id:string;company:string;role:string;link:string}
type Results={items:Job[];next_cursor:string|null;incomplete:boolean}

export default function JobLinks(){
 const [params,setParams]=useSearchParams()
 const keyword=params.get("q")||""
 const day=params.get('day')||''
 const [draft,setDraft]=useState(keyword),[cursors,setCursors]=useState([""]),[selected,setSelected]=useState<Set<string>>(new Set()),[copying,setCopying]=useState(false)
 const toast=useToast()
 const cursor=cursors[cursors.length-1]
 useEffect(()=>{setDraft(keyword)},[keyword])
 useEffect(()=>{setCursors([""]);setSelected(new Set())},[keyword,day])
 const changeDay=(value:string)=>{
  setCursors(['']);setSelected(new Set())
  const next=new URLSearchParams(params)
  if(value)next.set('day',value);else next.delete('day')
  setParams(next)
 }
 const query=useQuery({queryKey:["job-links",keyword,day,cursor],queryFn:({signal})=>request<Results>(`/api/job-links?${new URLSearchParams({q:keyword,cursor,day})}`,{signal})})
 const rows=query.data?.items||[]
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
   <div className="sourcing-toolbar-days"><SourcingDays day={day} onChange={changeDay} disabled={false} snapshot={null} onAssign={()=>{}} canAssign={false} readOnly compact allowAll/></div>
   <form className="sourcing-search job-links-search" onSubmit={event=>{event.preventDefault();setCursors([""]);setSelected(new Set());const next=new URLSearchParams(params);if(draft.trim())next.set('q',draft.trim());else next.delete('q');setParams(next);}}>
    <Search size={16} aria-hidden="true"/>
    <input aria-label="Search job links" value={draft} onChange={event=>setDraft(event.target.value)} maxLength={200} placeholder="Company, role or job link"/>
    <Button type="submit" variant="outline" size="sm">Search</Button>
   </form>
   <Button variant="outline" size="sm" disabled={query.isFetching} aria-label="Refresh job links" onClick={()=>void query.refetch()}><RefreshCw size={15}/></Button>
  </div>
  <section className="sheet-editor">
   <div className="sheet-edit-toolbar">
    <span>{rows.length} links{chosen.length?` · ${chosen.length} selected`:''}</span>
    <Button variant="outline" size="sm" title="Copy selected URLs, one per line" disabled={!chosen.length||copying||query.isFetching} onClick={()=>void copy(chosen.map(row=>row.link).join('\n'))}><Copy size={15}/>Copy links</Button>
    <Button variant="outline" size="sm" disabled={!chosen.length||copying||query.isFetching} onClick={()=>void copy(serializeTSV(chosen.map(row=>[row.company,row.role,row.link])))}><Copy size={15}/>Copy selected rows</Button>
   </div>
   {query.data?.incomplete&&<p role="alert" className="inline-error">Some saved links are temporarily unavailable. Refresh to search the complete library.</p>}
   {query.isPending?<Loading label="Loading job links…"/>:query.isError?<p role="alert" className="inline-error">{query.error.message}</p>:<>
    <SheetGrid snapshot={snapshot} changes={[]} onChange={()=>{}} disabled ariaLabel="Shared job links"
     onSelection={selection=>setSelected(new Set(selection.rows.map(row=>rows[row-1]?.id).filter((id):id is string=>!!id)))}/>
    {!rows.length&&<p className="sourcing-viewer-message">No matching job links.</p>}
   </>}
   <div className="sourcing-viewer-pagination">
    <Button variant="outline" size="sm" disabled={cursors.length===1||query.isFetching} onClick={()=>{setSelected(new Set());setCursors(cursors.slice(0,-1))}}>Previous</Button>
    <span>Page {cursors.length}</span>
    <Button variant="outline" size="sm" disabled={!query.data?.next_cursor||query.isFetching} onClick={()=>{setSelected(new Set());setCursors([...cursors,query.data!.next_cursor!])}}>Next</Button>
   </div>
  </section>
 </div>
}
