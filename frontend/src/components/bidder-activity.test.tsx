import { useState } from "react"
import { afterEach, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { request } from "@/lib/api"
import BidderActivity from "./bidder-activity"
vi.mock("@/lib/api", () => ({request: vi.fn()}))
const probe = vi.hoisted(() => ({tooltip: null as any, lines: [] as string[]}))
vi.mock("recharts", () => ({ResponsiveContainer: ({children}: any) => <div>{children}</div>, LineChart: ({children, data}: any) => <div data-testid="chart-points" data-points={JSON.stringify(data)}>{children}</div>, Line: ({type}: any) => {probe.lines.push(type); return null}, ReferenceLine: ({x}: any) => <div data-testid="now-marker" data-time={x}/>, CartesianGrid: () => null, Tooltip: (props: any) => {probe.tooltip = props.labelFormatter; return null}, XAxis: () => null, YAxis: () => null}))
const clients: QueryClient[] = []
afterEach(() => {cleanup(); clients.forEach(c => c.clear()); clients.length = 0; vi.resetAllMocks(); vi.restoreAllMocks(); vi.useRealTimers()})
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
it("filters graph and heatmap by bidder without redundant cards or summary table", async () => {
  vi.mocked(request).mockResolvedValue(payload()); mount()
  await screen.findByRole("button", {name:"Alex"})
  expect(screen.queryByText("Links with confirmation time")).toBeNull()
  expect(screen.queryByText("Busiest confirmation hour")).toBeNull()
  expect(screen.queryByText("Checks recorded this week")).toBeNull()
  expect(screen.queryByRole("columnheader",{name:"Latest / previous check"})).toBeNull()
  expect(screen.getByLabelText("2026-10-12, 10am: 7 matched checked links")).toBeTruthy()
  expect(screen.queryByText("-100%")).toBeNull()
  fireEvent.click(screen.getByRole("button", {name:"Alex"}))
  expect(screen.queryByText("Blair", {selector:"th"})).toBeNull()
  expect(screen.getByLabelText("2026-10-12, 10am: 5 matched checked links")).toBeTruthy()
  fireEvent.click(screen.getByRole("button", {name:"By day"}))
  expect(screen.getByRole("button", {name:"By day"}).getAttribute("aria-pressed")).toBe("true")
})
it("does not invent historical activity when no checks are recorded", async () => {
  vi.mocked(request).mockResolvedValue({...payload(), bidders:[],timeline:[],check_count:0}); mount()
  expect(await screen.findByText("No confirmations in this workday")).toBeTruthy()
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
  fireEvent.click(screen.getByRole("button", {name:"shared@outlook.com"}))
  expect(screen.queryByText("other@outlook.com", {selector:"th"})).toBeNull()
  expect(screen.getByLabelText("2026-10-12, 10am: 5 matched checked links")).toBeTruthy()
  fireEvent.click(screen.getByRole("button", {name:"By bidder"}))
  expect(await screen.findByRole("button", {name:"Alex"})).toBeTruthy()
})


it("separates quarter-hour confirmations, exact workday runs and weekly totals", async () => {
  const base = payload()
  const workday = {date:"2026-10-12",start:"2026-10-12T11:00:00Z",end:"2026-10-13T11:00:00Z",
    confirmations:[{at:"2026-10-12T15:15:00Z",source:"confirmation",counts:{"1":3,"2":1}}],
    runs:[{at:"2026-10-13T10:59:12Z",source:"global-check",counts:{"1":2,"2":0}}],account_confirmations:[],account_runs:[]}
  vi.mocked(request).mockResolvedValue({...base,workday}); mount()
  await screen.findByRole("button", {name:"Alex"})
  expect(screen.getByTestId("chart-points").getAttribute("data-points")).toContain("15:15")
  expect(screen.getByText(/^15-minute intervals/)).toBeTruthy()
  fireEvent.click(screen.getByRole("button", {name:"Check runs"}))
  expect(screen.getByTestId("chart-points").getAttribute("data-points")).toContain("10:59:12")
  expect(screen.getByText(/Every recorded run/)).toBeTruthy()
  fireEvent.click(screen.getByRole("button", {name:"By day"}))
  expect(screen.getByTestId("chart-points").getAttribute("data-points")).toContain('"1":5')
  expect(screen.queryByLabelText("Activity workday")).toBeNull()
  fireEvent.click(screen.getByRole("button", {name:"Check runs"}))
  fireEvent.change(screen.getByLabelText("Activity workday"), {target:{value:"2026-10-13"}})
  expect(vi.mocked(request).mock.calls.some(([url]) => String(url).includes("day=2026-10-13"))).toBe(true)
})


it("formats tooltip dates safely during mode changes and uses connected lines", async () => {
  const base = payload()
  vi.mocked(request).mockResolvedValue({...base,workday:{date:"2026-10-12",start:"2026-10-12T11:00:00Z",end:"2026-10-13T11:00:00Z",confirmations:base.timeline,runs:base.timeline,account_runs:[],account_confirmations:[]}})
  mount(); await screen.findByRole("button", {name:"Alex"})
  expect(() => probe.tooltip("2026-10-12", [])).not.toThrow()
  expect(probe.tooltip("stale label", [{payload:{at:"2026-10-12T15:00:00Z",stamp:Date.parse("2026-10-12T15:00:00Z")}}])).toContain("10:00:00 AM")
  for (const value of [undefined,null,"",NaN,"invalid"]) expect(() => probe.tooltip(value, [])).not.toThrow()
  expect(probe.lines.every(type => type === "linear")).toBe(true)
  fireEvent.click(screen.getByRole("button", {name:"By day"}))
  expect(probe.tooltip("stale", [{payload:{at:"2026-10-12"}}])).toBe("Oct 12")
  expect(() => probe.tooltip(123, [])).not.toThrow()
})


it("places a live current-time marker precisely within the Chicago workday", async () => {
  vi.useFakeTimers({toFake:["setInterval","clearInterval"]})
  const clock = vi.spyOn(Date,"now").mockReturnValue(Date.parse("2026-10-12T15:23:45Z"))
  const base = payload()
  vi.mocked(request).mockResolvedValue({...base,workday:{date:"2026-10-12",start:"2026-10-12T11:00:00Z",end:"2026-10-13T11:00:00Z",confirmations:base.timeline,runs:base.timeline,account_runs:[],account_confirmations:[]}})
  mount(); await screen.findByRole("button", {name:"Alex"})
  expect(screen.getByTestId("now-marker").getAttribute("data-time")).toBe(String(Date.parse("2026-10-12T15:23:45Z")))
  expect(screen.getByText(/Now · Oct 12, 10:23:45 AM CDT/)).toBeTruthy()
  clock.mockReturnValue(Date.parse("2026-10-12T15:23:46Z"))
  act(() => {vi.advanceTimersByTime(1000)})
  expect(screen.getByTestId("now-marker").getAttribute("data-time")).toBe(String(Date.parse("2026-10-12T15:23:46Z")))
  fireEvent.click(screen.getByRole("button", {name:"Check runs"}))
  expect(screen.getByTestId("now-marker")).toBeTruthy()
  fireEvent.click(screen.getByRole("button", {name:"By day"}))
  expect(screen.queryByTestId("now-marker")).toBeNull()
  clock.mockReturnValue(Date.parse("2026-10-13T11:00:00Z"))
  act(() => {vi.advanceTimersByTime(1000)})
  fireEvent.click(screen.getByRole("button", {name:"Confirmation time"}))
  expect(screen.queryByTestId("now-marker")).toBeNull()
})
