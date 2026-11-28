/** Browser preferences are optional; blocked storage must never stop startup. */
export function readBrowserPreference(key: string, fallback = ""): string {
  try { return localStorage.getItem(key) ?? fallback } catch { return fallback }
}
export function writeBrowserPreference(key: string, value: string): boolean {
  try { localStorage.setItem(key, value); return true } catch { return false }
}
