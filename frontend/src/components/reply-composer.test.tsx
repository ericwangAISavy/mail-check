import {afterEach, expect, it, vi} from "vitest"
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react"
import {QueryClient, QueryClientProvider} from "@tanstack/react-query"
import {ToastProvider} from "@/components/common"
import {api, request} from "@/lib/api"
import ReplyComposer from "./reply-composer"
vi.mock("@/lib/api",() => ({api:{post:vi.fn(),reader:vi.fn()},ApiError:class ApiError extends Error{},request:vi.fn()}))
vi.mock("./outlook-dialog",()=>({default:()=>null}))
const clients: QueryClient[]=[]
afterEach(()=>{cleanup();clients.forEach(c=>c.clear());clients.length=0;localStorage.clear();vi.resetAllMocks()})
const context={from:"me@outlook.com",to:["recruiter@example.test"],cc:[],subject:"Re: Interview"}
function mount(pk=1){const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client);return render(<QueryClientProvider client={client}><ToastProvider><ReplyComposer pk={pk} accountLabel="Personal" mode="reply" onModeChange={()=>{}} replies={[]}/></ToastProvider></QueryClientProvider>)}
it("previews the original inbox and recipient, sends only explicitly, and clears its draft",async()=>{
 vi.mocked(request).mockResolvedValue(context);vi.mocked(api.post).mockResolvedValue({ok:true,done:false})
 mount();await screen.findByDisplayValue("recruiter@example.test")
 expect(screen.getByDisplayValue("me@outlook.com")).toBeTruthy()
 expect(api.post).not.toHaveBeenCalled()
 fireEvent.change(screen.getByRole("textbox",{name:"Your reply"}),{target:{value:"Monday works."}})
 fireEvent.click(screen.getByRole("button",{name:"Send"}))
 await waitFor(()=>expect(api.post).toHaveBeenCalledWith("/api/messages/1/reply",expect.objectContaining({body:"Monday works.",mode:"reply",mark_done:false,operation:expect.any(String)})))
 await waitFor(()=>expect((screen.getByRole("textbox",{name:"Your reply"}) as HTMLTextAreaElement).value).toBe(""))
 expect(localStorage.getItem("mailcheck:reply:Personal:1")).toBeNull()
})
it("keeps drafts separate per message and preserves text after a send failure",async()=>{
 vi.mocked(request).mockResolvedValue(context);vi.mocked(api.post).mockRejectedValue(new Error("Microsoft unavailable"))
 const first=mount();await screen.findByDisplayValue("recruiter@example.test")
 fireEvent.change(screen.getByRole("textbox",{name:"Your reply"}),{target:{value:"Keep my draft"}})
 fireEvent.click(screen.getByRole("button",{name:"Send & Done"}))
 expect(await screen.findByText("Microsoft unavailable")).toBeTruthy()
 expect((screen.getByRole("textbox",{name:"Your reply"}) as HTMLTextAreaElement).value).toBe("Keep my draft")
 first.unmount();const second=mount(2);await screen.findByDisplayValue("recruiter@example.test")
 expect((screen.getByRole("textbox",{name:"Your reply"}) as HTMLTextAreaElement).value).toBe("")
 second.unmount();mount(1);await screen.findByDisplayValue("recruiter@example.test")
 expect((screen.getByRole("textbox",{name:"Your reply"}) as HTMLTextAreaElement).value).toBe("Keep my draft")
})


it("locks a lost send response and reconciles the original operation instead of duplicating",async()=>{
 vi.mocked(request).mockResolvedValue(context);vi.mocked(api.post).mockRejectedValue(new TypeError("Failed to fetch"))
 mount();await screen.findByDisplayValue("recruiter@example.test")
 fireEvent.change(screen.getByRole("textbox",{name:"Your reply"}),{target:{value:"One reply only"}})
 fireEvent.click(screen.getByRole("button",{name:"Send & Done"}))
 await screen.findByText("Failed to fetch")
 expect((screen.getByRole("textbox",{name:"Your reply"}) as HTMLTextAreaElement).disabled).toBe(true)
 expect((screen.getByRole("button",{name:"Send"}) as HTMLButtonElement).disabled).toBe(true)
 const original=vi.mocked(api.post).mock.calls[0][1] as {operation:string}
 vi.mocked(api.reader).mockResolvedValue({message:{} as any,body_html:"",replies:[{operation:original.operation,body:"One reply only",mode:"reply",status:"sent",created_at:"2026-10-22T20:00:00Z",sent_at:"2026-10-22T20:00:00Z",recipients:"{}",error:""}]})
 fireEvent.click(screen.getByRole("button",{name:"Check send status"}))
 await waitFor(()=>expect((screen.getByRole("textbox",{name:"Your reply"}) as HTMLTextAreaElement).value).toBe(""))
 expect(api.post).toHaveBeenCalledTimes(1)
})


it("safe retries preserve the original request and unlock after confirmed acceptance",async()=>{
 localStorage.setItem("mailcheck:reply:Personal:1",JSON.stringify({body:"Previous reply-all draft",mode:"reply_all",operation:"88f217ea-8a48-4f35-9f3d-cce368533630"}))
 vi.mocked(request).mockResolvedValue(context)
 vi.mocked(api.post).mockRejectedValueOnce(new TypeError("Failed to fetch")).mockResolvedValueOnce({ok:true,done:true})
 mount();await screen.findByDisplayValue("recruiter@example.test")
 fireEvent.change(screen.getByRole("textbox",{name:"Your reply"}),{target:{value:"Send once"}})
 fireEvent.click(screen.getByRole("button",{name:"Send & Done"}))
 await screen.findByText("Failed to fetch")
 const original=vi.mocked(api.post).mock.calls[0][1]
 fireEvent.click(screen.getByRole("button",{name:"Retry original send safely"}))
 await waitFor(()=>expect(api.post).toHaveBeenCalledTimes(2))
 expect(vi.mocked(api.post).mock.calls[1][1]).toEqual(original)
 await waitFor(()=>expect((screen.getByRole("textbox",{name:"Your reply"}) as HTMLTextAreaElement).disabled).toBe(false))
})
