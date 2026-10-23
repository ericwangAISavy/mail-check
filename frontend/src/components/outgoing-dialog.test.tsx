import {afterEach,expect,it,vi} from "vitest"
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react"
import {api,request} from "@/lib/api"
import {ToastProvider} from "@/components/common"
import OutgoingDialog from "./outgoing-dialog"
vi.mock("@/lib/api",()=>({api:{post:vi.fn()},request:vi.fn()}))
afterEach(()=>{cleanup();vi.resetAllMocks()})
it("shows SMTP suggestions and tests settings only after the user saves",async()=>{
 vi.mocked(request).mockResolvedValue({host:"smtp.gmail.com",port:465,security:"ssl",username:"me@gmail.com"})
 vi.mocked(api.post).mockResolvedValue({ok:true})
 const saved=vi.fn(),close=vi.fn()
 render(<ToastProvider><OutgoingDialog open onOpenChange={close} label="Personal" onSaved={saved}/></ToastProvider>)
 await screen.findByDisplayValue("smtp.gmail.com")
 expect(api.post).not.toHaveBeenCalled()
 fireEvent.change(screen.getByLabelText("SMTP host"),{target:{value:"smtp.example.test"}})
 fireEvent.click(screen.getByRole("button",{name:"Test & save"}))
 await waitFor(()=>expect(api.post).toHaveBeenCalledWith("/api/accounts/Personal/outgoing",{host:"smtp.example.test",port:465,security:"ssl",username:"me@gmail.com"}))
 await waitFor(()=>expect(saved).toHaveBeenCalledOnce())
 expect(close).toHaveBeenCalledWith(false)
})
