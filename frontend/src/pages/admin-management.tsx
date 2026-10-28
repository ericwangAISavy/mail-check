import {useState} from "react"
import {useQuery,useQueryClient} from "@tanstack/react-query"
import {api,request,setWorkspaceIdentity} from "@/lib/api"
import {useAuth} from "@/components/auth"
import {Button} from "@/components/ui/button"
import {Card} from "@/components/ui/card"
import {Loading,PageHeading} from "@/components/common"

type Admin={id:number;username:string;owner:number;enabled:number;must_change:number;workspace_id:string;workspace_name:string;health:string}
export default function AdminManagement(){
  const {session}=useAuth(),client=useQueryClient()
  const [error,setError]=useState("")
  const [busy,setBusy]=useState(false)
  const [resetting,setResetting]=useState<number|null>(null)
  const query=useQuery({queryKey:["owner-admins"],queryFn:()=>request<{admins:Admin[];max_workspaces:number}>("/api/admin/users"),enabled:!!session?.is_owner,refetchInterval:10000})
  const audit=useQuery({queryKey:["owner-audit"],queryFn:()=>request<{events:{id:number;at:number;actor:number;action:string;target:string}[]}>("/api/admin/audit"),enabled:!!session?.is_owner})
  const write=async(url:string,body:unknown)=>{
    setBusy(true);setError("")
    try{await api.post(url,body);await Promise.all([client.invalidateQueries({queryKey:["owner-admins"]}),client.invalidateQueries({queryKey:["owner-audit"]})]);return true}
    catch(e){setError(e instanceof Error?e.message:"Could not save.");return false}
    finally{setBusy(false)}
  }
  const open=async(wid:string)=>{
    if(!window.confirm("Open this workspace? Finish or save any work in other tabs first. Pending operations remain in their original workspace."))return
    setBusy(true);setError("")
    try{await api.post("/api/admin/switch",{workspace_id:wid});setWorkspaceIdentity();client.clear();window.location.assign("/")}
    catch(e){setError(e instanceof Error?e.message:"Could not switch workspace.");setBusy(false)}
  }
  if(!session?.is_owner)return <div className="page-wrap"><PageHeading title="Owner access required"/></div>
  return <div className="page-wrap admin-management-page"><PageHeading title="Admin management" description="Create private workspaces and manage admin access. Suspended workspaces keep their data."/>
    {error&&<p role="alert" className="inline-error">{error}</p>}
    <Card className="owner-create-card"><h2>Add admin</h2><form className="owner-admin-form" onSubmit={async e=>{
      e.preventDefault();const form=e.currentTarget;const data=new FormData(form)
      if(await write("/api/admin/users",{username:data.get("username"),workspace_name:data.get("workspace"),password:data.get("password")}))form.reset()
    }}><label>Username<input name="username" required minLength={3} maxLength={64} pattern="[a-zA-Z][a-zA-Z0-9_.\-]{2,63}" autoComplete="off"/></label><label>Workspace name<input name="workspace" required maxLength={100}/></label><label>Temporary password<input name="password" type="password" required minLength={12} maxLength={256} autoComplete="new-password"/></label><Button disabled={busy}>Create admin</Button></form><p className="form-hint">New admins start with an empty workspace and must change their temporary password. Capacity: {query.data?.max_workspaces ?? "…"} enabled workspaces, including yours.</p></Card>
    {query.isPending?<Loading/>:query.error?<p role="alert">{query.error.message}</p>:<div className="owner-admin-list">{query.data?.admins.map(admin=><Card key={admin.id} className="owner-admin-card"><div><h2>{admin.workspace_name}</h2><p>{admin.username}{admin.owner?" · Owner":""} · {admin.health}{admin.must_change?" · Password change required":""}</p></div><div className="owner-admin-actions"><Button size="sm" variant="outline" disabled={busy||!admin.enabled||session.workspace_id===admin.workspace_id} onClick={()=>void open(admin.workspace_id)}>{session.workspace_id===admin.workspace_id?"Current workspace":"Open workspace"}</Button>{!admin.owner&&<><Button size="sm" variant="outline" disabled={busy} onClick={()=>setResetting(resetting===admin.id?null:admin.id)}>Reset password</Button><Button size="sm" variant="outline" disabled={busy} onClick={()=>{if(window.confirm(admin.enabled?"Suspend this admin and stop their workspace jobs? Already dispatched emails cannot be recalled.":"Enable this admin and restart their workspace?"))void write(`/api/admin/users/${admin.id}`,{enabled:!admin.enabled})}}>{admin.enabled?"Suspend":"Enable"}</Button></>}</div>{resetting===admin.id&&<form className="owner-admin-form" onSubmit={async e=>{e.preventDefault();const form=e.currentTarget;if(await write(`/api/admin/users/${admin.id}`,{password:new FormData(form).get("password")})){form.reset();setResetting(null)}}}><label>New temporary password for {admin.username}<input name="password" type="password" required minLength={12} maxLength={256} autoComplete="new-password"/></label><Button size="sm" disabled={busy}>Save temporary password</Button></form>}</Card>)}</div>}
    <details className="owner-audit"><summary>Recent admin activity</summary>{audit.error?<p role="alert">{audit.error.message}</p>:<ul>{audit.data?.events.map(event=><li key={event.id}>{new Date(event.at*1000).toLocaleString()} · {event.action} · {event.target}</li>)}</ul>}</details>
  </div>
}
