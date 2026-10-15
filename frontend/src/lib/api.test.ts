import { afterEach, describe, expect, it, vi } from "vitest"
import { request, triageParams } from "./api"

describe("triageParams", () => {
  it("defaults invalid views and ranges while preserving supported filters", () => {
    const result = triageParams("?view=sent&days=180&account=work&category=assessment")
    expect(result.get("view")).toBe("queue")
    expect(result.get("days")).toBe("30")
    expect(result.get("account")).toBe("work")
    expect(result.get("category")).toBe("assessment")
  })

  it("preserves the all mail and completed views", () => {
    expect(triageParams("?view=all&days=7").get("view")).toBe("all")
    expect(triageParams("?view=completed&days=90").get("days")).toBe("90")
  })

  it("ignores empty filters", () => {
    const result = triageParams("?view=queue&account=&category=")
    expect(result.has("account")).toBe(false)
    expect(result.has("category")).toBe(false)
  })
})


afterEach(() => vi.unstubAllGlobals())
it("shows FastAPI validation fields and messages for invalid form values", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: [
    { loc: ["body", "amount"], msg: "Decimal input should have no more than 2 decimal places" },
    { loc: ["query", "week"], msg: "Input should be a valid date" },
  ] }), { status: 422, headers: { "Content-Type": "application/json" } })))
  await expect(request("/api/payments")).rejects.toThrow("amount: Decimal input should have no more than 2 decimal places; week: Input should be a valid date")
})
it("shows string detail errors without replacing them with a generic failure", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "That record was not found" }), { status: 404, headers: { "Content-Type": "application/json" } })))
  await expect(request("/api/example")).rejects.toThrow("That record was not found")
})
