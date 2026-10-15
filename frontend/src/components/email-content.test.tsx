import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import { EmailContent } from "./email-content"

beforeEach(() => { vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} }) })
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
