import { afterEach, expect, it, vi } from 'vitest'
import { assetImportRuntime } from '../../asset-import-retry'
const createRetry = (load: (url:string)=>Promise<unknown>) => new Function('load', assetImportRuntime.replace('import(/* @vite-ignore */ url.href)', 'load(url.href)')+';return __offerpathImport')(load) as (path:string,base:string)=>Promise<unknown>
afterEach(()=>vi.useRealTimers())
it('retries the exact built entry URL without replacing the current document',async()=>{
 vi.useFakeTimers()
 const module={default:'Page'}
 const load=vi.fn().mockRejectedValueOnce(new TypeError('Failed to fetch dynamically imported module')).mockResolvedValue(module)
 const result=createRetry(load)('./triage-hash.js','https://app.example/assets/index-hash.js')
 await vi.advanceTimersByTimeAsync(600)
 expect(await result).toBe(module)
 expect(load.mock.calls.map(call=>call[0])).toEqual(['https://app.example/assets/triage-hash.js','https://app.example/assets/triage-hash.js?_offerpath_asset_retry=1'])
})
it('bounds retries and propagates persistent download failures to existing recovery',async()=>{
 vi.useFakeTimers()
 const error=new TypeError('Failed to fetch dynamically imported module')
 const load=vi.fn().mockRejectedValue(error)
 const result=createRetry(load)('./triage.js','https://app.example/assets/main.js')
 const checked=expect(result).rejects.toBe(error)
 await vi.advanceTimersByTimeAsync(2400);await checked
 expect(load).toHaveBeenCalledTimes(3)
})
it('does not retry module evaluation errors or change successful modules',async()=>{
 const error=new TypeError('Cannot read properties of undefined')
 const load=vi.fn().mockRejectedValue(error)
 await expect(createRetry(load)('./page.js','https://app.example/assets/main.js')).rejects.toBe(error)
 expect(load).toHaveBeenCalledTimes(1)
 const success=vi.fn().mockResolvedValue({default:'ok'})
 expect(await createRetry(success)('./page.js','https://app.example/assets/main.js')).toEqual({default:'ok'})
 expect(success).toHaveBeenCalledTimes(1)
})
