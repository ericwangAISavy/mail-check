import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { api, request } from "@/lib/api"
import BidderManagement from "@/components/bidder-management"
vi.mock("@/lib/api", () => ({ api: { post: vi.fn() }, request: vi.fn() }))
vi.mock("@/components/common", () => ({ Loading: ({ label }: { label: string }) => <div>{label}</div>, PageHeading: ({ title }: { title: string }) => <h1>{title}</h1>, useToast: () => vi.fn() }))
const clients: QueryClient[] = []
const data = () => ({ week_start: "2026-10-12", week_end: "2026-10-18", today: "2026-10-20", timezone: "America/Chicago", currency: "USD", dates: ["2026-10-12","2026-10-13","2026-10-14","2026-10-15","2026-10-16","2026-10-17","2026-10-18"], daily: [3,0,0,0,0,0,0], unassigned: 0, accounts: [{ id: 1, label: "Work inbox" }], bidders: [{ id: 1, name: "Alex", assignments: [{ id: 10, account_id: 1, account_label: "Work inbox", start_date: "2026-10-12", end_date: null }], daily: [3,0,0,0,0,0,0], total: 3, payment: null }] })
beforeEach(() => { vi.mocked(request).mockResolvedValue(data()); vi.mocked(api.post).mockResolvedValue({ ok: true }) })
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); vi.resetAllMocks() })
function mount() { const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); clients.push(client); return render(<QueryClientProvider client={client}><BidderManagement /></QueryClientProvider>) }


it("adds a bidder and assigns an existing account with effective dates", async () => {
  mount()
  fireEvent.click(await screen.findByText("Manage bidders and account assignments"))
  fireEvent.change(await screen.findByLabelText("Bidder name"), { target: { value: "Blair" } })
  fireEvent.click(screen.getByRole("button", { name: "Add bidder" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/payments/bidders", { name: "Blair" }))
  fireEvent.change(screen.getByLabelText("Account"), { target: { value: "1" } })
  fireEvent.change(screen.getByLabelText("First assigned day"), { target: { value: "2026-10-21" } })
  fireEvent.click(screen.getByRole("button", { name: "Assign account" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/payments/bidders/1/assignments", { account_id: 1, start_date: "2026-10-21", end_date: null }))
})
it("edits assignment dates and can restore an ongoing rule", async () => {
  mount()
  fireEvent.click(await screen.findByText("Manage bidders and account assignments"))
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }))
  const form = screen.getByRole("form", { name: "Edit assignment for Work inbox" })
  fireEvent.change(within(form).getByLabelText("First assigned day"), { target: { value: "2026-10-10" } })
  fireEvent.click(within(form).getByRole("button", { name: "Save changes" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/payments/assignments/10", { account_id: 1, start_date: "2026-10-10", end_date: null }))
})
it("requires an inline confirmation before removing an assignment", async () => {
  mount()
  fireEvent.click(await screen.findByText("Manage bidders and account assignments"))
  fireEvent.click(await screen.findByRole("button", { name: "Remove" }))
  expect(api.post).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
  expect(screen.queryByRole("button", { name: "Remove assignment" })).toBeNull()
  fireEvent.click(await screen.findByRole("button", { name: "Remove" }))
  fireEvent.click(screen.getByRole("button", { name: "Remove assignment" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/payments/assignments/10/remove", {}))
})
it("keeps the editor open and shows a rejected change beside the rule", async () => {
  vi.mocked(api.post).mockRejectedValue(new Error("This change would affect a week with a recorded payment"))
  mount()
  fireEvent.click(await screen.findByText("Manage bidders and account assignments"))
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }))
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }))
  await screen.findByText("This change would affect a week with a recorded payment")
  expect(screen.getByRole("button", { name: "Save changes" })).toBeTruthy()
})
