import { afterEach, describe, expect, it, vi } from "vitest"
import { request, triageParams, setWorkspaceIdentity, ApiError } from "./api"

describe("triageParams", () => {
  it("defaults invalid views and ranges while preserving supported filters", () => {
    const result = triageParams("?view=sent&days=180&account=work&category=assessment")
    expect(result.get("view")).toBe("queue")
    expect(result.get("days")).toBe("30")
    expect(result.get("account")).toBe("work")
    expect(result.get("category")).toBe("assessment")
  })

  it("preserves the all mail and completed views", () => {
    expect(triageParams("?view=all&days=7").get("view")).toBe("all")
    expect(triageParams("?view=completed&days=90").get("days")).toBe("90")
  })

  it("ignores empty filters", () => {
    const result = triageParams("?view=queue&account=&category=")
    expect(result.has("account")).toBe(false)
    expect(result.has("category")).toBe(false)
  })
})


afterEach(() => {vi.unstubAllGlobals();setWorkspaceIdentity()})
it("shows FastAPI validation fields and messages for invalid form values", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: [
    { loc: ["body", "amount"], msg: "Decimal input should have no more than 2 decimal places" },
    { loc: ["query", "week"], msg: "Input should be a valid date" },
  ] }), { status: 422, headers: { "Content-Type": "application/json" } })))
  await expect(request("/api/payments")).rejects.toThrow("amount: Decimal input should have no more than 2 decimal places; week: Input should be a valid date")
})
it("shows string detail errors without replacing them with a generic failure", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "That record was not found" }), { status: 404, headers: { "Content-Type": "application/json" } })))
  await expect(request("/api/example")).rejects.toThrow("That record was not found")
})

it("sends the selected workspace and rejects an old workspace response", async () => {
  const {setWorkspaceIdentity}=await import("./api")
  let resolve!: (value:Response)=>void
  const fetchMock=vi.fn((_url: string, _init: RequestInit)=>new Promise<Response>(done=>{resolve=done}))
  vi.stubGlobal("fetch",fetchMock)
  setWorkspaceIdentity("alice")
  const pending=request("/api/messages/1")
  expect((fetchMock.mock.calls[0][1].headers as Record<string,string>)["X-OfferPath-Workspace"]).toBe("alice")
  setWorkspaceIdentity("bob")
  resolve(new Response(JSON.stringify({body_html:"Alice private message"}),{status:200,headers:{"Content-Type":"application/json"}}))
  await expect(pending).rejects.toThrow("Workspace changed")
  setWorkspaceIdentity()
})

it("downloads CSV with the workspace header instead of an unauthenticated navigation",async()=>{
  const {downloadFile,setWorkspaceIdentity}=await import("./api")
  const click=vi.spyOn(HTMLAnchorElement.prototype,"click").mockImplementation(()=>{})
  Object.defineProperty(URL,"createObjectURL",{configurable:true,value:vi.fn(()=>"blob:export")})
  Object.defineProperty(URL,"revokeObjectURL",{configurable:true,value:vi.fn()})
  const fetchMock=vi.fn().mockResolvedValue(new Response("Company,Role\nAcme,Engineer",{status:200,headers:{"Content-Type":"text/csv"}}))
  vi.stubGlobal("fetch",fetchMock);setWorkspaceIdentity("alice")
  await downloadFile("/api/sourcing/tabs/1/export?work_date=all","jobs.csv")
  expect(fetchMock.mock.calls[0][1].headers["X-OfferPath-Workspace"]).toBe("alice")
  expect(click).toHaveBeenCalledOnce()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:export")
  setWorkspaceIdentity();click.mockRestore()
})

it("does not rebind live page requests before AuthGate completes a session handoff",async()=>{
  const {api,getWorkspaceIdentity,setWorkspaceIdentity}=await import("./api")
  setWorkspaceIdentity("alice")
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify({role:"admin",workspace_id:"bob"}),{status:200,headers:{"Content-Type":"application/json"}})))
  const session=await api.session()
  expect(session.workspace_id).toBe("bob")
  expect(getWorkspaceIdentity()).toBe("alice")
  setWorkspaceIdentity()
})

it.each([502,503,504,520,522,524])("replaces upstream HTML errors (%s) with a concise connection message",async status=>{
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response('<!DOCTYPE html><html><head><title>Cloudflare Bad gateway</title></head><body>private proxy diagnostics</body></html>',{status,headers:{"Content-Type":"text/html"}})))
 const error=await request("/api/dashboard").catch(error=>error) as ApiError
 expect(error.status).toBe(status)
 expect(error.message).toContain(String(status))
 expect(error.message).not.toMatch(/DOCTYPE|<html|diagnostics/)
 expect(error.message.length).toBeLessThan(180)
})
it("handles a gateway error whose JSON content type does not match its HTML body",async()=>{
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response('<html>Bad gateway</html>',{status:502,headers:{"Content-Type":"application/json"}})))
 await expect(request("/api/dashboard")).rejects.toThrow("OfferPath is temporarily unavailable (502)")
})
it("rejects an HTML login or proxy page returned with a successful status",async()=>{
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response('<html><body>Proxy login</body></html>',{headers:{"Content-Type":"text/html"}})))
 await expect(request("/api/dashboard")).rejects.toThrow("unexpected response")
})
it("provides a readable connection error when fetch fails",async()=>{
 vi.stubGlobal("fetch",vi.fn().mockRejectedValue(new TypeError("Failed to fetch")))
 await expect(request("/api/dashboard")).rejects.toThrow("Could not connect to OfferPath")
})
it("does not retry a failed mutation automatically",async()=>{
 const fetchMock=vi.fn().mockResolvedValue(new Response('<html>Bad gateway</html>',{status:502,headers:{"Content-Type":"text/html"}}));vi.stubGlobal("fetch",fetchMock)
 await expect(request("/api/messages/1/send",{method:"POST",body:"{}"})).rejects.toThrow("temporarily unavailable")
 expect(fetchMock).toHaveBeenCalledTimes(1)
})
it("retains the cancellation signal instead of reporting a server outage",async()=>{
 const controller=new AbortController();controller.abort()
 const error=new DOMException("Cancelled","AbortError")
 vi.stubGlobal("fetch",vi.fn().mockRejectedValue(error))
 await expect(request("/api/dashboard",{signal:controller.signal})).rejects.toBe(error)
})
it("rejects HTML returned to a CSV download without creating a file",async()=>{
 const create=vi.spyOn(URL,"createObjectURL")
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response('<html>Bad gateway</html>',{headers:{"Content-Type":"text/html"}})))
 const {downloadFile}=await import("./api")
 await expect(downloadFile("/api/sourcing/tabs/1/export","jobs.csv")).rejects.toThrow("unexpected response")
 expect(create).not.toHaveBeenCalled();create.mockRestore()
})

it('times out stalled read requests including response body reads',async()=>{
 vi.useFakeTimers()
 try {
  vi.stubGlobal('fetch',vi.fn((_url,init)=>new Promise((_resolve,reject)=>{
   init.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')))
  })))
  const pending=request('/api/dashboard')
  const rejected=expect(pending).rejects.toThrow(/took too long/i)
  await vi.advanceTimersByTimeAsync(30_000)
  await rejected
 } finally {vi.useRealTimers()}
})

it('keeps the read deadline active while parsing a stalled response body',async()=>{
 vi.useFakeTimers()
 try {
  vi.stubGlobal('fetch',vi.fn(async(_url,init)=>({
   ok:true,headers:new Headers({'content-type':'application/json'}),
   json:()=>new Promise((_resolve,reject)=>init.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError'))))
  })))
  const pending=request('/api/interviews')
  const rejected=expect(pending).rejects.toThrow(/took too long/i)
  await vi.advanceTimersByTimeAsync(30_000)
  await rejected
 } finally {vi.useRealTimers()}
})
