import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from "react"
import { Navigate, useLocation, useNavigationType } from "react-router-dom"

const LIMIT = 8192
const prefix = "offerpath.page-state.v1:"
type Store = { read: (page: string, key: string) => unknown; write: (page: string, key: string, value: unknown) => void }
const Context = createContext<Store | null>(null)
const primitive = (value: unknown) => value === null || typeof value === "string" || typeof value === "boolean" || typeof value === "number" && Number.isFinite(value)

/** Session-only UI preferences, isolated from other authenticated identities. */
export function PageStateProvider({ scope, children }: { scope: string; children: ReactNode }) {
  const store = useMemo<Store>(() => {
    const memory = new Map<string, unknown>()
    const name = (page: string, key: string) => prefix + JSON.stringify([scope, page, key])
    return {
      read(page, key) {
        const id = name(page, key)
        if (memory.has(id)) return memory.get(id)
        try { const raw = sessionStorage.getItem(id); return raw !== null && raw.length <= LIMIT ? JSON.parse(raw) : undefined } catch { return undefined }
      },
      write(page, key, value) {
        if (!primitive(value)) return
        const raw = JSON.stringify(value)
        if (raw.length > LIMIT) return
        const id = name(page, key)
        memory.delete(id)
        memory.set(id, value)
        if (memory.size > 256) memory.delete(memory.keys().next().value!)
        try { sessionStorage.setItem(id, raw) } catch { /* Retain session preferences in memory when browser storage is unavailable. */ }
      },
    }
  }, [scope])
  return <Context.Provider value={store}>{children}</Context.Provider>
}

export function usePageState<T>(page: string, key: string, initial: T | (() => T), validate?: (value: T) => boolean): [T, Dispatch<SetStateAction<T>>] {
  const store = useContext(Context)
  const load = () => {
    const fallback = typeof initial === "function" ? (initial as () => T)() : initial
    const saved = store?.read(page, key)
    const value = primitive(saved) && typeof saved === typeof fallback && (saved === null) === (fallback === null) && (!validate || validate(saved as T)) ? saved as T : fallback
    return { store, page, key, value }
  }
  const [state, setState] = useState(load)
  // React retries this render before committing children or effects. Never copy a
  // previous identity's preference into a newly selected scope or key.
  const current = state.store === store && state.page === page && state.key === key ? state : load()
  if (current !== state) setState(current)
  const setValue: Dispatch<SetStateAction<T>> = useCallback(next => setState(previous => ({
    ...previous,
    value: typeof next === "function" ? (next as (value: T) => T)(previous.value) : next,
  })), [])
  useEffect(() => { store?.write(page, key, current.value) }, [store, page, key, current.value])
  return [current.value, setValue]
}

/** Strict date-only preference validation; dates remain within supported UI years. */
export function isPageDate(value: string, allowEmpty = false): boolean {
  if (value === "") return allowEmpty
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const year = Number(value.slice(0, 4))
  if (year < 1971 || year > 2100) return false
  const date = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value
}

const queryKeys: Record<string, readonly string[]> = {
  "/dashboard": ["q", "days", "interval", "tz", "start", "end", "account", "bidder", "status", "action", "sort", "focus_date", "focus_category", "category", "page"],
  "/interviews": ["account", "status", "company", "calendar_view", "calendar_date", "calendar_tz"],
  "/sourcing": ["tab", "q", "account"],
  "/": ["view", "q", "account", "category", "days"],
  "/inbox": ["view", "q", "account", "category", "days"],
}
function filterQuery(path: string, search: string) {
  const result = new URLSearchParams()
  if (search.length > LIMIT) return ""
  new URLSearchParams(search).forEach((value, key) => { if (queryKeys[path]?.includes(key)) result.append(key, value) })
  return result.toString()
}

/** Redirect before mounting pages so restored filters drive their first request. */
export function PageQueryBoundary({ children }: { children: ReactNode }) {
  const store = useContext(Context)
  const location = useLocation()
  const navigation = useNavigationType()
  const previousPath = useRef<string | null>(null)
  const visited = useRef(new Set<string>())
  const supported = !!queryKeys[location.pathname]
  const entering = previousPath.current !== location.pathname
  const saved = supported ? store?.read(location.pathname, "query") : undefined
  const restore = store && supported && entering && !location.search && !(navigation === "POP" && visited.current.has(location.key)) && typeof saved === "string" ? filterQuery(location.pathname, saved) : ""
  useEffect(() => {
    if (restore) return
    previousPath.current = location.pathname
    visited.current.add(location.key)
    if (supported) store?.write(location.pathname, "query", filterQuery(location.pathname, location.search))
  }, [store, location.pathname, location.search, location.key, supported, restore])
  useEffect(() => {
    const changed = () => {
      if (supported && window.location.pathname === location.pathname) store?.write(location.pathname, "query", filterQuery(location.pathname, window.location.search))
    }
    window.addEventListener("offerpath:page-query-changed", changed)
    return () => window.removeEventListener("offerpath:page-query-changed", changed)
  }, [store, location.pathname, supported])
  if (restore) return <Navigate replace to={{ pathname: location.pathname, search: `?${restore}`, hash: location.hash }} state={location.state} />
  return children
}
