import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { AccountSync } from './realtime-accounts'

afterEach(()=>{cleanup();vi.unstubAllGlobals()})
const json=(body:unknown)=>new Response(JSON.stringify(body),{headers:{'Content-Type':'application/json'}})
function serve(status:{configured:boolean;accounts:{account_id:number;enabled:boolean}[]}) {
  const fetch=vi.fn().mockImplementation(async(_url:string,init?:RequestInit)=>json(init?.method==='POST'?{ok:true}:status))
  vi.stubGlobal('fetch',fetch)
  return fetch
}
function mount(account:{id:number;label:string;enabled:boolean;provider:string},onChanged=vi.fn()) {
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><AccountSync account={account} onChanged={onChanged}/></QueryClientProvider>)
  return onChanged
}
const posts=(fetch:ReturnType<typeof vi.fn>)=>fetch.mock.calls.filter(([,init])=>init?.method==='POST').map(([url,init])=>[url,init.body])

it('turns automatic sync on for an account only when asked',async()=>{
  const fetch=serve({configured:true,accounts:[{account_id:1,enabled:false}]})
  const onChanged=mount({id:1,label:'Work',enabled:true,provider:'outlook'})
  const toggle=await screen.findByRole('switch',{name:'Sync Work'})
  await waitFor(()=>expect((toggle as HTMLButtonElement).disabled).toBe(false))
  expect(toggle.getAttribute('aria-checked')).toBe('false')
  expect(posts(fetch)).toEqual([])
  fireEvent.click(toggle)
  await waitFor(()=>expect(posts(fetch)).toEqual([['/api/realtime/accounts/1','{"enabled":true}']]))
  await waitFor(()=>expect(onChanged).toHaveBeenCalled())
})

it('includes a paused account in checks again when sync is turned on',async()=>{
  const fetch=serve({configured:true,accounts:[{account_id:2,enabled:true}]})
  mount({id:2,label:'Old inbox',enabled:false,provider:'imap'})
  const toggle=await screen.findByRole('switch',{name:'Sync Old inbox'})
  await waitFor(()=>expect((toggle as HTMLButtonElement).disabled).toBe(false))
  expect(toggle.getAttribute('aria-checked')).toBe('false')   // a paused account is not syncing
  fireEvent.click(toggle)
  await waitFor(()=>expect(posts(fetch)).toEqual([
    ['/api/accounts/Old%20inbox/toggle?enabled=true',undefined],
    ['/api/realtime/accounts/2','{"enabled":true}']]))
})

it('turns sync off without pausing the account',async()=>{
  const fetch=serve({configured:true,accounts:[{account_id:1,enabled:true}]})
  mount({id:1,label:'Work',enabled:true,provider:'outlook'})
  const toggle=await screen.findByRole('switch',{name:'Sync Work'})
  await waitFor(()=>expect(toggle.getAttribute('aria-checked')).toBe('true'))
  fireEvent.click(toggle)
  await waitFor(()=>expect(posts(fetch)).toEqual([['/api/realtime/accounts/1','{"enabled":false}']]))
})

it('disables sync with an explanation when the server has no automatic sync',async()=>{
  serve({configured:false,accounts:[]})
  mount({id:1,label:'Work',enabled:true,provider:'outlook'})
  const toggle=await screen.findByRole('switch',{name:'Sync Work'})
  await waitFor(()=>expect(toggle.closest('.account-sync')?.getAttribute('title')).toBe('Automatic sync is not available on this server.'))
  expect((toggle as HTMLButtonElement).disabled).toBe(true)
})
