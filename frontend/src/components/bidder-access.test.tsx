import {afterEach,expect,it,vi} from "vitest"
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react"
import {BidderAccess} from "./bidder-access"
afterEach(cleanup)
it("enables an account with an admin-set password and clears the password after saving",async()=>{
 const write=vi.fn().mockResolvedValue({ok:true})
 render(<BidderAccess bidderId={3} name="Dany" enabled={false} busy={false} write={write}/>)
 fireEvent.change(screen.getByLabelText("Bidder password"),{target:{value:"new-bidder-password"}})
 fireEvent.click(screen.getByRole("button",{name:"Enable bidder access"}))
 await waitFor(()=>expect(write).toHaveBeenCalledWith("/api/auth/bidders/3/password",{password:"new-bidder-password",enabled:true}))
 await waitFor(()=>expect(screen.getByLabelText("Bidder password")).toHaveProperty("value",""))
})
it("allows disabling access without requiring a new password",async()=>{
 const write=vi.fn().mockResolvedValue({ok:true})
 render(<BidderAccess bidderId={3} name="Dany" enabled busy={false} write={write}/>)
 fireEvent.click(screen.getByRole("button",{name:"Disable bidder access"}))
 await waitFor(()=>expect(write).toHaveBeenCalledWith("/api/auth/bidders/3/password",{enabled:false}))
 expect(screen.getByRole("button",{name:"Reset bidder password"})).toBeTruthy()
})
