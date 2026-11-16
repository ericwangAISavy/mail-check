import {cleanup, fireEvent, render, screen, within} from '@testing-library/react'
import {afterEach, expect, it} from 'vitest'
import MonitorEventHistory from './monitor-event-history'
afterEach(cleanup)
const events=[
 {id:'a',at:100,workspace:'one',component:'mail',action:'queued',status:'healthy' as const,job_id:'job-1'},
 {id:'b',at:160,workspace:'two',component:'classify',action:'retry_scheduled',status:'degraded' as const,job_id:'job-2'},
 {id:'c',at:220,workspace:'one',component:'events',action:'published',status:'healthy' as const,job_id:'change-3'},
]
it('plots recorded events by time and component and opens selected details without a table',()=>{
 render(<MonitorEventHistory events={events} names={new Map([['one','Original'],['two','Austin']])}/> )
 const graph=screen.getByRole('region',{name:'Status history'})
 expect(within(graph).queryByRole('table')).toBeNull()
 expect(screen.getByText('published')).toBeTruthy()
 const point=screen.getByRole('button',{name:/Classification.*degraded.*1 event/i})
 fireEvent.keyDown(point,{key:'Enter'})
 expect(screen.getByText('retry scheduled')).toBeTruthy()
 expect(screen.getByText(/Austin/)).toBeTruthy()
 expect(screen.getByText('job-2')).toBeTruthy()
 expect(screen.queryByText('change-3')).toBeNull()
})
it('groups nearby events without discarding their identities',()=>{
 render(<MonitorEventHistory events={[events[0],{...events[0],id:'copy',job_id:'job-copy'}]} names={new Map()}/> )
 expect(screen.getByRole('button',{name:/2 events/i})).toBeTruthy()
 expect(screen.getByText('job-1')).toBeTruthy()
 expect(screen.getByText('job-copy')).toBeTruthy()
})
it('handles empty filters and a selection that disappears on refresh',()=>{
 const {rerender}=render(<MonitorEventHistory events={events} names={new Map()}/> )
 fireEvent.click(screen.getByRole('button',{name:/Classification.*degraded.*1 event/i}))
 rerender(<MonitorEventHistory events={[events[0]]} names={new Map()}/> )
 expect(screen.getByText('queued')).toBeTruthy()
 rerender(<MonitorEventHistory events={[]} names={new Map()}/> )
 expect(screen.getByText(/No events match/)).toBeTruthy()
})

it('retains the selected event as live events extend the time range',()=>{
 const {rerender}=render(<MonitorEventHistory events={events} names={new Map()}/> )
 fireEvent.click(screen.getByRole('button',{name:/Classification.*degraded.*1 event/i}))
 rerender(<MonitorEventHistory events={[...events,{...events[2],id:'later',at:1000,job_id:'later-change'}]} names={new Map()}/> )
 expect(screen.getByText('job-2')).toBeTruthy()
 expect(screen.queryByText('later-change')).toBeNull()
})
