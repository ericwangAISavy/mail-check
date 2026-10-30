import {useState} from "react"
import {useQuery,useQueryClient} from "@tanstack/react-query"
import {api,request,getWorkspaceIdentity} from "@/lib/api"
import {Button} from "./ui/button"
import {Card} from "./ui/card"
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
export default function BackupManagement(){
  const client=useQueryClient(),[draft,setDraft]=useState<{enabled:boolean;retain:number}|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState("")
  const query=useQuery({queryKey:["owner-backups"],queryFn:()=>request<BackupStatus>("/api/admin/backups"),refetchInterval:q=>q.state.data?.running?10000:false})
  const data=query.data,settings=draft||(data?{enabled:data.enabled,retain:data.retain}:null)
  const action=async(fn:()=>Promise<unknown>,message:string)=>{setBusy(true);setError("");setNotice("");try{await fn();setNotice(message);await client.invalidateQueries({queryKey:["owner-backups"]})}catch(e){setError(e instanceof Error?e.message:"Backup action failed. Please try again.")}finally{setBusy(false)}}
  return <Card className="backup-management"><div className="backup-heading"><div><h2>Backup &amp; restore</h2><p>Move your complete installation, including every admin workspace, to another PC.</p></div><Button disabled={!data||busy||data.running} onClick={()=>void action(()=>api.post("/api/admin/backups/create",{}),"Backup created.")}>{data?.running?"Creating backup…":"Create backup"}</Button></div>
    <p className="backup-sensitive">Backups are plain ZIP files containing private mail and password hashes. Store and share them securely.</p>
    {query.isPending&&<p role="status">Loading backups…</p>}{query.error&&<p role="alert" className="inline-error">{query.error.message}</p>}{error&&<p role="alert" className="inline-error">{error}</p>}{notice&&<p role="status">{notice}</p>}
    {data&&settings&&<><form className="backup-settings" onSubmit={e=>{e.preventDefault();if(!Number.isInteger(settings.retain)||settings.retain<1||settings.retain>30){setError("Choose between 1 and 30 automatic backups.");return}void action(async()=>{await api.post("/api/admin/backups/settings",settings);setDraft(null)},"Backup settings saved.")}}><label className="backup-toggle"><input type="checkbox" checked={settings.enabled} onChange={e=>setDraft({...settings,enabled:e.target.checked})}/>Daily automatic backups</label><label>Automatic backups to keep<input type="number" min={1} max={30} required value={Number.isNaN(settings.retain)?"":settings.retain} onChange={e=>setDraft({...settings,retain:e.target.valueAsNumber})}/></label><Button variant="outline" disabled={busy}>Save backup settings</Button></form>
      <p className="form-hint">Runs once every 24 hours while the server is running. Retention applies to automatic backups.</p><dl className="backup-status"><div><dt>Last successful backup</dt><dd>{date(data.last_success)}</dd></div><div><dt>Next automatic backup</dt><dd>{data.enabled?date(data.next_due):"Disabled"}</dd></div><div><dt>Backup folder</dt><dd className="backup-folder">{data.folder}</dd></div></dl>{data.last_error&&<p role="alert" className="inline-error">Last backup failed: {data.last_error}</p>}
      <h3>Available backups</h3>{data.archives.length?<ul className="backup-history">{data.archives.map(archive=><li key={archive.name}><div><strong>{archive.name}</strong><span>{date(archive.created_at)} · {size(archive.size)} · {archive.automatic?"Automatic":"Manual"}</span></div><Button size="sm" variant="outline" disabled={busy} aria-label={`Download ${archive.name}`} onClick={()=>void action(()=>downloadBackup(archive.name),"Backup download started.")}>Download</Button></li>)}</ul>:<p className="form-hint">No backups yet. Create your first backup above.</p>}</>}
    <details className="backup-restore"><summary>Restore on another PC</summary><ol><li>Install the same OfferPath release and copy the ZIP to the destination PC.</li><li>Stop the OfferPath server, then inspect and restore from a terminal:<code>python -m mailcheck backup inspect FILE.zip</code><code>python -m mailcheck backup restore FILE.zip</code>Restore uses a fresh destination by default. Replacing existing data requires the explicit <code className="backup-inline-code">--replace</code> option and creates a rollback backup.</li><li>Start OfferPath and sign in again. Reconnect Outlook and IMAP accounts, then check model/server addresses, Ollama models, Cloudflare and other external services, and network settings.</li></ol><p>Backups preserve accounts and business data. Credentials and external services must be reconnected after restore.</p></details>
  </Card>
}
