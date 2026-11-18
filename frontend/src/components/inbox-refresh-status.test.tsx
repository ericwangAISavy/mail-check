import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { act, cleanup, render, screen } from "@testing-library/react"
import { InboxRefreshStatus } from "./inbox-refresh-status"
import type { TriageData } from "@/lib/types"
const NOW=new Date('2026-11-18T18:00:00Z')
const ago=(seconds:number)=>new Date(NOW.getTime()-seconds*1000).toISOString()
const schedule=(updated:string|null=ago(20)):NonNullable<TriageData['check_schedule']>=>({automatic:true,running:false,next_at:null,live:{enabled:true,interval_seconds:30,running:false,last_checked_at:null,next_at:null,updated_at:updated}})
const bar=()=>screen.getByRole('region',{name:'Inbox update schedule'})
const status=()=>screen.getByRole('status').textContent
beforeEach(()=>{vi.useFakeTimers();vi.setSystemTime(NOW)})
afterEach(()=>{cleanup();vi.useRealTimers()})

it('shows one compact live line with how fresh the Inbox is, and no countdown',()=>{
 render(<InboxRefreshStatus schedule={schedule()}/>)
 expect(bar().className).toContain('tone-live')
 expect(screen.getByText('Live')).toBeTruthy()
 expect(status()).toBe('Updated 20 seconds ago')
 act(()=>vi.advanceTimersByTime(45000))
 expect(status()).toBe('Updated 1 min ago')
 expect(status()).not.toMatch(/Next|in \d+s|due/)
})
it('shows the exact update time on hover',()=>{
 render(<InboxRefreshStatus schedule={schedule()}/>)
 expect(screen.getByRole('status').querySelector('time')!.getAttribute('title')).toBe(new Date(ago(20)).toLocaleString())
})
it('keeps the explanation in a tooltip instead of a separate line',()=>{
 render(<InboxRefreshStatus schedule={schedule()}/>)
 const hint=screen.getByRole('img',{name:/Refresh Inbox reloads saved messages/})
 expect(hint.getAttribute('title')).toMatch(/collected automatically/)
 expect(screen.queryByText(/Refresh Inbox reloads/)).toBeNull()
})
it('falls back to the last live check when no Inbox-wide time is available',()=>{
 const value=schedule(null);value.live!.last_checked_at=ago(90)
 render(<InboxRefreshStatus schedule={value}/>)
 expect(status()).toBe('Updated 1 min ago')
})
it('waits for the first update',()=>{
 render(<InboxRefreshStatus schedule={schedule(null)}/>)
 expect(status()).toBe('Waiting for the first update')
})
it('shows active collection and server work as busy',()=>{
 const value=schedule();value.live!.running=true
 const {unmount}=render(<InboxRefreshStatus schedule={value}/>)
 expect(bar().className).toContain('tone-busy')
 expect(status()).toBe('Checking for new mail… · Updated 20 seconds ago')
 unmount()
 const busy=schedule();busy.running=true
 render(<InboxRefreshStatus schedule={busy}/>)
 expect(status()).toBe('Updated 20 seconds ago · server is busy')
})
it('highlights failed checks and stale updates',()=>{
 const failed=schedule(ago(7*60));failed.live!.last_check_ok=false
 const {unmount}=render(<InboxRefreshStatus schedule={failed}/>)
 expect(bar().className).toContain('tone-warn')
 expect(screen.getByText('Retrying')).toBeTruthy()
 expect(status()).toBe('Last check failed — retrying automatically · Updated 7 min ago')
 unmount()
 render(<InboxRefreshStatus schedule={schedule(ago(7*60))}/>)
 expect(screen.getByText('Delayed')).toBeTruthy()
 expect(status()).toBe('Updates are running late · Updated 7 min ago')
})
it('turns late only after five minutes',()=>{
 render(<InboxRefreshStatus schedule={schedule(ago(4*60+50))}/>)
 expect(screen.getByText('Live')).toBeTruthy()
 act(()=>vi.advanceTimersByTime(15000))
 expect(screen.getByText('Delayed')).toBeTruthy()
})
it('does not show stale timing while disconnected',()=>{
 render(<InboxRefreshStatus schedule={schedule()} unavailable/>)
 expect(screen.getByText('Offline')).toBeTruthy()
 expect(status()).toBe('Connection interrupted — retrying automatically')
})
it('shows a disabled reason and tolerates invalid saved timestamps',()=>{
 const value=schedule('bad-date');value.live!.enabled=false;value.live!.disabled_reason='No active assigned mailboxes.'
 render(<InboxRefreshStatus schedule={value}/>)
 expect(bar().className).toContain('tone-off')
 expect(status()).toBe('No active assigned mailboxes.')
 expect(screen.queryByText(/Invalid Date/)).toBeNull()
})
