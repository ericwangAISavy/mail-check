import {afterEach,beforeEach,expect,it,vi} from "vitest"
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react"
import {QueryClient,QueryClientProvider} from "@tanstack/react-query"
import {MemoryRouter} from "react-router-dom"
import App from "@/App"
import {api,setWorkspaceIdentity} from "@/lib/api"
vi.mock("@/pages/triage",()=>({default:()=> <h1>Team inbox</h1>}))
vi.mock("@/pages/dashboard",()=>({default:()=> <h1>Admin Dashboard</h1>}))
const clients:QueryClient[]=[]
beforeEach(()=>{
  vi.stubGlobal("fetch",vi.fn(async()=>new Response(JSON.stringify({admins:[{username:"owner"},{username:"alice"}]}),{headers:{"Content-Type":"application/json"}})))
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
  await screen.findByRole("option",{name:"owner"})
  expect(screen.getByLabelText("Username").tagName).toBe("SELECT")
  expect(screen.getByLabelText("Username")).toHaveProperty("value","owner")
  expect(screen.getByLabelText("Sign in as")).toBeTruthy()
  expect(screen.queryByLabelText("Your name")).toBeNull()
  expect(api.bootstrap).not.toHaveBeenCalled()
})
it("signs an additional admin into their own workspace without owner controls",async()=>{
  const identity={role:"admin" as const,user_id:2,workspace_id:"alice",workspace_name:"Alice workspace",username:"alice",is_owner:false}
  vi.spyOn(api,"login").mockImplementation(async()=>{vi.mocked(api.session).mockResolvedValue(identity);return identity})
  mount();await screen.findByRole("option",{name:"alice"});fireEvent.change(screen.getByLabelText("Username"),{target:{value:"alice"}})
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
  const client=mount();await screen.findByRole("option",{name:"owner"});fireEvent.change(await screen.findByLabelText("Password"),{target:{value:"wrong"}})
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
  expect(screen.getAllByRole("link").map(link=>link.textContent)).toEqual(["Dashboard","Job sourcing","Bidder management"])
  expect(screen.queryByRole("button",{name:"Check now"})).toBeNull()
  expect(screen.queryByRole("button",{name:"Change password"})).toBeNull()
})

it("keeps admin sign-in disabled when the account directory cannot load and supports retry",async()=>{
  const fetch=vi.fn().mockRejectedValue(new Error("offline"))
  vi.stubGlobal("fetch",fetch)
  mount()
  await screen.findByText("Could not load admins.")
  expect(screen.getByLabelText("Username").tagName).toBe("SELECT")
  expect(screen.getByRole("button",{name:"Sign in"})).toHaveProperty("disabled",true)
  fetch.mockResolvedValue(new Response(JSON.stringify({admins:[{username:"owner"}]}),{headers:{"Content-Type":"application/json"}}))
  fireEvent.click(screen.getByRole("button",{name:"Try again"}))
  await screen.findByRole("option",{name:"owner"})
  await waitFor(()=>expect(screen.getByRole("button",{name:"Sign in"})).toHaveProperty("disabled",false))
})

it("blocks bidder submission while the bidder directory is unavailable",async()=>{
  vi.stubGlobal("fetch",vi.fn(async(input:RequestInfo|URL)=>{
    if(String(input).includes("/api/auth/admins"))return new Response(JSON.stringify({admins:[{username:"owner"}]}),{headers:{"Content-Type":"application/json"}})
    throw new Error("offline")
  }))
  mount();fireEvent.change(await screen.findByLabelText("Sign in as"),{target:{value:"bidder"}})
  await screen.findByText("Could not load bidders.")
  expect(screen.getByRole("button",{name:"Sign in"})).toHaveProperty("disabled",true)
})

it("locks account selection and credentials while signing in",async()=>{
  vi.spyOn(api,"login").mockReturnValue(new Promise(()=>{}))
  mount();await screen.findByRole("option",{name:"owner"})
  fireEvent.change(screen.getByLabelText("Password"),{target:{value:"secret"}})
  fireEvent.click(screen.getByRole("button",{name:"Sign in"}))
  await screen.findByRole("button",{name:"Please wait…"})
  expect(screen.getByLabelText("Sign in as")).toHaveProperty("disabled",true)
  expect(screen.getByLabelText("Username")).toHaveProperty("disabled",true)
  expect(screen.getByLabelText("Password")).toHaveProperty("disabled",true)
})
