import {useEffect,useMemo,useRef,useState} from "react"
import {useQuery,useQueryClient} from "@tanstack/react-query"
import {api,request,getWorkspaceIdentity} from "@/lib/api"
import {Button} from "./ui/button"
import {Card} from "./ui/card"
import {Dialog,DialogContent,DialogTitle,DialogDescription} from "./ui/dialog"
import "./backup-management.css"

type BackupStatus={enabled:boolean;retain:number;folder:string;running:boolean;last_error:string|null;last_success:string|null;next_due:string|null;archives:{name:string;size:number;created_at:string;automatic:boolean}[]}
const date=(value:string|null)=>value?new Date(value).toLocaleString():"Not yet"
const size=(bytes:number)=>bytes>=1048576?`${(bytes/1048576).toFixed(1)} MB`:bytes>=1024?`${Math.round(bytes/1024)} KB`:`${bytes} B`
async function downloadBackup(name:string){
  const workspace=getWorkspaceIdentity()
  const {url}=await api.post<{url:string}>(`/api/admin/backups/download-ticket/${encodeURIComponent(name)}`,{})
  if(workspace!==getWorkspaceIdentity())throw new Error("Workspace changed. Reload before continuing.")
  let target:URL
  try{target=new URL(url,window.location.origin)}catch{throw new Error("OfferPath returned an unexpected backup response. Please try again.")}
  if(typeof url!=="string"||!url.startsWith("/api/admin/backups/file/")||target.origin!==window.location.origin||target.pathname!==`/api/admin/backups/file/${encodeURIComponent(name)}`||target.hash||!target.searchParams.get("ticket"))throw new Error("OfferPath returned an unexpected backup response. Please try again.")
  const anchor=document.createElement("a")
  try{anchor.href=url;anchor.download=name;document.body.appendChild(anchor);anchor.click()}finally{anchor.remove()}
}
const ARCHIVES_PER_PAGE=8
export default function BackupManagement({active=true}:{active?:boolean}){
  const client=useQueryClient(),[draft,setDraft]=useState<{enabled:boolean;retain:number}|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState("")
  const [historyOpen,setHistoryOpen]=useState(false),[archiveType,setArchiveType]=useState('all'),[page,setPage]=useState(0)
  const historyTrigger=useRef<HTMLButtonElement>(null)
  const query=useQuery({queryKey:["owner-backups"],queryFn:({ signal }) =>request<BackupStatus>("/api/admin/backups", { signal }),enabled:active,refetchInterval:q=>active&&q.state.data?.running?10000:false})
  const data=query.data,settings=draft||(data?{enabled:data.enabled,retain:data.retain}:null)
  const archives=useMemo(()=>[...(data?.archives||[])].sort((a,b)=>(Date.parse(b.created_at)||0)-(Date.parse(a.created_at)||0)||a.name.localeCompare(b.name)),[data?.archives])
  const filtered=archives.filter(a=>archiveType==='all'||(archiveType==='automatic'?a.automatic:!a.automatic))
  const pages=Math.max(1,Math.ceil(filtered.length/ARCHIVES_PER_PAGE)),currentPage=Math.min(page,pages-1)
  const visible=filtered.slice(currentPage*ARCHIVES_PER_PAGE,(currentPage+1)*ARCHIVES_PER_PAGE)
  const latest=archives[0]
  useEffect(()=>{if(!active)setHistoryOpen(false)},[active])
  const action=async(fn:()=>Promise<unknown>,message:string)=>{setBusy(true);setError("");setNotice("");try{await fn();setNotice(message);await client.invalidateQueries({queryKey:["owner-backups"]})}catch(e){setError(e instanceof Error?e.message:"Backup action failed. Please try again.")}finally{setBusy(false)}}
  return <Card className="backup-management"><div className="backup-heading"><div><h2>Backup &amp; restore</h2><p>Your complete installation, across every workspace.</p></div><Button size="sm" disabled={!data||busy||data.running} onClick={()=>void action(()=>api.post("/api/admin/backups/create",{}),"Backup created.")}>{data?.running?"Creating backup...":"Create backup"}</Button></div>
    {query.isPending&&<p role="status" className="inline-loading">Loading backups...</p>}{query.error&&<p role="alert" className="inline-error">{query.error.message}</p>}{error&&<p role="alert" className="inline-error">{error}</p>}{notice&&<p role="status">{notice}</p>}
    {data&&settings&&<>
      <dl className="backup-overview"><div><dt>Last successful backup</dt><dd>{date(data.last_success)}</dd></div><div><dt>Next automatic backup</dt><dd>{data.enabled?date(data.next_due):"Disabled"}</dd></div><div><dt>Saved backups</dt><dd>{archives.length}<small>{archives.filter(a=>a.automatic).length} automatic</small></dd></div></dl>
      <div className="backup-quick-actions">{latest&&<Button size="sm" variant="outline" disabled={busy} aria-label="Download latest backup" title={`${latest.name} / ${size(latest.size)}`} onClick={()=>void action(()=>downloadBackup(latest.name),"Backup download started.")}>Download latest</Button>}<Button ref={historyTrigger} size="sm" variant="outline" aria-label="Browse backups" onClick={()=>{setPage(0);setHistoryOpen(true)}}>Browse backups <span className="backup-count">{archives.length}</span></Button></div>
      {data.last_error&&<p role="alert" className="inline-error">Last backup failed: {data.last_error}</p>}
      <details className="backup-settings-panel"><summary><span>Automatic backups</span><small>{data.enabled?`Daily / keep ${data.retain}`:'Off'}</small></summary>
        <form className="backup-settings" onSubmit={e=>{e.preventDefault();if(!Number.isInteger(settings.retain)||settings.retain<1||settings.retain>30){setError("Choose between 1 and 30 automatic backups.");return}void action(async()=>{await api.post("/api/admin/backups/settings",settings);setDraft(null)},"Backup settings saved.")}}>
          <label className="backup-toggle"><input type="checkbox" disabled={busy} checked={settings.enabled} onChange={e=>setDraft({...settings,enabled:e.target.checked})}/>Daily automatic backups</label>
          <label>Automatic backups to keep<input type="number" min={1} max={30} required disabled={busy} value={Number.isNaN(settings.retain)?"":settings.retain} onChange={e=>setDraft({...settings,retain:e.target.valueAsNumber})}/></label>
          <Button size="sm" variant="outline" disabled={busy}>Save backup settings</Button>
        </form>
      </details>
      <details className="backup-location"><summary>Backup folder</summary><p className="backup-folder">{data.folder}</p></details>
    </>}
    <details className="backup-restore"><summary>Restore on another PC</summary><ol><li>Install the same OfferPath release and copy the ZIP to the destination PC.</li><li>Stop the OfferPath server, then inspect and restore from a terminal:<code>python -m mailcheck backup inspect FILE.zip</code><code>python -m mailcheck backup restore FILE.zip</code>Restore uses a fresh destination by default. Replacing existing data requires the explicit <code className="backup-inline-code">--replace</code> option and creates a rollback backup.</li><li>Start OfferPath and sign in again. Reconnect Outlook and IMAP accounts, then check model/server addresses, Ollama models, Cloudflare and other external services, and network settings.</li></ol><p>Backups preserve accounts and business data. Credentials and external services must be reconnected after restore.</p></details>
    <p className="backup-sensitive">Backups contain private mail. Store them securely.</p>
    <Dialog open={active&&historyOpen} onOpenChange={setHistoryOpen}><DialogContent className="backup-history-dialog" onCloseAutoFocus={event=>{event.preventDefault();if(active)historyTrigger.current?.focus()}}><DialogTitle>Available backups</DialogTitle><DialogDescription>Newest first. Download a backup when you need it.</DialogDescription>
      <div className="backup-browser-toolbar"><label>Backup type<select value={archiveType} onChange={e=>{setArchiveType(e.target.value);setPage(0)}}><option value="all">All backups</option><option value="automatic">Automatic</option><option value="manual">Manual</option></select></label><span>{filtered.length} backups</span></div>
      {error&&<p role="alert" className="inline-error">{error}</p>}
      {visible.length?<ul className="backup-history">{visible.map(archive=><li key={archive.name}><span className={`backup-kind ${archive.automatic?'is-automatic':''}`}>{archive.automatic?'Auto':'Manual'}</span><div><strong>{date(archive.created_at)} <small>{size(archive.size)}</small></strong><span title={archive.name}>{archive.name}</span></div><Button size="sm" variant="outline" disabled={busy} aria-label={`Download ${archive.name}`} onClick={()=>void action(()=>downloadBackup(archive.name),"Backup download started.")}>Download</Button></li>)}</ul>:<p className="form-hint">{archives.length?'No backups of this type.':'No backups yet. Create your first backup above.'}</p>}
      <div className="backup-pagination"><Button size="sm" variant="outline" aria-label="Previous backups" disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}>Previous</Button><span>Page {currentPage+1} of {pages}</span><Button size="sm" variant="outline" aria-label="Next backups" disabled={currentPage+1>=pages} onClick={()=>setPage(currentPage+1)}>Next</Button></div>
    </DialogContent></Dialog>
  </Card>
}
