import { StrictMode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { BrowserRouter, MemoryRouter, useLocation } from "react-router-dom"
import App from "./App"
import { AppErrorBoundary } from "@/components/app-error-boundary"
import { api, ApiError } from "@/lib/api"

type Status = Awaited<ReturnType<typeof api.status>>
const idle: Status = { running: false, auto: false, next_in: null, completion_id: 1, message: "", detail: "", ok: true, stage_elapsed: null }
const scheduled: Status = { ...idle, auto: true, next_in: 120 }
const updated: Status = { ...scheduled, updated_at: new Date().toISOString() }
const running: Status = { ...scheduled, running: true, message: "Reading mail…" }
const clients: QueryClient[] = []

beforeEach(() => {
  vi.spyOn(api, "applicationsToday").mockResolvedValue({applications_today:0})
  vi.spyOn(api, "session").mockResolvedValue({ role: "admin" })
  vi.spyOn(console, "error").mockImplementation(() => undefined)
  vi.stubGlobal("localStorage", { getItem: vi.fn(() => null), setItem: vi.fn() })
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
  vi.spyOn(api, "bootstrap").mockResolvedValue({
    readiness: { model: true, accounts: true, privacy_ack: true, outlook: false },
    counts: { actionable: 0 }, taxonomy: [], presets: [], last_run: "Never checked", account_count: 1,
  })
  vi.spyOn(api, "triage").mockResolvedValue({
    view: "queue", groups: [], total: 0, summary: {}, counts: {}, accounts: [],
    days: 30, selected_account: null, selected_category: null,
  })
})

afterEach(() => {
  cleanup()
  clients.splice(0).forEach((client) => client.clear())
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

// Browser translators replace React-owned text nodes with their own elements.
// Reproduce that DOM transformation without requiring an installed extension.
function replaceTextNodes(root: Element) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const nodes: Node[] = []
  while (walker.nextNode()) nodes.push(walker.currentNode)
  for (const node of nodes) {
    const wrapper = document.createElement("font")
    wrapper.textContent = node.textContent
    node.parentNode!.replaceChild(wrapper, node)
  }
}

it('contains keyboard focus in mobile navigation and restores it on Escape',async()=>{
  vi.spyOn(api,'status').mockResolvedValue(idle)
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
  render(<QueryClientProvider client={client}><MemoryRouter><App/></MemoryRouter></QueryClientProvider>)
  const trigger=await screen.findByRole('button',{name:'Open navigation'})
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
  trigger.focus();fireEvent.click(trigger)
  expect(trigger.getAttribute('aria-expanded')).toBe('true')
  const drawer=document.getElementById(trigger.getAttribute('aria-controls')!)!
  await waitFor(()=>expect(drawer.contains(document.activeElement)).toBe(true))
  const controls=Array.from(drawer.querySelectorAll<HTMLElement>('a[href],button:not(:disabled)'))
  controls.at(-1)!.focus();fireEvent.keyDown(document.activeElement!,{key:'Tab'})
  expect(document.activeElement).toBe(controls[0])
  fireEvent.keyDown(document.activeElement!,{key:'Tab',shiftKey:true})
  expect(document.activeElement).toBe(controls.at(-1))
  fireEvent.keyDown(document.activeElement!,{key:'Escape'})
  await waitFor(()=>expect(trigger.getAttribute('aria-expanded')).toBe('false'))
  expect(document.activeElement).toBe(trigger)
})

it.each([
  ["owner", {role:"admin",is_owner:true}, ["Workspace","Interviews","Jobs","Management","Administration"], ["/","/dashboard","/interviews","/interview-processes","/sourcing","/job-links","/payments","/accounts","/settings","/admin-management"]],
  ["admin", {role:"admin",is_owner:false}, ["Workspace","Interviews","Jobs","Management","Administration"], ["/","/dashboard","/interviews","/interview-processes","/sourcing","/payments","/accounts","/settings"]],
  ["bidder", {role:"bidder",bidder_id:1}, ["Workspace","Jobs","Management","Administration"], ["/inbox","/dashboard","/sourcing","/payments","/settings"]],
] as const)("groups only the destinations visible to the %s", async(_,identity,groups,links)=>{
  vi.mocked(api.session).mockResolvedValue({...identity,managed:true,workspace_id:"legacy"})
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/settings"]}><App/></MemoryRouter></QueryClientProvider>)
  const nav=await screen.findByRole("navigation",{name:"Main navigation"})
  expect(Array.from(nav.querySelectorAll("[role=group]"),group=>document.getElementById(group.getAttribute("aria-labelledby")!)?.textContent)).toEqual(groups)
  expect(Array.from(nav.querySelectorAll("a"),link=>link.getAttribute("href"))).toEqual(links)
  expect(nav.querySelector("[aria-current=page]")?.textContent).toBe("Settings")
  expect(screen.getByRole("button",{name:/view update history/}).closest(".sidebar-footer")).toBeTruthy()
})

it("aborts the header status poll when the workspace unmounts", async () => {
  let signal: AbortSignal | undefined
  vi.spyOn(api, "status").mockImplementation((nextSignal) => new Promise((_resolve, reject) => {
    signal = nextSignal
    signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")))
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  const { unmount } = render(<QueryClientProvider client={client}><MemoryRouter><App /></MemoryRouter></QueryClientProvider>)
  await waitFor(() => expect(api.status).toHaveBeenCalled())
  unmount()
  expect(signal?.aborted).toBe(true)
})

describe("header status after external text replacement", () => {
  it("refreshes page data after a manual check that completes immediately", async () => {
    let current = idle
    vi.spyOn(api, "status").mockImplementation(async () => current)
    vi.spyOn(api, "post").mockImplementation(async () => {
      current = { ...idle, completion_id: 2, message: "Check complete." }
      return { ok: true } as any
    })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    clients.push(client)
    render(<QueryClientProvider client={client}><MemoryRouter><App /></MemoryRouter></QueryClientProvider>)
    await screen.findByText("Your queue is clear")
    await waitFor(() => expect(api.status).toHaveBeenCalled())
    const previous = vi.mocked(api.bootstrap).mock.calls.length
    fireEvent.click(screen.getByRole("button", { name: "Check now" }))
    await waitFor(() => expect(vi.mocked(api.bootstrap).mock.calls.length).toBeGreaterThan(previous))
    expect(api.post).toHaveBeenCalledWith("/api/check", { mode: "mail" })
  })
  it.each(["/interviews", "/interview-processes"])("uses calendar collection on %s without a model", async (path) => {
    vi.spyOn(api, "status").mockResolvedValue(idle)
    vi.spyOn(api, "post").mockResolvedValue({ ok: true })
    vi.mocked(api.bootstrap).mockResolvedValue({ readiness: { model: false, accounts: true, privacy_ack: true, outlook: true }, counts: { actionable: 0 }, taxonomy: [], presets: [], last_run: "Never checked", account_count: 1 })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    clients.push(client)
    const { container } = render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>)
    await waitFor(() => expect(container.querySelector(".top-actions button:last-child")).toBeTruthy())
    const button = container.querySelector<HTMLButtonElement>(".top-actions button:last-child")!
    expect(button.disabled).toBe(false)
    fireEvent.click(button)
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/check", { mode: "calendar" }))
  })
  it.each([
    ["idle to updated", idle, updated, "Updated", "just now"],
    ["updated to running", updated, running, "Reading mail…", null],
    ["running to completed", running, { ...updated, completion_id: 2 }, "Updated", "just now"],
    ["updated to idle", updated, idle, "All systems ready", null],
    ["progress message", running, { ...running, message: "Classifying mail…" }, "Classifying mail…", null],
  ] as const)("survives %s and displays the latest status", async (_name, initial, next, label, freshness) => {
    let current: Status = initial
    vi.spyOn(api, "status").mockImplementation(async () => current)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    clients.push(client)
    const { container } = render(<StrictMode><AppErrorBoundary><QueryClientProvider client={client}>
      <MemoryRouter><App /></MemoryRouter>
    </QueryClientProvider></AppErrorBoundary></StrictMode>)
    await screen.findByText("Your queue is clear")
    const status = container.querySelector(".connection-status")!
    await waitFor(() => expect(status.textContent).toContain(initial.running ? initial.message : initial.updated_at ? "Updated" : "All systems ready"))
    replaceTextNodes(status)

    current = next
    await act(async () => { fireEvent.focus(window) })

    expect(screen.queryByRole("alert")?.querySelector("pre")?.textContent || "").toBe("")
    expect(container.querySelector(".connection-status")?.textContent).toContain(label)
    expect(container.querySelector(".connection-status .status-updated")?.textContent ?? null).toBe(freshness)
    expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeTruthy()
    expect(console.error).not.toHaveBeenCalled()
  })
})

describe("mail freshness", () => {
  // Fake only the interval and the clock: react-query, waitFor and the status
  // poll all rely on real setTimeout.
  beforeEach(() => { vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] }) })
  afterEach(() => { vi.useRealTimers() })

  const mount = () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    clients.push(client)
    return render(<QueryClientProvider client={client}><MemoryRouter><App /></MemoryRouter></QueryClientProvider>)
  }
  const freshness = (container: HTMLElement) => container.querySelector(".connection-status .status-updated")?.textContent ?? null

  it("shows how long ago mail was updated, ticking without asking the server again", async () => {
    const status = vi.spyOn(api, "status").mockResolvedValue({ ...scheduled, updated_at: new Date(Date.now() - 20_000).toISOString() })
    const { container } = mount()
    await waitFor(() => expect(freshness(container)).toBe("20 seconds ago"))
    const calls = status.mock.calls.length

    await act(async () => { vi.advanceTimersByTime(60_000) })

    expect(freshness(container)).toBe("1 min ago")
    expect(status.mock.calls.length).toBe(calls)
    expect(container.querySelector(".connection-status")?.textContent).not.toMatch(/Next check|\d:\d\d/)
  })

  it("polls right away when a scheduled check is due and switches to the running message", async () => {
    let current: Status = { ...scheduled, next_in: 0, updated_at: new Date().toISOString() }
    const status = vi.spyOn(api, "status").mockImplementation(async () => current)
    const { container } = mount()
    await waitFor(() => expect(freshness(container)).toBe("just now"))
    const calls = status.mock.calls.length

    current = { ...running, message: "Reading mail…" }
    await waitFor(() => expect(container.querySelector(".connection-status")?.textContent).toContain("Reading mail…"))
    expect(status.mock.calls.length).toBeGreaterThan(calls)
  })

  it("keeps the ticking time out of the live region and shows the exact time on hover", async () => {
    const stamp = new Date(Date.now() - 5 * 60_000).toISOString()
    vi.spyOn(api, "status").mockResolvedValue({ ...scheduled, updated_at: stamp })
    const { container } = mount()
    await waitFor(() => expect(freshness(container)).toBe("5 min ago"))
    const time = container.querySelector(".connection-status .status-updated")!
    expect(time.closest("[aria-live=polite]")).toBeNull()
    expect(time.getAttribute("title")).toBe(new Date(stamp).toLocaleString())
  })

  it("keeps the automatic-check toggle out of the header", async () => {
    vi.spyOn(api, "status").mockResolvedValue({ ...scheduled, interval_minutes: 10, updated_at: new Date().toISOString() })
    const { container } = mount()
    await waitFor(() => expect(freshness(container)).toBe("just now"))
    expect(screen.queryByRole("button", { name: /Auto-check/ })).toBeNull()
    expect(container.querySelector(".schedule-button")).toBeNull()
  })
})

it.each(["/", "/dashboard", "/accounts", "/sourcing", "/payments", "/interviews"])("shows today's received confirmations on %s", async (path) => {
  vi.mocked(api.bootstrap).mockResolvedValue({readiness:{model:true,accounts:true,privacy_ack:true,outlook:false},counts:{actionable:0,applications_today:3400},taxonomy:[],presets:[],last_run:"",account_count:2})
  vi.spyOn(api,"status").mockResolvedValue(idle)
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>)
  const badge=await screen.findByLabelText("3400 checked applications today")
  expect(badge.closest("a")).toBeNull()
  expect(badge.closest("header")).toBeTruthy()
  expect(badge.closest(".crumb")).toBeNull()
  expect(badge.textContent).toBe("3,400today")
  expect(screen.getByRole("button", {name:"OfferPath home"})).toBeTruthy()
  expect(document.title).toBe("OfferPath")
})

it("allows the owner to open Settings when bootstrap fails",async()=>{
 vi.mocked(api.session).mockResolvedValue({role:"admin",is_owner:true,workspace_id:"legacy"})
 vi.mocked(api.bootstrap).mockRejectedValue(new Error("Workspace data is unavailable"))
 vi.spyOn(api,"status").mockResolvedValue(idle)
 vi.spyOn(api,"settings").mockResolvedValue({settings:{llm:{base_url:"http://localhost:11434",batch_size:5,max_body_chars:1200,timeout_seconds:60,classification_deadline_seconds:300,concurrency:1,num_ctx:8192,think:false,keep_alive:"5m"},check:{lookback_days:7,retain_days:30},watch:{interval_minutes:10,auto_check:false},outlook:{client_id:""},privacy_ack:true},rules:[],categories:[],config_path:"config.toml",db_path:"mail.db"})
 vi.spyOn(api,"activeModel").mockResolvedValue({model:"test-model",loaded:true,message:"Ready"})
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
 render(<QueryClientProvider client={client}><MemoryRouter><App/></MemoryRouter></QueryClientProvider>)
 fireEvent.click(await screen.findByRole("button",{name:"Try settings"}))
 await screen.findByRole("heading",{name:"Settings"})
 expect(screen.queryByText("Check your local settings")).toBeNull()
 expect(api.settings).toHaveBeenCalled()
 const input=screen.getByLabelText("Ollama server URL",{exact:false})
 fireEvent.change(input,{target:{value:"http://unsaved-server:11434"}})
 await act(async()=>{await client.refetchQueries({queryKey:["bootstrap"]})})
 expect(screen.getByLabelText("Ollama server URL",{exact:false})).toBe(input)
 expect(input).toHaveProperty("value","http://unsaved-server:11434")
})

it("keeps owner Settings available when background bootstrap fails",async()=>{
 vi.mocked(api.session).mockResolvedValue({role:"admin",is_owner:true,workspace_id:"legacy"})
 vi.mocked(api.bootstrap).mockRejectedValue(new Error("Overview unavailable"))
 vi.spyOn(api,"status").mockResolvedValue(idle)
 vi.spyOn(api,"settings").mockRejectedValue(new Error("Settings service reached"))
 vi.spyOn(api,"activeModel").mockResolvedValue({model:null,loaded:false,message:"Not loaded"})
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
 render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/settings"]}><App/></MemoryRouter></QueryClientProvider>)
 await screen.findByText("Settings service reached")
 expect(api.bootstrap).toHaveBeenCalled()
})

it('does not overlap status polls when focus events arrive during a slow response',async()=>{
 let finish!:(value:Status)=>void
 const status=vi.spyOn(api,'status').mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
 render(<QueryClientProvider client={client}><MemoryRouter><App/></MemoryRouter></QueryClientProvider>)
 await screen.findByText('Your queue is clear')
 const calls=status.mock.calls.length
 fireEvent.focus(window);fireEvent.focus(window)
 expect(status.mock.calls.length).toBe(calls)
 await act(async()=>finish(idle))
})

it.each(["/admin-management","/settings"])("keeps the daily badge available on %s when workspace setup is unavailable",async(path)=>{
 vi.mocked(api.session).mockResolvedValue({role:"admin",is_owner:true,workspace_id:"legacy"})
 vi.mocked(api.bootstrap).mockRejectedValue(new Error("Invalid settings"))
 vi.mocked(api.applicationsToday).mockResolvedValue({applications_today:446})
 vi.spyOn(api,"status").mockResolvedValue(idle)
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
 render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App/></MemoryRouter></QueryClientProvider>)
 expect((await screen.findByLabelText("446 checked applications today")).closest("header")).toBeTruthy()
 expect(api.applicationsToday).toHaveBeenCalled()
})

it.each(["/payments", "/payments/"])("hides header counts from bidders on %s", async (path) => {
 vi.mocked(api.session).mockResolvedValue({role:"bidder",managed:true,workspace_id:"legacy",bidder_id:1})
 vi.mocked(api.bootstrap).mockResolvedValue({readiness:{model:true,accounts:true,privacy_ack:true,outlook:false},counts:{actionable:0,applications_today:171},taxonomy:[],presets:[],last_run:"",account_count:1})
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
 render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>)
 await screen.findByRole("button",{name:"Sign out"})
 expect(document.querySelector(".header-application-count")).toBeNull()
 expect(screen.queryByLabelText("171 checked applications today")).toBeNull()
})

it('gives bidders the restricted inbox navigation without admin triage or account controls',async()=>{
 vi.mocked(api.session).mockResolvedValue({role:'bidder',managed:true,workspace_id:'legacy',bidder_id:1})
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
 render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/inbox']}><App/></MemoryRouter></QueryClientProvider>)
 expect(await screen.findByRole('link',{name:'Inbox'})).toBeTruthy()
 expect(screen.queryByRole('link',{name:'Triage'})).toBeNull()
 expect(screen.queryByRole('link',{name:'Accounts'})).toBeNull()
 expect(await screen.findByText('All mail for your assigned accounts.')).toBeTruthy()
})

it("gives bidders a Settings page for appearance and personal mail alerts", async () => {
 vi.mocked(api.session).mockResolvedValue({role:"bidder",managed:true,workspace_id:"legacy",bidder_id:1})
 const settings=vi.spyOn(api,"settings")
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
 render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/inbox"]}><App/></MemoryRouter></QueryClientProvider>)
 fireEvent.click(await screen.findByRole("link",{name:"Settings"}))
 expect(await screen.findByRole("heading",{name:"Appearance"})).toBeTruthy()
 expect(screen.getByRole("switch",{name:"Desktop notifications"})).toBeTruthy()
 expect(screen.getByRole("switch",{name:"Play a sound"})).toBeTruthy()
 expect(screen.queryByRole("heading",{name:"Sign-in passwords"})).toBeNull()
 expect(settings).not.toHaveBeenCalled()
})

it("alerts for new assigned mail once and keeps listening outside Settings", async () => {
 vi.mocked(api.session).mockResolvedValue({role:"bidder",managed:true,workspace_id:"legacy",bidder_id:12})
 const stored=new Map<string,string>()
 vi.mocked(localStorage.getItem).mockImplementation(key=>stored.get(key)??null)
 vi.mocked(localStorage.setItem).mockImplementation((key,value)=>{stored.set(key,value)})
 const notify=vi.fn()
 vi.stubGlobal("Notification",class {
  static permission="default"
  static async requestPermission(){this.permission="granted";return this.permission}
  constructor(title:string,options:NotificationOptions){notify(title,options)}
 })
 const start={after:"2026-11-27T12:00:00+00:00",after_id:0}
 const later={after:"2026-11-27T12:00:10+00:00",after_id:44}
 let incoming=false
 const read=vi.spyOn(globalThis,"fetch").mockImplementation(async url=>{
  const path=String(url)
  const data=path.startsWith("/api/inbox/alerts")
   ? path.includes("?")&&incoming&&!path.includes("after_id=44") ? {cursor:later,message:44} : {cursor:path.includes("after_id=44")?later:start,message:null}
   : {configured:false}
  return new Response(JSON.stringify(data),{headers:{"Content-Type":"application/json"}})
 })
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
 render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/settings"]}><App/></MemoryRouter></QueryClientProvider>)
 expect(read.mock.calls.some(([url])=>String(url).startsWith("/api/inbox/alerts"))).toBe(false)
 fireEvent.click(await screen.findByRole("switch",{name:"Desktop notifications"}))
 await waitFor(()=>expect(client.getQueryData(["bidder-inbox-alerts",'["legacy",12]'])).toEqual({cursor:start,message:null}))
 expect(notify).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole("link",{name:"Inbox"}))
 await screen.findByRole("heading",{name:"Inbox"})
 incoming=true
 await act(()=>client.invalidateQueries({queryKey:["bidder-inbox-alerts"]}))
 await waitFor(()=>expect(notify).toHaveBeenCalledTimes(1))
 expect(notify).toHaveBeenCalledWith("New email in OfferPath",expect.objectContaining({tag:'offerpath-mail:["legacy",12]:44',silent:true}))
 await act(()=>client.invalidateQueries({queryKey:["bidder-inbox-alerts"]}))
 expect(notify).toHaveBeenCalledTimes(1)
 expect(read.mock.calls.some(([url])=>String(url).includes("after_id=44"))).toBe(true)
})

function CurrentAddress() {
 const l=useLocation();return <output data-testid="address">{l.pathname+l.search+l.hash}</output>
}
describe("same-page workspace navigation",()=>{
 const mount=(entry:string,role:"admin"|"bidder"="admin")=>{
  vi.spyOn(api,"status").mockResolvedValue(idle)
  vi.mocked(api.session).mockResolvedValue({role,is_owner:role==="admin",managed:true,workspace_id:"test"})
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[entry]}><App/><CurrentAddress/></MemoryRouter></QueryClientProvider>)
 }
 it.each([["/","Triage"],["/dashboard","Dashboard"],["/interviews","Interview"],["/interview-processes","Interview pipeline"],["/sourcing","Job sourcing"],["/payments","Bidder management"],["/accounts","Accounts"],["/settings","Settings"],["/admin-management","Admin management"]])("preserves filters and hash on %s",async(path,label)=>{
  const address=path+"?q=keep&account=2#results";mount(address)
  fireEvent.click(await screen.findByRole("link",{name:label}))
  expect(screen.getByTestId("address").textContent).toBe(address)
 })
 it("preserves home filters",async()=>{
  mount("/?q=keep#results");fireEvent.click(await screen.findByRole("button",{name:"OfferPath home"}))
  expect(screen.getByTestId("address").textContent).toBe("/?q=keep#results")
 })
 it("navigates to other pages without copying filters",async()=>{
  mount("/?q=keep#results");fireEvent.click(await screen.findByRole("link",{name:"Accounts"}))
  expect(screen.getByTestId("address").textContent).toBe("/accounts")
 })
 it.each([{ctrlKey:true},{metaKey:true},{shiftKey:true},{altKey:true},{button:1}])("allows browser modified clicks (%j)",async(modifiers)=>{
  mount("/?q=keep#results");const link=await screen.findByRole("link",{name:"Triage"})
  expect(fireEvent.click(link,modifiers)).toBe(true);expect(link.getAttribute("href")).toBe("/")
  expect(screen.getByTestId("address").textContent).toBe("/?q=keep#results")
 })
 it.each([["/inbox","Inbox"],["/dashboard","OfferPath home"]])("preserves bidder filters on %s",async(path,label)=>{
  mount(path+"?q=keep#results","bidder")
  const control=await screen.findByRole(label==="Inbox"?"link":"button",{name:label})
  fireEvent.click(control);expect(screen.getByTestId("address").textContent).toBe(path+"?q=keep#results")
 })
 it("preserves filters changed directly through browser history",async()=>{
  window.history.replaceState(null,"","/");vi.spyOn(api,"status").mockResolvedValue(idle)
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
  render(<QueryClientProvider client={client}><BrowserRouter><App/></BrowserRouter></QueryClientProvider>)
  const link=await screen.findByRole("link",{name:"Triage"})
  window.history.pushState(null,"","/?q=updated#results");fireEvent.click(link)
  expect(window.location.search+window.location.hash).toBe("?q=updated#results")
  window.history.replaceState(null,"","/")
 })
})


describe("bootstrap outage recovery", () => {
  const mount = () => {
    vi.spyOn(api, "status").mockResolvedValue(idle)
    const client = new QueryClient({defaultOptions:{queries:{retry:false}}})
    clients.push(client)
    render(<QueryClientProvider client={client}><MemoryRouter><App /></MemoryRouter></QueryClientProvider>)
    return client
  }
  it("keeps mounted workspace input during a failed refresh and retry", async () => {
    const client = mount()
    await screen.findByText("Your queue is clear")
    fireEvent.click(screen.getByRole("button", {name:"Filters"}))
    const input = screen.getByLabelText("Search mail")
    fireEvent.change(input, {target:{value:"unsaved search"}})
    vi.mocked(api.bootstrap).mockRejectedValue(new ApiError("Temporary gateway outage",502))
    await act(async () => {await client.refetchQueries({queryKey:["bootstrap"]})})
    await waitFor(() => expect(screen.getByLabelText("Search mail")).toBe(input))
    expect(input).toHaveProperty("value","unsaved search")
    expect(screen.queryByText("Check your local settings")).toBeNull()
    let finish!: (value: Awaited<ReturnType<typeof api.bootstrap>>) => void
    const bootstrap=client.getQueryData<Awaited<ReturnType<typeof api.bootstrap>>>(["bootstrap"])!
    vi.mocked(api.bootstrap).mockImplementation(() => new Promise(resolve => {finish=resolve}))
    fireEvent.click(screen.getByRole("button",{name:"Retry connection"}))
    await waitFor(() => expect(screen.getByRole("button",{name:"Retry connection"})).toHaveProperty("disabled",true))
    await act(async () => {finish(bootstrap)})
    await waitFor(() => expect(screen.queryByRole("button",{name:"Retry connection"})).toBeNull())
    expect(screen.getByLabelText("Search mail")).toBe(input)
  })
  it("offers retry for initial network outage without blaming configuration", async () => {
    const bootstrap=vi.mocked(api.bootstrap).getMockImplementation()!
    vi.mocked(api.bootstrap).mockRejectedValue(new ApiError("Could not connect to OfferPath.",0))
    mount()
    await screen.findByRole("heading",{name:"Workspace temporarily unavailable"})
    expect(screen.queryByText("Check your local settings")).toBeNull()
    vi.mocked(api.bootstrap).mockImplementation(bootstrap)
    fireEvent.click(screen.getByRole("button",{name:"Retry connection"}))
    await screen.findByText("Your queue is clear")
  })
  it("keeps configuration recovery for invalid saved configuration", async () => {
    vi.mocked(api.bootstrap).mockRejectedValue(new ApiError("The saved configuration at config.toml needs updating.",503))
    mount()
    await screen.findByRole("heading",{name:"Check your local settings"})
    expect(screen.getByRole("button",{name:"Try settings"})).toBeTruthy()
  })
})

it('removes embedded monitoring navigation and handles its former URL as a moved page',async()=>{
 vi.spyOn(api,'session').mockResolvedValue({role:'admin',is_owner:true,workspace_id:'legacy',workspace_name:'Original workspace',username:'owner'})
 vi.spyOn(api,'status').mockResolvedValue(idle)
 const fetch=vi.fn(async(_url: string)=>new Response(JSON.stringify({configured:false}),{headers:{'Content-Type':'application/json'}}))
 vi.stubGlobal('fetch',fetch)
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
 render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/system-monitoring']}><App/></MemoryRouter></QueryClientProvider>)
 await screen.findByRole('heading',{name:'That page moved'})
 expect(screen.queryByRole('heading',{name:'System monitoring'})).toBeNull()
 expect(screen.queryByRole('link',{name:'System monitoring'})).toBeNull()
 expect(fetch.mock.calls.some(call=>String(call[0]).includes('/api/admin/system-monitoring'))).toBe(false)
})

it('opens shared job links for an admin even when their workspace API is unavailable',async()=>{
 vi.stubGlobal('ResizeObserver',class{observe(){}unobserve(){}disconnect(){}})
 vi.spyOn(Element.prototype,'clientWidth','get').mockReturnValue(1200)
 vi.spyOn(Element.prototype,'clientHeight','get').mockReturnValue(500)
 Element.prototype.scrollTo=vi.fn()
 Element.prototype.scrollIntoView=vi.fn()
 const query=Element.prototype.querySelector
 vi.spyOn(Element.prototype,'querySelector').mockImplementation(function(this:Element,selector:string){return query.call(this,selector.startsWith('&')?':scope'+selector.slice(1):selector)} as typeof Element.prototype.querySelector)
 vi.spyOn(api,'session').mockResolvedValue({role:'admin',is_owner:false,job_links_access:true,workspace_id:'workspace-one',username:'alice'})
 vi.mocked(api.bootstrap).mockRejectedValue(new Error('Workspace API unavailable'))
 const status=vi.spyOn(api,'status').mockResolvedValue(idle)
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(
  String(url).startsWith('/api/job-links')?{items:[{id:'shared-row',company:'Shared company',role:'Engineer',link:'https://jobs.test/1'}],next_cursor:null,incomplete:false}:{configured:false}
 ),{headers:{'Content-Type':'application/json'}})))
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
 render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/job-links']}><App/></MemoryRouter></QueryClientProvider>)
 await screen.findByRole('grid',{name:'Shared job links'})
 expect(screen.getByRole('gridcell',{name:'Shared company'})).toBeTruthy()
 expect(screen.getByRole('link',{name:'Job links'})).toBeTruthy()
 expect(api.bootstrap).not.toHaveBeenCalled()
 expect(status).not.toHaveBeenCalled()
 vi.mocked(api.session).mockResolvedValue({role:'admin',is_owner:false,job_links_access:false,workspace_id:'workspace-one',username:'alice'})
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>String(url).startsWith('/api/job-links')?new Response(JSON.stringify({error:'Access revoked'}),{status:403,headers:{'Content-Type':'application/json'}}):new Response(JSON.stringify({configured:false}),{headers:{'Content-Type':'application/json'}})))
 fireEvent.click(screen.getByRole('button',{name:'Refresh job links'}))
 await screen.findByRole('heading',{name:'Job links access required'})
 expect(screen.queryByRole('link',{name:'Job links'})).toBeNull()
 await waitFor(()=>expect(client.getQueriesData({queryKey:['job-links']})).toHaveLength(0))
})

it('hides Job links and denies direct navigation for an admin without a grant',async()=>{
 vi.spyOn(api,'session').mockResolvedValue({role:'admin',is_owner:false,job_links_access:false,workspace_id:'workspace-one',username:'alice'})
 const fetch=vi.fn(async(_url:string)=>new Response(JSON.stringify({configured:false}),{headers:{'Content-Type':'application/json'}}))
 vi.stubGlobal('fetch',fetch)
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
 render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/job-links']}><App/></MemoryRouter></QueryClientProvider>)
 await screen.findByRole('heading',{name:'Job links access required'})
 expect(screen.queryByRole('link',{name:'Job links'})).toBeNull()
 expect(fetch.mock.calls.some(call=>String(call[0]).startsWith('/api/job-links'))).toBe(false)
})

it.each(['legacy','another-workspace'])('always allows owner Job links access while viewing %s',async(workspace_id)=>{
 vi.stubGlobal('ResizeObserver',class{observe(){}unobserve(){}disconnect(){}})
 vi.spyOn(api,'session').mockResolvedValue({role:'admin',is_owner:true,job_links_access:false,workspace_id})
 vi.stubGlobal('fetch',vi.fn(async(url:string)=>new Response(JSON.stringify(String(url).startsWith('/api/job-links')?{items:[],next_cursor:null,incomplete:false}:{configured:false}),{headers:{'Content-Type':'application/json'}})))
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
 render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/job-links']}><App/></MemoryRouter></QueryClientProvider>)
 await screen.findByRole('grid',{name:'Shared job links'})
 expect(screen.getByRole('link',{name:'Job links'})).toBeTruthy()
})
