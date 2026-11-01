import { expect, it } from "vitest"
import { calendarCounts, dayKey, exportInterviews, fallsOnDay, parseDay, placeEvents, viewDays } from "./interview-calendar"
import type { InterviewEvent } from "./types"
const day=new Date(2026,9,15)
const event=(id:number,hour:number,minute=0,endHour=hour+1,endMinute=minute):InterviewEvent=>({id,start_at:new Date(2026,9,15,hour,minute).toISOString(),end_at:new Date(2026,9,15,endHour,endMinute).toISOString(),company:'Acme',role:'Engineer',stage:'Technical Interview',status:'Scheduled',display_status:'Scheduled',calendar_uid:'same-source-uid',needs_review:false,timezone:'UTC',meeting_platform:'Zoom',meeting_url:'https://zoom.us/j/123',location:null,organizer_email:null,organizer_name:null,participants:[],notes:null,confidence:1,manual_fields:[],created_at:'2026-10-15T00:00:00Z',updated_at:'2026-10-15T00:00:00Z',review_reason:null})
it('defaults to a five-day Monday-to-Friday work week with real calendar dates',()=>{
 const days=viewDays(day,'workweek');expect(days.map(dayKey)).toEqual(['2026-10-12','2026-10-13','2026-10-14','2026-10-15','2026-10-16'])
 expect(viewDays(day,'week')).toHaveLength(7);expect(viewDays(day,'month')).toHaveLength(42);expect(viewDays(day,'day')).toHaveLength(1)
 expect(parseDay('2026-02-31')).toBeNull();expect(dayKey(parseDay('2026-10-15')!)).toBe('2026-10-15')
})
it('positions events by local clock minutes, partitions overlapping events, and resets after overlaps',()=>{
 const places=placeEvents([event(1,10,0,11,0),event(2,10,30,11,30),event(3,11,0,12,0),event(4,14,0,15,0)],day)
 expect(places.map(p=>[p.start,p.end,p.lane,p.lanes])).toEqual([[600,660,0,2],[630,690,1,2],[660,720,0,2],[840,900,0,1]])
})
it('does not overlap appointments that only touch at their boundary',()=>{
 expect(placeEvents([event(1,10),event(2,11)],day).map(p=>p.lanes)).toEqual([1,1])
})
it('clips multi-day events at midnight and does not duplicate an exclusive midnight end',()=>{
 const e={...event(1,23,30),end_at:new Date(2026,9,16,1).toISOString()}
 expect(placeEvents([e],day)[0]).toMatchObject({start:1410,end:1440,continuesAfter:true})
 expect(placeEvents([e],new Date(2026,9,16))[0]).toMatchObject({start:0,end:60,continuesBefore:true})
 expect(fallsOnDay({...e,end_at:new Date(2026,9,16,0).toISOString()},new Date(2026,9,16))).toBe(false)
})
it('keeps an unknown duration explicit and skips records without a valid start time',()=>{
 const e={...event(1,10),end_at:null}
 expect(placeEvents([e],day)[0]).toMatchObject({start:600,end:620,unknownEnd:true})
 expect(placeEvents([{...e,id:2,start_at:null},{...e,id:3,start_at:'bad date'}],day)).toEqual([])
})
it('exports valid escaped UTC snapshots with unique UIDs and real cancellation state',()=>{
 const e={...event(1,10),company:'Acme, Inc; \nBEGIN:BAD',notes:'Hello\nworld'}
 const data=exportInterviews([e,{...event(2,11),status:'Cancelled'},{...event(3,12),start_at:null}],new Date('2026-10-15T12:00:00Z'))
 expect(data).toContain('BEGIN:VCALENDAR\r\n');expect(data.match(/BEGIN:VEVENT/g)).toHaveLength(2)
 expect(data).toContain('UID:mailcheck-interview-1@local');expect(data).toContain('UID:mailcheck-interview-2@local')
 expect(data).toContain('STATUS:CANCELLED');expect(data).toContain('Acme\\, Inc\\; \\nBEGIN:BAD')
 expect(data).not.toContain('\r\nBEGIN:BAD');expect(data).toContain('DTSTAMP:20261015T120000Z')
 for(const line of data.split('\r\n'))expect(new TextEncoder().encode(line).length).toBeLessThanOrEqual(75)
})

it('counts visible unique interviews by actual duration, with 30 minutes counted as intro',()=>{
 const intro=event(1,10,0,10,30),short=event(2,11,0,11,15),tech=event(3,12,0,13,0)
 const unknown={...event(4,14),end_at:null},cancelled={...event(5,15),status:'Cancelled'}
 const outside={...event(6,10),start_at:new Date(2026,9,20,10).toISOString(),end_at:new Date(2026,9,20,11).toISOString()}
 expect(calendarCounts([intro,short,tech,unknown,cancelled,outside,intro],[day])).toEqual({total:4,intro:2,tech:1,unknown:1})
 expect(calendarCounts([intro,tech],[])).toEqual({total:0,intro:0,tech:0,unknown:0})
})
