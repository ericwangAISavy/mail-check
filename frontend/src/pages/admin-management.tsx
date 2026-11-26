import "./admin-management.css"
import BackupManagement from "@/components/backup-management"
import {useState} from "react"
import {useQuery,useQueryClient} from "@tanstack/react-query"
import {Plus,Search,ChevronRight,Users,Database,History,ArrowLeft} from "lucide-react"
import {api,request,setWorkspaceIdentity} from "@/lib/api"
import {useAuth} from "@/components/auth"
import {Button} from "@/components/ui/button"
import {Card} from "@/components/ui/card"
import {Loading,PageHeading} from "@/components/common"

type Admin={id:number;username:string;owner:number;enabled:number;must_change:number;job_links_access?:boolean|number;workspace_id:string;workspace_name:string;health:string;online?:boolean}
type Area='workspaces'|'create'|'backups'|'activity'
const tasks=[{id:'workspaces',label:'Workspaces',Icon:Users},{id:'backups',label:'Backups',Icon:Database},{id:'activity',label:'Activity',Icon:History}] as const
export default function AdminManagement(){
  const {session}=useAuth(),client=useQueryClient()
  const [area,setArea]=useState<Area>('workspaces'),[backupsVisited,setBackupsVisited]=useState(false)
  const [selectedId,setSelectedId]=useState<number|null>(null),[search,setSearch]=useState(''),[filter,setFilter]=useState('all')
  const [draft,setDraft]=useState({username:'',workspace:'',password:''})
  const [error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[resetting,setResetting]=useState<number|null>(null)
  const query=useQuery({queryKey:['owner-admins'],queryFn:({signal})=>request<{admins:Admin[];max_workspaces:number}>('/api/admin/users',{signal}),enabled:!!session?.is_owner,refetchInterval:area==='workspaces'?10000:false})
  const audit=useQuery({queryKey:['owner-audit'],queryFn:({signal})=>request<{events:{id:number;at:number;actor:number;action:string;target:string}[]}>('/api/admin/audit',{signal}),enabled:!!session?.is_owner&&area==='activity',staleTime:30000})
  const admins=query.data?.admins||[]
  const visible=admins.filter(a=>(filter==='all'||(filter==='active'?!!a.enabled:!a.enabled))&&`${a.workspace_name} ${a.username}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))
  const selected=visible.find(a=>a.id===selectedId)||visible.find(a=>a.workspace_id===session?.workspace_id)||visible[0]
  const choose=(next:Area)=>{setArea(next);setResetting(null);if(next==='backups')setBackupsVisited(true)}
  const write=async(url:string,body:unknown)=>{
    setBusy(true);setError('');setNotice('')
    try{await api.post(url,body);await Promise.all([client.invalidateQueries({queryKey:['owner-admins']}),client.invalidateQueries({queryKey:['owner-audit']})]);return true}
    catch(e){setError(e instanceof Error?e.message:'Could not save.');return false}
    finally{setBusy(false)}
  }
  const remove=async(admin:Admin)=>{
    if(busy||!window.confirm(`Remove ${admin.workspace_name} (${admin.username}) and its admin access? All admin and bidder sessions will be signed out and workspace jobs stopped. Stored workspace data is retained offline, but this workspace cannot be re-enabled here. Already dispatched emails cannot be recalled.`))return
    if(await write(`/api/admin/users/${admin.id}/remove`,{username:admin.username})){
      setResetting(null);setNotice(`${admin.workspace_name} removed. Stored workspace data is retained offline.`)
    }
  }
  const open=async(wid:string)=>{
    if(busy||!window.confirm('Open this workspace? Save work in other tabs first.'))return
    setBusy(true);setError('');setNotice('')
    try{await api.post('/api/admin/switch',{workspace_id:wid});setWorkspaceIdentity();client.clear();window.location.assign('/')}
    catch(e){setError(e instanceof Error?e.message:'Could not switch workspace.');setBusy(false)}
  }
  if(!session?.is_owner)return <div className="page-wrap"><PageHeading title="Owner access required"/></div>
  return <div className="page-wrap admin-management-page">
    <PageHeading title="Admin management" description="Workspaces, access and recovery." action={<Button size="sm" disabled={busy} onClick={()=>choose('create')}><Plus size={15}/>Add admin</Button>}/>
    <div className="owner-taskbar"><div role="tablist" aria-label="Admin management tasks" className="owner-task-tabs">
      {tasks.map(({id,label,Icon},index)=><button type="button" key={id} id={`owner-tab-${id}`} role="tab" aria-selected={area===id} aria-controls={`owner-panel-${id}`} tabIndex={area===id||area==='create'&&index===0?0:-1} onClick={()=>choose(id)} onKeyDown={e=>{
        const offset=e.key==='ArrowRight'?1:e.key==='ArrowLeft'?-1:0
        if(offset||e.key==='Home'||e.key==='End'){e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?tasks.length-1:(index+offset+tasks.length)%tasks.length;choose(tasks[next].id);document.getElementById(`owner-tab-${tasks[next].id}`)?.focus()}
      }}><Icon size={15}/>{label}</button>)}
    </div><span className="owner-capacity">{admins.filter(a=>a.enabled).length} / {query.data?.max_workspaces??'...'} active workspaces</span></div>
    {error&&<p role="alert" className="inline-error">{error}</p>}{notice&&<p role="status" className="owner-notice">{notice}</p>}
    {area==='create'&&<Card className="owner-create-panel">
      <div className="owner-panel-heading"><div><h2>Add admin</h2><p>A separate workspace with its own accounts and data.</p></div><Button variant="ghost" size="sm" onClick={()=>choose('workspaces')}><ArrowLeft size={14}/>Back</Button></div>
      <form className="owner-admin-form" onSubmit={async e=>{e.preventDefault();if(await write('/api/admin/users',{username:draft.username,workspace_name:draft.workspace,password:draft.password})){setDraft({username:'',workspace:'',password:''});choose('workspaces');setSearch(draft.username);setFilter('all');setNotice(`Admin ${draft.username} created.`)}}}>
        <label>Username<input name="username" required minLength={3} maxLength={64} pattern="[a-zA-Z][a-zA-Z0-9_.\-]{2,63}" autoComplete="off" disabled={busy} value={draft.username} onChange={e=>setDraft({...draft,username:e.target.value})}/></label>
        <label>Workspace name<input name="workspace" required maxLength={100} disabled={busy} value={draft.workspace} onChange={e=>setDraft({...draft,workspace:e.target.value})}/></label>
        <label>Temporary password<input name="password" type="password" required minLength={12} maxLength={256} autoComplete="new-password" disabled={busy} value={draft.password} onChange={e=>setDraft({...draft,password:e.target.value})}/></label>
        <p className="form-hint">The admin must change this password at first sign-in. Job links access starts off.</p>
        <div className="owner-form-actions"><Button variant="outline" type="button" disabled={busy} onClick={()=>{setDraft({username:'',workspace:'',password:''});choose('workspaces')}}>Cancel</Button><Button disabled={busy}>Create admin</Button></div>
      </form>
    </Card>}
    {area==='workspaces'&&<section id="owner-panel-workspaces" role="tabpanel" aria-labelledby="owner-tab-workspaces">
      {query.error&&query.data&&<p role="alert" className="inline-error">Workspace status could not refresh. {query.error.message}<Button variant="outline" size="sm" onClick={()=>void query.refetch()}>Try again</Button></p>}
      {query.isPending?<Loading/>:query.error&&!query.data?<p role="alert" className="inline-error">{query.error.message}<Button variant="outline" size="sm" onClick={()=>void query.refetch()}>Try again</Button></p>:<div className="owner-workspace-layout">
        <Card className="owner-directory"><div className="owner-directory-tools"><label className="owner-search"><Search size={15} aria-hidden="true"/><input aria-label="Search workspaces" placeholder="Find workspace or admin" value={search} onChange={e=>{setSearch(e.target.value);setResetting(null)}}/></label><select aria-label="Workspace status" value={filter} onChange={e=>{setFilter(e.target.value);setResetting(null)}}><option value="all">All workspaces</option><option value="active">Active</option><option value="suspended">Suspended</option></select></div>
          <div className="owner-directory-count">{visible.length} workspace{visible.length===1?'':'s'}</div>
          <ul className="owner-workspace-list">{visible.map(admin=><li key={admin.id}><button type="button" aria-label={`Manage ${admin.workspace_name}`} aria-pressed={selected?.id===admin.id} onClick={()=>{setSelectedId(admin.id);setResetting(null)}}>
            <span className="owner-workspace-avatar" aria-hidden="true">{admin.workspace_name.slice(0,1).toUpperCase()}</span>
            <span className="owner-workspace-identity"><strong>{admin.workspace_name}</strong><small>{admin.username}{admin.owner?' / Owner':''}{!admin.enabled&&<em className="owner-directory-suspended">Suspended</em>}</small></span>
            <span className={`admin-presence ${admin.online?'is-online':'is-offline'}`} title="Visible signed-in tab active within the last 90 seconds"><span aria-hidden="true"/>{admin.online?'Online':'Offline'}</span><ChevronRight size={14} aria-hidden="true"/>
          </button></li>)}</ul>
          {!visible.length&&<p className="owner-directory-empty">No matching workspaces.<button type="button" onClick={()=>{setSearch('');setFilter('all')}}>Clear filters</button></p>}
        </Card>
        {selected?<Card key={selected.id} className="owner-workspace-detail" role="region" aria-label="Workspace details">
          <div className="owner-detail-heading"><div><h2>{selected.workspace_name}</h2><p>{selected.username}{selected.owner?' / Owner':''}</p></div><span className={`owner-state ${selected.enabled?'is-active':'is-suspended'}`}>{selected.enabled?'Active':'Suspended'}</span></div>
          <dl className="owner-workspace-meta"><div><dt>Workspace service</dt><dd>{selected.health||'Unknown'}</dd></div><div><dt>Password</dt><dd>{selected.must_change?'Change required':'Set'}</dd></div></dl>
          <Button size="sm" disabled={busy||!selected.enabled||session.workspace_id===selected.workspace_id} onClick={()=>void open(selected.workspace_id)}>{session.workspace_id===selected.workspace_id?'Current workspace':'Open workspace'}</Button>
          <div className="owner-detail-section"><h3>Page access</h3>{selected.owner?<p className="form-hint">Job links access: always enabled</p>:<label className="owner-job-links-access"><span><strong>Job links</strong><small>Search and copy links shared by all workspaces.</small></span><input type="checkbox" aria-label={`Job links access for ${selected.username}`} checked={!!selected.job_links_access} disabled={busy} onChange={e=>{const granted=e.target.checked;void write(`/api/admin/users/${selected.id}`,{job_links_access:granted}).then(saved=>{if(saved)setNotice(`${selected.username}: Job links access ${granted?'granted':'revoked'}.`)})}}/></label>}</div>
          {!selected.owner&&<><div className="owner-detail-section"><h3>Account access</h3><div className="owner-detail-actions"><Button size="sm" variant="outline" disabled={busy} onClick={()=>setResetting(resetting===selected.id?null:selected.id)}>Reset password</Button><Button size="sm" variant="outline" disabled={busy} onClick={()=>{if(window.confirm(selected.enabled?'Suspend this admin and stop their workspace jobs? Already dispatched emails cannot be recalled.':'Enable this admin and restart their workspace?'))void write(`/api/admin/users/${selected.id}`,{enabled:!selected.enabled})}}>{selected.enabled?'Suspend':'Enable'}</Button></div>
            {resetting===selected.id&&<form className="owner-admin-form owner-password-form" onSubmit={async e=>{e.preventDefault();const form=e.currentTarget;if(await write(`/api/admin/users/${selected.id}`,{password:new FormData(form).get('password')})){form.reset();setResetting(null);setNotice(`Temporary password reset for ${selected.username}.`)}}}><label>New temporary password for {selected.username}<input name="password" type="password" required minLength={12} maxLength={256} autoComplete="new-password" disabled={busy}/></label><Button size="sm" disabled={busy}>Save temporary password</Button></form>}
          </div><div className="owner-remove-row"><span>Remove admin access; retain data offline.</span><Button size="sm" variant="outline" aria-label={`Remove ${selected.workspace_name}`} disabled={busy||session.workspace_id===selected.workspace_id} title={session.workspace_id===selected.workspace_id?'Switch to your own workspace before removing this workspace':'Remove admin access; retain data offline'} onClick={()=>void remove(selected)}>Remove workspace</Button></div></>}
        </Card>:<Card className="owner-workspace-detail owner-detail-empty">Select a workspace to manage its access.</Card>}
      </div>}
    </section>}
    {backupsVisited&&<section id="owner-panel-backups" role="tabpanel" aria-labelledby="owner-tab-backups" hidden={area!=='backups'}><BackupManagement active={area==='backups'}/></section>}
    {area==='activity'&&<section id="owner-panel-activity" role="tabpanel" aria-labelledby="owner-tab-activity"><Card className="owner-activity-panel"><div className="owner-panel-heading"><div><h2>Recent admin activity</h2><p>Access changes and workspace administration.</p></div><Button size="sm" variant="outline" disabled={audit.isFetching} onClick={()=>void audit.refetch()}>Refresh activity</Button></div>{audit.isPending?<Loading label="Loading activity..."/>:audit.error?<p role="alert">{audit.error.message}</p>:audit.data?.events.length?<ul className="owner-activity-list">{audit.data.events.map(event=><li key={event.id}><span>{event.action}</span><span>{event.target}</span><time dateTime={new Date(event.at*1000).toISOString()}>{new Date(event.at*1000).toLocaleString()}</time></li>)}</ul>:<p className="owner-muted">No admin activity recorded yet.</p>}</Card></section>}
  </div>
}
