import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react'
import {QueryClient,QueryClientProvider} from '@tanstack/react-query'
import {InterviewFeedback,feedbackChunks} from './interview-feedback'
import {FeedbackBadges,FeedbackIndicator} from './interview-feedback-badges'

afterEach(()=>{cleanup();vi.unstubAllGlobals()})

it('prioritizes warning feedback and uses a normal indicator only without warnings',()=>{
 const view=render(<FeedbackIndicator tags={['normal','linkedin']}/>)
 expect(screen.getByRole('img',{name:'Warning feedback: linkedin'})).toBeTruthy()
 expect(screen.queryByRole('img',{name:'Normal feedback'})).toBeNull()
 view.rerender(<FeedbackIndicator tags={['normal']}/>)
 expect(screen.getByRole('img',{name:'Normal feedback'})).toBeTruthy()
 view.rerender(<FeedbackIndicator tags={[]}/>)
 expect(screen.queryByRole('img')).toBeNull()
})

it('bounds company queries by count and encoded URL size',()=>{
 const companies=Array.from({length:125},(_,i)=>`Company ${i} ${'界'.repeat(180)}`)
 const chunks=feedbackChunks([...companies,...companies,'Unknown company'])
 expect(chunks.flat()).toHaveLength(125)
 for(const chunk of chunks){expect(chunk.length).toBeLessThanOrEqual(40);expect(encodeURIComponent(JSON.stringify(chunk)).length).toBeLessThanOrEqual(6000)}
})

it('displays exactly the four fixed badge labels',()=>{
 render(<FeedbackBadges tags={['in-person','linkedin','fuck','normal']}/>);
 const group=screen.getByRole('group',{name:'Shared company feedback'})
 expect([...group.children].map(node=>node.textContent)).toEqual(['in-person','linkedin','fuck','normal'])
})

it('selects several badges and keeps feedback supplied by other admins visible',async()=>{
 let mine:string[]=[]
 const fetch=vi.fn(async(_url:string,init?:RequestInit)=>{
  if(init?.method==='POST'){mine=JSON.parse(String(init.body)).tags;return new Response(JSON.stringify({ok:true}),{headers:{'content-type':'application/json'}})}
  return new Response(JSON.stringify({companies:{Acme:{tags:[...new Set([...mine,'normal'])],mine}}}),{headers:{'content-type':'application/json'}})
 })
 vi.stubGlobal('fetch',fetch)
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 render(<QueryClientProvider client={client}><InterviewFeedback eventId={7} company="Acme"/></QueryClientProvider>)
 const linkedin=await screen.findByRole('button',{name:'linkedin'})
 fireEvent.click(linkedin)
 await waitFor(()=>expect(linkedin.getAttribute('aria-pressed')).toBe('true'))
 fireEvent.click(screen.getByRole('button',{name:'in-person'}))
 await waitFor(()=>expect(mine).toEqual(['in-person','linkedin']))
 expect(within(screen.getByRole('group',{name:'Shared company feedback'})).getByText('normal')).toBeTruthy()
 expect(screen.queryByRole('textbox')).toBeNull()
 const posts=fetch.mock.calls.filter(([,init])=>init?.method==='POST')
 expect(JSON.parse(String(posts.at(-1)?.[1]?.body))).toEqual({event_id:7,company:'Acme',tags:['in-person','linkedin']})
 client.clear()
})

it('shows a retry when shared feedback is unavailable',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({detail:'Feedback unavailable.'}),{status:503,headers:{'content-type':'application/json'}})))
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 render(<QueryClientProvider client={client}><InterviewFeedback eventId={7} company="Acme"/></QueryClientProvider>)
 expect(await screen.findByRole('alert')).toBeTruthy()
 expect(screen.getByRole('button',{name:'Retry feedback'})).toBeTruthy()
 client.clear()
})
