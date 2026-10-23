import { afterEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { ToastProvider } from "@/components/common"
import InterviewCalendar from "./interview-calendar"
import type { InterviewEvent } from "@/lib/types"
const accounts=[{id:1,label:'personal',email:'me@example.test'},{id:2,label:'work',email:'work@example.test'}]
const event=(id:number,label:string):InterviewEvent=>({id,account_labels:[label],company:label==='work'?'Work Company':'Personal Company',role:'Engineer',stage:'Technical Interview',calendar_uid:null,status:'Scheduled',display_status:'Scheduled',start_at:new Date(2026,9,15,10).toISOString(),end_at:new Date(2026,9,15,11).toISOString(),timezone:'UTC',meeting_platform:null,meeting_url:null,location:null,organizer_name:null,organizer_email:null,participants:[],notes:null,confidence:1,needs_review:false,review_reason:null,manual_fields:[],created_at:'2026-10-15T00:00:00Z',updated_at:'2026-10-15T00:00:00Z'})
const clipboard=Object.getOwnPropertyDescriptor(navigator,'clipboard')
afterEach(()=>{cleanup();if(clipboard)Object.defineProperty(navigator,'clipboard',clipboard);else Reflect.deleteProperty(navigator,'clipboard');vi.restoreAllMocks()})
function mount(){render(<MemoryRouter initialEntries={['/interviews?calendar_date=2026-10-15&account=work']}><ToastProvider><InterviewCalendar events={[event(1,'personal'),event(2,'work')]} accounts={accounts} account="" filterCount={0} filters={<label>Account filter<input aria-label="Account filter"/></label>} onSelect={()=>undefined}/></ToastProvider></MemoryRouter>)}
it('opens real filters and partitions split calendars by source account',()=>{
 mount();expect(screen.queryByLabelText('Account filter')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'Filter'}));expect(screen.getByLabelText('Account filter')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'Split view'}))
 const calendars=document.querySelectorAll('.outlook-account-calendar')
 expect(calendars.length).toBe(2)
 expect(calendars[0].querySelectorAll('.outlook-time-event').length).toBe(1)
 expect(calendars[0].querySelector('.outlook-time-event')!.textContent).toContain('Personal Company')
 expect(calendars[1].querySelector('.outlook-time-event')!.textContent).toContain('Work Company')
})
it('uses the date picker and switches between work week, full week, month and day',()=>{
 mount();expect(document.querySelectorAll('.outlook-day-heading').length).toBe(5)
 fireEvent.click(screen.getByRole('button',{name:'Week'}));expect(document.querySelectorAll('.outlook-day-heading').length).toBe(7)
 fireEvent.click(screen.getByRole('button',{name:'Month'}));expect(document.querySelectorAll('.outlook-month-day').length).toBe(42)
 fireEvent.click(screen.getByRole('button',{name:'Day'}));expect(document.querySelectorAll('.outlook-day-heading').length).toBe(1)
 fireEvent.click(screen.getByRole('button',{name:/^Thursday, October 15, 2026/}))
 fireEvent.change(screen.getByLabelText('Go to date'),{target:{value:'2026-10-20'}})
 expect(screen.getByRole('button',{name:/^Tuesday, October 20, 2026/})).toBeTruthy()
})
it('copies a canonical calendar link with view/date/filters and prints on demand',async()=>{
 const writeText=vi.fn().mockResolvedValue(undefined);Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText}})
 const print=vi.spyOn(window,'print').mockImplementation(()=>undefined)
 mount();fireEvent.click(screen.getByRole('button',{name:'Share'}));fireEvent.click(screen.getByRole('button',{name:'Copy calendar link'}))
 await waitFor(()=>expect(writeText).toHaveBeenCalledTimes(1))
 const url=new URL(writeText.mock.calls[0][0]);expect(url.searchParams.get('calendar_view')).toBe('workweek');expect(url.searchParams.get('calendar_date')).toBe('2026-10-15');expect(url.searchParams.get('account')).toBe('work')
 fireEvent.click(screen.getByRole('button',{name:'Print'}));expect(print).toHaveBeenCalledTimes(1)
})
it('keeps a combined meeting color stable when source account order changes',()=>{
 const value={...event(3,'work'),account_labels:['work','personal']}
 const draw=(labels:string[])=>render(<MemoryRouter initialEntries={['/interviews?calendar_date=2026-10-15']}><ToastProvider><InterviewCalendar events={[{...value,account_labels:labels}]} accounts={accounts} account="" filterCount={0} filters={null} onSelect={()=>undefined}/></ToastProvider></MemoryRouter>)
 draw(value.account_labels)
 const first=screen.getByRole('button',{name:/Work Company, Technical Interview/}).className.match(/account-color-\d/)![0]
 cleanup();draw(['personal','work'])
 expect(screen.getByRole('button',{name:/Work Company, Technical Interview/}).className).toContain(first)
})
it('shows intro and tech totals next to the current period and updates on navigation',async()=>{
 const intro={...event(1,'personal'),end_at:new Date(2026,9,15,10,30).toISOString()}
 render(<MemoryRouter initialEntries={['/interviews?calendar_date=2026-10-15']}><ToastProvider><InterviewCalendar events={[intro,event(2,'work')]} accounts={accounts} account="" filterCount={0} filters={null} onSelect={()=>undefined}/></ToastProvider></MemoryRouter>)
 expect(screen.getByRole('status',{name:'Interview counts'}).textContent).toBe('Total 2 / Intro 1 / Tech 1')
 fireEvent.click(screen.getByRole('button',{name:'Next calendar period'}))
 await waitFor(()=>expect(screen.getByRole('status',{name:'Interview counts'}).textContent).toBe('Total 0 / Intro 0 / Tech 0'))
})
it('keeps an account color unchanged when the account list is reordered',()=>{
 const draw=(list:typeof accounts)=>render(<MemoryRouter initialEntries={['/interviews?calendar_date=2026-10-15']}><ToastProvider><InterviewCalendar events={[event(1,'work')]} accounts={list} account="" filterCount={0} filters={null} onSelect={()=>undefined}/></ToastProvider></MemoryRouter>)
 draw(accounts)
 const before=screen.getByRole('button',{name:/Work Company, Technical Interview/}).className.match(/account-color-\d/)![0]
 cleanup();draw([...accounts].reverse())
 expect(screen.getByRole('button',{name:/Work Company, Technical Interview/}).className).toContain(before)
})
