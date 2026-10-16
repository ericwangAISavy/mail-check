import { expect, it } from "vitest"
import { dateInput, periodWindow, movePeriod, positionMilestones } from "./process-timeline"

it("uses calendar boundaries for daily, Monday weekly, monthly and two-month windows", () => {
  for (const [period, first, last] of [["daily", "2026-10-16", "2026-10-17"], ["weekly", "2026-10-12", "2026-10-19"], ["monthly", "2026-10-01", "2026-11-01"], ["two-months", "2026-10-01", "2026-12-01"]] as const) {
    const window = periodWindow("2026-10-16", period)
    expect(dateInput(window.start)).toBe(first)
    expect(dateInput(window.end)).toBe(last)
  }
})
it("moves windows across leap years and year boundaries without month overflow", () => {
  expect(movePeriod("2028-01-31", "monthly", 1)).toBe("2028-02-01")
  expect(movePeriod("2026-12-20", "two-months", 1)).toBe("2027-02-01")
  expect(movePeriod("2026-10-16", "weekly", -1)).toBe("2026-10-05")
})
it("excludes the end boundary and gives simultaneous milestones equal sequential spacing", () => {
  const window = periodWindow("2026-10-16", "daily")
  const start = window.start.toISOString(), end = window.end.toISOString()
  const layout = positionMilestones([{ id: "one", occurred_at: start }, { id: "two", occurred_at: start }, { id: "end", occurred_at: end }], window)
  expect(layout.map(item => [item.milestone.id, item.position])).toEqual([["one", 0], ["two", 1]])
})
it("places the first and last milestones at the endpoints regardless of time gaps", () => {
  const window = periodWindow("2026-10-16", "monthly")
  const layout = positionMilestones([
    { id: "last", occurred_at: "2026-10-30T10:00:00Z" },
    { id: "first", occurred_at: "2026-10-02T10:00:00Z" },
    { id: "middle", occurred_at: "2026-10-02T10:01:00Z" },
  ], window)
  expect(layout.map(item => [item.milestone.id, item.position])).toEqual([["first", 0], ["middle", .5], ["last", 1]])
})
it("places a single milestone at the beginning", () => {
  const layout = positionMilestones([{ id: "one", occurred_at: "2026-10-16T10:00:00Z" }], periodWindow("2026-10-16", "monthly"))
  expect(layout[0].position).toBe(0)
})
