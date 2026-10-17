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
  vi.mocked(request).mockImplementation(async (url) => {
    if (url === "/api/interviews/1") return { event: { id: 1, company: "Meeting with Appian", role: "Engineer", stage: "Technical Interview", status: "Scheduled", display_status: "Scheduled", start_at: "2026-10-18T15:30:00Z", end_at: "2026-10-18T16:30:00Z", timezone: "UTC", meeting_platform: "Zoom", meeting_url: "https://zoom.us/j/123", location: null, organizer_email: "hr@appian.com", participants: ["hr@appian.com"], notes: "Event details from calendar", needs_review: false, manual_fields: [], updated_at: "2026-10-16T12:00:00Z" }, sources: [], stages: ["Technical Interview", "Other"], statuses: ["Scheduled", "Cancelled"] } as never
    if (url === "/api/messages/1") return { message: { pk: 1, subject: "Choose a time", from_name: "Recruiter", from_addr: "hr@appian.com", account_label: "Work", date_utc: "2026-10-16T15:30:00Z", summary: "Recruiter asks for your availability.", open_url: null }, body_html: "<p>Full message details beyond the milestone summary.</p>" } as never
    return report() as never
  })
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
  expect(await screen.findByRole("button", { name: "View event" })).toBeTruthy()
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
it("adds a highlighted Follow up endpoint only for processes whose entire history has passed", async () => {
  const data = report()
  data.processes[0].milestones = [milestone("event:1", 13), milestone("message:1", 14)]
  vi.mocked(request).mockResolvedValue(data)
  mount()
  const reminder = await screen.findByRole("status", { name: "Follow up needed for appian.com" })
  expect(reminder.style.left).toBe("100%")
  expect(screen.getByText("Follow up")).toBeTruthy()
  expect(screen.queryByRole("status", { name: "Follow up needed for Unassigned" })).toBeNull()
  expect(screen.getAllByRole("button", { name: /^(Event|Email):/ })).toHaveLength(3)
})
it("defaults to All and opens the shared interview dialog directly on click", async () => {
  mount()
  const trigger = (await screen.findAllByRole("button", { name: /Event: Technical interview/ }))[0]
  expect(screen.getByRole("button", { name: "All" }).getAttribute("aria-pressed")).toBe("true")
  trigger.focus()
  fireEvent.click(trigger, { detail: 0 })
  const dialog = await screen.findByRole("dialog", { name: "Meeting with Appian" })
  expect(dialog.textContent).toContain("Calendar event details and local corrections.")
  expect(screen.getByRole("button", { name: "Edit details" })).toBeTruthy()
  expect(screen.getByText("Event details from calendar")).toBeTruthy()
  expect(screen.queryByRole("dialog", { name: "Milestone preview" })).toBeNull()
  fireEvent.click(screen.getByRole("button", { name: "Edit details" }))
  expect(screen.getByRole("option", { name: "Other" })).toBeTruthy()
  fireEvent.click(screen.getByRole("button", { name: "Close" }))
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
  expect(document.activeElement).toBe(trigger)
})
it("opens full saved message content in the same dialog shell", async () => {
  mount()
  fireEvent.click(await screen.findByRole("button", { name: /Email: Choose a time/ }))
  const dialog = await screen.findByRole("dialog", { name: "Choose a time" })
  expect(dialog.textContent).toContain("Full message details beyond the milestone summary.")
  expect(screen.getByText("hr@appian.com")).toBeTruthy()
  expect(screen.queryByRole("button", { name: "Edit details" })).toBeNull()
  expect(dialog.classList.contains("interview-dialog")).toBe(true)
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
  fireEvent.mouseEnter(screen.getByRole("button", { name: /Event: Technical interview/ }))
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
it("removes a process and restores it from Removed processes while keeping All selected", async () => {
  const data = { ...report(), removed: [] as { organization: string | null; removed_at: string }[] }
  const original = data.processes[0]
  vi.mocked(request).mockImplementation(async (_url, init) => {
    if (init?.method === "POST") {
      const { removed } = JSON.parse(String(init.body))
      data.processes = removed ? data.processes.filter(process => process.organization !== "appian.com") : [original, ...data.processes]
      data.removed = removed ? [{ organization: "appian.com", removed_at: "2026-10-16" }] : []
      return { ok: true } as never
    }
    return data as never
  })
  mount()
  fireEvent.click(await screen.findByRole("button", { name: "Remove appian.com" }))
  await waitFor(() => expect(screen.queryByRole("heading", { name: "appian.com" })).toBeNull())
  fireEvent.click(screen.getByRole("button", { name: "Removed processes (1)" }))
  fireEvent.click(screen.getByRole("button", { name: "Restore appian.com" }))
  expect(await screen.findByRole("heading", { name: "appian.com" })).toBeTruthy()
  expect(screen.getByRole("button", { name: "All" }).getAttribute("aria-pressed")).toBe("true")
})
it("keeps the process visible when removal fails", async () => {
  mount()
  const remove = await screen.findByRole("button", { name: "Remove appian.com" })
  vi.mocked(request).mockRejectedValueOnce(new Error("Could not remove process"))
  fireEvent.click(remove)
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Could not remove process")
  expect(screen.getByRole("heading", { name: "appian.com" })).toBeTruthy()
})

it("shows every process and full history in All, retaining full history in narrower windows", async () => {
 const data = report()
 data.processes[1].milestones = [milestone("event:old", 10), milestone("message:old", 11)]
 vi.mocked(request).mockResolvedValue(data)
 mount()
 await screen.findByRole("heading", { name: "Unassigned" })
 expect(screen.getByRole("button", { name: "All" }).getAttribute("aria-pressed")).toBe("true")
 expect(screen.getAllByRole("button", { name: /^(Event|Email):/ })).toHaveLength(5)
 expect(screen.queryByRole("button", { name: "Next period" })).toBeNull()
 fireEvent.click(screen.getByRole("button", { name: "Weekly" }))
 expect(screen.queryByRole("heading", { name: "Unassigned" })).toBeNull()
 expect(screen.getAllByRole("button", { name: /^(Event|Email):/ })).toHaveLength(3)
 fireEvent.click(screen.getByRole("button", { name: "All" }))
 expect(screen.getAllByRole("button", { name: /^(Event|Email):/ })).toHaveLength(5)
})

it("creates a named empty process and shows elapsed time on existing processes", async () => {
 const data = report()
 data.processes[0].milestones = [{ ...milestone("event:1", 16), occurred_at: "2026-09-18T12:00:00Z" }, { ...milestone("message:1", 16), occurred_at: "2026-08-01T12:00:00Z" }]
 vi.mocked(request).mockImplementation(async (url, init) => {
  if (url === "/api/interview-processes" && init?.method === "POST") {
   const { name } = JSON.parse(String(init.body))
   data.processes.push({ organization: name, pinned: false, event_count: 0, message_count: 0, next_interview: null, events: [], milestones: [] })
   return { ok: true } as never
  }
  return { ...data, processes: [...data.processes] } as never
 })
 mount()
 await screen.findByText("4 weeks")
 expect(screen.getByRole("heading", { name: "appian.com" }).closest(".process-timeline-card")?.classList.contains("process-age-extended")).toBe(true)
 expect(screen.getByRole("group", { name: "Process age colors" })).toBeTruthy()
 fireEvent.change(screen.getByRole("textbox", { name: "Company or organization name" }), { target: { value: "Acme Labs" } })
 fireEvent.click(screen.getByRole("button", { name: "Add process" }))
 await screen.findByRole("heading", { name: "Acme Labs" })
 expect(screen.getByText("No milestones yet")).toBeTruthy()
 expect(vi.mocked(request)).toHaveBeenCalledWith("/api/interview-processes", expect.objectContaining({ method: "POST", body: JSON.stringify({ name: "Acme Labs" }) }))
})

it("keeps the entered name and reports creation failures", async () => {
 vi.mocked(request).mockImplementation(async (_url, init) => {
  if (init?.method === "POST") throw new Error("An interview process with this name already exists")
  return report() as never
 })
 mount()
 const input = screen.getByRole("textbox", { name: "Company or organization name" })
 fireEvent.change(input, { target: { value: "Acme Labs" } })
 fireEvent.click(screen.getByRole("button", { name: "Add process" }))
 expect((await screen.findByRole("alert")).textContent).toContain("already exists")
 expect((input as HTMLInputElement).value).toBe("Acme Labs")
})

it("sorts pinned first, then oldest by elapsed days, then most calendar events for equal ages", async () => {
 const base = report().processes[0]
 const make = (organization: string, date: string | null, event_count: number, pinned = false) => ({
  ...base, organization, event_count, pinned,
  milestones: date ? [{ ...milestone(`event:${organization}`, 16), occurred_at: date }] : [],
 })
 const data = { processes: [
  make("newer", "2026-10-15T12:00:00Z", 20),
  make("old-fewer", "2026-09-01T10:00:00Z", 2),
  make("future", "2026-11-01T12:00:00Z", 10),
  make("empty", null, 0),
  make("old-more", "2026-09-01T11:00:00Z", 5),
  make("pinned", "2026-10-16T11:00:00Z", 1, true),
 ] }
 vi.mocked(request).mockResolvedValue(data)
 mount()
 await screen.findByRole("heading", { name: "old-more" })
 const names = () => [...document.querySelectorAll('.process-identity h2')].map(el => el.textContent)
 expect(names()).toEqual(["pinned", "old-more", "old-fewer", "newer", "future", "empty"])
 fireEvent.change(screen.getByRole("searchbox", { name: "Find organization" }), { target: { value: "old-" } })
 expect(names()).toEqual(["old-more", "old-fewer"])
})
