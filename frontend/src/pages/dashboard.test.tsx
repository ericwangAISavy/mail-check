import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { ToastProvider } from "@/components/common"
import { api } from "@/lib/api"
import { accountAliases, changeText, money, type DashboardMetrics } from "@/lib/dashboard-metrics"
import DashboardPage from "./dashboard"

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
  ComposedChart: ({ children, data }: any) => <div data-testid="chart" data-rows={JSON.stringify(data)}>{children}</div>,
  Line: ({ dataKey, name }: any) => <span data-testid={`line-${dataKey}`}>{name}</span>,
  CartesianGrid: () => null, XAxis: () => null, YAxis: () => null, Tooltip: () => null, Customized: () => null,
}))

const empty = { interview_rate: [null, null], rejection_rate: [null, null] }
const bidderPoint = (over: Record<string, unknown> = {}) => ({ carryover: 2, new: 8, available: 10, completed: 7, expired: 1, remaining: 2, completion_rate: 0.7, checked: 7, ...over })
const buckets = [{ start: "2026-11-30", partial: false }, { start: "2026-12-07", partial: true }]
const work = { buckets, series: [{ id: 1, name: "Alex", points: [bidderPoint(), bidderPoint({ checked: 3 })] }],
  workload: [{ new: 20, checked: 25, backlog: 9, expired: 1 }, { new: 5, checked: 3, backlog: 11, expired: 0 }] }
const metrics = (over: Partial<DashboardMetrics> = {}): DashboardMetrics => ({
  as_of: "2026-12-09T18:00:00+00:00", timezone: "America/Chicago", today: "2026-12-09",
  range: { weeks: 8, start: "2026-10-19", end: "2026-12-13" },
  summaries: { week_start: "2026-12-07", week_end: "2026-12-13",
    applications: { current: 1123, previous_comparable: 663, previous_full: 977, average: 1453.5, average_weeks: 4, change: { absolute: 460, percent: 69.4 },
      trend: [{ week: "2026-11-30", value: 977, partial: false }, { week: "2026-12-07", value: 1123, partial: true }] },
    interviews: { scheduled: 15, so_far: 9, previous_so_far: 0, previous_full: 0, average: 22, average_weeks: 4, change: { absolute: 15, percent: null },
      trend: [{ week: "2026-11-30", value: 0, partial: false }, { week: "2026-12-07", value: 15, partial: true }] } },
  profiles: { weeks: buckets, cohort_days: 14, mature_through: "2026-11-24", replies_since: "2026-11-10",
    rates: { interview_rate: { available: false, reason: "Only 89 of 235 emails can be matched.", emails: 235, matched: 89, share: 0.38 },
      rejection_rate: { available: true, reason: null, emails: 10, matched: 9, share: 0.9 } },
    series: [{ id: 1, label: "thomas.dan@example.test", email: "thomas.dan@example.test", color: 5, points: { interviews: [9, 7], applications: [300, 200], rejections: [12, 4], ...empty,
      rejection_rate: [{ value: 0.25, hits: 1, base: 4 }, null] } },
    { id: 2, label: "eric.wang@example.test", email: "eric.wang@example.test", color: 4, points: { interviews: [6, 4], applications: [100, 90], rejections: [3, 1], ...empty } }] },
  bidders: { daily: work, weekly: work, history_since: "2026-10-19" },
  attention: [{ id: "missing_confirmations", severity: "warning", count: 233, href: "/sourcing", label: "Unconfirmed links", detail: "Checked." },
    { id: "expiring_links", severity: "warning", count: 272, href: "/sourcing", label: "Expiring within 48 hours", detail: "Soon." }],
  payments: { week_start: "2026-12-07", week_end: "2026-12-13", currency: "USD", gross_cents: 3505, deductions_cents: 0, net_payable_cents: 3505, recorded_cents: 0,
    outstanding_cents: null, reconciled: false, week_ended: false, missing_rates: [], checked: 907, bidders: 6 },
  ...over,
})
const clients: QueryClient[] = []
beforeEach(() => {
  vi.spyOn(api, "dashboardMetrics").mockImplementation(async () => metrics())
  vi.spyOn(api, "dashboardAccounts").mockResolvedValue({ accounts: [{ label: "thomas.dan@example.test" }, { label: "Beta" }], bidders: [{ id: 1, name: "Alex" }] })
})
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); vi.restoreAllMocks() })
function mount(path = "/dashboard", readOnly = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><ToastProvider><DashboardPage readOnly={readOnly} /></ToastProvider></MemoryRouter></QueryClientProvider>)
}
const lastParams = () => { const calls = vi.mocked(api.dashboardMetrics).mock.calls; return calls[calls.length - 1][0] }
const rows = async () => JSON.parse((await screen.findByTestId("chart")).getAttribute("data-rows")!)

it("formats changes, cents and short account names", () => {
  expect(changeText({ absolute: 460, percent: 69.4 })).toBe("+460 (+69.4%)")
  expect(changeText({ absolute: -10, percent: -40 })).toBe("−10 (−40%)")
  expect(changeText({ absolute: 15, percent: null })).toBe("+15")
  expect(changeText(null)).toBeNull()
  expect(money(3505)).toBe("$35.05")
  expect(accountAliases([{ id: 1, label: "eric.wang.swe1115@x.test" }, { id: 2, label: "eric.wang@x.test" }, { id: 3, label: "timJones1228@x.test" }, { id: 4, label: "Personal" }]))
    .toEqual({ 1: "Eric 2", 2: "Eric", 3: "Tim", 4: "Personal" })
})

it("shows two weekly summaries with labelled comparisons and no data table", async () => {
  mount()
  const apps = (await screen.findByRole("heading", { name: /Applications this week/ })).closest("section")!
  expect(within(apps).getByText("1,123")).toBeTruthy()
  expect(within(apps).getByText("+460 (+69.4%)")).toBeTruthy()
  expect(within(apps).getByText("vs 663 by this time last week")).toBeTruthy()
  expect(within(apps).getByText("4-week average 1,454")).toBeTruthy()
  const meetings = screen.getByRole("heading", { name: /Interviews this week/ }).closest("section")!
  expect(within(meetings).getByText("15")).toBeTruthy()
  expect(within(meetings).getByText("9 started so far")).toBeTruthy()
  expect(within(meetings).getByText("vs last week’s full schedule")).toBeTruthy()
  expect(screen.queryByRole("table")).toBeNull()
})

it("charts calendar interviews per profile by default with the unfinished week dashed", async () => {
  mount()
  expect(await screen.findByRole("heading", { name: "Weekly interview performance" })).toBeTruthy()
  const data = await rows()
  expect([data[0]["s:p1"], data[1]["s:p1"]]).toEqual([9, null])
  expect([data[0]["d:p1"], data[1]["d:p1"]]).toEqual([9, 7])
  expect(screen.getByTestId("line-s:p2").textContent).toBe("Eric")
})

it("switches profile metrics and explains an unreliable rate instead of charting it", async () => {
  mount()
  fireEvent.click(await screen.findByRole("button", { name: "Applications" }))
  expect((await rows())[0]["s:p1"]).toBe(300)
  fireEvent.click(screen.getByRole("button", { name: "Interview conversion" }))
  expect(await screen.findByText("Only 89 of 235 emails can be matched.")).toBeTruthy()
  expect(screen.queryByTestId("chart")).toBeNull()
  fireEvent.click(screen.getByRole("button", { name: "Rejection rate" }))
  expect((await rows())[0]["s:p1"]).toBe(0.25)
})

it("replaces the graph per tab, with bidder metrics and workload series toggles", async () => {
  mount()
  fireEvent.click(await screen.findByRole("tab", { name: "Bidder productivity" }))
  expect((await rows())[0]["s:b1"]).toBe(0.7)
  fireEvent.click(screen.getByRole("button", { name: "Checked" }))
  expect((await rows())[1]["d:b1"]).toBe(3)
  fireEvent.click(screen.getByRole("tab", { name: "Workload" }))
  expect((await rows())[0]).toMatchObject({ "s:new": 20, "s:checked": 25 })
  expect(screen.queryByTestId("line-s:backlog")).toBeNull()
  fireEvent.click(screen.getByRole("button", { name: "Backlog" }))
  expect(await screen.findByTestId("line-s:backlog")).toBeTruthy()
  expect(screen.getAllByTestId("chart").length).toBe(1)
})

it("reveals the numbers only on request", async () => {
  mount()
  fireEvent.click(await screen.findByRole("button", { name: "View data" }))
  const table = screen.getByRole("table", { name: "Weekly interview performance data" })
  expect(within(table).getByText("Dec 7 (in progress)")).toBeTruthy()
  fireEvent.click(screen.getByRole("button", { name: "Hide data" }))
  expect(screen.queryByRole("table")).toBeNull()
})

it("keeps payments exact and links attention items to their pages", async () => {
  mount()
  const pay = (await screen.findByRole("heading", { name: "Payments" })).closest("section")!
  expect(within(pay).getAllByText("$35.05").length).toBe(2)
  expect(within(pay).queryByText("Outstanding")).toBeNull()
  expect(within(pay).getByRole("link", { name: /View breakdown/ }).getAttribute("href")).toBe("/payments")
  expect(screen.getByRole("link", { name: /233\s*Unconfirmed links/ }).getAttribute("href")).toBe("/sourcing")
})

it("sends range and entity filters and resets them", async () => {
  mount()
  await screen.findByRole("heading", { name: "Payments" })
  expect(lastParams().get("weeks")).toBe("8")
  fireEvent.change(screen.getByLabelText("Graph range"), { target: { value: "12" } })
  await waitFor(() => expect(lastParams().get("weeks")).toBe("12"))
  fireEvent.change(screen.getByLabelText("Account"), { target: { value: "Beta" } })
  await waitFor(() => expect(lastParams().get("account")).toBe("Beta"))
  fireEvent.change(await screen.findByLabelText("Bidder"), { target: { value: "1" } })
  await waitFor(() => expect(lastParams().get("bidder")).toBe("1"))
  fireEvent.click(screen.getByRole("button", { name: "Reset" }))
  await waitFor(() => expect(lastParams().toString()).toBe("weeks=8"))
})

it("custom ranges wait for both dates", async () => {
  mount("/dashboard?start=2026-11-01&end=")
  expect(await screen.findByText("Choose a start and end date.")).toBeTruthy()
  expect(api.dashboardMetrics).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText("Through"), { target: { value: "2026-12-05" } })
  await waitFor(() => expect(lastParams().toString()).toBe("start=2026-11-01&end=2026-12-05"))
})

it("never sends a bidder filter for bidder sign-ins and shows load errors with a retry", async () => {
  mount("/dashboard?bidder=7", true)
  await screen.findByRole("heading", { name: "Payments" })
  expect(screen.queryByLabelText("Bidder")).toBeNull()
  expect(lastParams().get("bidder")).toBeNull()
  cleanup()
  vi.mocked(api.dashboardMetrics).mockRejectedValue(new Error("Database is busy"))
  mount()
  expect(await screen.findByText("Database is busy")).toBeTruthy()
  expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy()
})
