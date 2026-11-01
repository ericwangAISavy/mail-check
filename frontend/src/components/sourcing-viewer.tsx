import {useEffect,useRef,useState} from "react"
import {useQuery} from "@tanstack/react-query"
import {Copy} from "lucide-react"
import {request} from "@/lib/api"
import {chicagoDay,serializeTSV,type Snapshot,type Tab} from "@/lib/sourcing"
import {copyPaymentReport as copyText} from "@/lib/payment-report"
import {Button} from "@/components/ui/button"
import SourcingDays from "./sourcing-days"

/** Deliberately separate from the editor: no mutation, draft or autosave hooks. */
export default function SourcingViewer({tab,highlightId,highlightRow,initialDay,onDayChange}:{tab:Tab;highlightId?:string;highlightRow?:number;initialDay?:string;onDayChange?:(day:string)=>void}) {
 const [day,setDay]=useState(initialDay||chicagoDay()),[page,setPage]=useState(0)
 const [message,setMessage]=useState(""),[copying,setCopying]=useState(false)
 const resolved=useRef("")
 const query=useQuery({queryKey:["sourcing-viewer",tab.id],queryFn:()=>request<Snapshot>(`/api/sourcing/tabs/${tab.id}`),staleTime:Infinity,refetchOnWindowFocus:false,refetchOnReconnect:false})
 const snapshot=query.data
 useEffect(()=>{onDayChange?.(day);setMessage("")},[day,onDayChange])
 useEffect(()=>{
  if(!snapshot)return
  const target=highlightId? snapshot.row_ids.indexOf(highlightId):highlightRow
  const key=highlightId||String(highlightRow??"")
  if(key&&key!==resolved.current&&target!=null&&target>0){
   resolved.current=key;setDay(snapshot.row_dates?.[target]||"undated")
   const targetDate=snapshot.row_dates?.[target]||"undated"
   const preceding=snapshot.rows.slice(1,target).filter((row,index)=>(snapshot.row_dates?.[index+1]||"undated")===targetDate&&row.some((cell,col)=>snapshot.columns[col]?.kind!=="check"&&String(cell.value).trim())).length
   setPage(Math.floor(preceding/100))
  }
 },[snapshot,highlightId,highlightRow])
 const rows=snapshot?.rows.map((cells,index)=>({cells,index})).filter(({cells,index})=>index>0&&(snapshot.row_dates?.[index]||"undated")===(day||"undated")&&cells.some((cell,col)=>snapshot.columns[col]?.kind!=="check"&&String(cell.value).trim()))||[]
 const pages=Math.max(1,Math.ceil(rows.length/100)),currentPage=Math.min(page,pages-1)
 const copy=async(text:string)=>{
  setCopying(true);setMessage("")
  try{await copyText(text);setMessage("Copied to clipboard.")}catch{setMessage("Automatic copy is unavailable. Select the text in the table and copy it manually.")}finally{setCopying(false)}
 }
 const text=(cell:Snapshot["rows"][number][number]|undefined)=>String(cell?.display??cell?.value??"")
 return <section className="sheet-editor sourcing-viewer" aria-label="Read-only job sourcing">
  <SourcingDays day={day} onChange={value=>{setDay(value);setPage(0)}} disabled={query.isPending} snapshot={snapshot||null} canAssign={false} onAssign={()=>{}} readOnly/>
  <div className="sheet-edit-toolbar"><span className="payment-muted">Read only · Select text or copy jobs</span><Button variant="outline" size="sm" disabled={!rows.length||copying} onClick={()=>void copy(serializeTSV([snapshot!.columns.map((col,index)=>text(snapshot!.rows[0]?.[index])||col.title),...rows.map(row=>row.cells.map(text))]))}><Copy size={15}/>Copy jobs for this date</Button></div>
  {message&&<p role="status" className="sourcing-viewer-message">{message}</p>}
  {query.isPending?<p role="status">Loading saved jobs…</p>:query.error?<p role="alert">{query.error.message}</p>:!rows.length?<p className="sourcing-viewer-message">No saved jobs for this date. Choose another date or History.</p>:<>
   <div className="sourcing-viewer-scroll"><table className="sourcing-viewer-table"><thead><tr><th scope="col">#</th>{snapshot!.columns.map((col,index)=><th scope="col" key={col.id}>{text(snapshot!.rows[0]?.[index])||col.title}</th>)}</tr></thead><tbody>{rows.slice(currentPage*100,(currentPage+1)*100).map(({cells,index},offset)=><tr key={snapshot!.row_ids[index]} className={snapshot!.row_ids[index]===highlightId?"sourcing-viewer-highlight":undefined}><th scope="row">{currentPage*100+offset+1}</th>{cells.map((cell,col)=>{
    const value=text(cell),isLink=snapshot!.columns[col]?.kind==="link"&&/^https?:\/\//i.test(String(cell.value))
    return <td key={snapshot!.columns[col]?.id||col} style={{fontWeight:cell.style?.bold?700:undefined,fontStyle:cell.style?.italic?"italic":undefined,textAlign:cell.style?.align}}>{snapshot!.columns[col]?.kind==="check"?<span aria-label={String(cell.value)==="true"?"Checked":"Not checked"}>{String(cell.value)==="true"?"✓":"—"}</span>:isLink?<div className="sourcing-viewer-link"><a href={String(cell.value)} target="_blank" rel="noopener noreferrer">{value}</a><Button variant="ghost" size="icon" aria-label={`Copy job link ${currentPage*100+offset+1}`} disabled={copying} onClick={()=>void copy(String(cell.value))}><Copy size={14}/></Button></div>:value}</td>
   })}</tr>)}</tbody></table></div>
   {pages>1&&<div className="sourcing-viewer-pagination"><Button variant="outline" size="sm" disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}>Previous rows</Button><span>Page {currentPage+1} of {pages} · {rows.length} jobs</span><Button variant="outline" size="sm" disabled={currentPage>=pages-1} onClick={()=>setPage(currentPage+1)}>Next rows</Button></div>}
  </>}
 </section>
}
