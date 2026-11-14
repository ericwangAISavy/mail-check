import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import RealtimeAccounts from './realtime-accounts'

afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('requires an explicit account opt-in and reports sync health',async()=>{
  const fetch=vi.fn().mockImplementation(async(_url:string,init?:RequestInit)=>new Response(JSON.stringify(
    init?.method==='POST'?{ok:true}:{configured:true,public_ready:true,accounts:[{account_id:1,enabled:false,last_sync:null,last_error:''}]}),{headers:{'Content-Type':'application/json'}}))
  vi.stubGlobal('fetch',fetch)
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><RealtimeAccounts accounts={[{id:1,label:'Work',enabled:true,provider:'outlook'}]} /></QueryClientProvider>)
  const toggle=await screen.findByRole('switch',{name:'Automatic updates for Work'})
  expect(fetch.mock.calls.every(([,init])=>!init?.method)).toBe(true)
  fireEvent.click(toggle)
  await waitFor(()=>expect(fetch).toHaveBeenCalledWith('/api/realtime/accounts/1',expect.objectContaining({method:'POST',body:'{"enabled":true}'})))
})

it('explains when automatic updates are not configured',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('{"configured":false,"accounts":[]}',{headers:{'Content-Type':'application/json'}})))
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><RealtimeAccounts accounts={[]} /></QueryClientProvider>)
  expect(await screen.findByText(/Automatic updates are not configured/)).toBeTruthy()
})
