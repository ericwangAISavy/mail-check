import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { ToastProvider } from "@/components/common"
import { api } from "@/lib/api"
import type { Bootstrap, Settings } from "@/lib/types"
import SettingsPage from "./settings"

vi.mock("@/components/auth", () => ({ useAuth: () => ({ role: "admin", signOut: vi.fn() }) }))
const clients: QueryClient[] = []
let saved: Settings
const bootstrap: Bootstrap = { readiness: { model: true, accounts: true, privacy_ack: false, outlook: false }, counts: {}, taxonomy: [], presets: [], account_count: 1, last_run: "Never checked" }
beforeEach(() => {
  saved = { llm: { base_url: "http://localhost:11434", batch_size: 5, max_body_chars: 1200, timeout_seconds: 60, classification_deadline_seconds: 300, concurrency: 1, num_ctx: 8192, think: false, keep_alive: "5m" }, check: { lookback_days: 2, retain_days: 7 }, watch: { interval_minutes: 10, auto_check: false }, outlook: { client_id: "" }, privacy_ack: false }
  vi.spyOn(api, "settings").mockImplementation(async () => ({ settings: structuredClone(saved), rules: [], categories: [], config_path: "config.toml", db_path: "mail.db" }))
  vi.spyOn(api, "activeModel").mockResolvedValue({ model: "test-model", loaded: true, message: "Ready" })
})
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); vi.restoreAllMocks() })
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  clients.push(client)
  render(<QueryClientProvider client={client}><ToastProvider><SettingsPage bootstrap={bootstrap} /></ToastProvider></QueryClientProvider>)
}
it("does not discard unsaved model settings when privacy acknowledgement is saved", async () => {
  const post = vi.spyOn(api, "post").mockImplementation(async () => { saved.privacy_ack = true; return { message: "Saved" } as any })
  mount()
  fireEvent.change(await screen.findByLabelText("Ollama server URL", { exact: false }), { target: { value: "http://new-server:11434" } })
  fireEvent.click(screen.getByRole("checkbox"))
  await waitFor(() => expect(post).toHaveBeenCalledWith("/api/settings", { privacy_ack: true }))
  await screen.findByText("Privacy acknowledgement saved.")
  expect((screen.getByLabelText("Ollama server URL", { exact: false }) as HTMLInputElement).value).toBe("http://new-server:11434")
  expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(true)
  expect(screen.getAllByRole("button", { name: "Save changes" }).length).toBe(2)
})
it("rolls privacy acknowledgement back if the server rejects it", async () => {
  vi.spyOn(api, "post").mockRejectedValue(new Error("Could not save privacy"))
  mount(); fireEvent.click(await screen.findByRole("checkbox"))
  await screen.findByText("Could not save privacy")
  expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(false)
})
it("preserves edits made while a settings save is in flight", async () => {
  let finish!: (value: unknown) => void
  const post = vi.spyOn(api, "post").mockImplementation(() => new Promise((resolve) => { finish = resolve as typeof finish }))
  mount()
  const input = await screen.findByLabelText("Ollama server URL", { exact: false })
  fireEvent.change(input, { target: { value: "http://first:11434" } })
  fireEvent.click(screen.getAllByRole("button", { name: "Save changes" })[0])
  await waitFor(() => expect(post).toHaveBeenCalledOnce())
  fireEvent.change(input, { target: { value: "http://second:11434" } })
  saved.llm.base_url = "http://first:11434"
  await act(async () => finish({ message: "Settings saved." }))
  await screen.findByText("Settings saved.")
  expect((input as HTMLInputElement).value).toBe("http://second:11434")
})

it("does not test the old saved endpoint while a different model URL is unsaved", async () => {
  const post = vi.spyOn(api, "post")
  mount()
  fireEvent.change(await screen.findByLabelText("Ollama server URL", { exact: false }), { target: { value: "http://unsaved:11434" } })
  expect((screen.getByRole("button", { name: "Test connection" }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.getByText("Save model changes before testing this connection.")).toBeTruthy()
  expect(post).not.toHaveBeenCalled()
})
