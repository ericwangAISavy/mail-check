import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { request } from "@/lib/api"
import InterviewProcessesPage from "./interview-processes"

vi.mock("@/lib/api", () => ({ request: vi.fn() }))
const clients: QueryClient[] = []
const event = (id: number, reason: string | null = null) => ({ id, company: `Calendar booking ${id}`, stage: "Technical Interview", role: "Engineer", display_status: "Scheduled", start_at: "2027-10-18T15:30:00Z", end_at: "2027-10-18T16:30:00Z", organizer_email: "hr@appian.com", participants: ["hr@appian.com"], account_labels: ["Work"], assignment_reason: reason, organization_domains: reason ? ["appian.com", "rava.com"] : ["appian.com"] })
const report = () => ({ processes: [
  { organization: "appian.com", event_count: 2, next_interview: event(1), events: [event(1), event(2)] },
  { organization: null, event_count: 1, next_interview: null, events: [event(3, "Multiple organization domains")] },
] })
beforeEach(() => { vi.mocked(request).mockResolvedValue(report()) })
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); vi.resetAllMocks() })
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  return render(<QueryClientProvider client={client}><MemoryRouter><InterviewProcessesPage /></MemoryRouter></QueryClientProvider>)
}
it("shows one organization process with its history and an explained Unassigned group", async () => {
  mount()
  expect(await screen.findByRole("heading", { name: "appian.com" })).toBeTruthy()
  expect(screen.getByRole("heading", { name: "Unassigned" })).toBeTruthy()
  expect(screen.getByText("Multiple organization domains")).toBeTruthy()
  expect(screen.getByText("appian.com, rava.com")).toBeTruthy()
  expect(screen.getByRole("heading", { name: "Calendar booking 1 · Engineer" })).toBeTruthy()
  expect(screen.getAllByRole("link", { name: /View event/ }).map(link => link.getAttribute("href"))).toEqual(["/interviews?event=1", "/interviews?event=2", "/interviews?event=3"])
})
it("filters organizations and preserves access to Unassigned", async () => {
  mount()
  await screen.findByRole("heading", { name: "appian.com" })
  fireEvent.change(screen.getByRole("searchbox", { name: "Find organization" }), { target: { value: "RAVA" } })
  expect(screen.queryByRole("heading", { name: "appian.com" })).toBeNull()
  expect(screen.getByRole("heading", { name: "Unassigned" })).toBeTruthy()
})
it("offers collection from the Interview page when no processes exist", async () => {
  vi.mocked(request).mockResolvedValue({ processes: [] })
  mount()
  expect(await screen.findByText("No interview processes yet")).toBeTruthy()
  expect(screen.getByRole("link", { name: "Open Interview calendar" }).getAttribute("href")).toBe("/interviews")
})
it("finds Unassigned by its label without case sensitivity", async () => {
  mount()
  await screen.findByRole("heading", { name: "Unassigned" })
  fireEvent.change(screen.getByRole("searchbox", { name: "Find organization" }), { target: { value: "unassigned" } })
  expect(screen.getByRole("heading", { name: "Unassigned" })).toBeTruthy()
  expect(screen.queryByRole("heading", { name: "appian.com" })).toBeNull()
})
it("shows load errors and retries", async () => {
  vi.mocked(request).mockRejectedValueOnce(new Error("Calendar history unavailable"))
  mount()
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Calendar history unavailable")
  fireEvent.click(screen.getByRole("button", { name: "Try again" }))
  expect(await screen.findByRole("heading", { name: "appian.com" })).toBeTruthy()
})
