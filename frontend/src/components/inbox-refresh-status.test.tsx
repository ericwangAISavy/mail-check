import { afterEach, expect, it, vi } from "vitest"
import { act, cleanup, render, screen } from "@testing-library/react"
import { InboxRefreshStatus } from "./inbox-refresh-status"
import type { TriageData } from "@/lib/types"
const schedule=():NonNullable<TriageData['check_schedule']>=>({automatic:true,running:false,next_at:null,live:{enabled:true,interval_seconds:30,running:false,last_checked_at:null,next_at:new Date(Date.now()+30000).toISOString()}})
afterEach(()=>{cleanup();vi.useRealTimers()})
it('counts down without making additional server requests',()=>{
 vi.useFakeTimers();vi.setSystemTime(new Date('2026-11-10T18:00:00Z'))
 render(<InboxRefreshStatus schedule={schedule()}/>)
 expect(screen.getByText('(in 30s)')).toBeTruthy()
 act(()=>vi.advanceTimersByTime(1000))
 expect(screen.getByText('(in 29s)')).toBeTruthy()
})
it('prioritizes active mail collection over the generic server task state',()=>{
 const value=schedule();value.running=true;value.live!.running=true
 render(<InboxRefreshStatus schedule={value}/>)
 expect(screen.getByRole('status').textContent).toContain('checking for new mail…')
 expect(screen.queryByText(/Next live check:/)).toBeNull()
})
it('explains server delays, failed checks and successful freshness separately',()=>{
 const value=schedule();value.running=true;value.live!.last_check_ok=false;value.live!.last_checked_at='2026-11-10T17:00:00Z'
 render(<InboxRefreshStatus schedule={value}/>)
 expect(screen.getByText('Next live check: after the current server task finishes')).toBeTruthy()
 expect(screen.getByText(/last live mail check failed/)).toBeTruthy()
 expect(screen.getByText(/Last successful live check:/)).toBeTruthy()
})
it('does not show a stale countdown while disconnected',()=>{
 render(<InboxRefreshStatus schedule={schedule()} unavailable/>)
 expect(screen.getByRole('status').textContent).toContain('connection interrupted')
 expect(screen.queryByText(/Next live check:/)).toBeNull()
})
it('shows a disabled reason and tolerates invalid saved timestamps',()=>{
 const value=schedule();value.live!.enabled=false;value.live!.disabled_reason='No active assigned mailboxes.';value.live!.last_checked_at='bad-date'
 render(<InboxRefreshStatus schedule={value}/>)
 expect(screen.getByText('No active assigned mailboxes.')).toBeTruthy()
 expect(screen.queryByText(/Invalid Date/)).toBeNull()
})
