import { afterEach, expect, it, vi } from "vitest"
import { cleanup, render, screen, within } from "@testing-library/react"
import { ToastProvider } from "@/components/common"
import { PersonalSettingsPage } from "./settings"
import { api } from "@/lib/api"

vi.mock("@/components/auth", () => ({ useAuth: () => ({ role: "admin", signOut: vi.fn() }) }))
afterEach(() => { cleanup(); vi.restoreAllMocks() })

it("shows an admin only their own sign-in, appearance and alerts", () => {
  const get = vi.spyOn(api, "settings")
  render(<ToastProvider><PersonalSettingsPage /></ToastProvider>)
  const nav = screen.getByRole("navigation", { name: "Settings sections" })
  expect(within(nav).getAllByRole("link").map(link => link.textContent)).toEqual(["Sign-in", "Appearance", "Notifications"])
  for (const heading of ["Sign-in passwords", "Appearance", "Notifications"]) expect(screen.getByRole("heading", { name: heading })).toBeTruthy()
  for (const hidden of ["Model", "Checking", "Outlook", "Local rules", "Privacy & local data"]) expect(screen.queryByRole("heading", { name: hidden })).toBeNull()
  expect(screen.queryByRole("button", { name: /Save changes|All saved/ })).toBeNull()
  expect(get).not.toHaveBeenCalled()
})

it("never asks the server for workspace settings", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { headers: { "content-type": "application/json" } }))
  render(<ToastProvider><PersonalSettingsPage /></ToastProvider>)
  await new Promise(resolve => setTimeout(resolve, 50))
  const urls = fetch.mock.calls.map(([url]) => String(url))
  expect(urls.filter(url => /\/api\/(settings|rules|autocheck)/.test(url))).toEqual([])
  expect(screen.getByText(/Workspace settings are managed by the owner/)).toBeTruthy()
})
