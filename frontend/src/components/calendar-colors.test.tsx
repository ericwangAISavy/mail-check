import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, expect, it, vi } from "vitest"
import { api } from "@/lib/api"
import CalendarColors, { autoCalendarColor, calendarColorOf } from "./calendar-colors"

afterEach(() => { cleanup(); vi.restoreAllMocks() })
const mount = (accounts: Parameters<typeof CalendarColors>[0]["accounts"], client = new QueryClient()) =>
  render(<QueryClientProvider client={client}><CalendarColors accounts={accounts} /></QueryClientProvider>)

it("keeps the automatic color until one is chosen", () => {
  expect(calendarColorOf({ id: 3, label: "a", email: "a" })).toBe(autoCalendarColor(3))
  expect(calendarColorOf({ id: 3, label: "a", email: "a", calendar_color: 7 })).toBe(7)
  expect(calendarColorOf({ id: 3, label: "a", email: "a", calendar_color: 99 })).toBe(autoCalendarColor(3))
  expect(calendarColorOf({ id: 3, label: "a", email: "a", calendar_default_color: 6 })).toBe(6)
})

it("picks a palette color per account and can reset it to automatic", async () => {
  const post = vi.spyOn(api, "post").mockResolvedValue({ ok: true } as never)
  mount([{ id: 1, label: "work@example.com", email: "work@example.com" },
         { id: 2, label: "side@example.com", email: "side@example.com", calendar_color: 6 }])
  fireEvent.click(screen.getByRole("button", { name: "Colors" }))
  const menu = screen.getByRole("dialog", { name: "Account colors" })
  const work = within(menu).getByRole("radiogroup", { name: "Calendar color for work@example.com" })
  expect(within(work).getAllByRole("radio")).toHaveLength(8)
  const cyan = within(work).getByRole("radio", { name: "Cyan" })
  expect(cyan.getAttribute("aria-checked")).toBe("true")
  fireEvent.keyDown(cyan, { key: "End" })
  await waitFor(() => expect(post).toHaveBeenCalledWith("/api/interviews/account-colors/1", { color: 7 }))
  fireEvent.click(within(menu).getByRole("button", { name: "Edit color for side@example.com" }))
  const side = within(menu).getByRole("radiogroup", { name: "Calendar color for side@example.com" })
  expect(within(side).getByRole("radio", { name: "Coral" }).getAttribute("aria-checked")).toBe("true")
  fireEvent.click(within(menu).getByRole("button", { name: "Reset to default" }))
  await waitFor(() => expect(post).toHaveBeenCalledWith("/api/interviews/account-colors/2", { color: null }))
  fireEvent.keyDown(document, { key: "Escape" })
  expect(screen.queryByRole("dialog", { name: "Account colors" })).toBeNull()
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Colors" }))
})

it("updates the calendar optimistically and restores the old color if saving fails", async () => {
  const client = new QueryClient()
  const account = { id: 1, label: "Work", email: "work@example.test", calendar_color: 5 }
  const key = ["interviews", "list", ""]
  client.setQueryData(key, { accounts: [account] })
  let rejectSave: (error: Error) => void = () => {}
  vi.spyOn(api, "post").mockImplementation(() => new Promise((_, reject) => { rejectSave = reject }))
  mount([account], client)
  fireEvent.click(screen.getByRole("button", { name: "Colors" }))
  fireEvent.click(screen.getByRole("radio", { name: "Teal" }))
  await waitFor(() => expect(client.getQueryData(key)).toEqual({ accounts: [{ ...account, calendar_color: 1 }] }))
  rejectSave(new Error("Offline"))
  await waitFor(() => expect(client.getQueryData(key)).toEqual({ accounts: [account] }))
})
