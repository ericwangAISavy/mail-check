import {Children,isValidElement} from "react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { ToastProvider } from "@/components/common"
import { api } from "@/lib/api"
import type { Bootstrap } from "@/lib/types"
import DashboardPage from "./dashboard"

const chart = vi.hoisted(() => ({ date: "2026-09-14",rows:[] as Record<string,any>[] }))
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
  ComposedChart: ({ children,data }: any) => {chart.rows=data;return <div>{Children.toArray(children).filter(child=>!isValidElement(child)||child.type!=="defs")}</div>},
  Bar: ({ name, onClick }: any) => <button aria-label={`Chart segment ${name}`} onClick={() => onClick({ date: chart.date })}>Bar</button>,
  Line: () => null, AreaChart: ({ data }: any) => <output aria-label="quality points">{JSON.stringify(data)}</output>,
  BarChart: ({ data }: any) => <output aria-label="quality bars">{JSON.stringify(data)}</output>,
  Area: () => null, Rectangle: () => null, CartesianGrid: () => null, XAxis: () => null, YAxis: () => null, Tooltip: () => null,
}))
const bootstrap: Bootstrap = { readiness: { model: true, accounts: true, privacy_ack: true, outlook: false }, counts: {}, taxonomy: [], presets: [], last_run: "Never checked", account_count: 1 }
const clients: QueryClient[] = []
const data = () => ({ filters: { start: "2026-09-15", end: "2026-10-14" }, summary: { total: 7, pending_attention: 2, completed: 1, unclassified: 0, retryable: 0 },
  categories: [{ name: "offer", label: "Offer", tier: "act", count: 0 }, { name: "rejection", label: "Rejection", tier: "info", count: 7 }],
  daily: [{ date: "2026-09-15", total: 7, counts: { offer: 0, rejection: 7 }, partial: false }],
  history: { retention_days: 30 }, messages: { items: [], total: 0, page: 1, total_pages: 0, page_size: 50 } })
beforeEach(() => {
  chart.date = "2026-09-14"
  vi.spyOn(api, "dashboard").mockImplementation(async () => data())
  vi.spyOn(api, "dashboardAccounts").mockResolvedValue({ accounts: [{ label: "personal" }] })
  vi.spyOn(api, "accounts").mockResolvedValue({ accounts: [{ id: 1, label: "personal", email: "me@example.test", provider: "imap", imap_host: "imap.example.test", imap_port: 993, use_ssl: true, folder: "INBOX", enabled: false }], outlook_ready: false })
})
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); vi.restoreAllMocks() })
function mount(path = "/dashboard", readOnly = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  clients.push(client)
  const page = <QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><ToastProvider><DashboardPage bootstrap={bootstrap} readOnly={readOnly} /></ToastProvider></MemoryRouter></QueryClientProvider>
  return render(page)
}
async function lastParam(name: string, value: string | null) {
  await waitFor(() => {
    const calls = vi.mocked(api.dashboard).mock.calls
    expect(calls[calls.length - 1][0].get(name)).toBe(value)
  })
}

it("keeps all four metrics and uses actual account inclusion state", async () => {
  mount()
  await screen.findByText("Messages collected")
  expect(screen.getByText("Unclassified")).toBeTruthy()
  expect(await screen.findByText("Paused")).toBeTruthy()
  expect(screen.queryByText("Connected", { exact: true })).toBeNull()
  expect(screen.queryByText(/\+12%/)).toBeNull()
})
it("quick ranges replace custom dates while preserving other filters", async () => {
  mount("/dashboard?start=2026-09-15&end=2026-10-14&account=personal&status=pending&focus_date=2026-09-15&page=2")
  fireEvent.click(await screen.findByRole("button", { name: "2 weeks" }))
  await lastParam("days", "14"); await lastParam("start", null); await lastParam("end", null)
  await lastParam("focus_date", null); await lastParam("account", "personal"); await lastParam("status", "pending")
  await lastParam("page", "1")
  expect((screen.getByLabelText("Date range") as HTMLSelectElement).value).toBe("14")
  expect(screen.getByRole("button", { name: "2 weeks" }).getAttribute("aria-pressed")).toBe("true")
})
it("keeps quick range buttons synchronized with the date dropdown", async () => {
  mount(); await screen.findByLabelText("Date range")
  await lastParam("days", "7")
  expect((screen.getByLabelText("Date range") as HTMLSelectElement).value).toBe("7")
  expect(screen.getByRole("button", { name: "1 week" }).getAttribute("aria-pressed")).toBe("true")
  for (const [days, label] of [["7", "1 week"], ["90", "3 months"]]) {
    fireEvent.click(screen.getByRole("button", { name: label }))
    await lastParam("days", days)
    expect((screen.getByLabelText("Date range") as HTMLSelectElement).value).toBe(days)
  }
  fireEvent.change(screen.getByLabelText("Date range"), { target: { value: "14" } })
  expect(screen.getByRole("button", { name: "2 weeks" }).getAttribute("aria-pressed")).toBe("true")
})
it("propagates every filter and synchronizes both grouping controls", async () => {
  mount(); await screen.findByLabelText("Date range")
  fireEvent.change(screen.getByLabelText("Date range"), { target: { value: "7" } }); await lastParam("days", "7")
  fireEvent.change(screen.getByLabelText("Group by"), { target: { value: "week" } }); await lastParam("interval", "week")
  expect((screen.getByLabelText("Chart grouping") as HTMLSelectElement).value).toBe("week")
  fireEvent.change(screen.getByLabelText("Account"), { target: { value: "personal" } }); await lastParam("account", "personal")
  fireEvent.change(screen.getByLabelText("Status"), { target: { value: "pending" } }); await lastParam("status", "pending")
  fireEvent.click(screen.getByRole("button", { name: "More" }))
  fireEvent.change(screen.getByLabelText("Action"), { target: { value: "yes" } }); await lastParam("action", "yes")
})
it("clears stale date focus when changing the date range", async () => {
  mount("/dashboard?focus_date=2026-09-15&focus_category=rejection")
  await screen.findByLabelText("Date range")
  fireEvent.change(screen.getByLabelText("Date range"), { target: { value: "7" } })
  await lastParam("focus_date", null); await lastParam("focus_category", null)
})
it("does not show a successful refresh when the API request fails", async () => {
  mount(); await screen.findByText("Messages collected")
  vi.mocked(api.dashboard).mockRejectedValue(new Error("Refresh is offline"))
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }))
  await screen.findByText("Refresh is offline")
  expect(screen.queryByText("Activity refreshed.")).toBeNull()
  expect(screen.getByText("Messages collected")).toBeTruthy()
})
it("uses the same series color for filtered chart legends", async () => {
  mount(); await screen.findByText("Messages collected")
  const legend = document.querySelector(".chart-legend")!
  const button = within(legend as HTMLElement).getByRole("button", { name: /Rejection/ })
  expect((button.querySelector("span") as HTMLElement).style.backgroundColor).toBe("var(--category-color-1)")
})
it("does not fetch admin account details for a guest", async () => {
  mount("/dashboard", true); await screen.findByText("Messages collected")
  expect(api.accounts).not.toHaveBeenCalled()
  expect(screen.queryByRole("link", { name: /Manage accounts/ })).toBeNull()
})
it("filters by bidder together with account and resets the selection", async () => {
  vi.mocked(api.dashboardAccounts).mockResolvedValue({ accounts: [{ label: "personal" }], bidders: [{ id: 7, name: "Alex" }] })
  mount("/dashboard?account=personal&page=2")
  await screen.findByRole("option", { name: "Alex" })
  fireEvent.change(screen.getByLabelText("Bidder"), { target: { value: "7" } })
  await lastParam("bidder", "7")
  await lastParam("account", "personal")
  await lastParam("page", "1")
  fireEvent.click(screen.getByRole("button", { name: "Reset" }))
  await lastParam("bidder", null)
  expect((screen.getByLabelText("Bidder") as HTMLSelectElement).value).toBe("")
})

it("hides refresh and account management for bidder viewers",async()=>{
  mount("/dashboard",true)
  await screen.findByRole("heading",{name:"Dashboard"})
  expect(screen.queryByRole("button",{name:"Refresh"})).toBeNull()
  expect(screen.queryByRole("link",{name:/Manage accounts/})).toBeNull()
  expect(api.accounts).not.toHaveBeenCalled()
})

it("recovers from a gateway outage using Try again",async()=>{
 vi.mocked(api.dashboard).mockRejectedValue(new Error("OfferPath is temporarily unavailable (502). Please try again shortly."))
 mount()
 await screen.findByText("Dashboard is unavailable")
 expect(screen.getByText(/temporarily unavailable \(502\)/)).toBeTruthy()
 vi.mocked(api.dashboard).mockResolvedValue(data())
 fireEvent.click(screen.getByRole("button",{name:"Try again"}))
 await screen.findByText("Messages collected")
 expect(screen.queryByText("Dashboard is unavailable")).toBeNull()
})

it("can reset invalid saved filters instead of retrying the same invalid request",async()=>{
 vi.mocked(api.dashboard).mockImplementation(async params=>{
  if(params.get("days")!=="7")throw new Error("Choose a range of at most 90 calendar days")
  return data()
 })
 mount("/dashboard?days=365&q=old-filter")
 await screen.findByText("Dashboard is unavailable")
 fireEvent.click(screen.getByRole("button",{name:"Clear filters"}))
 await screen.findByText("Messages collected")
 await lastParam("days","7");await lastParam("q",null)
})

it("uses the same real totals and category counts for weekly stacks and the trend",async()=>{
 const result=data();result.summary.total=13;result.categories[1].count=13
 result.daily=[{date:"2026-09-15",total:5,counts:{offer:0,rejection:5},partial:false},{date:"2026-09-16",total:8,counts:{offer:0,rejection:8},partial:false}]
 vi.mocked(api.dashboard).mockResolvedValue(result)
 mount("/dashboard?interval=week")
 await waitFor(()=>expect(chart.rows).toEqual([{date:"2026-09-14",total:13,partial:false,counts:{offer:0,rejection:13}}]))
})

it('shows only graphs and own account selector for bidders',async()=>{
 mount('/dashboard',true)
 await screen.findByText('Messages collected')
 expect(screen.queryByText('ACCOUNT STATUS')).toBeNull()
 expect(screen.queryByLabelText('Search stored mail')).toBeNull()
 expect(screen.queryByText('Find a message')).toBeNull()
 expect(document.getElementById('message-explorer')).toBeNull()
 expect(screen.queryByLabelText('Bidder')).toBeNull()
 expect(api.accounts).not.toHaveBeenCalled()
 expect(screen.getByLabelText('Account')).toBeTruthy()
 expect(screen.getByText('Applications over time')).toBeTruthy()
})

it("shows filters and skips explorer rows while the initial history read is pending", async () => {
  vi.mocked(api.dashboard).mockReturnValue(new Promise(() => {}))
  mount()
  expect(await screen.findByLabelText("Date range")).toBeTruthy()
  await lastParam("include_messages", null)
  expect(vi.mocked(api.dashboard).mock.lastCall?.[2]).toBe(false)
  expect(screen.queryByText("Messages collected")).toBeNull()
})


it("shows interview and rejection rates against received applications, grouped before dividing", async () => {
  const result = data()
  const sample = { ...result, daily: ["2026-09-15","2026-09-16","2026-09-17"].map(date => ({ ...result.daily[0], date })),
    profile_quality: {personal: {
      "2026-09-15": { applications: 1, interview: 1, rejection: 0 },
      "2026-09-16": { applications: 9, interview: 0, rejection: 3 },
      "2026-09-18": { applications: 0, interview: 2, rejection: 0 },
    }} }
  vi.mocked(api.dashboard).mockResolvedValue(sample)
  mount()
  await screen.findByLabelText("quality points")
  const rows = () => JSON.parse(screen.getByLabelText("quality points").textContent!)
  expect(screen.queryByText("Show messages")).toBeNull()
  fireEvent.click(screen.getByRole("button", { name: "Day" }))
  const daily = rows()
  expect(daily[2].interview).toBeNull()          // a day without applications has no rate
  fireEvent.click(screen.getByRole("button", { name: "Bar" }))
  expect(JSON.parse(screen.getByLabelText("quality bars").textContent!)).toEqual(daily)
  fireEvent.click(screen.getByRole("button", { name: "Line" }))
  fireEvent.click(screen.getByRole("button", { name: "Week" }))
  // Counts are added up first: 3 interviews / 10 applications, 3 rejections / 10 applications.
  expect(rows()).toEqual([{ date: "2026-09-14", counts: { applications: 10, interview: 3, rejection: 3 }, interview: 30, rejection: 30 }])
  fireEvent.click(screen.getByRole("button", { name: "Month" }))
  expect(rows()).toEqual([{ date: "2026-09-01", counts: { applications: 10, interview: 3, rejection: 3 }, interview: 30, rejection: 30 }])
  const card = screen.getByRole("article", { name: "personal profile quality" })
  expect(within(card).getByText("10 applications")).toBeTruthy()
  expect(within(card).getAllByText("30%")).toHaveLength(2)
  expect(within(card).getAllByText("3 / 10 applications", { selector: "small" })).toHaveLength(2)
})

it("explains an account with no received applications instead of showing empty charts", async () => {
  const result = data()
  vi.mocked(api.dashboard).mockResolvedValue({ ...result, profile_quality: {
    personal: { "2026-09-15": { applications: 0, interview: 0, rejection: 0 } },
    work: { "2026-09-15": { applications: 0, interview: 2, rejection: 1 } },
  } })
  mount()
  await screen.findByText("Profile quality")
  expect(within(screen.getByRole("article", { name: "personal profile quality" })).getByText("No application emails received yet.")).toBeTruthy()
  expect(within(screen.getByRole("article", { name: "work profile quality" })).getByText(/none were received yet/)).toBeTruthy()
  expect(screen.queryByLabelText("quality points")).toBeNull()
  expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4)
})

it("says where the profile comparison starts", async () => {
  const result = data()
  vi.mocked(api.dashboard).mockResolvedValue({ ...result, profile_quality_since: "2026-09-15", profile_quality: {
    personal: { "2026-09-15": { applications: 4, interview: 1, rejection: 0 } } } })
  mount()
  const note = await screen.findByText(/^Counting from /)
  expect(note.textContent).toContain("2026")
  expect(note.getAttribute("title")).toMatch(/kept from this day on/)
})
