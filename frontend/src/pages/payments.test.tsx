import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { api, request } from "@/lib/api"
import PaymentsPage from "./payments"
vi.mock("@/lib/api", () => ({ api: { post: vi.fn() }, request: vi.fn() }))
vi.mock("@/components/common", () => ({ Loading: ({ label }: { label: string }) => <div>{label}</div>, PageHeading: ({ title, action }: { title: string; action?: any }) => <><h1>{title}</h1>{action}</>, useToast: () => vi.fn() }))
const clients: QueryClient[] = []
const data = () => ({ payment_visible:true, week_start: "2026-10-12", week_end: "2026-10-18", today: "2026-10-20", timezone: "America/Chicago", currency: "USD", dates: ["2026-10-12","2026-10-13","2026-10-14","2026-10-15","2026-10-16","2026-10-17","2026-10-18"], daily: [3,0,0,0,0,0,0], unassigned: 0, accounts: [{ id: 1, label: "Work inbox" }], bidders: [{ id: 1, name: "Alex", assignments: [{ id: 10, account_id: 1, account_label: "Work inbox", start_date: "2026-10-12", end_date: null }], daily: [3,0,0,0,0,0,0], total: 3, checked_daily: [3,0,0,0,0,0,0], payment: null }] })
beforeEach(() => { vi.mocked(request).mockResolvedValue(data()); vi.mocked(api.post).mockResolvedValue({ ok: true }) })
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); vi.resetAllMocks() })
function mount(readOnly = false) { const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); clients.push(client); return render(<QueryClientProvider client={client}><PaymentsPage readOnly={readOnly} /></QueryClientProvider>) }
it("records an admin-entered amount with the reviewed week and count", async () => {
  mount()
  fireEvent.click(await screen.findByRole("button", { name: /Edit confirmed payment for Alex/ }))
  fireEvent.change(screen.getByLabelText("Amount (USD)"), { target: { value: "123.45" } })
  fireEvent.change(screen.getByLabelText("Reference or note (optional)"), { target: { value: "Bank reference" } })
  fireEvent.click(screen.getByRole("button", { name: "Record as paid" }))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/payments/bidders/1/paid", { week: "2026-10-12", expected_count: 3, expected_rule:{minimum_daily:0,amount_cents:0}, expected_calculated_amount_cents:null, amount: "123.45", note: "Bank reference" }))
})
it("supports previous week navigation", async () => {
  mount(true)
  fireEvent.click(await screen.findByRole("button", { name: "Previous week" }))
  await waitFor(() => expect(request).toHaveBeenCalledWith("/api/payments?week=2026-10-05"))
})
it("shows gross and net amounts independently of saved payment metadata", async () => {
  const report = data() as any
  report.bidders[0].payment = { amount_cents: 1025, application_count: 2, paid_at: "2026-10-19T12:00:00Z", note: "Paid by bank" }
  vi.mocked(request).mockResolvedValue(report)
  mount(true)
  const row=(await screen.findByRole("rowheader",{name:/Alex/})).closest("tr")!
  expect(within(row).getByLabelText("Before / after deductions").textContent).toBe("Rate not set / Unavailable")
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
it("shows checked applications before muted received replies", async () => {
  const report = data() as any
  report.bidders[0].daily[0] = 112
  report.bidders[0].checked_daily = [60,0,0,0,0,0,0]
  vi.mocked(request).mockResolvedValue(report)
  mount()
  const row = (await screen.findByRole("rowheader", {name: /Alex/})).closest("tr")!
  expect(within(row).getAllByRole("cell")[0].textContent).toBe("60 / 112")
  expect(within(row).getAllByTitle("Checked applications")[0].className).toBe("payment-checked-count")
  expect(within(row).getAllByTitle("Received replies")[0].className).toBe("payment-reply-count")
  expect(within(row).getAllByRole("cell")[7].textContent).toBe("60")
  expect(screen.getByText("Checked applications this week").parentElement!.querySelector("strong")!.textContent).toBe("60")
  expect(screen.getByText(/Checked applications \/ received replies/)).toBeTruthy()
})

it("shows daily and weekly totals to guests without management or payment controls", async () => {
  mount(true)
  const name = await screen.findByRole("rowheader", { name: /Alex/ })
  const row = name.closest("tr")!
  expect(within(row).getAllByRole("cell").map(cell => cell.textContent)).toEqual(["3","0","0","0","0","0","0","3","Rate not set / UnavailableAsk your admin to set a payment rate."])
  expect(screen.queryByRole("button", { name: /Edit confirmed payment for Alex/ })).toBeNull()
  expect(screen.queryByText("Manage bidders and account assignments")).toBeNull()
  expect(screen.getByText("Monday–Sunday · America/Chicago")).toBeTruthy()
})
it("keeps management on Accounts for admins", async () => {
  mount(); await screen.findByRole("rowheader", {name: /Alex/})
  expect(screen.queryByText("Manage bidders and account assignments")).toBeNull()
})

it("uses checked applications for overall totals and preserves bidder filtering", async () => {
  const report = data()
  report.today = "2026-10-12"
  report.bidders.push({ ...report.bidders[0], id: 2, name: "Blair" })
  report.daily=[6,0,0,0,0,0,0]
  vi.mocked(request).mockResolvedValue(report)
  mount()
  const heading = await screen.findByText("Checked applications this week")
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
  const row = (await screen.findByRole("rowheader", {name: /Unallocated received replies/})).closest("tr")!
  expect(within(row).getAllByRole("cell")[0].textContent).toBe("0 / 3")
  expect(screen.getByText("Checked applications this week").parentElement!.querySelector("strong")!.textContent).toBe("0")
  fireEvent.change(screen.getByLabelText("Bidder"), {target: {value: "1"}})
  expect(screen.queryByRole("rowheader", {name: /Unallocated received replies/})).toBeNull()
  expect(screen.getByText("Checked applications this week").parentElement!.querySelector("strong")!.textContent).toBe("0")
})

it("Refresh uses the displayed week and refreshes sourcing views", async () => {
  const dispatch = vi.spyOn(window, "dispatchEvent")
  mount(); await screen.findByRole("rowheader", {name: /Alex/})
  fireEvent.click(screen.getByRole("button", {name:"Refresh this week"}))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/payments/refresh", {week:"2026-10-12",mode:"refresh"}))
  await waitFor(() => expect(dispatch.mock.calls.some(([event]) => event.type === "mailcheck:check-completed")).toBe(true))
})
it("sums daily checked applications for the weekly total even when checked counts differ",async()=>{
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
 expect(within(row).getAllByRole('cell')[7].textContent).toBe('172')
 fireEvent.click(within(row).getByRole('button',{name:/Edit confirmed payment for Dany/}))
 expect(screen.getByText(/172 checked applications/)).toBeTruthy()
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
 Object.assign(report.bidders[0],{daily:[400,0,0,0,0,0,0],checked_daily:[309,0,0,0,0,0,0],pay_per_bid:'0.05',adjustment_percent:'20',calculated_amount_cents:1854,payable_amount_cents:1854,amount_override_cents:null})
 vi.mocked(request).mockResolvedValue(report);mount()
 fireEvent.click(await screen.findByRole('button',{name:/Edit confirmed payment for Alex/}))
 const input=screen.getByLabelText('Amount (USD)') as HTMLInputElement
 expect(input.value).toBe('18.54')
 fireEvent.change(input,{target:{value:'22.00'}})
 fireEvent.click(screen.getByRole('button',{name:'Save amount'}))
 await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/api/payments/bidders/1/amount',{week:'2026-10-12',expected_count:309,expected_rule:{minimum_daily:0,amount_cents:0},expected_calculated_amount_cents:1854,amount:'22.00'}))
 expect(vi.mocked(api.post).mock.calls.some(([url])=>url.endsWith('/paid'))).toBe(false)
})
it('edits an already-paid amount and can apply the current calculated amount',async()=>{
 const report=data() as any
 Object.assign(report.bidders[0],{daily:[400,0,0,0,0,0,0],checked_daily:[309,0,0,0,0,0,0],pay_per_bid:'0.05',adjustment_percent:'20',calculated_amount_cents:1854,payable_amount_cents:1970,payment:{amount_cents:1970,application_count:328,paid_at:'2026-10-19T12:00:00Z',note:'Original note',revision:0}})
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
 await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/api/payments/bidders/1/paid/edit',{week:'2026-10-12',expected_count:309,expected_rule:{minimum_daily:0,amount_cents:0},expected_calculated_amount_cents:1854,expected_revision:0,amount:'22.50',note:'Original note'}))
})
it('defaults the blue confirmed amount to the estimate until manually changed',async()=>{
 const report=data() as any
 Object.assign(report.bidders[0],{calculated_amount_cents:1854,payable_amount_cents:1854,pay_per_bid:'0.05',adjustment_percent:'20'})
 vi.mocked(request).mockResolvedValue(report);mount()
 const row=(await screen.findByRole('rowheader',{name:/Alex/})).closest('tr')!
 expect(within(row).getByLabelText('Before / after deductions').textContent).toBe('$18.54 / $18.54')
 expect(within(row).getByRole('button',{name:/Edit confirmed payment for Alex/}).className).toContain('payment-confirmed')
 expect(within(row).queryByText(/Calculated amount|Paid ·|Manual amount|previous values|×/)).toBeNull()
})

it("offers full rebuild for the displayed week", async () => {
  mount(); await screen.findByRole("rowheader", {name:/Alex/})
  fireEvent.click(screen.getByRole("button", {name:"Fully rebuild this week"}))
  await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/payments/refresh", {week:"2026-10-12",mode:"rebuild"}))
})

it('explains missing Nifemi rates and saves a rate during an in-progress week',async()=>{
 let report:any=data();report.today='2026-10-17';Object.assign(report.bidders[0],{name:'Nifemi',daily:[1,9,0,0,0,0,0],total:10,pay_per_bid:null,adjustment_percent:'20',calculated_amount_cents:null,payable_amount_cents:null})
 vi.mocked(request).mockImplementation(async()=>report)
 vi.mocked(api.post).mockImplementation(async()=>{
  report={...report,bidders:report.bidders.map((b:any)=>({...b,pay_per_bid:'0.05',calculated_amount_cents:60,payable_amount_cents:60}))};return {ok:true}
 })
 mount()
 fireEvent.click(await screen.findByRole('button',{name:'Set payment rate for Nifemi'}))
 expect((screen.getByLabelText('Pay per bid (USD)') as HTMLInputElement).value).toBe('')
 fireEvent.change(screen.getByLabelText('Pay per bid (USD)'),{target:{value:'0.05'}})
 fireEvent.click(screen.getByRole('button',{name:'Save rate'}))
 await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/api/payments/bidders/1/rate',{pay_per_bid:'0.05',adjustment_percent:'20'}))
 const row=(await screen.findByRole('rowheader',{name:/Nifemi/})).closest('tr')!
 await waitFor(()=>expect(within(row).getByLabelText('Before / after deductions').textContent).toBe('$0.60 / $0.60'))
})

it('explains unavailable amounts to bidders without offering financial editing',async()=>{
 const report:any=data();Object.assign(report.bidders[0],{name:'Nifemi',pay_per_bid:null,calculated_amount_cents:null,payable_amount_cents:null})
 vi.mocked(request).mockResolvedValue(report);mount(true)
 const row=(await screen.findByRole('rowheader',{name:/Nifemi/})).closest('tr')!
 expect(within(row).getByText('Rate not set')).toBeTruthy()
 expect(screen.queryByRole('button',{name:/Set payment rate/})).toBeNull()
 expect(within(row).getByText(/Ask your admin/)).toBeTruthy()
})

it('keeps the entered rate and missing-rate explanation when saving fails',async()=>{
 vi.mocked(api.post).mockRejectedValue(new Error('Could not save rate'))
 mount();fireEvent.click(await screen.findByRole('button',{name:'Set payment rate for Alex'}))
 fireEvent.change(screen.getByLabelText('Pay per bid (USD)'),{target:{value:'0.07'}})
 fireEvent.click(screen.getByRole('button',{name:'Save rate'}))
 await screen.findByText('Could not save rate')
 expect((screen.getByLabelText('Pay per bid (USD)') as HTMLInputElement).value).toBe('0.07')
 expect(screen.getByRole('button',{name:'Set payment rate for Alex'})).toBeTruthy()
})

it('displays an explicitly zero rate as zero money instead of a missing rate',async()=>{
 const report:any=data();Object.assign(report.bidders[0],{pay_per_bid:'0',calculated_amount_cents:0,payable_amount_cents:0})
 vi.mocked(request).mockResolvedValue(report);mount(true)
 const row=(await screen.findByRole('rowheader',{name:/Alex/})).closest('tr')!
 expect(within(row).getByLabelText('Before / after deductions').textContent).toBe('$0.00 / $0.00')
 expect(within(row).queryByText('Rate not set')).toBeNull()
})

it.each([false,true])("expands account counts with bidder visibility readOnly=%s",async(readOnly)=>{
 const report=data() as any
 report.bidders[0].account_breakdown=[
  {account_id:1,account_label:"Work inbox",daily:[2,0,0,0,0,0,0],checked_daily:[1,0,0,0,0,0,0],total:1},
  {account_id:2,account_label:"Other inbox",daily:[1,0,0,0,0,0,0],checked_daily:[2,0,0,0,0,0,0],total:2},
 ]
 vi.mocked(request).mockResolvedValue(report)
 mount(readOnly)
 const toggle=await screen.findByRole("button",{name:"Show accounts for Alex"})
 expect(within(toggle.closest("tr")!).queryByText("Work inbox")).toBeNull()
 expect(screen.queryByRole("row",{name:"Alex · Work inbox"})).toBeNull()
 fireEvent.click(toggle)
 const work=screen.getByRole("row",{name:"Alex · Work inbox"})
 const other=screen.getByRole("row",{name:"Alex · Other inbox"})
 expect(within(work).getAllByRole("cell")[0].textContent).toBe(readOnly ? "1" : "1 / 2")
 expect(within(other).getAllByRole("cell")[0].textContent).toBe(readOnly ? "2" : "2 / 1")
 expect(screen.getByRole("button",{name:"Hide accounts for Alex"}).getAttribute("aria-expanded")).toBe("true")
 expect(within(screen.getByRole("rowheader",{name:"Total"}).closest("tr")!).getAllByRole("cell")[0].textContent).toBe(readOnly ? "3" : "3 / 3")
 fireEvent.click(screen.getByRole("button",{name:"Hide accounts for Alex"}))
 expect(screen.queryByRole("row",{name:"Alex · Work inbox"})).toBeNull()
})

it('masks account emails in visible labels and accessible row names without changing report data', async () => {
 const report=data() as any
 const label='Primary (danny@outlook.com)'
 report.bidders[0].account_breakdown=[{account_id:1,account_label:label,daily:[3,0,0,0,0,0,0],checked_daily:[3,0,0,0,0,0,0],total:3}]
 vi.mocked(request).mockResolvedValue(report)
 mount(true)
 fireEvent.click(await screen.findByRole('button',{name:'Show accounts for Alex'}))
 expect(screen.getByRole('row',{name:'Alex · Primary (d****y@outlook.com)'})).toBeTruthy()
 expect(screen.getByText('Primary (d****y@outlook.com)')).toBeTruthy()
 expect(document.body.innerHTML).not.toContain('danny@outlook.com')
 expect(report.bidders[0].account_breakdown[0].account_label).toBe(label)
})

it("explains when saved payment counts differ from the checked payment basis", async () => {
 const report=data() as any
 report.bidders[0].payment={amount_cents:1000,application_count:171,paid_at:"2026-10-19T12:00:00Z",note:"",revision:0}
 vi.mocked(request).mockResolvedValue(report);mount()
 fireEvent.click(await screen.findByRole("button",{name:/Edit confirmed payment for Alex/}))
 expect(await screen.findByText("Recorded count: 171; current checked total: 3. Saved payment unchanged.")).toBeTruthy()
 expect(screen.getByLabelText("Before / after deductions").textContent).not.toContain("$10.00")
})
it("explains stale manual amount reviews without changing the saved amount", async () => {
 const report=data() as any
 Object.assign(report.bidders[0],{amount_override_cents:1200,override_application_count:171,calculated_amount_cents:18,payable_amount_cents:1200})
 vi.mocked(request).mockResolvedValue(report);mount()
 fireEvent.click(await screen.findByRole("button",{name:/Edit confirmed payment for Alex/}))
 expect(await screen.findByText("Saved amount reviewed at 171 count; current checked total: 3.")).toBeTruthy()
 expect(screen.getByLabelText("Before / after deductions").textContent).toBe("$0.18 / $0.18")
})

it("shows bidders checked counts only even if a cached payload contains replies", async () => {
 const report=data() as any
 report.daily=[171,0,0,0,0,0,0]
 Object.assign(report.bidders[0],{daily:[171,0,0,0,0,0,0],checked_daily:[76,0,0,0,0,0,0],received_reply_total:171,payment:{amount_cents:456,application_count:171,paid_at:"2026-10-19T12:00:00Z",note:""}})
 report.unallocated_daily=[93,0,0,0,0,0,0]
 vi.mocked(request).mockResolvedValue(report);mount(true)
 const row=(await screen.findByRole("rowheader",{name:/Alex/})).closest("tr")!
 expect(within(row).getAllByRole("cell")[0].textContent).toBe("76")
 expect(screen.queryAllByTitle("Received replies")).toHaveLength(0)
 expect(document.querySelector(".payment-reply-count")).toBeNull()
 expect(screen.queryByText(/received replies/i)).toBeNull()
 expect(screen.queryByText(/Recorded count:/)).toBeNull()
 expect(document.querySelector("tfoot td")!.textContent).toBe("76")
})

it('saves the daily rule explicitly and refreshes net pay while preserving recorded pay', async () => {
 let report:any=data()
 report.deduction_rule={minimum_daily:50,amount_cents:100}
 Object.assign(report.bidders[0],{pay_per_bid:'1',gross_amount_cents:360,calculated_amount_cents:260,deduction_total_cents:100,payment:{amount_cents:900,application_count:3,paid_at:'2026-10-19',note:''}})
 vi.mocked(request).mockImplementation(async()=>report)
 vi.mocked(api.post).mockImplementation(async()=>{report={...report,deduction_rule:{minimum_daily:60,amount_cents:200},bidders:[{...report.bidders[0],calculated_amount_cents:160,deduction_total_cents:200}]};return {ok:true}})
 mount()
 const minimum=await screen.findByLabelText('Minimum daily checked applications') as HTMLInputElement
 expect(minimum.value).toBe('50')
 expect((screen.getByLabelText('Daily deduction (USD)') as HTMLInputElement).value).toBe('1.00')
 fireEvent.change(minimum,{target:{value:'60'}})
 fireEvent.change(screen.getByLabelText('Daily deduction (USD)'),{target:{value:'2.00'}})
 expect(api.post).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'Save deduction rule'}))
 await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/api/payments/deduction-rule',{minimum_daily:60,deduction_amount:'2.00',expected_rule:{minimum_daily:50,amount_cents:100}}))
 await waitFor(()=>expect(screen.getByLabelText('Before / after deductions').textContent).toBe('$3.60 / $1.60'))
 expect(screen.queryByText('$3.60 − $2.00 deductions = $1.60')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:/Edit confirmed payment for Alex/}))
 expect(screen.getByText(/Calculated:.*\$3.60.*− \$2.00 deductions = \$1.60/)).toBeTruthy()
})
it('retains entered rule values on a save failure',async()=>{
 vi.mocked(api.post).mockRejectedValue(new Error('Could not save daily rule'))
 mount()
 fireEvent.change(await screen.findByLabelText('Minimum daily checked applications'),{target:{value:'80'}})
 fireEvent.click(screen.getByRole('button',{name:'Save deduction rule'}))
 expect(await screen.findByRole('alert')).toHaveProperty('textContent','Could not save daily rule')
 expect((screen.getByLabelText('Minimum daily checked applications') as HTMLInputElement).value).toBe('80')
})
it('uses backend eligibility for danger counts including zero-dollar deductions, without marking account details',async()=>{
 const report:any=data();report.deduction_rule={minimum_daily:10,amount_cents:0}
 report.bidders[0].below_minimum_daily=[true,false,false,false,false,false,false]
 report.bidders[0].deduction_daily=[0,0,0,0,0,0,0]
 report.bidders[0].account_breakdown=[{account_id:1,account_label:'Work inbox',daily:[3,0,0,0,0,0,0],checked_daily:[3,0,0,0,0,0,0],total:3}]
 vi.mocked(request).mockResolvedValue(report);mount(true)
 fireEvent.click(await screen.findByRole('button',{name:'Show accounts for Alex'}))
 expect(document.querySelectorAll('.payment-below-minimum')).toHaveLength(1)
 expect(screen.getByTitle('Below daily minimum of 10: $0.00 deduction').textContent).toBe('3')
 expect(screen.getByRole('row',{name:'Alex · Work inbox'}).querySelector('.payment-below-minimum')).toBeNull()
 expect(screen.queryByRole('button',{name:'Save deduction rule'})).toBeNull()
 expect(screen.queryByLabelText('Minimum daily checked applications')).toBeNull()
})

it('preserves a dirty rule across report refetches and requires loading a changed saved rule', async () => {
 let report:any={...data(),deduction_rule:{minimum_daily:50,amount_cents:100}}
 vi.mocked(request).mockImplementation(async()=>report)
 mount()
 const minimum=await screen.findByLabelText('Minimum daily checked applications') as HTMLInputElement
 const amount=screen.getByLabelText('Daily deduction (USD)') as HTMLInputElement
 fireEvent.change(minimum,{target:{value:'80'}})
 fireEvent.change(amount,{target:{value:'3.00'}})
 await act(async()=>{await clients[0].refetchQueries({queryKey:['payments']})})
 expect(minimum.value).toBe('80')
 report={...report,deduction_rule:{minimum_daily:60,amount_cents:200}}
 await act(async()=>{await clients[0].refetchQueries({queryKey:['payments']})})
 expect(minimum.value).toBe('80')
 expect(amount.value).toBe('3.00')
 await waitFor(()=>expect(screen.getByRole('alert').textContent).toContain('changed elsewhere'))
 const save=screen.getByRole('button',{name:'Save deduction rule'}) as HTMLButtonElement
 expect(save.disabled).toBe(true)
 fireEvent.submit(save.closest('form')!)
 expect(api.post).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'Load saved rule'}))
 expect(minimum.value).toBe('60')
 expect(amount.value).toBe('2.00')
 expect(save.disabled).toBe(false)
 fireEvent.change(minimum,{target:{value:'90'}})
 fireEvent.click(save)
 await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/api/payments/deduction-rule',{minimum_daily:90,deduction_amount:'2.00',expected_rule:{minimum_daily:60,amount_cents:200}}))
})
it('syncs a clean rule on report refetch and protects an unseen concurrent update with the base rule',async()=>{
 let report:any={...data(),deduction_rule:{minimum_daily:50,amount_cents:100}}
 vi.mocked(request).mockImplementation(async()=>report)
 mount()
 const minimum=await screen.findByLabelText('Minimum daily checked applications') as HTMLInputElement
 report={...report,deduction_rule:{minimum_daily:60,amount_cents:200}}
 await act(async()=>{await clients[0].refetchQueries({queryKey:['payments']})})
 expect(minimum.value).toBe('60')
 expect((screen.getByLabelText('Daily deduction (USD)') as HTMLInputElement).value).toBe('2.00')
 vi.mocked(api.post).mockRejectedValue(new Error('Daily deduction rule changed elsewhere. Load the saved rule and try again.'))
 fireEvent.change(minimum,{target:{value:'80'}})
 fireEvent.click(screen.getByRole('button',{name:'Save deduction rule'}))
 await screen.findByText('Daily deduction rule changed elsewhere. Load the saved rule and try again.')
 expect(minimum.value).toBe('80')
 expect(api.post).toHaveBeenCalledWith('/api/payments/deduction-rule',{minimum_daily:80,deduction_amount:'2.00',expected_rule:{minimum_daily:60,amount_cents:200}})
})
it('requires reopening a payment draft when the rule changes with unchanged application counts',async()=>{
 let report:any={...data(),deduction_rule:{minimum_daily:50,amount_cents:100}}
 Object.assign(report.bidders[0],{calculated_amount_cents:200,payable_amount_cents:200})
 vi.mocked(request).mockImplementation(async()=>report)
 mount()
 fireEvent.click(await screen.findByRole('button',{name:/Edit confirmed payment for Alex/}))
 const amount=screen.getByLabelText('Amount (USD)') as HTMLInputElement
 expect(amount.value).toBe('2.00')
 report={...report,deduction_rule:{minimum_daily:60,amount_cents:200},bidders:[{...report.bidders[0],calculated_amount_cents:100,payable_amount_cents:100}]}
 await act(async()=>{await clients[0].refetchQueries({queryKey:['payments']})})
 expect(screen.getByRole('alert').textContent).toBe('Deduction rule changed while editing. Close and reopen to review the updated amount.')
 expect((screen.getByRole('button',{name:'Save amount'}) as HTMLButtonElement).disabled).toBe(true)
 expect((screen.getByRole('button',{name:'Record as paid'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.submit(amount.closest('form')!)
 expect(api.post).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'Cancel'}))
 fireEvent.click(screen.getByRole('button',{name:/Edit confirmed payment for Alex/}))
 expect((screen.getByLabelText('Amount (USD)') as HTMLInputElement).value).toBe('1.00')
 fireEvent.click(screen.getByRole('button',{name:'Save amount'}))
 await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/api/payments/bidders/1/amount',{week:'2026-10-12',expected_count:3,expected_rule:{minimum_daily:60,amount_cents:200},expected_calculated_amount_cents:100,amount:'1.00'}))
})
it('requires reopening a payment draft when net pay changes with the same rule and weekly count',async()=>{
 let report:any={...data(),deduction_rule:{minimum_daily:50,amount_cents:100}}
 Object.assign(report.bidders[0],{checked_daily:[50,50,0,0,0,0,0],calculated_amount_cents:1000,payable_amount_cents:1000})
 vi.mocked(request).mockImplementation(async()=>report)
 mount()
 fireEvent.click(await screen.findByRole('button',{name:/Edit confirmed payment for Alex/}))
 report={...report,bidders:[{...report.bidders[0],checked_daily:[49,51,0,0,0,0,0],calculated_amount_cents:900,payable_amount_cents:900}]}
 await act(async()=>{await clients[0].refetchQueries({queryKey:['payments']})})
 await waitFor(()=>expect(screen.getByRole('alert').textContent).toBe('Calculated amount changed while editing. Close and reopen to review the updated amount.'))
 expect((screen.getByRole('button',{name:'Save amount'}) as HTMLButtonElement).disabled).toBe(true)
 expect((screen.getByRole('button',{name:'Record as paid'}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.submit(screen.getByLabelText('Amount (USD)').closest('form')!)
 expect(api.post).not.toHaveBeenCalled()
})
it('starts a fresh payment draft when reopening the same bidder from the row',async()=>{
 let report:any={...data(),deduction_rule:{minimum_daily:50,amount_cents:100}}
 Object.assign(report.bidders[0],{calculated_amount_cents:3000,payable_amount_cents:3000})
 vi.mocked(request).mockImplementation(async()=>report)
 mount()
 fireEvent.click(await screen.findByRole('button',{name:/Edit confirmed payment for Alex/}))
 expect((screen.getByLabelText('Amount (USD)') as HTMLInputElement).value).toBe('30.00')
 report={...report,bidders:[{...report.bidders[0],calculated_amount_cents:2500,payable_amount_cents:2500}]}
 await act(async()=>{await clients[0].refetchQueries({queryKey:['payments']})})
 await waitFor(()=>expect((screen.getByRole('button',{name:'Save amount'}) as HTMLButtonElement).disabled).toBe(true))
 fireEvent.click(screen.getByRole('button',{name:/Edit confirmed payment for Alex/}))
 expect((screen.getByLabelText('Amount (USD)') as HTMLInputElement).value).toBe('25.00')
 expect(screen.queryByRole('alert')).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'Save amount'}))
 await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/api/payments/bidders/1/amount',{week:'2026-10-12',expected_count:3,expected_rule:{minimum_daily:50,amount_cents:100},expected_calculated_amount_cents:2500,amount:'25.00'}))
})

it('hides all payment displays when visibility is disabled',async()=>{
 const report:any=data();report.payment_visible=false
 Object.assign(report.bidders[0],{payment_visible:false,pay_per_bid:'1',gross_amount_cents:360,calculated_amount_cents:260,payment:{amount_cents:900}})
 vi.mocked(request).mockResolvedValue(report);mount(true)
 const row=(await screen.findByRole('rowheader',{name:/Alex/})).closest('tr')!
 expect(within(row).getAllByRole('cell')).toHaveLength(8)
 expect(screen.queryByText('Payments recorded')).toBeNull()
 expect(screen.queryByLabelText('Before / after deductions')).toBeNull()
 expect(document.body.textContent).not.toContain('$')
})
it('shows coworker payment amounts when payment and team visibility are enabled',async()=>{
 const report:any=data();report.other_work_visible=true
 Object.assign(report.bidders[0],{payment_visible:true,gross_amount_cents:360,calculated_amount_cents:260})
 report.bidders.push({...report.bidders[0],id:2,name:'Blair',payment_visible:true,assignments:[],account_breakdown:[]})
 vi.mocked(request).mockResolvedValue(report);mount(true)
 const peer=(await screen.findByRole('rowheader',{name:/Blair/})).closest('tr')!
 expect(within(peer).queryByLabelText('Payment hidden')).toBeNull()
 expect(within(peer).getByLabelText('Before / after deductions').textContent).toBe('$3.60 / $2.60')
 expect(screen.getAllByLabelText('Before / after deductions')).toHaveLength(2)
 expect(screen.queryByRole('button',{name:'By account'})).toBeNull()
})
it('resets a selected coworker when team visibility is revoked',async()=>{
 let report:any=data();report.other_work_visible=true
 report.bidders.push({...report.bidders[0],id:2,name:'Blair',assignments:[],payment_visible:false})
 vi.mocked(request).mockImplementation(async()=>report)
 mount(true)
 await screen.findByRole('rowheader',{name:/Alex/})
 fireEvent.change(screen.getByLabelText('Bidder'),{target:{value:'2'}})
 expect(screen.queryByRole('rowheader',{name:/Alex/})).toBeNull()
 report={...report,other_work_visible:false,bidders:[report.bidders[0]]}
 await act(async()=>{await clients[clients.length-1].invalidateQueries({queryKey:['payments']})})
 expect(await screen.findByRole('rowheader',{name:/Alex/})).toBeTruthy()
 expect((screen.getByLabelText('Bidder') as HTMLSelectElement).value).toBe('')
})
