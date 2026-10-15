import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import App from "@/App"
import { api } from "@/lib/api"

vi.mock("@/pages/sourcing", () => ({ default: () => <h1>Bidder sheets</h1> }))
vi.mock("@/pages/dashboard", () => ({ default: ({ readOnly }: { readOnly: boolean }) => <h1>{readOnly ? "Bidder sheets" : "Admin Dashboard"}</h1> }))

const clients: QueryClient[] = []
beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ok:true,headers:new Headers({"content-type":"application/json"}),json:async()=>({bidders:[{id:1,name:"Alex"}]})})))
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })))
  vi.spyOn(api, "session").mockResolvedValue({ role: null })
  vi.spyOn(api, "bootstrap").mockResolvedValue({ readiness: { model: true, accounts: true, privacy_ack: true, outlook: false }, counts: {}, taxonomy: [], presets: [], last_run: "Never checked", account_count: 0 })
  vi.spyOn(api, "status").mockResolvedValue({ running: false, auto: false, next_in: null, completion_id: 0, message: "", detail: "", ok: true, stage_elapsed: null })
})
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); vi.restoreAllMocks(); vi.unstubAllGlobals() })
function mount(path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime:15_000, refetchOnWindowFocus:false }, mutations: { retry: false } } })
  clients.push(client)
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>)
  return client
}

describe("sign-in and role navigation", () => {
  it("requires sign-in before loading any workspace data", async () => {
    mount("/settings")
    await screen.findByRole("heading", { name: "Sign in" })
    expect(api.bootstrap).not.toHaveBeenCalled()
    expect(screen.queryByRole("navigation")).toBeNull()
  })
  it("signs in a bidder and only shows the read-only Dashboard", async () => {
    vi.spyOn(api, "login").mockImplementation(async () => {
      vi.mocked(api.session).mockResolvedValue({ role: "bidder" })
      return { role: "bidder" }
    })
    mount()
    await screen.findByRole("option", {name:"Alex"})
    fireEvent.change(screen.getByLabelText("Your name"), {target:{value:"1"}})
    fireEvent.change(await screen.findByLabelText("Password"), { target: { value: "bidder" } })
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }))
    await screen.findByRole("heading", { name: "Bidder sheets" })
    expect(api.login).toHaveBeenCalledWith("bidder", "bidder", 1)
    expect(screen.getByRole("link", { name: "Job sourcing" })).toBeTruthy()
    for (const name of ["Triage", "Accounts", "Settings"]) expect(screen.queryByRole("link", { name })).toBeNull()
    expect(screen.queryByRole("button", { name: "Check now" })).toBeNull()
    expect(api.status).not.toHaveBeenCalled()
  })
  it.each(["/", "/accounts", "/settings", "/unknown"])("redirects a signed-in bidder from %s", async (path) => {
    vi.mocked(api.session).mockResolvedValue({ role: "bidder" })
    mount(path)
    await screen.findByRole("heading", { name: "Bidder sheets" })
    expect(screen.queryByRole("link", { name: "Settings" })).toBeNull()
  })
  it("shows all navigation for admin", async () => {
    vi.mocked(api.session).mockResolvedValue({ role: "admin" })
    mount("/dashboard")
    await screen.findByRole("heading", { name: "Admin Dashboard" })
    for (const name of ["Triage", "Dashboard", "Accounts", "Settings"]) expect(screen.getByRole("link", { name })).toBeTruthy()
  })
  it("keeps a failed password attempt on the sign-in form", async () => {
    vi.spyOn(api, "login").mockRejectedValue(new Error("Incorrect role or password."))
    mount()
    await screen.findByRole("option", {name:"Alex"})
    fireEvent.change(screen.getByLabelText("Your name"), {target:{value:"1"}})
    fireEvent.change(await screen.findByLabelText("Password"), { target: { value: "wrong" } })
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }))
    expect((await screen.findByRole("alert")).textContent).toContain("Incorrect role or password")
    expect(api.bootstrap).not.toHaveBeenCalled()
  })
  it("signs out and removes cached private data", async () => {
    vi.mocked(api.session).mockResolvedValue({ role: "bidder" })
    vi.spyOn(api, "post").mockResolvedValue({ ok: true })
    const client = mount("/dashboard")
    await screen.findByRole("heading", { name: "Bidder sheets" })
    client.setQueryData(["reader", 1], { body_html: "private" })
    vi.mocked(api.session).mockResolvedValue({ role: null })
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }))
    await screen.findByRole("heading", { name: "Sign in" })
    await waitFor(() => expect(client.getQueryData(["reader", 1])).toBeUndefined())
  })
})


it("refreshes bidder names when returning after other bidders are enabled", async () => {
  mount("/login")
  await screen.findByRole("option", {name:"Alex"})
  vi.mocked(fetch).mockImplementation(async () => ({ok:true,headers:new Headers({"content-type":"application/json"}),json:async()=>({bidders:[{id:1,name:"Alex"},{id:2,name:"Blair"},{id:3,name:"Casey"},{id:4,name:"Drew"}]})}) as Response)
  await act(async () => { focusManager.setFocused(false); focusManager.setFocused(true) })
  await screen.findByRole("option", {name:"Drew"})
  for(const name of ["Alex","Blair","Casey","Drew"])expect(screen.getByRole("option",{name})).toBeTruthy()
  focusManager.setFocused(undefined)
})
