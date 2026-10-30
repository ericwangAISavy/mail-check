import { StrictMode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import App from "./App"
import { AppErrorBoundary } from "@/components/app-error-boundary"
import { api } from "@/lib/api"

type Status = Awaited<ReturnType<typeof api.status>>
const idle: Status = { running: false, auto: false, next_in: null, completion_id: 1, message: "", detail: "", ok: true, stage_elapsed: null }
const scheduled: Status = { ...idle, auto: true, next_in: 120 }
const running: Status = { ...scheduled, running: true, message: "Reading mail…" }
const clients: QueryClient[] = []

beforeEach(() => {
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
    ["idle to scheduled", idle, scheduled, "Next check", "2:00"],
    ["scheduled to running", scheduled, running, "Reading mail…", null],
    ["running to completed", running, { ...scheduled, completion_id: 2 }, "Next check", "2:00"],
    ["scheduled to idle", scheduled, idle, "All systems ready", null],
    ["progress message", running, { ...running, message: "Classifying mail…" }, "Classifying mail…", null],
    ["countdown tick", scheduled, { ...scheduled, next_in: 119 }, "Next check", "1:59"],
  ] as const)("survives %s and displays the latest status", async (_name, initial, next, label, countdown) => {
    let current: Status = initial
    vi.spyOn(api, "status").mockImplementation(async () => current)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    clients.push(client)
    const { container } = render(<StrictMode><AppErrorBoundary><QueryClientProvider client={client}>
      <MemoryRouter><App /></MemoryRouter>
    </QueryClientProvider></AppErrorBoundary></StrictMode>)
    await screen.findByText("Your queue is clear")
    const status = container.querySelector(".connection-status")!
    await waitFor(() => expect(status.textContent).toContain(initial.running ? initial.message : initial.auto ? "Next check" : "All systems ready"))
    replaceTextNodes(status)

    current = next
    await act(async () => { fireEvent.focus(window) })

    expect(screen.queryByRole("alert")?.querySelector("pre")?.textContent || "").toBe("")
    expect(container.querySelector(".connection-status")?.textContent).toContain(label)
    expect(container.querySelector(".connection-status strong")?.textContent ?? null).toBe(countdown)
    expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeTruthy()
    expect(console.error).not.toHaveBeenCalled()
  })
})

describe("live countdown", () => {
  // Fake only the interval and the clock: react-query, waitFor and the status
  // poll all rely on real setTimeout.
  beforeEach(() => { vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] }) })
  afterEach(() => { vi.useRealTimers() })

  const mount = () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    clients.push(client)
    return render(<QueryClientProvider client={client}><MemoryRouter><App /></MemoryRouter></QueryClientProvider>)
  }
  const digits = (container: HTMLElement) => container.querySelector(".connection-status strong")?.textContent ?? null

  it("counts down every second without asking the server again", async () => {
    const status = vi.spyOn(api, "status").mockResolvedValue({ ...scheduled, next_in: 120 })
    const { container } = mount()
    await waitFor(() => expect(digits(container)).toBe("2:00"))
    const calls = status.mock.calls.length

    await act(async () => { vi.advanceTimersByTime(5000) })

    expect(digits(container)).toBe("1:55")
    expect(status.mock.calls.length).toBe(calls)
  })

  it("re-baselines on the server's value after a poll", async () => {
    let current: Status = { ...scheduled, next_in: 120 }
    vi.spyOn(api, "status").mockImplementation(async () => current)
    const { container } = mount()
    await waitFor(() => expect(digits(container)).toBe("2:00"))
    await act(async () => { vi.advanceTimersByTime(5000) })

    current = { ...scheduled, next_in: 200 }
    await act(async () => { fireEvent.focus(window) })

    expect(digits(container)).toBe("3:20")
  })

  it("polls right away at zero and switches to the running message", async () => {
    let current: Status = { ...scheduled, next_in: 3 }
    const status = vi.spyOn(api, "status").mockImplementation(async () => current)
    const { container } = mount()
    await waitFor(() => expect(digits(container)).toBe("0:03"))
    const calls = status.mock.calls.length

    current = { ...running, message: "Reading mail…" }
    await act(async () => { vi.advanceTimersByTime(3000) })

    await waitFor(() => expect(container.querySelector(".connection-status")?.textContent).toContain("Reading mail…"))
    expect(status.mock.calls.length).toBeGreaterThan(calls)
  })

  it("keeps the ticking digits out of the live region", async () => {
    vi.spyOn(api, "status").mockResolvedValue({ ...scheduled, next_in: 60 })
    const { container } = mount()
    await waitFor(() => expect(digits(container)).toBe("1:00"))
    expect(container.querySelector(".connection-status")?.getAttribute("aria-live")).toBeNull()
    expect(container.querySelector(".connection-status strong")?.closest("[aria-live=polite]")).toBeNull()
  })

  it("shows the schedule as a pressed toggle", async () => {
    vi.spyOn(api, "status").mockResolvedValue({ ...scheduled, interval_minutes: 10 })
    mount()
    const toggle = await screen.findByRole("button", { name: "Auto-check on" })
    expect(toggle.getAttribute("aria-pressed")).toBe("true")
  })
})

it("shows today's received confirmations beside Bidder management", async () => {
  vi.mocked(api.bootstrap).mockResolvedValue({readiness:{model:true,accounts:true,privacy_ack:true,outlook:false},counts:{actionable:0,applications_today:3400},taxonomy:[],presets:[],last_run:"",account_count:2})
  vi.spyOn(api,"status").mockResolvedValue(idle)
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/payments"]}><App /></MemoryRouter></QueryClientProvider>)
  const badge=await screen.findByLabelText("3400 application confirmations received today")
  expect(badge.closest("a")).toBeNull()
  expect(badge.closest("header")?.textContent).toContain("Bidder management")
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
