import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import { AppErrorBoundary } from "./app-error-boundary"

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe("AppErrorBoundary", () => {
  it("shows a recovery action instead of leaving the app blank after a render crash", () => {
    function BrokenPage(): never { throw new Error("render failed") }
    vi.spyOn(console, "error").mockImplementation(() => undefined)

    render(<AppErrorBoundary><BrokenPage /></AppErrorBoundary>)

    expect(screen.getByRole("alert").textContent).toContain("couldn’t open")
    expect(screen.getByRole("button", { name: /reload/i })).toBeTruthy()
    const details = screen.getByText("Technical details").closest("details")!
    expect(details.textContent).toContain("Error: render failed")
    expect(details.textContent).toContain("BrokenPage")
  })
})

it('handles a failed page-module download as a recoverable loading error',async()=>{
 function MissingPage():never{throw new TypeError('Failed to fetch dynamically imported module: https://app.offerpath.bid/assets/dashboard-old.js')}
 vi.spyOn(console,'error').mockImplementation(()=>undefined)
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('Bad gateway',{status:502})))
 render(<AppErrorBoundary><MissingPage/></AppErrorBoundary>)
 expect(await screen.findByRole('heading',{name:'This page couldn’t finish loading'})).toBeTruthy()
 expect(screen.getByRole('button',{name:/Retry loading page|Checking connection/})).toBeTruthy()
 expect(screen.getByText('Technical details').closest('details')!.textContent).toContain('dashboard-old.js')
})
