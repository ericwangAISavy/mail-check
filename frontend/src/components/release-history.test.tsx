import {afterEach,expect,it} from "vitest"
import {cleanup,fireEvent,render,screen,within} from "@testing-library/react"
import ReleaseHistory from "./release-history"
import releases from "../../../releases.json"

afterEach(cleanup)
it("opens the current version and readable update history",async()=>{
  render(<ReleaseHistory />)
  fireEvent.click(screen.getByRole("button",{name:`Version ${releases[0].version} — view update history`}))
  expect(await screen.findByRole("dialog")).toBeTruthy()
  expect(screen.getByRole("heading",{name:"Version history"})).toBeTruthy()
  expect(screen.getByText(/Isolated admin workspaces/)).toBeTruthy()
  fireEvent.click(screen.getByRole("button",{name:"Close"}))
  expect(screen.queryByRole("dialog")).toBeNull()
})

it("shows category labels and distinguishes the latest release",async()=>{
  render(<ReleaseHistory />)
  fireEvent.click(screen.getByRole("button",{name:`Version ${releases[0].version} — view update history`}))
  expect(screen.getByRole("group",{name:"Update categories"})).toBeTruthy()
  expect(screen.getByText("Latest")).toBeTruthy()
  const baseline=screen.getByRole("article",{name:"Version 2.1.0"})
  expect(within(baseline).getByText("Performance")).toBeTruthy()
  expect(within(baseline).getAllByRole("listitem").length).toBe(releases.find(release=>release.version==="2.1.0")!.changes.length)
})
