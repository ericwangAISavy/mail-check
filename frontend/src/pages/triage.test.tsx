import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { ToastProvider } from "@/components/common"
import type { Bootstrap, Message } from "@/lib/types"
import TriagePage, { Reader } from "./triage"

const messages: Message[] = [1, 2].map((pk) => ({
  pk, message_id: `${pk}@example.test`, subject: `Interview ${pk}`, from_addr: "recruiter@example.test",
  from_name: "Recruiter", date_utc: null, snippet: "", provider_url: null, handled_at: null,
  account_label: "Personal", provider: "imap", category: "interview_invite", category_label: "Interview invite",
  tier: "act", confidence: .9, company: "Acme", role: "Engineer", deadline: null,
  deadline_display: "", date_display: "Today", date_estimated: false, action_required: true,
  summary: `Summary ${pk}`, source: "llm", open_url: null, open_label: "",
}))
const bootstrap = {
  readiness: { model: true, accounts: true, privacy_ack: true, outlook: false },
  counts: { actionable: 2, informational: 0, done: 0 }, taxonomy: [], presets: [], last_run: "Never checked", account_count: 1,
} as Bootstrap

let done = new Set<number>()
let failDone = false
let slowDone = false
let finishDone: (() => void) | null = null
let requests: string[] = []
let unclassified = 0
let jobStatus = { running: false, message: "" }

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }))
}

function renderPage(bidderInbox=false) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><ToastProvider><TriagePage bootstrap={bidderInbox ? {...bootstrap,readiness:{...bootstrap.readiness,model:false,accounts:false}} : bootstrap} bidderInbox={bidderInbox} /></ToastProvider></QueryClientProvider>)
}

function renderWithReader(message: Message, readOnly = false) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><ToastProvider><Reader message={message} mobile onBack={() => undefined} onDone={() => undefined} busy={false} canRetry readOnly={readOnly} /></ToastProvider></QueryClientProvider>)
}

it("keeps the guest dashboard reader read-only", async () => {
  renderWithReader({ ...messages[0], category: "unclassified" }, true)
  await screen.findByText("Interview 1")
  expect(screen.queryByRole("button", { name: "Done" })).toBeNull()
  expect(screen.queryByRole("button", { name: "Restore" })).toBeNull()
  expect(screen.queryByRole("button", { name: "Try classification again" })).toBeNull()
})

function setCompactViewport(matches: boolean) {
  Object.defineProperty(window, "matchMedia", { configurable: true, value: vi.fn(() => ({ matches })) })
}

beforeEach(() => {
  done = new Set()
  failDone = false
  slowDone = false
  finishDone = null
  requests = []
  unclassified = 0
  jobStatus = { running: false, message: "" }
  window.history.replaceState({}, "", "/")
  setCompactViewport(false)
  HTMLElement.prototype.scrollIntoView = vi.fn()
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    requests.push(`${init?.method || "GET"} ${url} ${String(init?.body || "")}`)
    if (url.startsWith("/api/triage")) {
      const visible = messages.filter((message) => !done.has(message.pk))
      return response({ view: "queue", groups: visible.length ? [{ tier: "act", label: "Act now", items: visible }] : [],
        total: visible.length, summary: { actionable: visible.length, informational: 0, done: done.size },
        counts: { interview_invite: visible.length, unclassified }, accounts: [{ label: "Personal", enabled: true }],
        days: 30, selected_account: null, selected_category: null })
    }
    if (url === "/api/messages/clear-queue/batch-1/undo") {
      done.clear()
      return response({ message: "Restored 2 messages.", count: 2 })
    }
    if (url === "/api/messages/clear-queue" && !failDone) {
      const complete = () => { messages.forEach(message => done.add(message.pk)); return response({ ok: true, count: 2, operation: "batch-1", message: "Moved 2 messages to Completed." }) }
      if (slowDone) return new Promise(resolve => { finishDone = () => { resolve(complete()) } })
      return complete()
    }
    if (url.startsWith("/api/messages/") && init?.method === "POST") {
      if (failDone) return response({ error: "Server rejected the change" }, 500)
      const pk = Number(url.match(/messages\/(\d+)/)?.[1])
      if (slowDone) return new Promise((resolve) => { finishDone = () => { done.add(pk); resolve(response({ ok: true, message: "Updated", summary: {} })) } })
      if (url.includes("/handled?done=true")) done.add(pk)
      return response({ ok: true, message: "Updated", summary: {} })
    }
    if (url.startsWith("/api/messages/undo-last")) return response({ message: "Restored." })
    if (url === "/api/reclassify") return response({ ok: true, message: "Started." })
    if (url === "/api/status") return response({ ...jobStatus, completion_id: 1, auto: false, next_in: null, detail: "", ok: true, stage_elapsed: null })
    if (url.startsWith("/api/messages/")) {
      const pk = Number(url.split("/").pop())
      const message = messages.find((item) => item.pk === pk)
      return response({ message, body_html: `<p>Body for ${pk}</p>` })
    }
    return response({ error: "Not found" }, 404)
  }))
})

afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals() })

describe("triage interactions", () => {
  it("keeps rendering after completing the final message in the queue", async () => {
    renderPage()
    const first = await screen.findByRole("option", { name: /Summary 1/ })
    first.focus()
    fireEvent.keyDown(first, { key: "e" })
    await waitFor(() => expect(screen.queryByRole("option", { name: /Summary 1/ })).toBeNull())
    const last = screen.getByRole("option", { name: /Summary 2/ })
    last.focus()
    fireEvent.keyDown(last, { key: "e" })
    expect(await screen.findByText("Your queue is clear")).toBeTruthy()
    expect(screen.queryByRole("option")).toBeNull()
  })

  it("loads the selected reader and follows arrow-key focus", async () => {
    renderPage()
    expect(await screen.findByText("Interview 1")).toBeTruthy()
    expect(await screen.findByText("Body for 1")).toBeTruthy()
    const page = document.querySelector(".triage-page")!
    fireEvent.keyDown(page, { key: "ArrowDown" })
    await waitFor(() => expect(document.activeElement).toBe(document.querySelector('[data-pk="2"]')))
    expect(await screen.findByText("Body for 2")).toBeTruthy()
  })

  it("advances the selection after a successful Done", async () => {
    renderPage()
    expect(await screen.findByText("Body for 1")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Done" }))
    await waitFor(() => expect(document.querySelector('[data-pk="2"]')?.getAttribute("aria-selected")).toBe("true"))
    await waitFor(() => expect(document.activeElement).toBe(document.querySelector('[data-pk="2"]')))
    expect(requests.some((request) => request.includes("POST /api/messages/1/handled?done=true"))).toBe(true)
  })

  it("moves keyboard focus to the next message after E completes the current one", async () => {
    renderPage()
    const current = await screen.findByRole("option", { name: /Summary 1/ })
    current.focus()
    fireEvent.keyDown(current, { key: "e" })
    await waitFor(() => expect(document.querySelector('[data-pk="2"]')?.getAttribute("aria-selected")).toBe("true"))
    await waitFor(() => expect(document.activeElement).toBe(document.querySelector('[data-pk="2"]')))
    fireEvent.keyDown(document.activeElement!, { key: "e" })
    await waitFor(() => expect(requests.some((request) => request.includes("POST /api/messages/2/handled?done=true"))).toBe(true))
  })

  it("returns focus to the restored message after a failed Done", async () => {
    renderPage()
    const current = await screen.findByRole("option", { name: /Summary 1/ })
    current.focus()
    failDone = true
    fireEvent.keyDown(current, { key: "e" })
    await waitFor(() => expect(document.activeElement).toBe(document.querySelector('[data-pk="1"]')))
  })

  it("ignores a second E while the first Done request is still pending", async () => {
    renderPage()
    const current = await screen.findByRole("option", { name: /Summary 1/ })
    current.focus()
    slowDone = true
    fireEvent.keyDown(current, { key: "e" })
    await waitFor(() => expect(requests.filter((request) => request.includes("POST /api/messages/")).length).toBe(1))
    fireEvent.keyDown(current, { key: "e" })
    expect(requests.filter((request) => request.includes("POST /api/messages/")).length).toBe(1)
    await act(async () => { finishDone?.(); await Promise.resolve() })
    await waitFor(() => expect(document.activeElement).toBe(document.querySelector('[data-pk="2"]')))
  })

  it("returns focus to the selected row when leaving the mobile reader", async () => {
    setCompactViewport(true)
    renderPage()
    fireEvent.click(await screen.findByRole("option", { name: /Summary 1/ }))
    expect(await screen.findByText("Body for 1")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "All messages" }))
    await waitFor(() => expect(document.activeElement).toBe(document.querySelector('[data-pk="1"]')))
  })

  it("keeps keyboard focus in the mobile reader while advancing after Done", async () => {
    setCompactViewport(true)
    renderPage()
    fireEvent.click(await screen.findByRole("option", { name: /Summary 1/ }))
    expect(await screen.findByText("Body for 1")).toBeTruthy()
    await waitFor(() => expect(document.activeElement).toBe(document.querySelector(".reader-pane")))
    fireEvent.keyDown(document.activeElement!, { key: "e" })
    await waitFor(() => expect(requests.some((request) => request.includes("POST /api/messages/1/handled?done=true"))).toBe(true))
    expect(await screen.findByText("Body for 2")).toBeTruthy()
    await waitFor(() => expect(document.activeElement).toBe(document.querySelector(".reader-pane")))
    fireEvent.keyDown(document.activeElement!, { key: "e" })
    await waitFor(() => expect(requests.some((request) => request.includes("POST /api/messages/2/handled?done=true"))).toBe(true))
  })

  it("advances after Done and restores selection when the mutation fails", async () => {
    renderPage()
    expect(await screen.findByText("Body for 1")).toBeTruthy()
    failDone = true
    fireEvent.click(screen.getByRole("button", { name: "Done" }))
    await waitFor(() => expect(document.querySelector('[data-pk="1"]')?.getAttribute("aria-selected")).toBe("true"))
    expect(requests.some((request) => request.includes("POST /api/messages/1/handled?done=true"))).toBe(true)
    expect(await screen.findByText("Server rejected the change")).toBeTruthy()
  })

  it("uses the undo shortcut and does not steal undo from an input", async () => {
    renderPage()
    await screen.findByText("Interview 1")
    const input = document.createElement("input")
    document.body.appendChild(input)
    fireEvent.keyDown(input, { key: "z", ctrlKey: true })
    input.remove()
    expect(requests.some((request) => request.includes("/api/messages/undo-last"))).toBe(false)
    fireEvent.keyDown(document, { key: "z", ctrlKey: true })
    await waitFor(() => expect(requests.some((request) => request.includes("/api/messages/undo-last"))).toBe(true))
  })

  it("retries one unclassified message from the shared reader", async () => {
    const message = { ...messages[0], category: "unclassified", category_label: "Needs a manual look" }
    renderWithReader(message)
    fireEvent.click(await screen.findByRole("button", { name: "Try classification again" }))
    await waitFor(() => expect(requests.some((request) => request.includes('POST /api/reclassify {"pks":[1]}'))).toBe(true))
  })
})

describe("triage chrome", () => {
  it("counts active filters on the Filters button even when the panel is closed", async () => {
    window.history.replaceState({}, "", "/?days=7&account=Personal")
    renderPage()
    const button = await screen.findByRole("button", { name: /Filters/ })
    expect(button.textContent).toContain("2")
  })

  it("offers Try again when the queue fails to load", async () => {
    const original = globalThis.fetch as unknown as (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
    let failures = 1
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).startsWith("/api/triage") && failures-- > 0) return response({ error: "Database is busy" }, 500)
      return original(input, init)
    }))
    renderPage()
    expect(await screen.findByText(/Database is busy/)).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: /Try again/ }))
    expect(await screen.findByRole("option", { name: /Summary 1/ })).toBeTruthy()
  })

  it("labels the undo shortcut with the platform's modifier", async () => {
    renderPage()
    await screen.findByRole("option", { name: /Summary 1/ })
    expect(screen.getByTitle("Undo the most recent Done action").textContent).toMatch(/Undo\s*(Ctrl|⌘)\+Z/)
  })
})

describe("unclassified banner", () => {
  it("stays out of the way when nothing needs a closer look", async () => {
    renderPage()
    await screen.findByRole("option", { name: /Summary 1/ })
    expect(document.querySelector(".attention-banner")).toBeNull()
  })

  it("sits above the mail explorer and retries the whole backlog", async () => {
    unclassified = 16
    renderPage()
    expect(await screen.findByText("16 messages need a closer look")).toBeTruthy()
    const banner = document.querySelector(".attention-banner")!
    expect(banner.compareDocumentPosition(document.querySelector(".triage-split")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Try classification again" }))
    await waitFor(() => expect(requests.some((request) => request.includes("POST /api/reclassify {}"))).toBe(true))
  })

  it("uses the singular for one message", async () => {
    unclassified = 1
    renderPage()
    expect(await screen.findByText("1 message needs a closer look")).toBeTruthy()
  })

  it("shows live progress and disables the button while a retry is running", async () => {
    unclassified = 16
    jobStatus = { running: true, message: "Re-classifying… 5 of 16" }
    renderPage()
    expect(await screen.findByText("Re-classifying… 5 of 16")).toBeTruthy()
    const button = screen.getByRole("button", { name: "Retrying…" }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
  })

  it("is hidden in the Completed view", async () => {
    unclassified = 16
    window.history.replaceState({}, "", "/?view=completed")
    renderPage()
    await screen.findByRole("option", { name: /Summary 1/ })
    expect(screen.getByRole("tab", { name: /Completed/ }).getAttribute("aria-selected")).toBe("true")
    expect(document.querySelector(".attention-banner")).toBeNull()
  })
})

it("opens the target message and reply composer from a follow-up link without generating", async () => {
  window.history.replaceState({}, "", "/?view=all&days=90&message=2&reply=1")
  renderPage()
  await screen.findByRole("button", {name:"Close reply composer and keep draft"})
  expect(screen.getByRole("option",{name:/Summary 2/}).getAttribute("aria-selected")).toBe("true")
  expect(requests.some(r=>r.startsWith("GET /api/messages/2/reply"))).toBe(true)
  expect(requests.some(r=>r.includes("/generate")||r.startsWith("POST /api/messages/2/reply"))).toBe(false)
})

it("offers Today and Last 24 hours and sends the selected range", async () => {
  renderPage()
  await screen.findByText("Interview 1")
  fireEvent.click(screen.getByRole("button", { name: /Filters/ }))
  const range = screen.getByLabelText("Time range")
  expect(screen.getByRole("option", { name: "Today" })).toBeTruthy()
  expect(screen.getByRole("option", { name: "Last 24 hours" })).toBeTruthy()
  fireEvent.change(range, { target: { value: "0" } })
  await waitFor(() => expect(requests.some(url => url.includes("days=0"))).toBe(true))
  fireEvent.change(range, { target: { value: "1" } })
  await waitFor(() => expect(requests.some(url => url.includes("days=1"))).toBe(true))
})

it("submits text search with existing filters and clears it", async () => {
  window.history.replaceState({}, "", "/?view=all&days=1&account=Personal")
  renderPage()
  await screen.findByText("Interview 1")
  fireEvent.click(screen.getByRole("button", { name: /Filters/ }))
  fireEvent.change(screen.getByLabelText("Search mail"), { target: { value: "  Acme  " } })
  fireEvent.click(screen.getByRole("button", { name: "Search" }))
  await waitFor(() => expect(requests.some(url => url.includes("q=Acme") && url.includes("days=1") && url.includes("account=Personal"))).toBe(true))
  fireEvent.click(screen.getByRole("button", { name: "Clear filters" }))
  await waitFor(() => expect((screen.getByLabelText("Search mail") as HTMLInputElement).value).toBe(""))
  expect(new URLSearchParams(window.location.search).has("q")).toBe(false)
})

it('reuses triage for bidder Info requests with reading and scoped Done only',async()=>{
 const base=vi.mocked(fetch).getMockImplementation()!
 window.history.replaceState({},'', '/inbox?category=offer')
 vi.mocked(fetch).mockImplementation(async(input,init)=>{
  const url=String(input)
  if(url.includes('/handled?done=false'))done.delete(Number(url.match(/messages\/(\d+)/)?.[1]))
  const res=await base(input,init)
  const data=await res.json()
  if(url.startsWith('/api/triage')){
   data.groups=data.groups.map((group:any)=>({...group,items:group.items.map((message:any)=>({...message,category:'info_request',category_label:'Info request'}))}))
   data.counts={info_request:data.total}
   data.check_schedule={automatic:true,running:false,next_at:"2026-11-06T20:30:00Z"}
  }else if(url.startsWith('/api/messages/')&&init?.method!=='POST'){
   data.message={...data.message,category:'info_request',category_label:'Info request',open_url:'https://outlook.live.com/mail/',open_label:'Open in Outlook'}
   data.body_html='<p>Your verification code is 123456</p>'
  }
  return response(data,res.status)
 })
 renderPage(true)
 expect(await screen.findByText('Your verification code is 123456')).toBeTruthy()
 expect(screen.getByText(/Next mail check:.*your local time/)).toBeTruthy()
 expect(requests.some(url=>url.startsWith('GET /api/triage?')&&url.includes('category=info_request'))).toBe(true)
 expect(screen.queryByRole('button',{name:'Reply'})).toBeNull()
 expect(screen.queryByRole('link',{name:/Open in Outlook/})).toBeNull()
 expect(screen.queryByRole('button',{name:/Try classification again/})).toBeNull()
 expect(screen.queryByRole('button',{name:/Undo/})).toBeNull()
 expect(screen.queryByRole('button',{name:'Continue setup'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:/Filters/}))
 expect((screen.getByLabelText('Category') as HTMLSelectElement).disabled).toBe(true)
 expect((screen.getByLabelText('Category') as HTMLSelectElement).value).toBe('info_request')
 fireEvent.click(screen.getByRole('button',{name:'Done'}))
 await screen.findByText('Moved to Completed.')
 fireEvent.click(screen.getByRole('button',{name:'Undo'}))
 await waitFor(()=>expect(requests.some(url=>url.startsWith('POST /api/messages/1/handled?done=false'))).toBe(true))
 expect(requests.some(url=>url.includes('/api/messages/undo-last'))).toBe(false)
})

it('hides cached reader metadata when bidder access is rejected',async()=>{
 vi.mocked(fetch).mockImplementation(()=>response({error:'No such message.'},404))
 renderWithReader(messages[0],true)
 expect((await screen.findByRole('alert')).textContent).toContain('This message is unavailable')
 expect(screen.queryByText('Interview 1')).toBeNull()
 expect(screen.queryByText('Acme')).toBeNull()
})

it('refreshes bidder inbox through the scoped GET without starting a manual mail check', async () => {
  renderPage(true)
  const refresh = await screen.findByRole('button', { name: 'Refresh Inbox' })
  const before = requests.filter(request => request.startsWith('GET /api/triage?')).length
  fireEvent.click(refresh)
  await waitFor(() => expect(requests.filter(request => request.startsWith('GET /api/triage?')).length).toBe(before + 1))
  expect(requests.filter(request => request.includes('/api/triage?')).every(request => request.includes('category=info_request'))).toBe(true)
  expect(requests.some(request => request.includes('/api/check'))).toBe(false)
})

it('polls visible bidder inbox every three seconds and refreshes immediately on visibility or focus', async () => {
  vi.useFakeTimers()
  renderPage(true)
  await act(async () => { await vi.advanceTimersByTimeAsync(20) })
  const count = () => requests.filter(request => request.startsWith('GET /api/triage?')).length
  try {
    const before = count()
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(count()).toBe(before + 1)
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    fireEvent(document, new Event('visibilitychange'))
    const hiddenCount = count()
    await act(async () => { await vi.advanceTimersByTimeAsync(9000) })
    expect(count()).toBe(hiddenCount)
    fireEvent(window, new Event('focus'))
    expect(count()).toBe(hiddenCount)
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    await act(async () => { fireEvent(document, new Event('visibilitychange')) })
    expect(count()).toBe(hiddenCount + 1)
    await act(async () => { fireEvent(window, new Event('focus')) })
    expect(count()).toBe(hiddenCount + 2)
  } finally {
    vi.useRealTimers()
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
  }
})

it('does not offer a bidder refresh button on admin triage', async () => {
  renderPage()
  await screen.findByText('Body for 1')
  expect(screen.queryByRole('button', { name: 'Refresh Inbox' })).toBeNull()
})

it.each([
  [true, false, false, 'Live inbox: checks for new mail about every 30 seconds'],
  [true, true, false, 'Live inbox: checks for new mail about every 30 seconds; checking for new mail…'],
  [true, false, true, 'Live inbox: checks for new mail about every 30 seconds; server is processing updates'],
  [false, false, false, 'Automatic mail checks are off'],
])('describes live inbox state (enabled=%s, fetching=%s, processing=%s)', async (enabled, running, processing, label) => {
  const base = vi.mocked(fetch).getMockImplementation()!
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const res = await base(input, init)
    if (!String(input).startsWith('/api/triage')) return res
    const data = await res.json()
    data.check_schedule = { automatic: enabled, running: processing, next_at: null,
      live: { enabled, interval_seconds: 30, running, last_checked_at: null, next_at: null } }
    return response(data)
  })
  renderPage(true)
  expect(await screen.findByText(label)).toBeTruthy()
  expect(requests.some(request => request.startsWith('GET /api/triage?') && request.includes('live=1'))).toBe(true)
})

it('waits for visibility before requesting a hidden bidder inbox', async () => {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
  try {
    renderPage(true)
    await act(async () => { await Promise.resolve() })
    expect(requests).toEqual([])
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    fireEvent(document, new Event('visibilitychange'))
    await screen.findByText('Body for 1')
    expect(requests.some(request => request.includes('live=1'))).toBe(true)
    fireEvent.click(screen.getByRole('tab', { name: 'All mail' }))
    expect(new URLSearchParams(window.location.search).has('live')).toBe(false)
  } finally {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
  }
})


describe("clear entire queue", () => {
  it("requires confirmation and explains the workspace scope", async () => {
    window.history.replaceState({}, "", "/?q=old&days=7")
    renderPage()
    fireEvent.click(await screen.findByRole("button", { name: "Mark all as done" }))
    expect(requests.some(request => request.includes("clear-queue"))).toBe(false)
    expect(screen.getByRole("dialog").textContent).toMatch(/entire workspace Queue/i)
    expect(screen.getByRole("dialog").textContent).toMatch(/outside.*filters/i)
    expect(screen.getByRole("dialog").textContent).toMatch(/All mail.*Completed/)
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
    expect(screen.queryByRole("dialog")).toBeNull()
  })
  it("hides the action outside Queue and for bidder inboxes", async () => {
    renderPage()
    await screen.findByRole("button", { name: "Mark all as done" })
    fireEvent.click(screen.getByRole("tab", { name: "All mail" }))
    expect(screen.queryByRole("button", { name: "Mark all as done" })).toBeNull()
    cleanup()
    renderPage(true)
    await screen.findByRole("button", { name: "Refresh Inbox" })
    expect(screen.queryByRole("button", { name: "Mark all as done" })).toBeNull()
  })
  it("keeps a failed confirmation open without automatic retries", async () => {
    failDone = true
    renderPage()
    fireEvent.click(await screen.findByRole("button", { name: "Mark all as done" }))
    fireEvent.click(screen.getByRole("button", { name: "Confirm mark all as done" }))
    expect((await screen.findByRole("alert")).textContent).toContain("Server rejected the change")
    expect(screen.getByRole("dialog")).toBeTruthy()
    expect(requests.filter(request => request.includes("POST /api/messages/clear-queue"))).toHaveLength(1)
  })
})


it("clears with no request body and offers batch undo", async () => {
  renderPage()
  fireEvent.click(await screen.findByRole("button", { name: "Mark all as done" }))
  fireEvent.click(screen.getByRole("button", { name: "Confirm mark all as done" }))
  await screen.findByText("Moved 2 messages to Completed.")
  expect(requests).toContain("POST /api/messages/clear-queue ")
  expect(screen.queryByRole("dialog")).toBeNull()
  fireEvent.click(screen.getByRole("button", { name: "Undo" }))
  await screen.findByText("Restored 2 messages.")
  expect(requests).toContain("POST /api/messages/clear-queue/batch-1/undo ")
})

it("keeps clearing available with no visible messages", async () => {
  done = new Set([1, 2])
  renderPage()
  await screen.findByText("Your queue is clear")
  expect(screen.getByRole("button", { name: "Mark all as done" })).toBeTruthy()
})

it("guards pending clear against closing and other message actions", async () => {
  slowDone = true
  renderPage()
  fireEvent.click(await screen.findByRole("button", { name: "Mark all as done" }))
  fireEvent.click(screen.getByRole("button", { name: "Confirm mark all as done" }))
  expect((screen.getByRole("button", { name: "Cancel" }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole("button", { name: "Close" }))
  fireEvent.keyDown(document, { key: "Escape" })
  fireEvent.keyDown(document, { key: "z", ctrlKey: true })
  fireEvent.keyDown(document.querySelector(".triage-page")!, { key: "e" })
  expect(screen.getByRole("dialog")).toBeTruthy()
  expect(requests.filter(request => request.startsWith("POST"))).toHaveLength(1)
  await act(async () => { finishDone?.(); await Promise.resolve() })
  await screen.findByText("Moved 2 messages to Completed.")
})
