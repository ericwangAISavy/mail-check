import {afterEach,expect,it} from 'vitest'
import {browserTimezone,calendarParts,calendarTimezone,CALENDAR_TIMEZONE_KEY,savedCalendarTimezone} from './calendar-timezone'
afterEach(()=>localStorage.clear())
it('falls back safely for invalid stored and shared zones',()=>{
 localStorage.setItem(CALENDAR_TIMEZONE_KEY,'Invalid/Zone')
 expect(savedCalendarTimezone()).toBe('local')
 expect(calendarTimezone(new URLSearchParams('calendar_tz=Invalid/Zone'))).toBe(browserTimezone())
 expect(calendarTimezone(new URLSearchParams('calendar_tz=UTC'),'Asia/Tokyo')).toBe('UTC')
})
it('preserves target wall-clock parts even during a browser DST gap',()=>{
 expect(calendarParts(new Date('2026-03-07T17:30:00Z'),'Asia/Tokyo')).toMatchObject({key:'2026-03-08',minutes:150})
})
