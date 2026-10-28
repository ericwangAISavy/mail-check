import { afterEach, describe, expect, it, vi } from "vitest"
import { request, triageParams, setWorkspaceIdentity } from "./api"

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
