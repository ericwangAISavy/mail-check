import { readBrowserPreference, writeBrowserPreference } from "./browser-preferences"

/** Curated theme families. Colors live in design/themes.css; only these ids are stored. */
export const THEMES = [
  { id: "classic", name: "Classic Cyan", note: "The original OfferPath look" },
  { id: "iris", name: "Iris", note: "Warm ink and iris" },
  { id: "midnight", name: "Midnight", note: "Midnight and periwinkle" },
  { id: "forest", name: "Forest", note: "Forest and porcelain" },
  { id: "champagne", name: "Champagne", note: "Espresso and champagne" },
  { id: "bordeaux", name: "Bordeaux", note: "Burgundy and rose quartz" },
  { id: "monograph", name: "Monograph", note: "Obsidian and silver" },
  { id: "cobalt", name: "Cobalt", note: "Slate and porcelain cobalt" },
  { id: "terracotta", name: "Terracotta", note: "Clay and copper" },
] as const
export type ThemeId = (typeof THEMES)[number]["id"]
export type AppearanceMode = "system" | "light" | "dark"
export type Appearance = { theme: ThemeId; mode: AppearanceMode }

const DEFAULT_THEME: ThemeId = "classic"
const DEFAULT_MODE: AppearanceMode = "dark"
/** The device-level mode key that predates personal appearance; it still sets the sign-in screen. */
export const DEVICE_MODE_KEY = "mailcheck.theme"
const PREFIX = "offerpath.appearance.v1:"

export const isThemeId = (value: unknown): value is ThemeId => THEMES.some(theme => theme.id === value)
export const isMode = (value: unknown): value is AppearanceMode => value === "system" || value === "light" || value === "dark"

/** Appearance belongs to a person, never a workspace: admins by their stable id, bidders by theirs. */
export function appearanceIdentity(session?: { role?: string | null; user_id?: number; bidder_id?: number } | null): string | undefined {
  if (session?.role === "admin") return `admin:${session.user_id ?? "local"}`
  if (session?.role === "bidder" && session.bidder_id != null) return `bidder:${session.bidder_id}`
  return undefined
}

const deviceMode = (): AppearanceMode => { const value = readBrowserPreference(DEVICE_MODE_KEY, DEFAULT_MODE); return isMode(value) ? value : DEFAULT_MODE }

function load(identity: string): Appearance {
  let saved: Partial<Appearance> = {}
  try { const raw = readBrowserPreference(PREFIX + identity); if (raw) saved = JSON.parse(raw) ?? {} } catch { saved = {} }
  return { theme: isThemeId(saved.theme) ? saved.theme : DEFAULT_THEME, mode: isMode(saved.mode) ? saved.mode : deviceMode() }
}

let identity: string | undefined
let state: Appearance = { theme: DEFAULT_THEME, mode: deviceMode() }
const listeners = new Set<() => void>()
let media: MediaQueryList | undefined

export function resolvedDark(mode: AppearanceMode) {
  return mode === "dark" || (mode === "system" && typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches)
}

function apply() {
  const root = document.documentElement, dark = resolvedDark(state.mode)
  root.classList.toggle("dark", dark)
  root.dataset.theme = dark ? "dark" : "light"
  root.style.colorScheme = dark ? "dark" : "light"
  if (state.theme === DEFAULT_THEME) delete root.dataset.palette
  else root.dataset.palette = state.theme
}
function emit() { apply(); listeners.forEach(listener => listener()) }
function watchSystem() {
  if (typeof matchMedia !== "function") return
  media ??= matchMedia("(prefers-color-scheme: dark)")
  media?.removeEventListener?.("change", apply)
  if (state.mode === "system") media?.addEventListener?.("change", apply)
}
function persist(): boolean {
  writeBrowserPreference(DEVICE_MODE_KEY, state.mode)
  return identity ? writeBrowserPreference(PREFIX + identity, JSON.stringify(state)) : true
}

/** Applies the device mode with Classic before anyone is signed in. */
export function initAppearance() { state = { theme: DEFAULT_THEME, mode: deviceMode() }; identity = undefined; watchSystem(); emit() }

/** Switches to the signed-in person's own appearance; no one sees another person's choice. */
export function setAppearanceIdentity(next?: string) {
  if (next === identity) return
  identity = next
  state = next ? load(next) : { theme: DEFAULT_THEME, mode: deviceMode() }
  watchSystem(); emit()
}

/** Each change applies at once and returns whether it was remembered on this device. */
export function setTheme(theme: ThemeId): boolean {
  if (!isThemeId(theme)) return false
  state = { ...state, theme }; emit(); return persist()
}
export function setMode(mode: AppearanceMode): boolean {
  if (!isMode(mode)) return false
  state = { ...state, mode }; watchSystem(); emit(); return persist()
}
export function resetAppearance(): boolean {
  state = { theme: DEFAULT_THEME, mode: DEFAULT_MODE }; watchSystem(); emit()
  writeBrowserPreference(DEVICE_MODE_KEY, DEFAULT_MODE)
  if (!identity) return true
  try { localStorage.removeItem(PREFIX + identity); return true } catch { return false }
}

export const getAppearance = () => state
export function subscribeAppearance(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener) } }
