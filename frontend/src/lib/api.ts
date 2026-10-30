import type { Account, Bootstrap, Settings, TriageData } from "./types"

export type Session = {role: "admin" | "bidder" | null; bidder_id?: number; bidder_name?:string; user_id?: number; username?: string; is_owner?: boolean; workspace_id?: string; workspace_name?: string; must_change_password?: boolean; managed?: boolean}
let workspaceId: string | undefined
export function setWorkspaceIdentity(id?: string) { workspaceId = id }
export function getWorkspaceIdentity() {return workspaceId}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message) }
}

function errorText(value:unknown):string {
  if(typeof value!=="string")return ""
  const text=value.trim()
  // Proxy documents and diagnostics never belong in user-facing error panels.
  return text.length<=400&&!/<[!/?a-z][^>]*>/i.test(text)?text:""
}

/** Bound page reads through body parsing; writes retain their completion semantics. */
export async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  if (!["GET", "HEAD", "OPTIONS"].includes((init.method || "GET").toUpperCase())) return performRequest<T>(url, init)
  const controller = new AbortController()
  const cancel = () => controller.abort(init.signal?.reason)
  if (init.signal?.aborted) cancel()
  else init.signal?.addEventListener("abort", cancel, {once: true})
  let timedOut = false
  const timer = window.setTimeout(() => { timedOut = true; controller.abort() }, 30_000)
  try {
    return await performRequest<T>(url, {...init, signal: controller.signal})
  } catch (error) {
    if (timedOut) throw new ApiError("OfferPath took too long to respond. Check your connection and try again.", 504)
    throw error
  } finally {
    window.clearTimeout(timer)
    init.signal?.removeEventListener("abort", cancel)
  }
}

async function performRequest<T>(url: string, init: RequestInit = {}): Promise<T> {
  const requestWorkspace = workspaceId
  const mutating=!["GET","HEAD","OPTIONS"].includes((init.method||"GET").toUpperCase())
  const advice=mutating?"Check whether the action completed before trying again.":"Please try again shortly."
  const unavailable=(status:number)=>`${status===504||status===524?"OfferPath took too long to respond":"OfferPath is temporarily unavailable"} (${status}). ${advice}`
  let response:Response
  try {
    response=await fetch(url, {
      ...init,
      headers: { ...(requestWorkspace ? {"X-OfferPath-Workspace":requestWorkspace} : {}), ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers },
    })
  } catch(reason) {
    if(init.signal?.aborted || reason instanceof Error && reason.name==="AbortError")throw reason
    throw new ApiError(`Could not connect to OfferPath. ${mutating?advice:"Check your connection and try again."}`,0)
  }
  if (!url.startsWith("/api/auth/") && requestWorkspace !== workspaceId) throw new ApiError("Workspace changed. Reload before continuing.",409)
  const contentType = (response.headers.get("content-type") || "").toLowerCase()
  let html=contentType.includes("html")
  let value:any
  let malformed=false
  try {
    if(contentType.includes("json")) {
      try{value=await response.json()}catch(reason){
        if(init.signal?.aborted || reason instanceof Error && reason.name==="AbortError")throw reason
        malformed=true
      }
    } else {
      value=await response.text()
      html ||= /^\s*(?:<!doctype\b|<html\b|<head\b|<body\b)/i.test(value)
    }
  } catch(reason) {
    if(init.signal?.aborted || reason instanceof Error && reason.name==="AbortError")throw reason
    throw new ApiError(`Could not connect to OfferPath. ${mutating?advice:"Check your connection and try again."}`,0)
  }
  if (!url.startsWith("/api/auth/") && requestWorkspace !== workspaceId) throw new ApiError("Workspace changed. Reload before continuing.",409)
  if (response.status === 409 && value?.workspace_changed) window.dispatchEvent(new Event("offerpath:workspace-changed"))
  if (!response.ok) {
    if (response.status === 401 && !url.startsWith("/api/auth/")) window.dispatchEvent(new Event("mailcheck:unauthorized"))
    const detail = value?.detail
    const validation = Array.isArray(detail) ? detail.map((item) => {
      if(!item||typeof item!=="object")return ""
      const field = (Array.isArray(item.loc)?item.loc:[]).filter((part:unknown)=>part!=="body"&&part!=="query").join(".")
      const message=errorText(item.msg)
      return message ? `${field ? field + ": " : ""}${message}` : ""
    }).filter(Boolean).join("; ") : errorText(detail)
    const message = html||malformed?"":typeof value === "string"?errorText(value):errorText(value?.error)||errorText(validation)
    throw new ApiError(message||(response.status>=500?unavailable(response.status):`The request could not be completed (${response.status}). ${advice}`),response.status)
  }
  if(html||malformed)throw new ApiError(`OfferPath returned an unexpected response. ${advice}`,502)
  return value as T
}

export const api = {
  startCheck: async (mode: "mail" | "calendar" = "mail"): Promise<{ ok: boolean }> => {
    const result = await api.post<{ ok: boolean }>("/api/check", { mode })
    window.dispatchEvent(new Event("mailcheck:check-started"))
    return result
  },
  session: () => request<Session>("/api/auth/session"),
  login: (role: "admin" | "bidder", password: string, bidder_id?: number, username="owner") => request<Session>("/api/auth/login", { method: "POST", body: JSON.stringify({ role, password, username, ...(role==="bidder"?{bidder_id}: {}) }) }),
  dashboardAccounts: () => request<{ accounts: { label: string }[]; bidders?: { id: number; name: string }[] }>("/api/dashboard/accounts"),
  bootstrap: () => request<Bootstrap>("/api/bootstrap"),
  triage: (params: URLSearchParams) => request<TriageData>(`/api/triage?${params}`),
  reader: (pk: number) => request<{ message: import("./types").Message; body_html: string; original_html?: string | null; replies?: import("./types").SentReply[] }>(`/api/messages/${pk}`),
  accounts: () => request<{ accounts: Account[]; outlook_ready: boolean }>("/api/accounts"),
  settings: () => request<{ settings: Settings; rules: { category: string; sender: string | null; sender_domain: string | null; subject_contains: string | null }[]; categories: { name: string; label: string }[]; config_path: string; db_path: string }>("/api/settings"),
  activeModel: () => request<{ model: string | null; loaded: boolean; message: string }>("/api/settings/model"),
  dashboard: (params: URLSearchParams) => request<Record<string, any>>(`/api/dashboard?${params}`),
  status: () => request<{ running: boolean; completion_id: number; auto: boolean; interval_minutes?: number; next_in: number | null; message: string; detail: string; ok: boolean; stage_elapsed: number | null; interview_changes?: { id: number; company: string | null; status: string; start_at: string | null }[] }>("/api/status"),
  post: <T,>(url: string, body?: unknown) => request<T>(url, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
}

export function triageParams(search: string) {
  const source = new URLSearchParams(search)
  const params = new URLSearchParams()
  const view = source.get("view")
  params.set("view", view === "all" || view === "completed" ? view : "queue")
  const days = source.get("days")
  params.set("days", ["2", "3", "7", "14", "30", "90"].includes(days || "") ? days! : "30")
  for (const key of ["account", "category"]) if (source.get(key)) params.set(key, source.get(key)!)
  return params
}

/** Navigation downloads cannot carry workspace headers; use the guarded transport. */
export async function downloadFile(url: string, filename: string) {
  const content = await request<string>(url)
  const objectUrl = URL.createObjectURL(new Blob([content], {type:"text/csv;charset=utf-8"}))
  const anchor = document.createElement("a")
  try {
    anchor.href=objectUrl;anchor.download=filename
    document.body.appendChild(anchor);anchor.click()
  } finally {
    anchor.remove();URL.revokeObjectURL(objectUrl)
  }
}
