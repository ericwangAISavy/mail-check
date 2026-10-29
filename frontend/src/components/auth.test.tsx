import {afterEach,beforeEach,expect,it,vi} from "vitest"
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react"
import {QueryClient,QueryClientProvider} from "@tanstack/react-query"
import {MemoryRouter} from "react-router-dom"
import App from "@/App"
import {api,setWorkspaceIdentity} from "@/lib/api"
vi.mock("@/pages/dashboard",()=>({default:()=> <h1>Admin Dashboard</h1>}))
const clients:QueryClient[]=[]
beforeEach(()=>{
  vi.stubGlobal("matchMedia",vi.fn(()=>({matches:false,addEventListener:vi.fn(),removeEventListener:vi.fn()})))
  vi.spyOn(api,"session").mockResolvedValue({role:null})
  vi.spyOn(api,"bootstrap").mockResolvedValue({readiness:{model:true,accounts:true,privacy_ack:true,outlook:false},counts:{},taxonomy:[],presets:[],last_run:"",account_count:0})
  vi.spyOn(api,"status").mockResolvedValue({running:false,auto:false,next_in:null,completion_id:0,message:"",detail:"",ok:true,stage_elapsed:null})
})
afterEach(()=>{cleanup();clients.splice(0).forEach(c=>c.clear());vi.restoreAllMocks();vi.unstubAllGlobals();setWorkspaceIdentity()})
function mount(path="/"){
  const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});clients.push(client)
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App/></MemoryRouter></QueryClientProvider>)
  return client
}
it("offers only owner/admin username sign-in without publishing bidder names",async()=>{
  mount("/settings");await screen.findByRole("heading",{name:"Sign in"})
  expect(screen.getByLabelText("Username")).toHaveProperty("value","owner")
  expect(screen.getByLabelText("Sign in as")).toBeTruthy()
  expect(screen.queryByLabelText("Your name")).toBeNull()
  expect(api.bootstrap).not.toHaveBeenCalled()
})
it("signs an additional admin into their own workspace without owner controls",async()=>{
  const identity={role:"admin" as const,user_id:2,workspace_id:"alice",workspace_name:"Alice workspace",username:"alice",is_owner:false}
  vi.spyOn(api,"login").mockImplementation(async()=>{vi.mocked(api.session).mockResolvedValue(identity);return identity})
  mount();fireEvent.change(await screen.findByLabelText("Username"),{target:{value:"alice"}})
  fireEvent.change(screen.getByLabelText("Password"),{target:{value:"alice-password-123"}})
  fireEvent.click(screen.getByRole("button",{name:"Sign in"}))
  await screen.findByRole("link",{name:"Dashboard"})
  expect(api.login).toHaveBeenCalledWith("admin","alice-password-123",undefined,"alice")
  expect(screen.getByText("Alice workspace")).toBeTruthy()
  expect(screen.queryByRole("link",{name:"Admin management"})).toBeNull()
  expect(screen.queryByRole("link",{name:"Settings"})).toBeNull()
  expect(screen.getByRole("button",{name:"Change password"})).toBeTruthy()
  expect(screen.getByRole("button",{name:"Auto-check off"})).toHaveProperty("disabled",true)
})
it("shows owner controls and explicit workspace identity",async()=>{
  vi.mocked(api.session).mockResolvedValue({role:"admin",is_owner:true,workspace_id:"legacy",workspace_name:"Original workspace"})
  mount("/dashboard");await screen.findByRole("heading",{name:"Admin Dashboard"})
  expect(screen.getByRole("link",{name:"Admin management"})).toBeTruthy()
  expect(screen.getByText("Owner’s original workspace")).toBeTruthy()
})
it("requires new admins to change their temporary password before fetching workspace data",async()=>{
  vi.mocked(api.session).mockResolvedValue({role:"admin",workspace_id:"alice",must_change_password:true})
  vi.spyOn(api,"post").mockImplementation(async()=>{const identity={role:"admin" as const,workspace_id:"alice",must_change_password:false};vi.mocked(api.session).mockResolvedValue(identity);return {session:identity} as never})
  mount();await screen.findByRole("heading",{name:"Choose your password"})
  expect(api.bootstrap).not.toHaveBeenCalled()
  fireEvent.change(screen.getByLabelText("New password"),{target:{value:"new-password-123"}})
  fireEvent.change(screen.getByLabelText("Confirm password"),{target:{value:"new-password-123"}})
  fireEvent.click(screen.getByRole("button",{name:"Save password"}))
  await screen.findByRole("link",{name:"Dashboard"})
  expect(api.post).toHaveBeenCalledWith("/api/auth/password",{password:"new-password-123",role:"admin"})
})
it("does not accept an old bidder identity",async()=>{
  vi.mocked(api.session).mockResolvedValue({role:"bidder",bidder_id:1})
  mount();await screen.findByRole("heading",{name:"Sign in"})
  expect(api.bootstrap).not.toHaveBeenCalled()
})
it("preserves a failed sign-in form and clears private caches on sign-out",async()=>{
  vi.spyOn(api,"login").mockRejectedValue(new Error("Incorrect username or password."))
  const client=mount();fireEvent.change(await screen.findByLabelText("Password"),{target:{value:"wrong"}})
  fireEvent.click(screen.getByRole("button",{name:"Sign in"}))
  expect((await screen.findByRole("alert")).textContent).toContain("Incorrect username")
  vi.mocked(api.login).mockImplementation(async()=>{vi.mocked(api.session).mockResolvedValue({role:"admin"});return {role:"admin"}})
  fireEvent.click(screen.getByRole("button",{name:"Sign in"}));await screen.findByRole("link",{name:"Dashboard"})
  client.setQueryData(["reader",1],{body_html:"private"})
  vi.spyOn(api,"post").mockResolvedValue({ok:true})
  vi.mocked(api.session).mockResolvedValue({role:null})
  fireEvent.click(screen.getByRole("button",{name:"Sign out"}))
  await screen.findByRole("heading",{name:"Sign in"})
  await waitFor(()=>expect(client.getQueryData(["reader",1])).toBeUndefined())
})

it("signs bidders into their admin team with only viewer navigation",async()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>new Response(JSON.stringify({bidders:[{id:9,name:"Dany + alice"}]}),{headers:{"Content-Type":"application/json"}})))
  const identity={role:"bidder" as const,bidder_id:1,workspace_id:"alice",workspace_name:"Alice team",username:"alice",managed:true}
  vi.spyOn(api,"login").mockImplementation(async()=>{vi.mocked(api.session).mockResolvedValue(identity);return identity})
  mount();fireEvent.change(await screen.findByLabelText("Sign in as"),{target:{value:"bidder"}})
  await screen.findByRole("option",{name:"Dany + alice"})
  fireEvent.change(screen.getByLabelText("Your name"),{target:{value:"9"}})
  fireEvent.change(screen.getByLabelText("Password"),{target:{value:"bidder-password-123"}})
  fireEvent.click(screen.getByRole("button",{name:"Sign in"}))
  await screen.findByRole("heading",{name:"Admin Dashboard"})
  expect(api.login).toHaveBeenCalledWith("bidder","bidder-password-123",9,"owner")
  expect(screen.getAllByRole("link").map(link=>link.textContent)).toEqual(["Dashboard","Bidder management"])
  expect(screen.queryByRole("button",{name:"Check now"})).toBeNull()
  expect(screen.queryByRole("button",{name:"Change password"})).toBeNull()
})
