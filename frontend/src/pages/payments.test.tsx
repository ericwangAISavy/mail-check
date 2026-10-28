import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { api, request } from "@/lib/api"
import PaymentsPage from "./payments"
vi.mock("@/lib/api", () => ({ api: { post: vi.fn() }, request: vi.fn() }))
vi.mock("@/components/common", () => ({ Loading: ({ label }: { label: string }) => <div>{label}</div>, PageHeading: ({ title, action }: { title: string; action?: any }) => <><h1>{title}</h1>{action}</>, useToast: () => vi.fn() }))
const clients: QueryClient[] = []
const data = () => ({ week_start: "2026-10-12", week_end: "2026-10-18", today: "2026-10-20", timezone: "America/Chicago", currency: "USD", dates: ["2026-10-12","2026-10-13","2026-10-14","2026-10-15","2026-10-16","2026-10-17","2026-10-18"], daily: [3,0,0,0,0,0,0], unassigned: 0, accounts: [{ id: 1, label: "Work inbox" }], bidders: [{ id: 1, name: "Alex", assignments: [{ id: 10, account_id: 1, account_label: "Work inbox", start_date: "2026-10-12", end_date: null }], daily: [3,0,0,0,0,0,0], total: 3, checked_daily: [3,0,0,0,0,0,0], payment: null }] })
beforeEach(() => { vi.mocked(request).mockResolvedValue(data()); vi.mocked(api.post).mockResolvedValue({ ok: true }) })
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); vi.resetAllMocks() })
function mount(readOnly = false) { const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); clients.push(client); return render(<QueryClientProvider client={client}><PaymentsPage readOnly={readOnly} /></QueryClientProvider>) }
it("records an admin-entered amount with the reviewed week and count", async () => {
  mount()
  fireEvent.click(await screen.findByRole("button", { name: /Edit confirmed payment for Alex/ }))
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
it("shows only estimated and confirmed amounts without payment metadata", async () => {
  const report = data() as any
  report.bidders[0].payment = { amount_cents: 1025, application_count: 2, paid_at: "2026-10-19T12:00:00Z", note: "Paid by bank" }
  vi.mocked(request).mockResolvedValue(report)
  mount(true)
  const row=(await screen.findByRole("rowheader",{name:/Alex/})).closest("tr")!
  expect(within(row).getByLabelText("Estimated / confirmed payment").textContent).toBe("— / $10.25")
  expect(screen.queryByText("Count changed since payment")).toBeNull()
  expect(screen.queryByText("Paid by bank")).toBeNull()
  expect(screen.queryByText(/applications at recording/)).toBeNull()
})
it("shows loading failures with a retry action", async () => {
  vi.mocked(request).mockRejectedValue(new Error("Could not load totals"))
  mount(true)
  await screen.findByRole("alert")
  expect(screen.getByText("Could not load totals")).toBeTruthy()
  expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy()
})
it("shows received confirmations alongside checked sourcing links", async () => {
  const report = data() as any
  report.bidders[0].daily[0] = 112
  report.bidders[0].checked_daily = [60,0,0,0,0,0,0]
  vi.mocked(request).mockResolvedValue(report)
  mount(true)
  const row = (await screen.findByRole("rowheader", {name: /Alex/})).closest("tr")!
  expect(within(row).getByText("112 / 60")).toBeTruthy()
  expect(screen.getByText(/Estimated confirmations \/ checked applications/)).toBeTruthy()
})

it("shows daily and weekly totals to guests without management or payment controls", async () => {
  mount(true)
  const name = await screen.findByRole("rowheader", { name: /Alex/ })
  const row = name.closest("tr")!
  expect(within(row).getAllByRole("cell").map(cell => cell.textContent)).toEqual(["3 / 3","0 / 0","0 / 0","0 / 0","0 / 0","0 / 0","0 / 0","3","— / —"])
  expect(screen.queryByRole("button", { name: /Edit confirmed payment for Alex/ })).toBeNull()
  expect(screen.queryByText("Manage bidders and account assignments")).toBeNull()
  expect(screen.getByText("Monday–Sunday · America/Chicago")).toBeTruthy()
})
it("keeps management on Accounts for admins", async () => {
  mount(); await screen.findByRole("rowheader", {name: /Alex/})
  expect(screen.queryByText("Manage bidders and account assignments")).toBeNull()
})

it("uses estimated confirmations for overall totals and preserves bidder filtering", async () => {
  const report = data()
  report.today = "2026-10-12"
  report.bidders.push({ ...report.bidders[0], id: 2, name: "Blair" })
  report.daily=[6,0,0,0,0,0,0]
  vi.mocked(request).mockResolvedValue(report)
  mount()
  const heading = await screen.findByText("Estimated confirmations this week")
  expect(heading.parentElement!.querySelector("strong")!.textContent).toBe("6")
  const today = screen.getByText("Today")
  expect(today.parentElement!.querySelector("strong")!.textContent).toBe("6")
  const footer = document.querySelector("tfoot tr")!
  expect(within(footer as HTMLElement).getAllByRole("cell")[0].textContent).toBe("6 / 6")
  expect(within(footer as HTMLElement).getAllByRole("cell")[7].textContent).toBe("6")
  fireEvent.change(screen.getByLabelText("Bidder"), { target: { value: "2" } })
  expect(screen.queryByRole("rowheader", {name: /Alex/})).toBeNull()
  expect(heading.parentElement!.querySelector("strong")!.textContent).toBe("3")
})

it("puts shared-account bidders together using only assignments active that week", async () => {
  const report = data()
  const bidder = (id: number, name: string, accounts: number[]) => ({ ...report.bidders[0], id, name,
    assignments: accounts.map(account => ({ id: id * 10 + account, account_id: account, account_label: `${account}@example.test`, start_date: "2026-10-12", end_date: null })) })
  report.bidders = [bidder(1, "Abimeleck", [3]), bidder(2, "Daniel", [1]), bidder(3, "Dany", [2]), bidder(4, "Joseph", [1]), bidder(5, "Noorian", [3]), bidder(6, "Unassigned", [])]
  // An expired assignment must not pull Dany into the first group.
  report.bidders[2].assignments.push({ id: 99, account_id: 1, account_label: "1@example.test", start_date: "2026-09-01", end_date: "2026-09-30" } as any)
  vi.mocked(request).mockResolvedValue(report)
  mount()
  await screen.findByRole("rowheader", { name: /Daniel/ })
  expect(Array.from(document.querySelectorAll("tbody th strong")).map(row => row.textContent)).toEqual(["Daniel", "Joseph", "Dany", "Abimeleck", "Noorian", "Unassigned"])
})

it("shows unallocated confirmations without assigning them to bidder estimates", async () => {
  const report = {...data(), unallocated_daily: [3,0,0,0,0,0,0]}
  report.bidders[0].daily = [0,0,0,0,0,0,0]
  report.bidders[0].total = 0
  report.bidders[0].checked_daily = [0,0,0,0,0,0,0]
  vi.mocked(request).mockResolvedValue(report)
  mount()
  const row = (await screen.findByRole("rowheader", {name: /Unallocated confirmations/})).closest("tr")!
  expect(within(row).getAllByRole("cell")[0].textContent).toBe("3 / 0")
  expect(screen.getByText("Estimated confirmations this week").parentElement!.querySelector("strong")!.textContent).toBe("3")
  fireEvent.change(screen.getByLabelText("Bidder"), {target: {value: "1"}})
  expect(screen.queryByRole("rowheader", {name: /Unallocated confirmations/})).toBeNull()
  expect(screen.getByText("Estimated confirmations this week").parentElement!.querySelector("strong")!.textContent).toBe("0")
})

it("Refresh uses the displayed week and refreshes sourcing views", async () => {
  const dispatch = vi.spyOn(window, "dispatchEvent")
  mount(); await screen.findByRole("rowheader", {name: /Alex/})
  fireEvent.click(screen.getByRole("button", {name:"Refresh this week"}))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/payments/refresh", {week:"2026-10-12",mode:"refresh"}))
  await waitFor(() => expect(dispatch.mock.calls.some(([event]) => event.type === "mailcheck:check-completed")).toBe(true))
})
it("sums daily estimated confirmations for the weekly total even when checked counts differ",async()=>{
 const report=data() as any
 report.bidders[0].name='Dany'
 report.bidders[0].daily=[0,7,60,91,82,1,0]
 report.bidders[0].checked_daily=[0,7,71,81,12,1,0]
 report.bidders[0].application_total=172
 report.bidders[0].total=241
 report.daily=[0,7,60,91,82,1,0]
 vi.mocked(request).mockResolvedValue(report)
 mount()
 const row=(await screen.findByRole('rowheader',{name:/Dany/})).closest('tr')!
 expect(within(row).getByText('241')).toBeTruthy()
 fireEvent.click(within(row).getByRole('button',{name:/Edit confirmed payment for Dany/}))
 expect(screen.getByText(/241 estimated confirmations/)).toBeTruthy()
})
it('copies every bidder recorded payment in the selected week with its wallet',async()=>{
 const report=data() as any,writeText=vi.fn().mockResolvedValue(undefined)
 Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText}})
 report.bidders[0].wallet_network='USDT.BEP20';report.bidders[0].wallet_address='0x6A33C5254C47DEfE820d93EAa2F4bd7ab9C378BD';report.bidders[0].payment={amount_cents:4400,application_count:3,paid_at:'2026-10-19T12:00:00Z',note:''}
 vi.mocked(request).mockResolvedValue(report);mount()
 fireEvent.click(await screen.findByRole('button',{name:'Copy weekly payment report'}))
 await waitFor(()=>expect(writeText).toHaveBeenCalledWith('$44 -> USDT.BEP20 -> `0x6A33C5254C47DEfE820d93EAa2F4bd7ab9C378BD` -> Bidder -> Alex\n'+'='.repeat(80)+'\nTotal: $44'))
})
it('does not copy an incomplete report and identifies missing bidder details',async()=>{
 const writeText=vi.fn();Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText}})
 mount();fireEvent.click(await screen.findByRole('button',{name:'Copy weekly payment report'}))
 expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('Alex: missing payment amount (set a rate or manual amount), payment network, wallet address'))
 expect(writeText).not.toHaveBeenCalled()
})
it('prefills calculated weekly pay and can save a manual amount without marking paid',async()=>{
 const report=data() as any
 Object.assign(report.bidders[0],{daily:[309,0,0,0,0,0,0],pay_per_bid:'0.05',adjustment_percent:'20',calculated_amount_cents:1854,payable_amount_cents:1854,amount_override_cents:null})
 vi.mocked(request).mockResolvedValue(report);mount()
 fireEvent.click(await screen.findByRole('button',{name:/Edit confirmed payment for Alex/}))
 const input=screen.getByLabelText('Amount (USD)') as HTMLInputElement
 expect(input.value).toBe('18.54')
 fireEvent.change(input,{target:{value:'22.00'}})
 fireEvent.click(screen.getByRole('button',{name:'Save amount'}))
 await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/api/payments/bidders/1/amount',{week:'2026-10-12',expected_count:309,amount:'22.00'}))
 expect(vi.mocked(api.post).mock.calls.some(([url])=>url.endsWith('/paid'))).toBe(false)
})
it('edits an already-paid amount and can apply the current calculated amount',async()=>{
 const report=data() as any
 Object.assign(report.bidders[0],{daily:[309,0,0,0,0,0,0],pay_per_bid:'0.05',adjustment_percent:'20',calculated_amount_cents:1854,payable_amount_cents:1970,payment:{amount_cents:1970,application_count:328,paid_at:'2026-10-19T12:00:00Z',note:'Original note',revision:0}})
 vi.mocked(request).mockResolvedValue(report);mount()
 fireEvent.click(await screen.findByRole('button',{name:/Edit confirmed payment for Alex/}))
 expect(screen.getByRole('heading',{name:'Edit payment for Alex'})).toBeTruthy()
 const amount=screen.getByLabelText('Amount (USD)') as HTMLInputElement
 expect(amount.value).toBe('19.70')
 expect((screen.getByLabelText('Reference or note (optional)') as HTMLInputElement).value).toBe('Original note')
 expect(screen.queryByRole('button',{name:'Record as paid'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'Use calculated amount'}))
 expect(amount.value).toBe('18.54')
 fireEvent.change(amount,{target:{value:'22.50'}})
 fireEvent.click(screen.getByRole('button',{name:'Save changes'}))
 await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/api/payments/bidders/1/paid/edit',{week:'2026-10-12',expected_count:309,expected_revision:0,amount:'22.50',note:'Original note'}))
})
it('defaults the blue confirmed amount to the estimate until manually changed',async()=>{
 const report=data() as any
 Object.assign(report.bidders[0],{calculated_amount_cents:1854,payable_amount_cents:1854,pay_per_bid:'0.05',adjustment_percent:'20'})
 vi.mocked(request).mockResolvedValue(report);mount()
 const row=(await screen.findByRole('rowheader',{name:/Alex/})).closest('tr')!
 expect(within(row).getByLabelText('Estimated / confirmed payment').textContent).toBe('$18.54 / $18.54')
 expect(within(row).getByRole('button',{name:/Edit confirmed payment for Alex/}).className).toContain('payment-confirmed')
 expect(within(row).queryByText(/Calculated amount|Paid ·|Manual amount|previous values|×/)).toBeNull()
})

it("offers full rebuild for the displayed week", async () => {
  mount(); await screen.findByRole("rowheader", {name:/Alex/})
  fireEvent.click(screen.getByRole("button", {name:"Fully rebuild this week"}))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/payments/refresh", {week:"2026-10-12",mode:"rebuild"}))
})
