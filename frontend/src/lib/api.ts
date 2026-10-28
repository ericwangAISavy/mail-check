import type { Account, Bootstrap, Settings, TriageData } from "./types"

export type Session = {role: "admin" | "bidder" | null; bidder_id?: number; user_id?: number; username?: string; is_owner?: boolean; workspace_id?: string; workspace_name?: string; must_change_password?: boolean; managed?: boolean}
let workspaceId: string | undefined
export function setWorkspaceIdentity(id?: string) { workspaceId = id }
export function getWorkspaceIdentity() {return workspaceId}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message) }
}

export async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const requestWorkspace = workspaceId
  const response = await fetch(url, {
    ...init,
    headers: { ...(requestWorkspace ? {"X-OfferPath-Workspace":requestWorkspace} : {}), ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers },
  })
  const contentType = response.headers.get("content-type") || ""
  const value = contentType.includes("json") ? await response.json() : await response.text()
  if (!url.startsWith("/api/auth/") && requestWorkspace !== workspaceId) throw new ApiError("Workspace changed. Reload before continuing.",409)
  if (response.status === 409 && value?.workspace_changed) window.dispatchEvent(new Event("offerpath:workspace-changed"))
  if (!response.ok) {
    if (response.status === 401 && !url.startsWith("/api/auth/")) window.dispatchEvent(new Event("mailcheck:unauthorized"))
    const detail = value?.detail
    const validation = Array.isArray(detail) ? detail.map((item: { loc?: (string | number)[]; msg?: string }) => {
      const field = (item.loc || []).filter(part => part !== "body" && part !== "query").join(".")
      return item.msg ? `${field ? field + ": " : ""}${item.msg}` : ""
    }).filter(Boolean).join("; ") : typeof detail === "string" ? detail : ""
    const message = typeof value === "string" ? value : value?.error || validation || "Something went wrong."
    throw new ApiError(message, response.status)
  }
  return value as T
}

export const api = {
  startCheck: async (mode: "mail" | "calendar" = "mail"): Promise<{ ok: boolean }> => {
    const result = await api.post<{ ok: boolean }>("/api/check", { mode })
    window.dispatchEvent(new Event("mailcheck:check-started"))
    return result
  },
  session: async () => {const session=await request<Session>("/api/auth/session");setWorkspaceIdentity(session.workspace_id);return session},
  login: async (role: "admin" | "bidder", password: string, _bidder_id?: number, username="owner") => {const session=await request<Session>("/api/auth/login", { method: "POST", body: JSON.stringify({ role, password, username }) });setWorkspaceIdentity(session.workspace_id);return session},
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
