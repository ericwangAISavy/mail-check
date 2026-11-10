import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { setWorkspaceIdentity } from "@/lib/api"
import { ToastProvider, useToast } from "./common"

let notify: ReturnType<typeof useToast>
function Source() { notify = useToast(); return null }
afterEach(() => { cleanup(); setWorkspaceIdentity(); vi.restoreAllMocks() })
describe("toast identity scope", () => {
  it.each(["workspace", "username", "relogin"])("discards old actions and late notifications after %s changes", (change) => {
    setWorkspaceIdentity("a", "alice")
    render(<ToastProvider><Source /></ToastProvider>)
    const oldNotify = notify
    const undo = vi.fn()
    act(() => notify("Moved to Completed.", "success", { label: "Undo", run: undo }))
    const oldButton = screen.getByRole("button", { name: "Undo" })
    act(() => {
      if (change === "workspace") setWorkspaceIdentity("b", "alice")
      else if (change === "username") setWorkspaceIdentity("a", "bob")
      else { setWorkspaceIdentity(); setWorkspaceIdentity("a", "alice") }
      fireEvent.click(oldButton)
      oldNotify("Late completion", "success", { label: "Undo", run: undo })
    })
    expect(undo).not.toHaveBeenCalled()
    expect(screen.queryByText("Moved to Completed.")).toBeNull()
    expect(screen.queryByText("Late completion")).toBeNull()
    act(() => notify("Current completion"))
    expect(screen.getByText("Current completion")).toBeTruthy()
  })
})
