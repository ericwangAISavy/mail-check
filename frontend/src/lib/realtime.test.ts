import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider, QueryObserver } from '@tanstack/react-query'
import { createElement } from 'react'
import { connectRealtime, useRealtimeUpdates } from './realtime'
import { setWorkspaceIdentity } from './api'
import SourcingViewer from '@/components/sourcing-viewer'

vi.mock('@/components/auth',()=>({useAuth:()=>({session:{workspace_id:'legacy',role:'bidder',bidder_id:1}})}))

class Stream {
  static all: Stream[] = []
  listeners = new Map<string, (event: MessageEvent) => void>()
  onerror: (()=>void) | null = null
  close = vi.fn()
  constructor(readonly url: string) { Stream.all.push(this) }
  addEventListener(name: string, listener: (event: MessageEvent)=>void) { this.listeners.set(name, listener) }
  emit(name: string, id='1-0') { this.listeners.get(name)?.({lastEventId:id} as MessageEvent) }
}
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals();setWorkspaceIdentity();Stream.all=[]})

it('coalesces committed updates and closes immediately when workspace identity changes', async()=>{
  vi.stubGlobal('EventSource', Stream)
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"configured":true}',{headers:{'Content-Type':'application/json'}})))
  setWorkspaceIdentity('legacy','owner')
  const changed=vi.fn(), ended=vi.fn()
  const stop=connectRealtime('legacy',changed,ended)
  await vi.waitFor(()=>expect(Stream.all).toHaveLength(1))
  const stream=Stream.all[0]
  expect(stream.url).toContain('workspace=legacy')
  stream.emit('changed');stream.emit('changed')
  await vi.waitFor(()=>expect(changed).toHaveBeenCalledTimes(1))
  setWorkspaceIdentity('other','other-user')
  expect(stream.close).toHaveBeenCalled()
  stream.emit('session-ended')
  expect(ended).not.toHaveBeenCalled()
  stop()
})

it('does not open a stream when realtime is not configured',async()=>{
  vi.stubGlobal('EventSource', Stream)
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('{"configured":false}',{headers:{'Content-Type':'application/json'}})))
  setWorkspaceIdentity('legacy','owner')
  const stop=connectRealtime('legacy',vi.fn(),vi.fn())
  await new Promise(resolve=>setTimeout(resolve,10))
  expect(Stream.all).toHaveLength(0)
  stop()
})

it('revalidates authentication when the server ends a session stream',async()=>{
  vi.stubGlobal('EventSource', Stream)
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('{"configured":true}',{headers:{'Content-Type':'application/json'}})))
  setWorkspaceIdentity('legacy','owner')
  const ended=vi.fn()
  const stop=connectRealtime('legacy',vi.fn(),ended)
  await vi.waitFor(()=>expect(Stream.all).toHaveLength(1))
  Stream.all[0].emit('session-ended')
  expect(ended).toHaveBeenCalledOnce()
  expect(Stream.all[0].close).toHaveBeenCalled()
  stop()
})

it('refreshes an open read-only sourcing sheet after a committed realtime update',async()=>{
  vi.stubGlobal('EventSource',Stream)
  let company='Acme'
  const cell=(value:string)=>({value,display:value,style:{}})
  vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(url==='/api/realtime/capabilities'?{configured:true}:{
    columns:[{id:'company',title:'Company',kind:'company'}],row_ids:['header','job'],row_dates:[null,'2026-11-13'],
    rows:[[cell('Company')],[cell(company)]],
  }),{headers:{'Content-Type':'application/json'}})))
  setWorkspaceIdentity('legacy','bidder')
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
  function View(){useRealtimeUpdates();return createElement(SourcingViewer,{tab:{id:7,title:'Work',account_id:1,header_row:1,refreshed_at:0},initialDay:'2026-11-13'})}
  const view=render(createElement(QueryClientProvider,{client},createElement(View)))
  try {
    await screen.findByText('Acme')
    await vi.waitFor(()=>expect(Stream.all).toHaveLength(1))
    company='Updated company'
    Stream.all[0].emit('changed')
    await screen.findByText('Updated company')
    expect(screen.queryByText('Acme')).toBeNull()
  } finally { view.unmount();client.clear() }
})

it('refreshes active business views and filters after committed changes',async()=>{
  vi.stubGlobal('EventSource',Stream)
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('{"configured":true}',{headers:{'Content-Type':'application/json'}})))
  setWorkspaceIdentity('legacy','bidder')
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
  const keys=['sourcing-filters','sourcing-role-filters','bidder-management','bidder-visibility','bidder-access','followups','reply-context']
  const reads=keys.map(()=>vi.fn(async()=>'updated'))
  const stops=keys.map((key,index)=>{
    client.setQueryData([key],'initial')
    return new QueryObserver(client,{queryKey:[key],queryFn:reads[index],staleTime:Infinity}).subscribe(()=>{})
  })
  function Live(){useRealtimeUpdates();return null}
  const view=render(createElement(QueryClientProvider,{client},createElement(Live)))
  try {
    await vi.waitFor(()=>expect(Stream.all).toHaveLength(1))
    Stream.all[0].emit('changed')
    await vi.waitFor(()=>reads.forEach(read=>expect(read).toHaveBeenCalledOnce()))
    keys.forEach(key=>expect(client.getQueryData([key])).toBe('updated'))
  } finally {view.unmount();stops.forEach(stop=>stop());client.clear()}
})
