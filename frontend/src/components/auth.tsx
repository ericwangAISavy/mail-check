import { OfferPathMark } from "@/components/offerpath-mark"
import { createContext, useContext, useEffect, useState, type ReactNode } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"
import { LogIn, UserRound, LockKeyhole, Eye, EyeOff, ShieldCheck, CircleCheck, CalendarDays, FileText, Crosshair } from "lucide-react"
import { api, setWorkspaceIdentity, type Session } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Loading } from "@/components/common"
import "./sign-in.css"

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
  useEffect(()=>{
    if(activeIdentity!==identity||data?.role!=="admin"||!data.workspace_id||data.must_change_password)return
    const heartbeat=async()=>{
      if(document.visibilityState!=="visible")return
      try{await api.post("/api/auth/presence",{})}catch{/* Presence must not interrupt the workspace. */}
    }
    void heartbeat()
    const interval=window.setInterval(()=>void heartbeat(),30000)
    document.addEventListener("visibilitychange",heartbeat)
    return ()=>{window.clearInterval(interval);document.removeEventListener("visibilitychange",heartbeat)}
  },[activeIdentity,identity,data?.role,data?.workspace_id,data?.must_change_password])
  const [loginRole,setLoginRole]=useState<Role>("admin")
  const [username,setUsername]=useState(""),[password,setPassword]=useState(""),[confirmation,setConfirmation]=useState("")
  const [showPassword,setShowPassword]=useState(false)
  const [error,setError]=useState(""),[busy,setBusy]=useState(false)
  const reset=()=>{setWorkspaceIdentity();client.clear();client.setQueryData(["auth"],{role:null});setPassword("");setUsername("");setShowPassword(false);navigate("/login",{replace:true})}
  useEffect(()=>{
    const expired=()=>reset()
    const changed=()=>{void client.cancelQueries();client.removeQueries({predicate:q=>q.queryKey[0]!=="auth"});void session.refetch()}
    window.addEventListener("mailcheck:unauthorized",expired)
    window.addEventListener("offerpath:workspace-changed",changed)
    return ()=>{window.removeEventListener("mailcheck:unauthorized",expired);window.removeEventListener("offerpath:workspace-changed",changed)}
  },[client,navigate])
  const signOut=async()=>{await api.post("/api/auth/logout",{});reset()}
  const accountReady=!!username.trim() && !!password
  const submit=async(event:React.FormEvent)=>{
    event.preventDefault()
    if(busy||(!data?.must_change_password&&!accountReady))return
    setBusy(true);setError("")
    try {
      if(data?.must_change_password){
        if(password!==confirmation)throw new Error("Passwords do not match.")
        const result=await api.post<{session:Session}>("/api/auth/password",{password,role:"admin"})
        client.clear();client.setQueryData(["auth"],result.session)
      } else {
        const result=await api.login(loginRole,password,undefined,username.trim())
        client.clear();client.setQueryData(["auth"],result)
      }
      setPassword("");setConfirmation("");navigate(loginRole==="bidder"?"/dashboard":"/",{replace:true})
    } catch(reason){setError(reason instanceof Error?reason.message:"Could not sign in.")}
    finally{setBusy(false)}
  }
  if(session.isPending || activeIdentity!==identity)return <Loading label="Checking sign-in…"/>
  if((data?.role==="admin" || data?.role==="bidder" && data.managed && data.workspace_id) && !data.must_change_password)return <AuthContext.Provider value={{role:data.role,session:data,signOut}}>{children}</AuthContext.Provider>
  return <main className="sign-in-page offerpath-login">
    <div className="login-layout">
      <header className="login-brand-header">
        <div className="sign-in-brand" aria-label="OfferPath"><span className="sign-in-brand-icon"><OfferPathMark size={64}/></span><span className="sign-in-wordmark">Offer<span>Path</span></span></div>
        <p className="login-tagline">MustGetJoboffer</p>
      </header>
      <aside className="login-pitch" aria-label="Your path to a job offer">
        <h2>Turn Your Skills into a <strong>Job Offer</strong></h2>
        <ul><li><CircleCheck/>AI-Powered Job Matching</li><li><CircleCheck/>Application Automation</li><li><CircleCheck/>Offer-Ready Preparation</li></ul>
      </aside>
      <section className="sign-in-card login-glass" aria-labelledby="login-title">
        <h1 id="login-title" aria-label={data?.must_change_password?"Choose your password":"Sign In to OfferPath"}>{data?.must_change_password?"Choose your password":<>Sign In to Offer<span>Path</span></>}</h1>
        <p className="login-subtitle">{data?.must_change_password?"Replace your temporary password before opening your workspace.":"Your AI-Powered Path to a Job Offer"}</p>
        {session.error && <div role="alert" className="inline-error">Could not reach sign-in. <button type="button" onClick={()=>void session.refetch()}>Try again</button></div>}
        <form onSubmit={event=>void submit(event)}>
          {!data?.must_change_password && <>
            <label className="setting-field"><span>Sign in as</span><select aria-label="Sign in as" disabled={busy} value={loginRole} onChange={e=>{setLoginRole(e.target.value as Role);setPassword("");setUsername("");setShowPassword(false);setError("")}}><option value="admin">Admin</option><option value="bidder">Bidder</option></select></label>
            <label className="setting-field"><span>Username</span><span className="login-input-wrap"><UserRound size={20} aria-hidden="true"/><input name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} required maxLength={192} value={username} onChange={e=>setUsername(e.target.value)} disabled={busy} placeholder="Enter your username" aria-describedby={loginRole==="bidder"?"bidder-username-help":undefined}/></span></label>
            {loginRole==="bidder" && <p id="bidder-username-help" className="login-help">Use your name + your admin’s username, exactly as provided by your admin.</p>}
          </>}
          <label className="setting-field"><span>{data?.must_change_password?"New password":"Password"}</span><span className="login-input-wrap"><LockKeyhole size={20} aria-hidden="true"/><input aria-label={data?.must_change_password?"New password":"Password"} disabled={busy} name="password" type={showPassword?"text":"password"} autoComplete={data?.must_change_password?"new-password":"current-password"} required minLength={data?.must_change_password?12:1} maxLength={256} value={password} onChange={e=>setPassword(e.target.value)} placeholder="Enter your password"/><button className="login-password-toggle" type="button" disabled={busy} aria-label={showPassword?"Hide password":"Show password"} aria-pressed={showPassword} onClick={()=>setShowPassword(!showPassword)}>{showPassword?<EyeOff size={20}/>:<Eye size={20}/>}</button></span></label>
          {data?.must_change_password && <label className="setting-field"><span>Confirm password</span><span className="login-input-wrap"><LockKeyhole size={20} aria-hidden="true"/><input disabled={busy} type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={confirmation} onChange={e=>setConfirmation(e.target.value)}/></span></label>}
          {error && <p role="alert" className="inline-error">{error}</p>}
          <Button className="login-submit" type="submit" disabled={busy||(!data?.must_change_password&&!accountReady)}><LogIn size={22}/>{busy?"Please wait…":data?.must_change_password?"Save password":"Sign in"}</Button>
        </form>
        {data?.must_change_password && <Button variant="ghost" onClick={()=>void signOut()}>Sign out</Button>}
        <p className="login-security"><ShieldCheck size={16}/>Secure · Private · Your Data Stays Yours</p>
      </section>
      <aside className="login-milestones" aria-label="Your career journey"><span><CalendarDays/>Interview</span><span><FileText/>Application</span><span><Crosshair/>Job Match</span><span><UserRound/>Profile &amp; Skills</span></aside>
    </div>
  </main>
}
