import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { createMemoryRouter, RouterProvider, useNavigate } from "react-router-dom"
import SourcingDraftGuard from "./sourcing-draft-guard"
const NativeRequest=Request
beforeEach(()=>vi.stubGlobal('Request',class extends NativeRequest {constructor(input:RequestInfo|URL,init?:RequestInit){super(input,{...init,signal:undefined})}}))
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
function Editor(){const navigate=useNavigate();return <><SourcingDraftGuard dirty saving={false}/><button onClick={()=>navigate(-1)}>Browser back</button></>}
it('warns before browser Back replaces a dirty editor with same-path search results',async()=>{
 const router=createMemoryRouter([{path:'/sourcing',element:<Editor/>}],{initialEntries:['/sourcing?q=Acme','/sourcing?row=1'],initialIndex:1})
 render(<RouterProvider router={router}/>)
 fireEvent.click(await screen.findByRole('button',{name:'Browser back'}))
 await screen.findByRole('heading',{name:'Keep your unsaved edits?'})
 expect(router.state.location.search).toBe('?row=1')
 fireEvent.click(screen.getByRole('button',{name:'Keep editing'}))
 expect(router.state.location.search).toBe('?row=1')
})
