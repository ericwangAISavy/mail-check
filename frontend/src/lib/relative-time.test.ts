import { expect, it } from "vitest"
import { parseStamp, timeAgo } from "./relative-time"
const base = new Date("2026-11-18T12:00:00Z").getTime()
const ago = (seconds: number) => timeAgo(new Date(base - seconds * 1000), base)
it("describes freshness briefly", () => {
  expect(ago(3)).toBe("just now")
  expect(ago(20)).toBe("20 seconds ago")
  expect(ago(60)).toBe("1 min ago")
  expect(ago(7 * 60 + 5)).toBe("7 min ago")
  expect(ago(3600)).toBe("1 hour ago")
  expect(ago(5 * 3600)).toBe("5 hours ago")
  expect(ago(-30)).toBe("just now")  // clock skew never reads as the future
})
it("rejects invalid stamps", () => {
  expect(parseStamp("bad")).toBeNull()
  expect(parseStamp(null)).toBeNull()
  expect(parseStamp("2026-11-18T12:00:00Z")?.toISOString()).toBe("2026-11-18T12:00:00.000Z")
})
