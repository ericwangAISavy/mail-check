import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { ToastProvider } from "@/components/common"
import { PasswordSettings } from "./settings"
import { api } from "@/lib/api"

const mocks = vi.hoisted(() => ({ signOut: vi.fn() }))
vi.mock("@/components/auth", () => ({ useAuth: () => ({ role: "admin", signOut: mocks.signOut }) }))
beforeEach(() => { mocks.signOut.mockResolvedValue(undefined) })
afterEach(() => { cleanup(); vi.restoreAllMocks(); mocks.signOut.mockReset() })
const mount = () => render(<ToastProvider><PasswordSettings /></ToastProvider>)
function fill(password: string, confirmation = password) {
  fireEvent.change(screen.getByLabelText("New password"), { target: { value: password } })
  fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: confirmation } })
  fireEvent.click(screen.getByRole("button", { name: "Update password" }))
}
it("rejects mismatched passwords without calling the server", async () => {
  const post = vi.spyOn(api, "post")
  mount(); fill("one", "two")
  expect((await screen.findByRole("alert")).textContent).toContain("do not match")
  expect(post).not.toHaveBeenCalled()
})
it("updates guest passwords without signing out the admin", async () => {
  const post = vi.spyOn(api, "post").mockResolvedValue({ message: "Guest password updated." })
  mount(); fill("new guest password")
  await waitFor(() => expect(post).toHaveBeenCalledWith("/api/auth/password", { role: "guest", password: "new guest password" }))
  await waitFor(() => expect((screen.getByLabelText("New password") as HTMLInputElement).value).toBe(""))
  expect(mocks.signOut).not.toHaveBeenCalled()
})
it("signs out after updating the admin password", async () => {
  vi.spyOn(api, "post").mockResolvedValue({ message: "Admin password updated." })
  mount()
  fireEvent.change(screen.getByLabelText("Account role"), { target: { value: "admin" } })
  fill("new admin password")
  await waitFor(() => expect(mocks.signOut).toHaveBeenCalledOnce())
})
