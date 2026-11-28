import { expect, it } from "vitest"
import { chicagoDayStart, defaultView, nextQueueBoundary, queueCounts, visibleRows, QUEUE_LIFETIME_MS, QUEUE_WARNING_MS, type Snapshot } from "./sourcing"

const HOUR = 3600_000
const NOW = Date.UTC(2026, 10, 26, 18) // 12:00 in Chicago
const DAY_START = chicagoDayStart(NOW)
const cell = (value: string) => ({ value, display: value, style: {}, formula: false, link: "", version: 0 })
const columns = [
  { id: "c", title: "Company", kind: "company" as const, width: 200 },
  { id: "l", title: "Job link", kind: "link" as const, width: 300 },
  { id: "k", title: "Check", kind: "check" as const, width: 76 },
]
/** [company, checked, created (ms)] per row; null company is a blank input row. */
function sheet(rows: [string | null, boolean, number | null][]): Snapshot {
  return {
    id: 1, title: "Work", revision: "1", structure_revision: 1, refreshed_at: 0, columns,
    row_ids: ["", ...rows.map((_, i) => `r${i}`)],
    row_dates: [null, ...rows.map(() => "2026-11-20")],
    row_created: [null, ...rows.map(([, , created]) => created == null ? null : created / 1000)],
    rows: [[cell("Company"), cell("Job link"), cell("Check")], ...rows.map(([company, done]) => [cell(company ?? ""), cell(company ? `https://jobs.test/${company}` : ""), cell(done ? "true" : "")])],
    properties: { gridProperties: { rowCount: rows.length + 1, columnCount: 3 } },
  }
}
const queue = (status: "todo" | "completed" | "expired" | "all", focus: "new" | "carryover" | "expiring" | null = null) => ({ ...defaultView, queue: { status, focus, now: NOW, dayStart: DAY_START } })
const names = (snapshot: Snapshot, rows: number[]) => rows.filter(r => r > 0).map(r => String(snapshot.rows[r][0].value)).filter(Boolean)

const fixture = sheet([
  ["Today", false, NOW - HOUR],                                       // new today
  ["Yesterday", false, NOW - 30 * HOUR],                              // carryover
  ["Expiring", false, NOW - QUEUE_LIFETIME_MS + QUEUE_WARNING_MS - 1], // 48h minus 1ms left
  ["Expired", false, NOW - QUEUE_LIFETIME_MS],                        // exactly 168h
  ["DoneOld", true, NOW - 40 * 24 * HOUR],                            // completed long ago: never expires
  [null, false, null],                                                // blank input row
])

it("keeps unfinished jobs from earlier days in To do, oldest and expiring first", () => {
  expect(names(fixture, visibleRows(fixture, [], queue("todo")))).toEqual(["Expiring", "Yesterday", "Today"])
})

it("sorts by exact availability and keeps missing stamps last in both directions", () => {
  const data = sheet([["Unknown", false, null], ["Newest", false, NOW - HOUR], ["Oldest", false, NOW - 30 * HOUR], ["Same time", false, NOW - HOUR]])
  const view = queue("todo")
  expect(names(data, visibleRows(data, [], { ...view, queue: { ...view.queue, ageOrder: "asc" } }))).toEqual(["Oldest", "Newest", "Same time", "Unknown"])
  expect(names(data, visibleRows(data, [], { ...view, queue: { ...view.queue, ageOrder: "desc" } }))).toEqual(["Newest", "Same time", "Oldest", "Unknown"])
})

it("separates completed, expired and all history", () => {
  expect(names(fixture, visibleRows(fixture, [], queue("completed")))).toEqual(["DoneOld"])
  expect(names(fixture, visibleRows(fixture, [], queue("expired")))).toEqual(["Expired"])
  expect(names(fixture, visibleRows(fixture, [], queue("all")))).toEqual(["Today", "Yesterday", "Expiring", "Expired", "DoneOld"])
})

it("counts To do as New today plus Carryover, with Expiring soon inside To do", () => {
  const counts = queueCounts(fixture, [], NOW, DAY_START)
  expect(counts).toEqual({ todo: 3, new_today: 1, carryover: 2, expiring: 1, completed: 1, expired: 1, all: 5 })
  expect(names(fixture, visibleRows(fixture, [], queue("todo", "new")))).toEqual(["Today"])
  expect(names(fixture, visibleRows(fixture, [], queue("todo", "carryover")))).toEqual(["Expiring", "Yesterday"])
  expect(names(fixture, visibleRows(fixture, [], queue("todo", "expiring")))).toEqual(["Expiring"])
})

it("moves a job to Completed the moment it is checked, before saving", () => {
  const counts = queueCounts(fixture, [{ row: 2, col: 2, value: "true" }], NOW, DAY_START)
  expect([counts.todo, counts.carryover, counts.completed]).toEqual([2, 1, 2])
})

it("keeps a just-checked job visible in To do when asked, so rows do not jump", () => {
  const changes = [{ row: 2, col: 2, value: "true" }]
  const view = { ...queue("todo"), queue: { ...queue("todo").queue, keep: new Set(["r1"]) } }
  expect(names(fixture, visibleRows(fixture, changes, view))).toContain("Yesterday")
  expect(names(fixture, visibleRows(fixture, changes, queue("todo")))).not.toContain("Yesterday")
})

it("treats a pasted job that is not saved yet as new today", () => {
  const counts = queueCounts(fixture, [{ row: 6, col: 0, value: "Pasted" }], NOW, DAY_START)
  expect([counts.todo, counts.new_today]).toEqual([4, 2])
})

it("a history day narrows the view without changing the default queue", () => {
  const dated = { ...fixture, row_dates: [null, "2026-11-26", "2026-11-25", "2026-11-20", "2026-11-19", "2026-10-17", null] }
  expect(names(dated, visibleRows(dated, [], { ...queue("todo"), day: "2026-11-25" }))).toEqual(["Yesterday"])
  expect(names(dated, visibleRows(dated, [], queue("todo")))).toHaveLength(3)
})

it("wakes at the next boundary and finds Chicago midnight across daylight saving", () => {
  // At noon the next change is the midnight rollover (New today becomes Carryover)...
  expect(nextQueueBoundary(fixture, [], NOW, DAY_START)).toBe(DAY_START + 24 * HOUR + 60_000)
  // ...and late in the evening it is the moment "Expiring" reaches 168 hours.
  const late = DAY_START + 23 * HOUR, expiring = sheet([["Expiring", false, late - QUEUE_LIFETIME_MS + 30 * 60_000]])
  expect(nextQueueBoundary(expiring, [], late, DAY_START)).toBe(late + 30 * 60_000)
  expect(new Date(chicagoDayStart(Date.UTC(2026, 2, 8, 18))).toISOString()).toBe("2026-03-08T06:00:00.000Z") // spring forward: midnight was CST
  expect(new Date(chicagoDayStart(Date.UTC(2026, 2, 9, 18))).toISOString()).toBe("2026-03-09T05:00:00.000Z")
  expect(new Date(DAY_START).toISOString()).toBe("2026-11-26T06:00:00.000Z")
})

it("wakes once at the real midnight on the 25-hour autumn day, not an hour early", () => {
  const evening = Date.UTC(2026, 10, 1, 23) // 1 Nov 2026, clocks fell back at 2:00; 17:00 CST
  const start = chicagoDayStart(evening)
  expect(new Date(start).toISOString()).toBe("2026-11-01T05:00:00.000Z") // midnight was still CDT
  expect(new Date(nextQueueBoundary(sheet([]), [], evening, start)).toISOString()).toBe("2026-11-02T06:01:00.000Z")
})

it("keeps a just-checked job by its id even after the sheet is re-ordered", () => {
  const reordered = { ...fixture, row_ids: ["", "r1", "r0", ...fixture.row_ids.slice(3)], rows: [fixture.rows[0], fixture.rows[2], fixture.rows[1], ...fixture.rows.slice(3)], row_created: [null, fixture.row_created![2], fixture.row_created![1], ...fixture.row_created!.slice(3)] }
  const checked = { ...reordered, rows: reordered.rows.map((row, r) => r === 1 ? [row[0], row[1], cell("true")] : row) }
  const view = { ...queue("todo"), queue: { ...queue("todo").queue, keep: new Set(["r1"]) } }
  expect(names(checked, visibleRows(checked, [], view))).toContain("Yesterday")
})

it("ages saved jobs from their sourcing day when the server has not stamped them yet", () => {
  // An older server sends no row_created: the job dated 2026-11-15 is 11 days old, not new.
  const unstamped = { ...sheet([["Old", false, null], ["Recent", false, null]]), row_created: undefined, row_dates: [null, "2026-11-15", "2026-11-26"] }
  const counts = queueCounts(unstamped, [], NOW, DAY_START)
  expect([counts.todo, counts.new_today, counts.expired]).toEqual([1, 1, 1])
  expect(names(unstamped, visibleRows(unstamped, [], queue("expired")))).toEqual(["Old"])
})

it("shows a job link as its site", async () => {
  const { jobSite } = await import("./sourcing")
  expect(jobSite("https://www.boards.greenhouse.io/acme/jobs/123?gh_src=x")).toBe("boards.greenhouse.io")
  expect(jobSite("not a url")).toBe("not a url")
})
