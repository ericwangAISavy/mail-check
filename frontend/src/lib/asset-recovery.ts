const RETRY_MARKER = "_offerpath_chunk_retry"
const RETRY_WINDOW = 10 * 60_000
let lastAttempt: number | null = (() => {
  try { const value = new URL(location.href).searchParams.get(RETRY_MARKER); return value === null ? null : Number(value) || Date.now() } catch { return null }
})()

export function clearAssetRecoveryMarker() {
  try { const url = new URL(location.href); if (url.searchParams.has(RETRY_MARKER)) { url.searchParams.delete(RETRY_MARKER); history.replaceState(history.state, "", url.pathname + url.search + url.hash) } } catch { /* Optional URL cleanup. */ }
}
export function isAssetLoadError(error: unknown) {
  return error instanceof Error && (error.name === "ChunkLoadError" || /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Unable to preload CSS/i.test(error.message))
}
export async function probeApplication(signal?: AbortSignal) {
  const controller = new AbortController(), abort = () => controller.abort()
  if (signal?.aborted) return false
  signal?.addEventListener("abort", abort, { once: true })
  const timeout = window.setTimeout(abort, 5000)
  try {
    const url = new URL("/login", location.origin); url.searchParams.set("_offerpath_probe", String(Date.now()))
    const response = await fetch(url.toString(), { cache: "no-store", credentials: "same-origin", signal: controller.signal })
    if (!response.ok || !response.headers.get("content-type")?.includes("html")) return false
    return /<div\b[^>]*\bid=["']root["']/i.test(await response.text())
  } catch { return false }
  finally { window.clearTimeout(timeout); signal?.removeEventListener("abort", abort) }
}
function pause(ms: number, signal?: AbortSignal) {
  return new Promise<void>(resolve => {
    if (signal?.aborted) { resolve(); return }
    const finish = () => { window.clearTimeout(timer); signal?.removeEventListener("abort", finish); resolve() }
    const timer = window.setTimeout(finish, ms)
    signal?.addEventListener("abort", finish, { once: true })
  })
}
export async function recoverPageAssets({ signal, manual = false }: { signal?: AbortSignal; manual?: boolean } = {}): Promise<"reloading" | "unavailable" | "exhausted"> {
  if (!manual && lastAttempt !== null && Date.now() - lastAttempt < RETRY_WINDOW) return "exhausted"
  for (const delay of [0, 1000, 3000]) {
    if (delay) await pause(delay, signal)
    if (signal?.aborted) return "unavailable"
    if (await probeApplication(signal)) {
      if (signal?.aborted) return "unavailable"
      lastAttempt = Date.now()
      const url = new URL(location.href); url.searchParams.set(RETRY_MARKER, String(lastAttempt))
      try { location.replace(url.toString()); return "reloading" } catch { return "unavailable" }
    }
  }
  return "unavailable"
}
