import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { EmailContent } from "./email-content"

const resizes: (() => void)[] = []
beforeEach(() => { resizes.length = 0; vi.stubGlobal("ResizeObserver", class { constructor(callback: () => void) { resizes.push(callback) } observe() {} disconnect() {} }) })
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it("isolates original email layout, adapts colors, and blocks active and remote content", () => {
  const html = '<table cellpadding="20"><tr><td style="font-size:18px">Hello <b>applicant</b></td></tr></table>'
  render(<EmailContent html={html} />)
  const frame = screen.getByTitle("Original email content")
  expect(frame.tagName).toBe("IFRAME")
  expect(frame.getAttribute("srcdoc")).toContain(html)
  expect(frame.getAttribute("srcdoc")).toContain("default-src 'none'")
  expect(frame.getAttribute("srcdoc")).toContain("img-src data:")
  expect(frame.getAttribute("sandbox")).not.toContain("allow-scripts")
  expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer")
})

it("keeps viewport-height emails stable instead of expanding on each resize", () => {
  render(<EmailContent html="<div style='min-height:100vh'>Email content</div>" />)
  const frame = screen.getByTitle("Original email content") as HTMLIFrameElement
  const body = frame.contentDocument!.body
  Object.defineProperty(body, "scrollHeight", { configurable: true, get: () => Number.parseInt(frame.style.height || "80") + 10 })
  vi.spyOn(body, "getBoundingClientRect").mockImplementation(() => ({ height: Number.parseInt(frame.style.height || "80") }) as DOMRect)
  fireEvent.load(frame)
  const initial = frame.style.height
  for (let i = 0; i < 5; i++) resizes[resizes.length - 1]()
  expect(frame.style.height).toBe(initial)
  expect(Number.parseInt(initial)).toBeGreaterThanOrEqual(80)
})
