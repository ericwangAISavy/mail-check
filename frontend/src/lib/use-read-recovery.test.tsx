import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ApiError } from './api'
import { useReadRecovery } from './use-read-recovery'
afterEach(()=>{cleanup();vi.useRealTimers()})
it('recovers a transient read with increasing delays and a three-attempt budget',async()=>{
 vi.useFakeTimers();const retry=vi.fn().mockResolvedValue(undefined),error=new ApiError('Cloudflare unavailable',530)
 const {result,rerender}=renderHook(({revision})=>useReadRecovery({scope:'queue',error,errorUpdatedAt:revision,isFetching:false,isSuccess:false,retry}),{initialProps:{revision:1}})
 for(const [index,delay] of [5000,15000,30000].entries()){
  expect(result.current.scheduled).toBe(true);await act(()=>vi.advanceTimersByTimeAsync(delay));expect(retry).toHaveBeenCalledTimes(index+1);rerender({revision:index+2})
 }
 expect(result.current.scheduled).toBe(false);await act(()=>vi.advanceTimersByTimeAsync(60000));expect(retry).toHaveBeenCalledTimes(3)
})
it('cancels scheduled recovery when the page unmounts or a read succeeds',async()=>{
 vi.useFakeTimers();const retry=vi.fn().mockResolvedValue(undefined),error=new ApiError('Unavailable',530)
 const {rerender,unmount}=renderHook(({success})=>useReadRecovery({scope:'queue',error,errorUpdatedAt:1,isFetching:false,isSuccess:success,retry}),{initialProps:{success:false}})
 rerender({success:true});await act(()=>vi.advanceTimersByTimeAsync(60000));expect(retry).not.toHaveBeenCalled()
 rerender({success:false});unmount();await act(()=>vi.advanceTimersByTimeAsync(60000));expect(retry).not.toHaveBeenCalled()
})
it('does not retry permission failures or duplicate live-inbox polling',async()=>{
 vi.useFakeTimers();const retry=vi.fn().mockResolvedValue(undefined),errors:Record<number,ApiError>={403:new ApiError('Forbidden',403),530:new ApiError('Unavailable',530)}
 const {result,rerender}=renderHook(({status,enabled})=>useReadRecovery({scope:'queue',error:errors[status],errorUpdatedAt:1,isFetching:false,isSuccess:false,retry,enabled}),{initialProps:{status:403,enabled:true}})
 expect(result.current.scheduled).toBe(false);rerender({status:530,enabled:false});await act(()=>vi.advanceTimersByTimeAsync(60000));expect(retry).not.toHaveBeenCalled()
})
it('manual retry cancels the pending timer instead of starting a second read',async()=>{
 vi.useFakeTimers();const retry=vi.fn().mockResolvedValue(undefined),error=new ApiError('Unavailable',530)
 const {result}=renderHook(()=>useReadRecovery({scope:'queue',error,errorUpdatedAt:1,isFetching:false,isSuccess:false,retry}))
 await act(()=>result.current.retryNow());await act(()=>vi.advanceTimersByTimeAsync(60000));expect(retry).toHaveBeenCalledTimes(1)
})
