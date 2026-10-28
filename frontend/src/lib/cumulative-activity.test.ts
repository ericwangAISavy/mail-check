import { expect, it } from "vitest"
import { cumulativeActivity } from "./cumulative-activity"
it("accumulates bidders independently, carries quiet intervals, and preserves source counts", () => {
  const points = [{counts:{a:3,b:1}}, {counts:{a:0,b:2}}, {counts:{a:4,b:0}}]
  expect(cumulativeActivity(points,["a","b"]).map(p=>p.counts)).toEqual([{a:3,b:1},{a:3,b:3},{a:7,b:3}])
  expect(points[2].counts).toEqual({a:4,b:0})
})
it("fills missing account counts and resets for each new period", () => {
  expect(cumulativeActivity([{counts:{a:2}}, {counts:{b:3}}],["a","b"]).map(p=>p.counts)).toEqual([{a:2,b:0},{a:2,b:3}])
  expect(cumulativeActivity([{counts:{a:1}}],["a"])[0].counts.a).toBe(1)
})
