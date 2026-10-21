import { useState } from "react"
import { afterEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { request } from "@/lib/api"
import BidderActivity from "./bidder-activity"
vi.mock("@/lib/api", () => ({request: vi.fn()}))
vi.mock("recharts", () => ({ResponsiveContainer: ({children}: any) => <div>{children}</div>, LineChart: ({children}: any) => <div>{children}</div>, Line: () => null, CartesianGrid: () => null, Tooltip: () => null, XAxis: () => null, YAxis: () => null}))
const clients: QueryClient[] = []
afterEach(() => {cleanup(); clients.forEach(c => c.clear()); clients.length = 0; vi.resetAllMocks()})
function payload() {
  const hourly = Array(24).fill(0); hourly[10] = 5
  return {dates: ["2026-10-12"], timezone: "America/Chicago", tracking_since: "2026-10-12T12:00:00+00:00", check_count: 2,
    bidders: [{id:1,name:"Alex",hourly,daily:[5],heatmap:[hourly],new_checks:5,active_half_hours:1,last_detected:"2026-10-12T15:00:00+00:00",latest_check:{at:"2026-10-12T16:00:00+00:00",new_checks:0,checked_total:5},previous_check:{at:"2026-10-12T15:00:00+00:00",new_checks:5,checked_total:5}},
    {id:2,name:"Blair",hourly:hourly.map(n => n ? 2 : 0),daily:[2],heatmap:[hourly.map(n => n ? 2 : 0)],new_checks:2,active_half_hours:1,last_detected:null,latest_check:null,previous_check:null}],
    timeline:[{at:"2026-10-12T15:00:00+00:00",source:"global-check",counts:{"1":5,"2":2}},{at:"2026-10-12T16:00:00+00:00",source:"global-check",counts:{"1":0,"2":0}}]}
}
function mount() {
  const client = new QueryClient({defaultOptions:{queries:{retry:false}}}); clients.push(client)
  function Harness() {const [selected,setSelected] = useState(""); return <BidderActivity week="2026-10-12" selected={selected} onSelect={setSelected}/>}
  render(<QueryClientProvider client={client}><Harness/></QueryClientProvider>)
}
it("filters graph and heatmap by bidder and displays quiet-check changes", async () => {
  vi.mocked(request).mockResolvedValue(payload()); mount()
  await screen.findByRole("button", {name:"Alex"})
  expect(screen.getByText("New links detected", {selector:"span"}).querySelector("strong")!.textContent).toBe("7")
  expect(screen.getByLabelText("2026-10-12, 10am: 7 newly checked links")).toBeTruthy()
  expect(screen.getByText("-100%")).toBeTruthy()
  fireEvent.click(screen.getByRole("button", {name:"Alex"}))
  expect(screen.getByText("New links detected", {selector:"span"}).querySelector("strong")!.textContent).toBe("5")
  expect(screen.queryByText("Blair", {selector:"th"})).toBeNull()
  expect(screen.getByLabelText("2026-10-12, 10am: 5 newly checked links")).toBeTruthy()
  fireEvent.click(screen.getByRole("button", {name:"By day"}))
  expect(screen.getByRole("button", {name:"By day"}).getAttribute("aria-pressed")).toBe("true")
})
it("does not invent historical activity when no checks are recorded", async () => {
  vi.mocked(request).mockResolvedValue({...payload(), bidders:[],timeline:[],check_count:0}); mount()
  expect(await screen.findByText("Activity history starts here")).toBeTruthy()
  expect(screen.getByText(/not exact working hours/)).toBeTruthy()
})
it("offers a retry when activity cannot be loaded", async () => {
  vi.mocked(request).mockRejectedValue(new Error("Offline")); mount()
  await screen.findByRole("button", {name:"Retry activity"})
  vi.mocked(request).mockResolvedValue(payload())
  fireEvent.click(screen.getByRole("button", {name:"Retry activity"}))
  expect(await screen.findByRole("button", {name:"Alex"})).toBeTruthy()
})

it("switches to account trends and filters an account without mixing bidder controls", async () => {
  const base = payload()
  const accounts = [
    {...base.bidders[0], id:10, name:"shared@outlook.com"},
    {...base.bidders[1], id:20, name:"other@outlook.com"},
  ]
  vi.mocked(request).mockResolvedValue({...base,accounts,account_timeline:base.timeline.map(p => ({...p,counts:{"10":p.counts["1"],"20":p.counts["2"]}}))})
  mount(); await screen.findByRole("button", {name:"Alex"})
  fireEvent.click(screen.getByRole("button", {name:"By account"}))
  expect(await screen.findByRole("button", {name:"shared@outlook.com"})).toBeTruthy()
  expect(screen.getByRole("columnheader", {name:"Account"})).toBeTruthy()
  fireEvent.click(screen.getByRole("button", {name:"shared@outlook.com"}))
  expect(screen.getByText("New links detected", {selector:"span"}).querySelector("strong")!.textContent).toBe("5")
  expect(screen.queryByText("other@outlook.com", {selector:"th"})).toBeNull()
  expect(screen.getByLabelText("2026-10-12, 10am: 5 newly checked links")).toBeTruthy()
  fireEvent.click(screen.getByRole("button", {name:"By bidder"}))
  expect(await screen.findByRole("button", {name:"Alex"})).toBeTruthy()
})
