import {useState} from "react"
import {useMutation,useQuery,useQueryClient} from "@tanstack/react-query"
import {api,request} from "@/lib/api"
import {Button} from "@/components/ui/button"

type RoleAccount={id:number;label:string;email:string;keywords:string[]}
type RoleSettings={accounts:RoleAccount[]}
export default function SourcingRoleFilters({initialAccountId}:{initialAccountId?:number|null}) {
  const client=useQueryClient()
  const query=useQuery({queryKey:["sourcing-role-filters"],queryFn:()=>request<RoleSettings>("/api/sourcing/role-filters")})
  const [selected,setSelected]=useState<number>()
  const [drafts,setDrafts]=useState<Record<number,string>>({})
  const accounts=query.data?.accounts||[]
  const selectedId=selected??(accounts.some(a=>a.id===initialAccountId)?initialAccountId:accounts[0]?.id)
  const account=accounts.find(a=>a.id===selectedId)
  const text=account?(drafts[account.id]??account.keywords.join("\n")):""
  const save=useMutation({
    mutationFn:({id,text}:{id:number;text:string})=>api.post<{account_id:number;keywords:string[]}>(`/api/sourcing/role-filters/${id}`,{keywords:text.split("\n").map(word=>word.trim()).filter(Boolean)}),
    onSuccess:(result,variables)=>{
      client.setQueryData<RoleSettings>(["sourcing-role-filters"],old=>old?{accounts:old.accounts.map(a=>a.id===result.account_id?{...a,keywords:result.keywords}:a)}:old)
      setDrafts(old=>{const next={...old};delete next[variables.id];return next})
    },
  })
  return <div className="form-stack">
    <p className="form-hint">Removes new jobs when the Role contains any listed keyword or phrase for the selected email account. Matching ignores case, spaces and hyphens. Existing rows stay saved.</p>
    <label>Email account<select aria-label="Role filter email account" value={selectedId??""} disabled={query.isPending||save.isPending||!accounts.length} onChange={e=>{setSelected(Number(e.target.value));save.reset()}}>{accounts.map(a=><option key={a.id} value={a.id}>{a.label===a.email?a.email:`${a.label} · ${a.email}`}</option>)}</select></label>
    {!query.isPending&&!query.error&&!accounts.length&&<p>Connect an email account on the Accounts page first.</p>}
    <label htmlFor="blocked-role-keywords">Blocked role keywords · one keyword or phrase per line</label>
    <textarea id="blocked-role-keywords" rows={8} maxLength={201000} value={text} disabled={!account||save.isPending} onChange={e=>{if(account)setDrafts(old=>({...old,[account.id]:e.target.value}));save.reset()}} placeholder={"MLOps\nFull stack\nMachine learning"} style={{width:"100%",padding:12,background:"var(--background)",color:"var(--foreground)",border:"1px solid var(--border)",borderRadius:6}}/>
    <p className="form-hint">Only {account?.email||"the selected account"} uses this list, across all its bidders and job tabs. An empty list disables role filtering for this account.</p>
    {(query.error||save.error)&&<p role="alert" className="inline-error">{(query.error||save.error)?.message}</p>}
    {save.isSuccess&&account&&<p role="status">Role filters saved for {account.email}.</p>}
    <Button disabled={!account||query.isError||save.isPending} onClick={()=>{if(account)save.mutate({id:account.id,text})}}>{save.isPending?"Saving…":"Save role filters"}</Button>
  </div>
}
