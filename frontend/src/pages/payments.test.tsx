import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { api, request } from "@/lib/api"
import PaymentsPage from "./payments"
vi.mock("@/lib/api", () => ({ api: { post: vi.fn() }, request: vi.fn() }))
vi.mock("@/components/common", () => ({ Loading: ({ label }: { label: string }) => <div>{label}</div>, PageHeading: ({ title }: { title: string }) => <h1>{title}</h1>, useToast: () => vi.fn() }))
const clients: QueryClient[] = []
const data = () => ({ week_start: "2026-10-12", week_end: "2026-10-18", today: "2026-10-20", timezone: "America/Chicago", currency: "USD", dates: ["2026-10-12","2026-10-13","2026-10-14","2026-10-15","2026-10-16","2026-10-17","2026-10-18"], daily: [3,0,0,0,0,0,0], unassigned: 0, accounts: [{ id: 1, label: "Work inbox" }], bidders: [{ id: 1, name: "Alex", assignments: [{ id: 10, account_id: 1, account_label: "Work inbox", start_date: "2026-10-12", end_date: null }], daily: [3,0,0,0,0,0,0], total: 3, payment: null }] })
beforeEach(() => { vi.mocked(request).mockResolvedValue(data()); vi.mocked(api.post).mockResolvedValue({ ok: true }) })
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); vi.resetAllMocks() })
function mount(readOnly = false) { const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); clients.push(client); return render(<QueryClientProvider client={client}><PaymentsPage readOnly={readOnly} /></QueryClientProvider>) }
it("shows daily and weekly totals to guests without management or payment controls", async () => {
  mount(true)
  const name = await screen.findByRole("rowheader", { name: /Alex/ })
  const row = name.closest("tr")!
  expect(within(row).getAllByRole("cell").map(cell => cell.textContent)).toEqual(["3 / 0","0 / 0","0 / 0","0 / 0","0 / 0","0 / 0","0 / 0","3","Not recorded"])
  expect(screen.queryByRole("button", { name: "Record payment" })).toBeNull()
  expect(screen.queryByText("Manage bidders and account assignments")).toBeNull()
  expect(screen.getByText("Monday–Sunday · America/Chicago")).toBeTruthy()
})
it("records an admin-entered amount with the reviewed week and count", async () => {
  mount()
  fireEvent.click(await screen.findByRole("button", { name: "Record payment" }))
  fireEvent.change(screen.getByLabelText("Amount (USD)"), { target: { value: "123.45" } })
  fireEvent.change(screen.getByLabelText("Reference or note (optional)"), { target: { value: "Bank reference" } })
  fireEvent.click(screen.getByRole("button", { name: "Record as paid" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/payments/bidders/1/paid", { week: "2026-10-12", expected_count: 3, amount: "123.45", note: "Bank reference" }))
})
it("supports previous week navigation", async () => {
  mount(true)
  fireEvent.click(await screen.findByRole("button", { name: "Previous week" }))
  await waitFor(() => expect(request).toHaveBeenCalledWith("/api/payments?week=2026-10-05"))
})
it("shows recorded payment amount and flags later count changes", async () => {
  const report = data() as any
  report.bidders[0].payment = { amount_cents: 1025, application_count: 2, paid_at: "2026-10-19T12:00:00Z", note: "Paid by bank" }
  vi.mocked(request).mockResolvedValue(report)
  mount(true)
  await screen.findByText("Paid · 2 applications")
  expect(screen.getByText("Count changed since payment")).toBeTruthy()
  expect(screen.getByText("Paid by bank")).toBeTruthy()
})
it("adds a bidder and assigns an existing account with effective dates", async () => {
  mount()
  fireEvent.click(await screen.findByText("Manage bidders and account assignments"))
  fireEvent.change(screen.getByLabelText("Bidder name"), { target: { value: "Blair" } })
  fireEvent.click(screen.getByRole("button", { name: "Add bidder" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/payments/bidders", { name: "Blair" }))
  fireEvent.change(screen.getByLabelText("Account"), { target: { value: "1" } })
  fireEvent.change(screen.getByLabelText("First assigned day"), { target: { value: "2026-10-21" } })
  fireEvent.click(screen.getByRole("button", { name: "Assign account" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/payments/bidders/1/assignments", { account_id: 1, start_date: "2026-10-21", end_date: null }))
})
it("shows loading failures with a retry action", async () => {
  vi.mocked(request).mockRejectedValue(new Error("Could not load totals"))
  mount(true)
  await screen.findByRole("alert")
  expect(screen.getByText("Could not load totals")).toBeTruthy()
  expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy()
})
it("edits assignment dates and can restore an ongoing rule", async () => {
  mount()
  fireEvent.click(await screen.findByText("Manage bidders and account assignments"))
  fireEvent.click(screen.getByRole("button", { name: "Edit" }))
  const form = screen.getByRole("form", { name: "Edit assignment for Work inbox" })
  fireEvent.change(within(form).getByLabelText("First assigned day"), { target: { value: "2026-10-10" } })
  fireEvent.click(within(form).getByRole("button", { name: "Save changes" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/payments/assignments/10", { account_id: 1, start_date: "2026-10-10", end_date: null }))
})
it("requires an inline confirmation before removing an assignment", async () => {
  mount()
  fireEvent.click(await screen.findByText("Manage bidders and account assignments"))
  fireEvent.click(screen.getByRole("button", { name: "Remove" }))
  expect(api.post).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
  expect(screen.queryByRole("button", { name: "Remove assignment" })).toBeNull()
  fireEvent.click(screen.getByRole("button", { name: "Remove" }))
  fireEvent.click(screen.getByRole("button", { name: "Remove assignment" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/payments/assignments/10/remove", {}))
})
it("keeps the editor open and shows a rejected change beside the rule", async () => {
  vi.mocked(api.post).mockRejectedValue(new Error("This change would affect a week with a recorded payment"))
  mount()
  fireEvent.click(await screen.findByText("Manage bidders and account assignments"))
  fireEvent.click(screen.getByRole("button", { name: "Edit" }))
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }))
  await screen.findByText("This change would affect a week with a recorded payment")
  expect(screen.getByRole("button", { name: "Save changes" })).toBeTruthy()
})

it("shows received confirmations alongside checked sourcing links", async () => {
  const report = data() as any
  report.bidders[0].daily[0] = 112
  report.bidders[0].checked_daily = [60,0,0,0,0,0,0]
  vi.mocked(request).mockResolvedValue(report)
  mount(true)
  const row = (await screen.findByRole("rowheader", {name: /Alex/})).closest("tr")!
  expect(within(row).getByText("112 / 60")).toBeTruthy()
  expect(screen.getByText(/Received confirmations \/ checked sourcing links/)).toBeTruthy()
})
