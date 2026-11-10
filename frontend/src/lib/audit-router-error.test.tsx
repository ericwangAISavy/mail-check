import { afterEach, expect, it, vi } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import type { ReactNode } from "react"
const entry = vi.hoisted(() => ({ tree: null as ReactNode }))
vi.mock("react-dom/client", () => ({ default: { createRoot: () => ({ render: (tree: ReactNode) => { entry.tree = tree } }) } }))
vi.mock("@/App", async () => {
 const { lazy, Suspense } = await import("react")
 const Page = lazy(() => Promise.reject(new Error("Failed to fetch dynamically imported module")))
 return { default: () => <Suspense fallback={<p>Loading page…</p>}><Page /></Suspense> }
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
it("recovers from a rejected lazy page import through the production router boundary", async () => {
 vi.spyOn(console, "error").mockImplementation(() => undefined)
 vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false })))
 await import("@/main")
 render(entry.tree)
 expect(await screen.findByRole("button", { name: /Retry loading page|Checking connection/ })).toBeTruthy()
 expect(screen.getByRole("heading", { name: "This page couldn’t finish loading" })).toBeTruthy()
 expect(screen.queryByText("Unexpected Application Error!")).toBeNull()
})
