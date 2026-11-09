import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom"
import { PageQueryBoundary, PageStateProvider, usePageState, isPageDate } from "./page-state"
beforeEach(() => sessionStorage.clear())
afterEach(() => { cleanup(); vi.restoreAllMocks() })
function Preference() {
 const [value,setValue]=usePageState("test","expanded",false)
 return <button onClick={()=>setValue(v=>!v)}>{String(value)}</button>
}
it("persists across remounts and isolates identities",()=>{
 const mount=(scope:string)=>render(<PageStateProvider scope={scope}><Preference/></PageStateProvider>)
 let view=mount("a");fireEvent.click(screen.getByText("false"));view.unmount()
 view=mount("a");expect(screen.getByText("true")).toBeTruthy();view.unmount()
 mount("b");expect(screen.getByText("false")).toBeTruthy()
})
it("without context behaves as useState",()=>{
 const view=render(<Preference/>);fireEvent.click(screen.getByText("false"));view.unmount()
 render(<Preference/>);expect(screen.getByText("false")).toBeTruthy();expect(sessionStorage.length).toBe(0)
})
it.each(['"wrong type"','{broken','"'+'x'.repeat(9000)+'"'])('ignores invalid stored values (%#)',raw=>{
 sessionStorage.setItem('offerpath.page-state.v1:["a","test","expanded"]',raw)
 render(<PageStateProvider scope="a"><Preference/></PageStateProvider>);expect(screen.getByText("false")).toBeTruthy()
})
it("tolerates blocked reads and quota failures",()=>{
 vi.spyOn(Storage.prototype,"getItem").mockImplementation(()=>{throw Error("blocked")})
 vi.spyOn(Storage.prototype,"setItem").mockImplementation(()=>{throw Error("quota")})
 render(<PageStateProvider scope="a"><Preference/></PageStateProvider>);fireEvent.click(screen.getByText("false"));expect(screen.getByText("true")).toBeTruthy()
})
const mounted:string[]=[]
function Content(){const l=useLocation();mounted.push(l.pathname+l.search);return <output>{l.pathname+l.search}</output>}
function Controls(){const nav=useNavigate();return <>
 <button onClick={()=>nav('/accounts')}>away</button><button onClick={()=>nav('/dashboard')}>return</button>
 <button onClick={()=>nav('/dashboard?q=explicit')}>explicit</button><button onClick={()=>nav('/dashboard')}>clear</button>
 <button onClick={()=>nav(-1)}>back</button><button onClick={()=>nav(1)}>forward</button>
 <PageQueryBoundary><Content/></PageQueryBoundary></>}
function router(entry:string,scope='a'){return render(<MemoryRouter initialEntries={[entry]}><PageStateProvider scope={scope}><Controls/></PageStateProvider></MemoryRouter>)}
it("restores before mounting, strips sensitive params, and honors explicit queries",async()=>{
 router('/dashboard?q=saved&category=a&category=b&token=secret&message=3')
 fireEvent.click(screen.getByText('away'));mounted.length=0;fireEvent.click(screen.getByText('return'))
 await waitFor(()=>expect(screen.getByText('/dashboard?q=saved&category=a&category=b')).toBeTruthy());expect(mounted).not.toContain('/dashboard')
 fireEvent.click(screen.getByText('away'));fireEvent.click(screen.getByText('explicit'));expect(screen.getByText('/dashboard?q=explicit')).toBeTruthy()
})
it("clear persists and history respects explicit empty entries",()=>{
 const view=router('/dashboard?q=saved');fireEvent.click(screen.getByText('clear'));expect(screen.getByText('/dashboard')).toBeTruthy()
 fireEvent.click(screen.getByText('away'));fireEvent.click(screen.getByText('back'));expect(screen.getByText('/dashboard')).toBeTruthy()
 fireEvent.click(screen.getByText('back'));expect(screen.getByText('/dashboard?q=saved')).toBeTruthy()
 fireEvent.click(screen.getByText('forward'));expect(screen.getByText('/dashboard')).toBeTruthy()
 view.unmount();router('/dashboard');expect(screen.getByText('/dashboard')).toBeTruthy()
})
it("reload restores only the same identity",async()=>{
 let view=router('/dashboard?q=saved');view.unmount();view=router('/dashboard')
 await waitFor(()=>expect(screen.getByText('/dashboard?q=saved')).toBeTruthy());view.unmount()
 router('/dashboard','b');expect(screen.getByText('/dashboard')).toBeTruthy()
})
it("switching scope or hook key loads the new default without leaking the previous value",()=>{
 function Switch({name}:{name:string}){const [value,setValue]=usePageState('switch',name,false);return <button onClick={()=>setValue(true)}>{String(value)}</button>}
 const mount=(scope:string,name:string)=><PageStateProvider scope={scope}><Switch name={name}/></PageStateProvider>
 const view=render(mount('a','first'));fireEvent.click(screen.getByText('false'))
 view.rerender(mount('b','first'));expect(screen.getByText('false')).toBeTruthy()
 view.rerender(mount('a','first'));expect(screen.getByText('true')).toBeTruthy()
 view.rerender(mount('a','second'));expect(screen.getByText('false')).toBeTruthy()
 view.rerender(mount('a','first'));expect(screen.getByText('true')).toBeTruthy()
})
it("captures only whitelisted filters from manual triage history updates",async()=>{
 window.history.replaceState(null,'','/')
 const view=router('/')
 window.history.pushState(null,'','/?q=manual&view=all&message=42&reply=1&token=secret')
 window.dispatchEvent(new Event('offerpath:page-query-changed'))
 view.unmount();router('/')
 await waitFor(()=>expect(screen.getByText('/?q=manual&view=all')).toBeTruthy())
 window.history.replaceState(null,'','/')
})
it("keeps preferences across child remounts when browser storage is blocked",()=>{
 vi.spyOn(Storage.prototype,'getItem').mockImplementation(()=>{throw Error('blocked')})
 vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('quota')})
 const mount=(visible:boolean)=><PageStateProvider scope="a">{visible&&<Preference/>}</PageStateProvider>
 const view=render(mount(true));fireEvent.click(screen.getByText('false'));view.rerender(mount(false));view.rerender(mount(true))
 expect(screen.getByText('true')).toBeTruthy()
})
it("applies an optional domain validator to saved primitives",()=>{
 sessionStorage.setItem('offerpath.page-state.v1:["a","domain","tab"]','"unsupported"')
 function Domain(){const [value]=usePageState('domain','tab','all',value=>['all','active'].includes(value));return <output>{value}</output>}
 render(<PageStateProvider scope="a"><Domain/></PageStateProvider>);expect(screen.getByText('all')).toBeTruthy()
})
it("restores calendar mode, date and timezone without event detail or duplicate loss",async()=>{
 let view=router('/interviews?calendar_view=week&calendar_date=2026-11-09&calendar_tz=UTC&calendar_tz=America%2FChicago&event=5&reply=1');view.unmount()
 view=router('/interviews')
 await waitFor(()=>expect(screen.getByText('/interviews?calendar_view=week&calendar_date=2026-11-09&calendar_tz=UTC&calendar_tz=America%2FChicago')).toBeTruthy())
 view.unmount()
})

it("validates bounded real calendar dates",()=>{
 expect(isPageDate("2024-02-29")).toBe(true)
 for(const value of ["2025-02-29","2026-04-31","1970-12-31","2101-01-01","invalid",""])expect(isPageDate(value)).toBe(false)
 expect(isPageDate("",true)).toBe(true)
})
