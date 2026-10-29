import { OfferPathMark } from "@/components/offerpath-mark"
import { createContext, useContext, useEffect, useState, type ReactNode } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"
import { LogIn } from "lucide-react"
import { api, request, setWorkspaceIdentity, type Session } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Loading } from "@/components/common"

export type Role = "admin" | "bidder"
const AuthContext = createContext<{ role: Role; session?: Session; signOut: () => Promise<void> } | null>(null)
export function useAuth() {
  const value=useContext(AuthContext)
  if (!value) throw new Error("Sign-in context is missing.")
  return value
}

export function AuthGate({children}:{children:ReactNode}) {
  const client=useQueryClient(), navigate=useNavigate()
  const session=useQuery({queryKey:["auth"],queryFn:api.session,retry:false,staleTime:0,refetchOnWindowFocus:true})
  const data=session.data
  const identity=data?.role==="bidder" && data.managed && data.workspace_id ? `bidder:${data.workspace_id}:${data.bidder_id}` : data?.role==="admin" ? `${data.user_id || "legacy"}:${data.workspace_id || "legacy"}:${Boolean(data.must_change_password)}` : "signed-out"
  const [activeIdentity,setActiveIdentity]=useState("")
  useEffect(()=>{
    if(session.isPending)return
    setWorkspaceIdentity(data?.workspace_id)
    if(activeIdentity!==identity){
      void client.cancelQueries({predicate:query=>query.queryKey[0]!=="auth"})
      client.removeQueries({predicate:query=>query.queryKey[0]!=="auth"})
      setActiveIdentity(identity)
    }
  },[identity,activeIdentity,session.isPending,client])
  const [loginRole,setLoginRole]=useState<Role>("admin"),[bidderId,setBidderId]=useState("")
  const bidders=useQuery({queryKey:["login-bidders"],queryFn:()=>request<{bidders:{id:number;name:string}[]}>("/api/auth/bidders"),enabled:loginRole==="bidder"&&!data?.role,retry:false,staleTime:0})
  const [username,setUsername]=useState("owner"),[password,setPassword]=useState(""),[confirmation,setConfirmation]=useState("")
  const [error,setError]=useState(""),[busy,setBusy]=useState(false)
  const reset=()=>{setWorkspaceIdentity();client.clear();client.setQueryData(["auth"],{role:null});setPassword("");navigate("/login",{replace:true})}
  useEffect(()=>{
    const expired=()=>reset()
    const changed=()=>{void client.cancelQueries();client.removeQueries({predicate:q=>q.queryKey[0]!=="auth"});void session.refetch()}
    window.addEventListener("mailcheck:unauthorized",expired)
    window.addEventListener("offerpath:workspace-changed",changed)
    return ()=>{window.removeEventListener("mailcheck:unauthorized",expired);window.removeEventListener("offerpath:workspace-changed",changed)}
  },[client,navigate])
  const signOut=async()=>{await api.post("/api/auth/logout",{});reset()}
  const submit=async(event:React.FormEvent)=>{
    event.preventDefault();setBusy(true);setError("")
    try {
      if(data?.must_change_password){
        if(password!==confirmation)throw new Error("Passwords do not match.")
        const result=await api.post<{session:Session}>("/api/auth/password",{password,role:"admin"})
        client.clear();client.setQueryData(["auth"],result.session)
      } else {
        const result=await api.login(loginRole,password,loginRole==="bidder"?Number(bidderId):undefined,username)
        client.clear();client.setQueryData(["auth"],result)
      }
      setPassword("");setConfirmation("");navigate(loginRole==="bidder"?"/dashboard":"/",{replace:true})
    } catch(reason){setError(reason instanceof Error?reason.message:"Could not sign in.")}
    finally{setBusy(false)}
  }
  if(session.isPending || activeIdentity!==identity)return <Loading label="Checking sign-in…"/>
  if((data?.role==="admin" || data?.role==="bidder" && data.managed && data.workspace_id) && !data.must_change_password)return <AuthContext.Provider value={{role:data.role,session:data,signOut}}>{children}</AuthContext.Provider>
  return <main className="sign-in-page"><Card className="sign-in-card"><span className="brand-mark"><OfferPathMark size={30}/></span><p className="eyebrow">OFFERPATH</p><h1>{data?.must_change_password?"Choose your password":"Sign in"}</h1><p className="page-description">{data?.must_change_password?"Replace your temporary password before opening your workspace.":"Every application, a step forward."}</p>
    {session.error && <div role="alert" className="inline-error">Could not reach sign-in. <button onClick={()=>void session.refetch()}>Try again</button></div>}
    <form onSubmit={event=>void submit(event)}>
      {!data?.must_change_password && <label className="setting-field"><span>Sign in as</span><select value={loginRole} onChange={e=>{setLoginRole(e.target.value as Role);setPassword("");setBidderId("");setError("")}}><option value="admin">Admin</option><option value="bidder">Bidder</option></select></label>}
      {!data?.must_change_password && loginRole==="bidder" && <label className="setting-field"><span>Your name</span><select aria-label="Your name" required value={bidderId} onChange={e=>setBidderId(e.target.value)} disabled={bidders.isPending||!!bidders.error}><option value="">{bidders.isPending?"Loading bidders…":"Choose your name and admin"}</option>{bidders.data?.bidders.map(b=><option key={b.id} value={b.id}>{b.name}</option>)}</select><small>Read-only access to your admin’s team Dashboard and Bidder management, plus your own Job sourcing.</small>{bidders.error?<span role="alert">Could not load bidders. <button type="button" onClick={()=>void bidders.refetch()}>Try again</button></span>:bidders.data?.bidders.length===0&&<small>No bidder accounts are enabled. Ask your admin to enable your access.</small>}</label>}
      {!data?.must_change_password && loginRole==="admin" && <label className="setting-field"><span>Username</span><input aria-label="Username" name="username" autoComplete="username" required maxLength={64} value={username} onChange={e=>setUsername(e.target.value)}/><small>Use owner for the original workspace, or the username provided by your owner.</small></label>}
      <label className="setting-field"><span>{data?.must_change_password?"New password":"Password"}</span><input name="password" type="password" autoComplete={data?.must_change_password?"new-password":"current-password"} required minLength={data?.must_change_password?12:1} maxLength={256} value={password} onChange={e=>setPassword(e.target.value)}/></label>
      {data?.must_change_password && <label className="setting-field"><span>Confirm password</span><input type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={confirmation} onChange={e=>setConfirmation(e.target.value)}/></label>}
      {error && <p role="alert" className="inline-error">{error}</p>}
      <Button type="submit" disabled={busy}><LogIn size={16}/>{busy?"Please wait…":data?.must_change_password?"Save password":"Sign in"}</Button>
    </form>{data?.must_change_password && <Button variant="ghost" onClick={()=>void signOut()}>Sign out</Button>}
  </Card></main>
}
