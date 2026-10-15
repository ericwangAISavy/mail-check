import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter, useNavigate } from "react-router-dom"
import { ToastProvider } from "@/components/common"
import { api } from "@/lib/api"
import type { Bootstrap } from "@/lib/types"
import DashboardPage from "./dashboard"

const chart = vi.hoisted(() => ({ date: "2026-09-14" }))
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
  BarChart: ({ children }: any) => <div>{children}</div>,
  Bar: ({ name, onClick }: any) => <button aria-label={`Chart segment ${name}`} onClick={() => onClick({ date: chart.date })}>Bar</button>,
  CartesianGrid: () => null, XAxis: () => null, YAxis: () => null, Tooltip: () => null,
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
function History() {
  const navigate = useNavigate()
  return <><button onClick={() => navigate("/dashboard?q=from-history")}>Other URL</button><button onClick={() => navigate(-1)}>Back</button></>
}
function mount(path = "/dashboard", readOnly = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  clients.push(client)
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><ToastProvider><History /><DashboardPage bootstrap={bootstrap} readOnly={readOnly} /></ToastProvider></MemoryRouter></QueryClientProvider>)
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
  expect(screen.getByText("Paused")).toBeTruthy()
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
  expect(screen.getByRole("button", { name: "1 month" }).getAttribute("aria-pressed")).toBe("true")
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
it("synchronizes the search box with URL history", async () => {
  mount("/dashboard?q=original"); await screen.findByLabelText("Search stored mail")
  fireEvent.click(screen.getByRole("button", { name: "Other URL" })); await lastParam("q", "from-history")
  expect((screen.getByLabelText("Search stored mail") as HTMLInputElement).value).toBe("from-history")
  fireEvent.click(screen.getByRole("button", { name: "Back" })); await lastParam("q", "original")
  expect((screen.getByLabelText("Search stored mail") as HTMLInputElement).value).toBe("original")
})
it("clears stale date focus when changing the date range", async () => {
  mount("/dashboard?focus_date=2026-09-15&focus_category=rejection")
  await screen.findByLabelText("Date range")
  fireEvent.change(screen.getByLabelText("Date range"), { target: { value: "7" } })
  await lastParam("focus_date", null); await lastParam("focus_category", null)
})
it("focuses the first visible day of a weekly bucket without changing its scope", async () => {
  mount("/dashboard?interval=week")
  fireEvent.click(await screen.findByRole("button", { name: "Chart segment Rejection" }))
  await lastParam("start", null); await lastParam("end", null)
  await lastParam("interval", "week"); await lastParam("focus_category", "rejection")
  await lastParam("focus_date", "2026-09-15")
})
it("focuses a daily chart segment using the existing day/category filters", async () => {
  chart.date = "2026-09-15"; mount()
  fireEvent.click(await screen.findByRole("button", { name: "Chart segment Rejection" }))
  await lastParam("focus_date", "2026-09-15"); await lastParam("focus_category", "rejection")
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
  expect((button.querySelector("span") as HTMLElement).style.backgroundColor).toBe("rgb(107, 125, 255)")
})
it("does not fetch admin account details for a guest", async () => {
  mount("/dashboard", true); await screen.findByText("Messages collected")
  expect(api.accounts).not.toHaveBeenCalled()
  expect(screen.queryByRole("link", { name: /Manage accounts/ })).toBeNull()
})
it("collapses the message explorer by default and expands it from View all", async () => {
  const response = data()
  response.messages.items = [{ pk: 123, subject: "Application update", received_at: "2026-10-14T12:00:00Z", category_label: "Rejection", account_label: "personal" }] as any
  vi.mocked(api.dashboard).mockResolvedValue(response)
  mount()
  await screen.findByText("Messages collected")
  const explorer = document.querySelector("#message-explorer") as HTMLDetailsElement
  expect(explorer.open).toBe(false)
  fireEvent.click(screen.getByRole("link", { name: /View all/ }))
  await waitFor(() => expect(explorer.open).toBe(true))
  explorer.open = false
  fireEvent(explorer, new Event("toggle"))
  await waitFor(() => expect(explorer.open).toBe(false))
})
