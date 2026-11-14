import { PageStateProvider } from "@/lib/page-state"
import { OfferPathMark } from "@/components/offerpath-mark"
import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react"
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

// Keep the complete form visible without changing the user's browser zoom.
function SignInViewport({children}:{children:ReactNode}) {
  const pageRef=useRef<HTMLElement>(null),layoutRef=useRef<HTMLDivElement>(null)
  useLayoutEffect(()=>{
    const page=pageRef.current!,layout=layoutRef.current!
    const roots=[document.documentElement,document.body]
    const properties={overflow:"hidden","min-width":"0"}
    const previous=roots.map(root=>Object.keys(properties).map(property=>({property,value:root.style.getPropertyValue(property),priority:root.style.getPropertyPriority(property)})))
    roots.forEach(root=>Object.entries(properties).forEach(([property,value])=>root.style.setProperty(property,value)))
    let frame=0,disposed=false
    const fit=()=>{
      const viewport=window.visualViewport
      page.style.width=`${viewport?.width ?? window.innerWidth}px`
      page.style.height=`${viewport?.height ?? window.innerHeight}px`
      page.style.left=`${viewport?.offsetLeft ?? 0}px`
      page.style.top=`${viewport?.offsetTop ?? 0}px`
      const style=getComputedStyle(page)
      const width=page.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight)
      const height=page.clientHeight-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom)
      const scale=Math.min(0.85,width/Math.max(layout.scrollWidth,1),height/Math.max(layout.offsetHeight,1))
      layout.style.transform=`scale(${Math.max(0,scale)})`
    }
    const schedule=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(fit)}
    fit()
    const observer=typeof ResizeObserver!=="undefined"?new ResizeObserver(schedule):undefined
    observer?.observe(layout)
    window.addEventListener("resize",schedule)
    window.visualViewport?.addEventListener("resize",schedule)
    window.visualViewport?.addEventListener("scroll",schedule)
    void document.fonts?.ready.then(()=>{if(!disposed)schedule()})
    return ()=>{
      disposed=true;cancelAnimationFrame(frame);observer?.disconnect()
      window.removeEventListener("resize",schedule)
      window.visualViewport?.removeEventListener("resize",schedule)
      window.visualViewport?.removeEventListener("scroll",schedule)
      roots.forEach((root,index)=>previous[index].forEach(({property,value,priority})=>{if(value)root.style.setProperty(property,value,priority);else root.style.removeProperty(property)}))
    }
  },[])
  return <main ref={pageRef} className="sign-in-page offerpath-login"><div ref={layoutRef} className="login-layout">{children}</div></main>
}

export function AuthGate({children}:{children:ReactNode}) {
  const client=useQueryClient(), navigate=useNavigate()
  const session=useQuery({queryKey:["auth"],queryFn:({ signal }) => api.session(signal),retry:false,staleTime:0,refetchOnWindowFocus:true})
  const data=session.data
  const pageScope=JSON.stringify([data?.workspace_id || "legacy",data?.user_id ?? data?.username ?? "legacy",data?.role,data?.bidder_id ?? null])
  const identity=JSON.stringify([pageScope,Boolean(data?.must_change_password),Boolean(data?.managed)])
  const [activeIdentity,setActiveIdentity]=useState("")
  useEffect(()=>{
    if(session.isPending)return
    setWorkspaceIdentity(data?.workspace_id,identity)
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
  const authAttempt=useRef(0)
  const reset=()=>{authAttempt.current++;setBusy(false);setWorkspaceIdentity();client.clear();client.setQueryData(["auth"],{role:null});setPassword("");setUsername("");setShowPassword(false);navigate("/login",{replace:true})}
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
    const attempt=++authAttempt.current
    setBusy(true);setError("")
    try {
      if(data?.must_change_password){
        if(password!==confirmation)throw new Error("Passwords do not match.")
        const result=await api.post<{session:Session}>("/api/auth/password",{password,role:"admin"})
        if(attempt!==authAttempt.current)return
        client.clear();client.setQueryData(["auth"],result.session)
      } else {
        const result=await api.login(loginRole,password,undefined,username.trim())
        if(attempt!==authAttempt.current)return
        client.clear();client.setQueryData(["auth"],result)
      }
      setPassword("");setConfirmation("");navigate(loginRole==="bidder"?"/dashboard":"/",{replace:true})
    } catch(reason){if(attempt===authAttempt.current)setError(reason instanceof Error?reason.message:"Could not sign in.")}
    finally{if(attempt===authAttempt.current)setBusy(false)}
  }
  if(session.isPending || activeIdentity!==identity)return <SignInViewport><div className="login-pending"><Loading label="Checking sign-in…"/></div></SignInViewport>
  if((data?.role==="admin" || data?.role==="bidder" && data.managed && data.workspace_id) && !data.must_change_password)return <AuthContext.Provider value={{role:data.role,session:data,signOut}}><PageStateProvider key={pageScope} scope={pageScope}>{children}</PageStateProvider></AuthContext.Provider>
  return <SignInViewport>
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
            {loginRole==="bidder" && <p id="bidder-username-help" className="login-help">Use the username provided by your admin.</p>}
          </>}
          <label className="setting-field"><span>{data?.must_change_password?"New password":"Password"}</span><span className="login-input-wrap"><LockKeyhole size={20} aria-hidden="true"/><input aria-label={data?.must_change_password?"New password":"Password"} disabled={busy} name="password" type={showPassword?"text":"password"} autoComplete={data?.must_change_password?"new-password":"current-password"} required minLength={data?.must_change_password?12:1} maxLength={256} value={password} onChange={e=>setPassword(e.target.value)} placeholder="Enter your password"/><button className="login-password-toggle" type="button" disabled={busy} aria-label={showPassword?"Hide password":"Show password"} aria-pressed={showPassword} onClick={()=>setShowPassword(!showPassword)}>{showPassword?<EyeOff size={20}/>:<Eye size={20}/>}</button></span></label>
          {data?.must_change_password && <label className="setting-field"><span>Confirm password</span><span className="login-input-wrap"><LockKeyhole size={20} aria-hidden="true"/><input disabled={busy} type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={confirmation} onChange={e=>setConfirmation(e.target.value)}/></span></label>}
          {error && <p role="alert" className="inline-error">{error}</p>}
          <Button className="login-submit" type="submit" disabled={busy||(!data?.must_change_password&&!accountReady)}><LogIn size={22}/>{busy?"Please wait…":data?.must_change_password?"Save password":"Sign in"}</Button>
        </form>
        {data?.must_change_password && <Button variant="ghost" disabled={busy} onClick={()=>void signOut()}>Sign out</Button>}
        <p className="login-security"><ShieldCheck size={16}/>Secure · Private · Your Data Stays Yours</p>
      </section>
      <aside className="login-milestones" aria-label="Your career journey"><span><CalendarDays/>Interview</span><span><FileText/>Application</span><span><Crosshair/>Job Match</span><span><UserRound/>Profile &amp; Skills</span></aside>
  </SignInViewport>
}
