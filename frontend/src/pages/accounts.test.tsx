import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { ToastProvider } from "@/components/common"
import { api } from "@/lib/api"
import type { Account } from "@/lib/types"
import AccountsPage from "./accounts"

const clients: QueryClient[] = []
let accounts: Account[] = []
beforeEach(() => {
  accounts = [{ id: 1, label: "personal", email: "me@example.test", provider: "imap", imap_host: "imap.example.test", imap_port: 993, folder: "INBOX", use_ssl: true, enabled: true }]
  vi.spyOn(api, "accounts").mockImplementation(async () => ({ accounts: structuredClone(accounts), outlook_ready: true }))
})
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); vi.restoreAllMocks(); vi.unstubAllGlobals() })
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  clients.push(client)
  render(<QueryClientProvider client={client}><ToastProvider><AccountsPage /></ToastProvider></QueryClientProvider>)
}
const json = (body: unknown) => new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } })

it("tests the selected account and prevents a concurrent toggle", async () => {
  let finish!: (value: unknown) => void
  const post = vi.spyOn(api, "post").mockImplementation(() => new Promise((resolve) => { finish = resolve as typeof finish }))
  mount(); fireEvent.click(await screen.findByRole("button", { name: "Test" }))
  expect(post).toHaveBeenCalledWith("/api/accounts/personal/test")
  expect((screen.getByRole("switch", { name: "Include personal in checks" }) as HTMLButtonElement).disabled).toBe(true)
  await act(async () => finish({ message: "Connection OK." }))
  await screen.findByText("Connection OK.")
  expect((screen.getByRole("switch", { name: "Include personal in checks" }) as HTMLButtonElement).disabled).toBe(false)
})
it("updates inclusion state through the existing account toggle API", async () => {
  const post = vi.spyOn(api, "post").mockImplementation(async () => { accounts[0].enabled = false; return { message: "Paused personal." } as any })
  mount(); fireEvent.click(await screen.findByRole("switch", { name: "Include personal in checks" }))
  await screen.findByText("Paused", { exact: true })
  expect(post).toHaveBeenCalledWith("/api/accounts/personal/toggle?enabled=false")
  expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("false")
})
it("respects removal confirmation and refreshes the account list", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
  const post = vi.spyOn(api, "post").mockImplementation(async () => { accounts = []; return { message: "Removed personal." } as any })
  mount(); fireEvent.click(await screen.findByTitle("Remove personal"))
  expect(post).not.toHaveBeenCalled()
  confirm.mockReturnValue(true)
  fireEvent.click(screen.getByTitle("Remove personal"))
  await screen.findByText("One inbox at a time")
  expect(post).toHaveBeenCalledWith("/api/accounts/personal/delete")
})
it("ignores stale provider lookups after the address changes", async () => {
  let first!: (value: Response) => void
  const fetch = vi.fn((url: string) => url.includes("gmail") ? new Promise<Response>((resolve) => { first = resolve }) : Promise.resolve(json({ preset: { host: "imap.mail.yahoo.com", port: 993, note: "Yahoo" } })))
  vi.stubGlobal("fetch", fetch)
  mount(); fireEvent.click(await screen.findByRole("button", { name: "Connect mailbox" }))
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "me@gmail.com" } })
  await waitFor(() => expect(fetch).toHaveBeenCalledOnce())
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "me@yahoo.com" } })
  await waitFor(() => expect((screen.getByLabelText("IMAP host") as HTMLInputElement).value).toBe("imap.mail.yahoo.com"))
  await act(async () => first(json({ preset: { host: "imap.gmail.com", port: 993, note: "Gmail" } })))
  expect((screen.getByLabelText("IMAP host") as HTMLInputElement).value).toBe("imap.mail.yahoo.com")
})
it("does not overwrite a manually edited server with a delayed preset", async () => {
  let finish!: (value: Response) => void
  const fetch = vi.fn(() => new Promise<Response>((resolve) => { finish = resolve }))
  vi.stubGlobal("fetch", fetch)
  mount(); fireEvent.click(await screen.findByRole("button", { name: "Connect mailbox" }))
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "me@gmail.com" } })
  await waitFor(() => expect(fetch).toHaveBeenCalledOnce())
  fireEvent.change(screen.getByLabelText("IMAP host"), { target: { value: "custom.example.test" } })
  await act(async () => finish(json({ preset: { host: "imap.gmail.com", port: 993, note: "Gmail" } })))
  expect((screen.getByLabelText("IMAP host") as HTMLInputElement).value).toBe("custom.example.test")
})
