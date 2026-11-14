import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { ToastProvider } from "@/components/common"
import * as apiModule from "@/lib/api"
import { api } from "@/lib/api"
import type { Account } from "@/lib/types"
import AccountsPage from "./accounts"

const clients: QueryClient[] = []
let accounts: Account[] = []
const originalRequest=apiModule.request
beforeEach(() => {
  vi.spyOn(apiModule,"request").mockImplementation((url,init)=>url==="/api/realtime/accounts" ? Promise.resolve({configured:false,accounts:[]} as any) : url.startsWith("/api/payments")||url==="/api/auth/bidders/manage" ? Promise.resolve({bidders:[],accounts:[]} as any) : originalRequest(url,init))
  accounts = [{ id: 1, label: "personal", email: "me@example.test", provider: "imap", imap_host: "imap.example.test", imap_port: 993, folder: "INBOX", use_ssl: true, enabled: true }]
  vi.spyOn(api, "accounts").mockImplementation(async () => ({ accounts: structuredClone(accounts), outlook_ready: true }))
})
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); vi.restoreAllMocks(); vi.unstubAllGlobals() })
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  clients.push(client)
  render(<QueryClientProvider client={client}><ToastProvider><AccountsPage /></ToastProvider></QueryClientProvider>)
}
const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } })

it("tests the selected account and prevents a concurrent toggle", async () => {
  let finish!: (value: unknown) => void
  const post = vi.spyOn(api, "post").mockImplementation(() => new Promise((resolve) => { finish = resolve as typeof finish }))
  mount(); fireEvent.click(await screen.findByRole("button", { name: "Test" }))
  expect(post).toHaveBeenCalledWith("/api/accounts/personal/test")
  expect((screen.getByRole("switch", { name: "Include personal in checks" }) as HTMLButtonElement).disabled).toBe(true)
  await act(async () => finish({ message: "Connection OK." }))
  await screen.findByText("Connection OK.")
  expect((screen.getByRole("switch", { name: "Include personal in checks" }) as HTMLButtonElement).disabled).toBe(false)
})
it("updates inclusion state through the existing account toggle API", async () => {
  const post = vi.spyOn(api, "post").mockImplementation(async () => { accounts[0].enabled = false; return { message: "Paused personal." } as any })
  mount(); fireEvent.click(await screen.findByRole("switch", { name: "Include personal in checks" }))
  await screen.findByText("Paused", { exact: true })
  expect(post).toHaveBeenCalledWith("/api/accounts/personal/toggle?enabled=false")
  expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("false")
})
it("respects removal confirmation and refreshes the account list", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
  const post = vi.spyOn(api, "post").mockImplementation(async () => { accounts = []; return { message: "Removed personal." } as any })
  mount(); fireEvent.click(await screen.findByTitle("Remove personal"))
  expect(post).not.toHaveBeenCalled()
  confirm.mockReturnValue(true)
  fireEvent.click(screen.getByTitle("Remove personal"))
  await screen.findByText("One inbox at a time")
  expect(post).toHaveBeenCalledWith("/api/accounts/personal/delete")
})
it("ignores stale provider lookups after the address changes", async () => {
  let first!: (value: Response) => void
  const fetch = vi.fn((url: string) => url.includes("gmail") ? new Promise<Response>((resolve) => { first = resolve }) : Promise.resolve(json({ preset: { host: "imap.mail.yahoo.com", port: 993, note: "Yahoo" } })))
  vi.stubGlobal("fetch", fetch)
  mount(); fireEvent.click(await screen.findByRole("button", { name: "Connect mailbox" }))
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "me@gmail.com" } })
  await waitFor(() => expect(fetch).toHaveBeenCalledOnce())
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "me@yahoo.com" } })
  await waitFor(() => expect((screen.getByLabelText("IMAP host") as HTMLInputElement).value).toBe("imap.mail.yahoo.com"))
  await act(async () => first(json({ preset: { host: "imap.gmail.com", port: 993, note: "Gmail" } })))
  expect((screen.getByLabelText("IMAP host") as HTMLInputElement).value).toBe("imap.mail.yahoo.com")
})
it("does not overwrite a manually edited server with a delayed preset", async () => {
  let finish!: (value: Response) => void
  const fetch = vi.fn(() => new Promise<Response>((resolve) => { finish = resolve }))
  vi.stubGlobal("fetch", fetch)
  mount(); fireEvent.click(await screen.findByRole("button", { name: "Connect mailbox" }))
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "me@gmail.com" } })
  await waitFor(() => expect(fetch).toHaveBeenCalledOnce())
  fireEvent.change(screen.getByLabelText("IMAP host"), { target: { value: "custom.example.test" } })
  await act(async () => finish(json({ preset: { host: "imap.gmail.com", port: 993, note: "Gmail" } })))
  expect((screen.getByLabelText("IMAP host") as HTMLInputElement).value).toBe("custom.example.test")
})

it("reconnects Outlook in place to grant read-only calendar access",async()=>{
  accounts[0].provider="outlook"
  const post=vi.spyOn(api,"post").mockResolvedValue({user_code:"TEST",verification_uri:"https://microsoft.com/devicelogin"})
  vi.stubGlobal("fetch",vi.fn().mockResolvedValue(json({state:"waiting",message:""})))
  mount();fireEvent.click(await screen.findByRole("button",{name:"Reconnect"}))
  const label=screen.getByLabelText("Account label") as HTMLInputElement
  expect(label.value).toBe("personal");expect(label.readOnly).toBe(true)
  expect(screen.getByText(/Calendars.Read/)).toBeTruthy()
  fireEvent.click(screen.getByRole("button",{name:"Continue with Microsoft"}))
  await waitFor(()=>expect(post).toHaveBeenCalledWith("/api/outlook/start",{label:"personal",reconnect:true}))
  expect(await screen.findByText("TEST")).toBeTruthy()
})

it("shows bidder and account assignment management on Accounts", async () => {
  mount()
  expect(await screen.findByText("Manage bidders and account assignments")).toBeTruthy()
})

it("reconnects an IMAP account in place with a new app password",async()=>{
 const post=vi.spyOn(api,"post").mockResolvedValue({message:"Mailbox reconnected."})
 mount();fireEvent.click(await screen.findByRole("button",{name:"Reconnect"}))
 expect(screen.getByRole("heading",{name:"Reconnect mailbox"})).toBeTruthy()
 expect(screen.getAllByText(/me@example.test/).length).toBeGreaterThan(0)
 fireEvent.change(screen.getByLabelText("New app password"),{target:{value:"abcd efgh ijkl mnop"}})
 fireEvent.click(screen.getByRole("button",{name:"Test & reconnect"}))
 await waitFor(()=>expect(post).toHaveBeenCalledWith("/api/accounts/personal/reconnect",{password:"abcd efgh ijkl mnop"}))
 await waitFor(()=>expect(screen.queryByRole("dialog")).toBeNull())
})
it("keeps the reconnect dialog open on failure and clears secrets on cancel",async()=>{
 vi.spyOn(api,"post").mockRejectedValue(new Error("Authentication failed."))
 mount();fireEvent.click(await screen.findByRole("button",{name:"Reconnect"}))
 fireEvent.change(screen.getByLabelText("New app password"),{target:{value:"wrong"}})
 fireEvent.click(screen.getByRole("button",{name:"Test & reconnect"}))
 expect(await screen.findByRole("alert")).toHaveProperty("textContent","Authentication failed.")
 fireEvent.click(screen.getByRole("button",{name:"Cancel"}))
 fireEvent.click(screen.getByRole("button",{name:"Reconnect"}))
 expect((screen.getByLabelText("New app password") as HTMLInputElement).value).toBe("")
})

it("shows Gmail app-password guidance and prevents duplicate reconnect submissions",async()=>{
 accounts[0].email="me@gmail.com";accounts[0].imap_host="imap.gmail.com"
 let finish!:(value:unknown)=>void
 const post=vi.spyOn(api,"post").mockImplementation(()=>new Promise(resolve=>{finish=resolve as typeof finish}))
 mount();fireEvent.click(await screen.findByRole("button",{name:"Reconnect"}))
 expect(screen.getByRole("link",{name:"Create a Google app password"}).getAttribute("href")).toBe("https://myaccount.google.com/apppasswords")
 fireEvent.change(screen.getByLabelText("New app password"),{target:{value:"new-password"}})
 fireEvent.click(screen.getByRole("button",{name:"Test & reconnect"}))
 expect((screen.getByRole("button",{name:"Reconnecting…"}) as HTMLButtonElement).disabled).toBe(true)
 expect((screen.getByRole("button",{name:"Cancel"}) as HTMLButtonElement).disabled).toBe(true)
 expect(post).toHaveBeenCalledTimes(1)
 await act(async()=>finish({message:"Reconnected."}))
})

it("shows each account's last successful mail check",async()=>{
 accounts[0].last_checked_at="2026-11-01T12:34:56Z"
 mount()
 expect(await screen.findByText(/Last mail check:/)).toBeTruthy()
 expect(screen.getByText(/Last mail check:/).textContent).toContain(new Date(accounts[0].last_checked_at).toLocaleString())
})

it('orders provider, bidder management, and visibility panels beneath connected accounts',async()=>{
 mount();await screen.findByText('Manage bidders and account assignments')
 const provider=document.getElementById('provider-options')!
 const management=document.getElementById('bidder-management')!
 const visibility=document.getElementById('bidder-visibility')!
 expect(provider.compareDocumentPosition(management)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
 expect(management.compareDocumentPosition(visibility)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
 expect(screen.getByRole('navigation',{name:'Account sections'})).toBeTruthy()
})

it("clears the previous provider server when a new address has no preset", async () => {
  vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(json({ preset: url.includes("gmail") ? { host: "imap.gmail.com", port: 993, note: "Gmail" } : null }))))
  mount(); fireEvent.click(await screen.findByRole("button", { name: "Connect mailbox" }))
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "me@gmail.com" } })
  await waitFor(() => expect((screen.getByLabelText("IMAP host") as HTMLInputElement).value).toBe("imap.gmail.com"))
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "me@custom.example" } })
  await screen.findByText("Add your provider’s IMAP hostname below.")
  expect((screen.getByLabelText("IMAP host") as HTMLInputElement).value).toBe("")
})

it("preserves a manual server when the provider lookup has no preset", async () => {
  let finish!: (value: Response) => void
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
  mount(); fireEvent.click(await screen.findByRole("button", { name: "Connect mailbox" }))
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "me@custom.example" } })
  await waitFor(() => expect(finish).toBeTypeOf("function"))
  fireEvent.change(screen.getByLabelText("IMAP host"), { target: { value: "imap.custom.example" } })
  fireEvent.change(screen.getByLabelText("Port"), { target: { value: "1993" } })
  await act(async () => finish(json({ preset: null })))
  expect((screen.getByLabelText("IMAP host") as HTMLInputElement).value).toBe("imap.custom.example")
  expect((screen.getByLabelText("Port") as HTMLInputElement).value).toBe("1993")
})

it.each(["me@custom.example", "me"])("clears the previous provider server immediately when the address changes to %s", async email => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ preset: { host: "imap.gmail.com", port: 1993, note: "Gmail" } })))
  mount(); fireEvent.click(await screen.findByRole("button", { name: "Connect mailbox" }))
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "me@gmail.com" } })
  await waitFor(() => expect((screen.getByLabelText("IMAP host") as HTMLInputElement).value).toBe("imap.gmail.com"))
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: email } })
  expect((screen.getByLabelText("IMAP host") as HTMLInputElement).value).toBe("")
  expect((screen.getByLabelText("Port") as HTMLInputElement).value).toBe("993")
})
