import { describe, expect, it } from "vitest"
import { interval, points, type Outcomes, type Profile } from "./profile-outcomes"

const profile: Profile = { id: 1, label: "one", duplicates: 0, unmatched: { interview: 0, rejection: 0 }, daily: {
  "2026-09-01": { applications: 1, windows: { "14": { eligible: 1, interview: 1, rejection: 0, answered: 1 } } },
  "2026-09-02": { applications: 99, windows: { "14": { eligible: 99, interview: 9, rejection: 30, answered: 39 } } },
  "2026-09-25": { applications: 200, windows: { "14": { eligible: 0, interview: 0, rejection: 0, answered: 0 } } },
} }
const data: Outcomes = { version: 1, history_since: "2026-09-01", timezone: "America/Chicago", mature_through: { "14": "2026-09-20" }, accounts: [profile] }
describe("application outcome trends", () => {
  it("weights rates by application volume and excludes immature cohorts", () => {
    const rows = points(data, 14, "Week", true, "interview", false)
    expect(rows.at(-1)?.s0).toBe(10)
    expect(rows.at(-1)?.counts[0].eligible).toBe(100)
    expect(rows.every(row => row.through <= "2026-09-20")).toBe(true)
  })
  it("keeps empty periods as gaps, suppresses small samples by default", () => {
    const rows = points(data, 14, "Day", false, "interview", false)
    expect(rows[0].s0).toBeNull()
    expect(rows[2].s0).toBeNull()
    expect(points(data, 14, "Day", false, "interview", true)[0].s0).toBe(100)
  })
  it("computes bounded Wilson intervals including zero and complete success", () => {
    expect(interval(0, 0)).toBeNull()
    expect(interval(0, 20)?.[0]).toBe(0)
    expect(interval(20, 20)?.[1]).toBe(100)
    expect(interval(10, 100)?.[0]).toBeCloseTo(5.52, 1)
    expect(interval(10, 100)?.[1]).toBeCloseTo(17.44, 1)
  })
})
