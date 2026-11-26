import "@testing-library/jest-dom/vitest"
import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"
import { EmptyState, Loading } from "../common"
import { Badge } from "./badge"
import { Button } from "./button"

afterEach(cleanup)

describe("shared visual primitives", () => {
  it("exposes default and explicit button sizes without changing native attributes", () => {
    render(<><Button>Default</Button><Button size="sm" variant="outline" type="button" disabled>Small</Button></>)
    expect(screen.getByRole("button", { name: "Default" })).toHaveAttribute("data-size", "default")
    const small = screen.getByRole("button", { name: "Small" })
    expect(small).toHaveAttribute("data-size", "sm")
    expect(small).toHaveAttribute("data-variant", "outline")
    expect(small).toHaveAttribute("type", "button")
    expect(small).toBeDisabled()
  })

  it("forwards button styling hooks through asChild", () => {
    render(<Button asChild size="icon"><a href="/settings" aria-label="Settings">Settings</a></Button>)
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("data-size", "icon")
  })

  it("exposes badge variants through a stable shared class", () => {
    render(<><Badge>Default badge</Badge><Badge variant="warning" className="custom-badge">Warning badge</Badge></>)
    expect(screen.getByText("Default badge")).toHaveClass("ui-badge")
    expect(screen.getByText("Default badge")).toHaveAttribute("data-variant", "default")
    expect(screen.getByText("Warning badge")).toHaveClass("ui-badge", "custom-badge")
    expect(screen.getByText("Warning badge")).toHaveAttribute("data-variant", "warning")
  })

  it("announces loading with its supplied label", () => {
    render(<Loading label="Loading accounts" />)
    expect(screen.getByRole("status", { name: "Loading accounts" })).toHaveTextContent("Loading accounts")
  })

  it("uses a neutral inbox symbol for an empty state", () => {
    const { container } = render(<EmptyState title="No messages" description="New messages will appear here." />)
    expect(screen.getByRole("heading", { name: "No messages" })).toBeInTheDocument()
    expect(container.querySelector(".empty-mark .lucide-inbox")).toBeInTheDocument()
    expect(container.querySelector(".empty-mark .lucide-check")).toBeNull()
  })
})
