import {afterEach,expect,it,vi} from 'vitest'
import {readBrowserPreference,writeBrowserPreference} from './browser-preferences'
afterEach(()=>{vi.restoreAllMocks();localStorage.clear()})
it('uses a safe fallback when browser storage is blocked',()=>{
 vi.spyOn(Storage.prototype,'getItem').mockImplementation(()=>{throw new DOMException('blocked','SecurityError')})
 expect(readBrowserPreference('mailcheck.theme','dark')).toBe('dark')
})
it('keeps preference changes usable when writing is denied',()=>{
 vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw new DOMException('full','QuotaExceededError')})
 expect(()=>writeBrowserPreference('mailcheck.theme','light')).not.toThrow()
 expect(writeBrowserPreference('mailcheck.theme','light')).toBe(false)
})
it('reads and saves available preferences',()=>{
 expect(writeBrowserPreference('mailcheck.theme','light')).toBe(true)
 expect(readBrowserPreference('mailcheck.theme','dark')).toBe('light')
})
