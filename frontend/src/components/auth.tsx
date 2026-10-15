import { createContext, useContext, useEffect, useState, type ReactNode } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"
import { LogIn, MailCheck } from "lucide-react"
import { api, request } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Loading } from "@/components/common"

export type Role = "admin" | "bidder"
const AuthContext = createContext<{ role: Role; signOut: () => Promise<void> } | null>(null)
export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error("Sign-in context is missing.")
  return value
}

export function AuthGate({ children }: { children: ReactNode }) {
  const client = useQueryClient()
  const navigate = useNavigate()
  const session = useQuery({ queryKey: ["auth"], queryFn: api.session, retry: false, staleTime: 0, refetchOnWindowFocus: true })
  const identity = session.data?.role ? `${session.data.role}:${session.data.bidder_id||""}` : "signed-out"
  const [activeIdentity,setActiveIdentity] = useState("")
  useEffect(()=>{if(session.isPending)return;if(activeIdentity!==identity){client.removeQueries({predicate:query=>query.queryKey[0]!=="auth"});setActiveIdentity(identity)}},[identity,activeIdentity,session.isPending,client])
  const [role, setRole] = useState<Role>("bidder")
  const bidders = useQuery({ queryKey: ["login-bidders"], queryFn: () => request<{bidders: {id:number;name:string}[]}>("/api/auth/bidders"), enabled: !session.data?.role, staleTime: 0, refetchOnWindowFocus: true, refetchInterval: 15_000 })
  const [bidder, setBidder] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const reset = () => {
    client.clear()
    client.setQueryData(["auth"], { role: null })
    setPassword("")
    navigate("/login", { replace: true })
  }
  useEffect(() => {
    const expired = () => reset()
    window.addEventListener("mailcheck:unauthorized", expired)
    return () => window.removeEventListener("mailcheck:unauthorized", expired)
  }, [client, navigate])
  const signOut = async () => { await api.post("/api/auth/logout", {}); reset() }
  const signIn = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true); setError("")
    try {
      const result = await api.login(role, password, Number(bidder))
      client.clear()
      client.setQueryData(["auth"], result)
      setPassword("")
      navigate(result.role === "admin" ? "/" : "/sourcing", { replace: true })
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not sign in.") }
    finally { setBusy(false) }
  }
  if (session.isPending || activeIdentity!==identity) return <Loading label="Checking sign-in…" />
  if (session.data?.role) return <AuthContext.Provider value={{ role: session.data.role, signOut }}>{children}</AuthContext.Provider>
  return <main className="sign-in-page"><Card className="sign-in-card">
    <span className="brand-mark"><MailCheck /></span>
    <p className="eyebrow">MAIL-CHECK</p><h1>Sign in</h1>
    <p className="page-description">Sign in to your job sourcing sheets and weekly application totals.</p>
    {session.error ? <div role="alert" className="inline-error">Could not reach sign-in. <button onClick={() => void session.refetch()}>Try again</button></div> : <form onSubmit={(event) => void signIn(event)}>
      <label className="setting-field"><span>Sign in as</span><select name="username" autoComplete="username" value={role} onChange={(event) => { setRole(event.target.value as Role); setError("") }}><option value="bidder">Bidder</option><option value="admin">Admin</option></select></label>
      {role === "bidder" && <label className="setting-field"><span>Your name</span><select aria-label="Your name" required value={bidder} onFocus={()=>void bidders.refetch()} onChange={e=>setBidder(e.target.value)}><option value="">Choose your name</option>{bidders.data?.bidders.map(b=><option key={b.id} value={b.id}>{b.name}</option>)}</select>{bidders.data?.bidders.length === 0 && <small>Ask your admin to enable your sign-in.</small>}</label>}
      <label className="setting-field"><span>Password</span><input name="password" type="password" autoComplete="current-password" required maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      {error && <p role="alert" className="inline-error">{error}</p>}
      <Button type="submit" disabled={busy}><LogIn size={16} />{busy ? "Signing in…" : "Sign in"}</Button>
    </form>}
  </Card></main>
}
