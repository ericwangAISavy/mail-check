import { useEffect, useRef, useSyncExternalStore } from "react"
import { useQuery } from "@tanstack/react-query"
import { getWorkspaceIdentityRevision, request, type Session } from "./api"
import { readBrowserPreference, writeBrowserPreference } from "./browser-preferences"

export const DESKTOP_ALERT = 1
export const SOUND_ALERT = 2
export const BIDDER_ALERT_QUERY = "bidder-inbox-alerts"
const preferenceChanged = "offerpath:bidder-mail-alert-preference"

export function bidderAlertScope(session?: Session) {
  return session?.role === "bidder" && session.bidder_id != null
    ? JSON.stringify([session.workspace_id ?? "legacy", session.bidder_id])
    : ""
}

const preferenceKey = (scope: string) => `offerpath.bidder-mail-alerts:${scope}`
function readPreferences(scope: string) {
  return scope ? Number(readBrowserPreference(preferenceKey(scope))) & (DESKTOP_ALERT | SOUND_ALERT) : 0
}

function subscribe(callback: () => void) {
  window.addEventListener(preferenceChanged, callback)
  window.addEventListener("storage", callback)
  return () => {
    window.removeEventListener(preferenceChanged, callback)
    window.removeEventListener("storage", callback)
  }
}

export function useBidderAlertPreferences(scope: string) {
  return useSyncExternalStore(subscribe, () => readPreferences(scope))
}

export function setBidderAlertPreference(scope: string, channel: number, enabled: boolean) {
  const current = readPreferences(scope)
  const next = enabled ? current | channel : current & ~channel
  if (!scope || !writeBrowserPreference(preferenceKey(scope), String(next))) return false
  window.dispatchEvent(new Event(preferenceChanged))
  return true
}

let audio: AudioContext | undefined

export async function unlockBidderAlertSound() {
  if (typeof AudioContext === "undefined") return false
  try {
    audio ??= new AudioContext()
    if (audio.state !== "running") await audio.resume()
    return audio.state === "running"
  } catch {
    return false
  }
}

function chime() {
  if (audio?.state !== "running") return false
  const output = audio.createGain()
  const sound = audio.createOscillator()
  const now = audio.currentTime
  output.gain.setValueAtTime(0, now)
  output.gain.linearRampToValueAtTime(0.12, now + 0.025)
  output.gain.exponentialRampToValueAtTime(0.001, now + 0.38)
  sound.frequency.setValueAtTime(587, now)
  sound.frequency.setValueAtTime(784, now + 0.13)
  sound.connect(output).connect(audio.destination)
  sound.onended = () => { sound.disconnect(); output.disconnect() }
  sound.start(now)
  sound.stop(now + 0.4)
  return true
}

export function showBidderMailAlert(preferences: number, message?: { id: number; scope: string }) {
  let played = false
  if (preferences & SOUND_ALERT) {
    try { played = chime() } catch { /* Audio can become unavailable while the browser is in the background. */ }
  }
  if (preferences & DESKTOP_ALERT && typeof Notification !== "undefined" && Notification.permission === "granted") {
    try {
      const identity = getWorkspaceIdentityRevision()
      const note = new Notification(message ? "New email in OfferPath" : "OfferPath alerts are ready", {
        body: message ? "Open your Inbox to view the new mail." : "This is a test of your new email alerts.",
        tag: message ? `offerpath-mail:${message.scope}:${message.id}` : "offerpath-mail-test",
        silent: true,
      })
      note.onclick = () => {
        window.focus()
        if (message && identity === getWorkspaceIdentityRevision()) window.location.assign(`/inbox?message=${message.id}`)
        note.close()
      }
      return true
    } catch { /* Some browsers disallow desktop notifications from a page. */ }
  }
  return played
}

type Cursor = { after: string; after_id: number }
type MailAlert = { cursor: Cursor; message: number | null }
const POLL_INTERVAL_MS = 12_000

/** Runs at the app shell so the alert works while using any workspace page. */
export function useBidderMailAlerts(scope: string, preferences: number) {
  const cursor = useRef<Cursor | null>(null)
  const { data, isFetchedAfterMount } = useQuery({
    queryKey: [BIDDER_ALERT_QUERY, scope],
    queryFn: ({ signal }) => {
      const query = cursor.current ? new URLSearchParams({
        after: cursor.current.after,
        after_id: String(cursor.current.after_id),
      }) : ""
      return request<MailAlert>(`/api/inbox/alerts${query ? `?${query}` : ""}`, { signal })
    },
    refetchInterval: POLL_INTERVAL_MS,
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })

  const sound = Boolean(preferences & SOUND_ALERT)
  useEffect(() => {
    if (!sound) return
    const unlock = () => void unlockBidderAlertSound()
    window.addEventListener("pointerdown", unlock, { capture: true, once: true })
    window.addEventListener("keydown", unlock, { capture: true, once: true })
    return () => {
      window.removeEventListener("pointerdown", unlock, true)
      window.removeEventListener("keydown", unlock, true)
    }
  }, [sound])

  useEffect(() => {
    if (!data || !isFetchedAfterMount) return
    const previous = cursor.current
    cursor.current = data.cursor
    if (!data.message || previous?.after === data.cursor.after && previous.after_id === data.cursor.after_id) return
    // Tabs in the same browser share the delivery marker for this bidder.
    const deliveredKey = `${preferenceKey(scope)}:delivered`
    const [deliveredAt, deliveredId] = readBrowserPreference(deliveredKey).split(" ")
    const { after, after_id } = data.cursor
    if (deliveredAt > after || deliveredAt === after && Number(deliveredId) >= after_id) return
    if (showBidderMailAlert(preferences, { id: data.message, scope })) {
      writeBrowserPreference(deliveredKey, `${after} ${after_id}`)
    }
  }, [data, isFetchedAfterMount, preferences, scope])
}
