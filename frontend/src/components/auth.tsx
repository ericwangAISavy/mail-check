import { createContext, useContext, useEffect, useState, type ReactNode } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"
import { LogIn, MailCheck } from "lucide-react"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Loading } from "@/components/common"

export type Role = "admin" | "guest"
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
  const [role, setRole] = useState<Role>("guest")
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
      const result = await api.login(role, password)
      client.clear()
      client.setQueryData(["auth"], result)
      setPassword("")
      navigate(result.role === "admin" ? "/" : "/dashboard", { replace: true })
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not sign in.") }
    finally { setBusy(false) }
  }
  if (session.isPending) return <Loading label="Checking sign-in…" />
  if (session.data?.role) return <AuthContext.Provider value={{ role: session.data.role, signOut }}>{children}</AuthContext.Provider>
  return <main className="sign-in-page"><Card className="sign-in-card">
    <span className="brand-mark"><MailCheck /></span>
    <p className="eyebrow">MAIL-CHECK</p><h1>Sign in</h1>
    <p className="page-description">Guests can view the Dashboard and bidder payment totals. Admins can manage the full workspace.</p>
    {session.error ? <div role="alert" className="inline-error">Could not reach sign-in. <button onClick={() => void session.refetch()}>Try again</button></div> : <form onSubmit={(event) => void signIn(event)}>
      <label className="setting-field"><span>Sign in as</span><select name="username" autoComplete="username" value={role} onChange={(event) => { setRole(event.target.value as Role); setError("") }}><option value="guest">Guest</option><option value="admin">Admin</option></select></label>
      <label className="setting-field"><span>Password</span><input name="password" type="password" autoComplete="current-password" required maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      {error && <p role="alert" className="inline-error">{error}</p>}
      <Button type="submit" disabled={busy}><LogIn size={16} />{busy ? "Signing in…" : "Sign in"}</Button>
    </form>}
  </Card></main>
}
