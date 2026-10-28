import { afterEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { api, request } from "@/lib/api"
import { Dialog } from "@/components/ui/dialog"
import SourcingFilters from "./sourcing-filters"
vi.mock("@/lib/api",()=>({request:vi.fn(),api:{post:vi.fn()}}))
afterEach(()=>{cleanup();vi.resetAllMocks()})
it("loads company names and preserves the edited list after a save failure",async()=>{
  vi.mocked(request).mockResolvedValue({companies:["Acme"]})
  vi.mocked(api.post).mockRejectedValueOnce(new Error("Could not save"))
  const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})
  render(<QueryClientProvider client={client}><Dialog open><SourcingFilters /></Dialog></QueryClientProvider>)
  const input=await screen.findByDisplayValue("Acme")
  fireEvent.change(input,{target:{value:"Acme\nNew Company\n"}})
  fireEvent.click(screen.getByRole("button",{name:"Save company filters"}))
  expect(await screen.findByRole("alert")).toHaveProperty("textContent","Could not save")
  expect(input).toHaveProperty("value","Acme\nNew Company\n")
  vi.mocked(api.post).mockResolvedValue({companies:["Acme","New Company"]})
  fireEvent.click(screen.getByRole("button",{name:"Save company filters"}))
  expect(await screen.findByText("Company filters saved.")).toBeTruthy()
  expect(api.post).toHaveBeenLastCalledWith("/api/sourcing/filters",{companies:["Acme","New Company"]})
  client.clear()
})
