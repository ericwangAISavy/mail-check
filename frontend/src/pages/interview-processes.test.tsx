import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { request } from "@/lib/api"
import InterviewProcessesPage from "./interview-processes"

vi.mock("@/lib/api", () => ({ request: vi.fn() }))
const clients: QueryClient[] = []
const milestone = (id: string, day: number, reason: string | null = null) => ({ id, kind: id.startsWith("message") ? "message" : "event", occurred_at: `2026-10-${day}T15:30:00Z`, title: id.startsWith("message") ? "Choose a time" : "Technical interview", summary: "Recruiter asks for your availability.", status: "Scheduled", sender: "hr@appian.com", account_labels: ["Work"], href: id.startsWith("message") ? null : "/interviews?event=1", assignment_reason: reason, organization_domains: reason ? ["appian.com", "rava.com"] : ["appian.com"] })
const report = () => ({ processes: [
  { organization: "appian.com", pinned: false, event_count: 2, message_count: 1, next_interview: null, events: [], milestones: [milestone("event:1", 18), milestone("message:1", 16), milestone("event:2", 25)] },
  { organization: null, pinned: false, event_count: 1, message_count: 0, next_interview: null, events: [], milestones: [milestone("event:3", 18, "Multiple organization domains")] },
] })
beforeEach(() => {
  vi.mocked(request).mockResolvedValue(report())
  vi.spyOn(Date, "now").mockReturnValue(new Date("2026-10-16T12:00:00Z").getTime())
})
afterEach(() => { cleanup(); clients.splice(0).forEach(client => client.clear()); vi.resetAllMocks(); vi.restoreAllMocks() })
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  clients.push(client)
  return render(<QueryClientProvider client={client}><MemoryRouter><InterviewProcessesPage /></MemoryRouter></QueryClientProvider>)
}
it("shows compact milestones and reveals summaries on hover and keyboard focus", async () => {
  mount()
  await screen.findByRole("heading", { name: "appian.com" })
  expect(screen.queryByText("Recruiter asks for your availability.")).toBeNull()
  fireEvent.mouseEnter(screen.getByRole("button", { name: /Email: Choose a time/ }))
  expect(await screen.findByRole("dialog", { name: "Milestone preview" })).toBeTruthy()
  expect(screen.getByText("Recruiter asks for your availability.")).toBeTruthy()
  fireEvent.keyDown(document, { key: "Escape" })
  expect(screen.queryByRole("dialog")).toBeNull()
  fireEvent.focus(screen.getAllByRole("button", { name: /Event: Technical interview/ })[0])
  expect(await screen.findByRole("link", { name: "View event" })).toHaveProperty("href", expect.stringContaining("/interviews?event=1"))
})
it("selects processes by period and retains their entire history", async () => {
  mount()
  await screen.findByRole("heading", { name: "appian.com" })
  fireEvent.click(screen.getByRole("button", { name: "Daily" }))
  expect(screen.queryAllByRole("button", { name: /Event: Technical interview/ })).toHaveLength(2)
  expect(screen.queryByRole("heading", { name: "Unassigned" })).toBeNull()
  expect(screen.getByRole("button", { name: /Email: Choose a time/ })).toBeTruthy()
  fireEvent.click(screen.getByRole("button", { name: "Weekly" }))
  expect(screen.getAllByRole("button", { name: /Event: Technical interview/ })).toHaveLength(3)
  fireEvent.click(screen.getByRole("button", { name: "Next period" }))
  expect(screen.getAllByRole("button", { name: /Event: Technical interview/ })).toHaveLength(2)
  fireEvent.click(screen.getByRole("button", { name: "Two months" }))
  expect(screen.getAllByRole("button", { name: /Event: Technical interview/ })).toHaveLength(3)
})
it("distinguishes event/email shapes and before/in/after-window colors", async () => {
  const data = report()
  data.processes[0].milestones.push(milestone("message:old", 1))
  vi.mocked(request).mockResolvedValue(data)
  mount()
  await screen.findByRole("heading", { name: "appian.com" })
  fireEvent.click(screen.getByRole("button", { name: "Weekly" }))
  const events = screen.getAllByRole("button", { name: /Event: Technical interview/ })
  expect(events.some(el => el.classList.contains("milestone-future"))).toBe(true)
  const emails = screen.getAllByRole("button", { name: /Email: Choose a time/ })
  expect(emails.every(el => el.classList.contains("milestone-message"))).toBe(true)
  expect(emails.some(el => el.classList.contains("milestone-past"))).toBe(true)
  expect(emails.some(el => el.classList.contains("milestone-present"))).toBe(true)
  fireEvent.click(screen.getByRole("button", { name: "Two weeks" }))
  expect(screen.getAllByRole("button", { name: /Event: Technical interview/ }).every(el => !el.classList.contains("milestone-future"))).toBe(true)
})
it("keeps pins as priority without including processes outside the selected window", async () => {
  const data = report(); data.processes[1].pinned = true
  vi.mocked(request).mockResolvedValue(data)
  mount()
  await screen.findByRole("heading", { name: "Unassigned" })
  fireEvent.click(screen.getByRole("button", { name: "Daily" }))
  expect(screen.queryByRole("heading", { name: "Unassigned" })).toBeNull()
})
it("moves focus into activated previews and restores the milestone on Escape", async () => {
  mount()
  const trigger = (await screen.findAllByRole("button", { name: /Event: Technical interview/ }))[0]
  trigger.focus()
  fireEvent.click(trigger, { detail: 0 })
  const preview = await screen.findByRole("dialog", { name: "Milestone preview" })
  expect(document.activeElement).toBe(preview)
  fireEvent.scroll(window)
  expect(screen.getByRole("dialog", { name: "Milestone preview" })).toBe(preview)
  fireEvent.keyDown(document, { key: "Escape" })
  expect(screen.queryByRole("dialog")).toBeNull()
  expect(document.activeElement).toBe(trigger)
})
it("pins a process persistently, reorders rows and reports write failures", async () => {
  const data = report()
  vi.mocked(request).mockImplementation(async (_url, init) => {
    if (init?.method === "POST") { data.processes[1].pinned = true; return { ok: true } as never }
    return data as never
  })
  mount()
  fireEvent.click(await screen.findByRole("button", { name: "Pin Unassigned" }))
  await waitFor(() => expect(screen.getByRole("button", { name: "Unpin Unassigned" })).toBeTruthy())
  expect(screen.getAllByRole("heading", { level: 2, name: /^(appian.com|Unassigned)$/ })[0].textContent).toBe("Unassigned")
  expect(request).toHaveBeenCalledWith("/api/interview-processes/pin", expect.objectContaining({ method: "POST", body: JSON.stringify({ organization: null, pinned: true }) }))
  vi.mocked(request).mockRejectedValueOnce(new Error("Could not save pin"))
  fireEvent.click(screen.getByRole("button", { name: "Unpin Unassigned" }))
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Could not save pin")
})
it("searches ambiguous domains and previews why the event is Unassigned", async () => {
  mount()
  await screen.findByRole("heading", { name: "appian.com" })
  fireEvent.change(screen.getByRole("searchbox", { name: "Find organization" }), { target: { value: "RAVA" } })
  expect(screen.queryByRole("heading", { name: "appian.com" })).toBeNull()
  fireEvent.click(screen.getByRole("button", { name: /Event: Technical interview/ }))
  expect(await screen.findByText("Multiple organization domains")).toBeTruthy()
})
it("offers collection for an empty workspace and retries load failures", async () => {
  vi.mocked(request).mockRejectedValueOnce(new Error("Calendar history unavailable")).mockResolvedValue({ processes: [] })
  mount()
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Calendar history unavailable")
  fireEvent.click(screen.getByRole("button", { name: "Try again" }))
  expect(await screen.findByText("No interview processes yet")).toBeTruthy()
  expect(screen.getByRole("link", { name: "Open Interview calendar" }).getAttribute("href")).toBe("/interviews")
})
