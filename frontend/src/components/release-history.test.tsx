import {afterEach,expect,it} from "vitest"
import {cleanup,fireEvent,render,screen} from "@testing-library/react"
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
