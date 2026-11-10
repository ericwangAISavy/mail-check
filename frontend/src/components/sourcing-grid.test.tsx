import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SheetGrid } from "./sourcing-grid";
import type { Snapshot } from "@/lib/sourcing";

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(1200);
  vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(500);
  Element.prototype.scrollTo = vi.fn();
  Element.prototype.scrollIntoView = vi.fn();
  const query = Element.prototype.querySelector;
  vi.spyOn(Element.prototype, "querySelector").mockImplementation(function(this: Element, selector: string) {
    return query.call(this, selector.startsWith("&") ? ":scope" + selector.slice(1) : selector);
  } as typeof Element.prototype.querySelector);
});
afterEach(() => {cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks()});
const cell = (value: string) => ({value, display: value, formula: false, link: "", version: 1, style: {}});
function snapshot(): Snapshot {
  return {id: 1, title: "personal", revision: "1", structure_revision: 1, refreshed_at: 1,
    columns: [{id:"company", title:"Company", kind:"company", width:220}, {id:"role",title:"Role",kind:"role",width:220}, {id:"link",title:"Job link",kind:"link",width:220}, {id:"check",title:"Check",kind:"check",width:76}],
    row_ids:["","row1"], rows:[[cell("Company"),cell("Role"),cell("Job link"),cell("Check")],[cell("Acme"),cell("Engineer"),cell("https://jobs.test/1"),cell("false")]],
    properties:{gridProperties:{rowCount:2,columnCount:4}}};
}
it("renders a compact Check checkbox and commits its state", () => {
  const change = vi.fn();
  render(<SheetGrid snapshot={snapshot()} changes={[]} onChange={change}/>);
  const check = screen.getByRole("checkbox",{name:"Check row 1"}) as HTMLInputElement;
  expect(check.checked).toBe(false);
  fireEvent.click(check);
  expect(change).toHaveBeenCalledWith([{row:1,col:3,value:"true",style:undefined}]);
});
it("shows the saved checked state and disables editing while saving", () => {
  const data = snapshot(); data.rows[1][3] = cell("true");
  render(<SheetGrid snapshot={data} changes={[]} onChange={vi.fn()} disabled/>);
  const check = screen.getByRole("checkbox",{name:"Check row 1"}) as HTMLInputElement;
  expect(check.checked).toBe(true);
  expect(check.disabled).toBe(true);
});
it("removes blank pasted rows before appending jobs beyond the input row", () => {
  const data = snapshot(); data.rows[1] = data.rows[1].map(() => cell(""));
  const append = vi.fn();
  render(<SheetGrid snapshot={data} changes={[]} onChange={vi.fn()} onAppendRows={append}/>);
  const grid = screen.getByRole("grid", {name: "Job sourcing spreadsheet"});
  fireEvent.paste(grid, {clipboardData: {getData: () => "Acme\tEngineer\thttps://jobs.test/1\n\t\t\nBeta\tEngineer\thttps://jobs.test/2\n\t\t"}});
  expect(append).toHaveBeenCalledWith([["Acme", "Engineer", "https://jobs.test/1"], ["Beta", "Engineer", "https://jobs.test/2"]]);
});
it("deletes all dragged rows with Delete instead of clearing cell values", () => {
  const data = snapshot();
  data.rows.push([cell("Beta"),cell("Designer"),cell("https://jobs.test/2"),cell("false")]);
  data.row_ids.push("row2");
  const remove = vi.fn(), change = vi.fn();
  render(<SheetGrid snapshot={data} changes={[]} onChange={change} onDeleteRows={remove}/>);
  const first = screen.getByRole("gridcell", {name: "Acme"});
  const last = screen.getByRole("gridcell", {name: "Designer"});
  fireEvent.mouseDown(first, {button:0, buttons:1});
  fireEvent.mouseMove(last, {buttons:1});
  fireEvent.mouseUp(document);
  fireEvent.keyDown(screen.getByRole("grid"), {key:"Delete"});
  expect(remove).toHaveBeenCalledWith([1,2]);
  expect(change).not.toHaveBeenCalled();
});
it("uses the filtered job identity for keyboard deletion", () => {
  const data = snapshot();
  data.rows.push([cell("Beta"),cell("Designer"),cell("https://jobs.test/2"),cell("false")]); data.row_ids.push("row2");
  const remove = vi.fn();
  render(<SheetGrid snapshot={data} changes={[]} onChange={vi.fn()} onDeleteRows={remove}
    view={{find:"Beta",filterColumn:0,filter:"",sortColumn:0,direction:"none"}}/>);
  fireEvent.keyDown(screen.getByRole("grid"), {key:"Delete"});
  expect(remove).toHaveBeenCalledWith([2]);
});
it("keeps Delete inside a text editor from deleting job rows", () => {
  const remove = vi.fn();
  render(<SheetGrid snapshot={snapshot()} changes={[]} onChange={vi.fn()} onDeleteRows={remove}/>);
  fireEvent.doubleClick(screen.getByRole("gridcell", {name:"Acme"}));
  const input = screen.getByRole("textbox", {name:"Edit cell"});
  fireEvent.keyDown(input, {key:"Delete"});
  expect(remove).not.toHaveBeenCalled();
});

it("prevents clearing an already checked job", () => {
  const data = snapshot(); data.rows[1][3] = cell("true");
  const change = vi.fn();
  render(<SheetGrid snapshot={data} changes={[]} onChange={change}/>);
  const check = screen.getByRole("checkbox", {name:"Check row 1"}) as HTMLInputElement;
  expect(check.checked).toBe(true);
  expect(check.disabled).toBe(true);
  fireEvent.click(check);
  expect(change).not.toHaveBeenCalled();
});

it("shows the matching confirmation received time on checked links", () => {
  const data = snapshot(); data.rows[1][3] = {...cell("true"),checked_at:"2026-10-21T14:23:00+00:00"};
  render(<SheetGrid snapshot={data} changes={[]} onChange={vi.fn()}/>);
  expect(screen.getByRole("checkbox", {name:"Check row 1"}).getAttribute("title")).toContain("9:23 AM")
});

it("uses fixed field headings and starts with the first job instead of an editable header row",()=>{
 const data=snapshot();data.columns[0].title="Old custom label";data.rows[0][0]=cell("Old custom label")
 const change=vi.fn()
 render(<SheetGrid snapshot={data} changes={[]} onChange={change}/>)
 expect(screen.getByRole("columnheader",{name:"Company"})).toBeTruthy()
 expect(screen.getByRole("columnheader",{name:"Role"})).toBeTruthy()
 expect(screen.getByRole("columnheader",{name:"Job link"})).toBeTruthy()
 expect(screen.getByRole("columnheader",{name:"Check"})).toBeTruthy()
 expect(screen.queryByRole("columnheader",{name:"A"})).toBeNull()
 expect(screen.queryByRole("gridcell",{name:"Old custom label"})).toBeNull()
 fireEvent.doubleClick(screen.getByRole("columnheader",{name:"Company"}))
 expect(screen.queryByRole("textbox",{name:"Edit cell"})).toBeNull()
 fireEvent.doubleClick(screen.getByRole("gridcell",{name:"Acme"}))
 const editor=screen.getByRole("textbox",{name:"Edit cell"})
 fireEvent.change(editor,{target:{value:"Updated company"}});fireEvent.blur(editor)
 expect(change).toHaveBeenCalledWith([{row:1,col:0,value:"Updated company",style:undefined}])
})

it("preserves the saved row identity when the first visible job is filtered",()=>{
 const data=snapshot();data.rows.push([cell("Beta"),cell("Designer"),cell("https://jobs.test/2"),cell("false")]);data.row_ids.push("row2")
 const change=vi.fn()
 render(<SheetGrid snapshot={data} changes={[]} onChange={change} view={{find:"Beta",filterColumn:0,filter:"",sortColumn:0,direction:"none"}}/>)
 fireEvent.doubleClick(screen.getByRole("gridcell",{name:"Beta"}))
 const editor=screen.getByRole("textbox",{name:"Edit cell"})
 fireEvent.change(editor,{target:{value:"Beta updated"}});fireEvent.blur(editor)
 expect(change).toHaveBeenCalledWith([{row:2,col:0,value:"Beta updated",style:undefined}])
})

it("selects and copies the whole row from any clicked cell",()=>{
 const selection=vi.fn(),setData=vi.fn()
 render(<SheetGrid snapshot={snapshot()} changes={[]} onChange={vi.fn()} onSelection={selection}/>)
 fireEvent.mouseDown(screen.getByRole("gridcell",{name:"Engineer"}),{button:0,buttons:1});fireEvent.mouseUp(document)
 expect(selection).toHaveBeenLastCalledWith({rows:[1],columns:[0,1,2,3]})
 fireEvent.copy(screen.getByRole("grid"),{clipboardData:{setData}})
 expect(setData).toHaveBeenCalledWith("text/plain","Acme\tEngineer\thttps://jobs.test/1\tfalse")
})

it("locks every cell in a checked row and gives it a checked style",()=>{
 const data=snapshot();data.rows[1][3]=cell("true")
 render(<SheetGrid snapshot={data} changes={[]} onChange={vi.fn()}/>)
 const company=screen.getByRole("gridcell",{name:"Acme"})
 fireEvent.doubleClick(company)
 expect(screen.queryByRole("textbox",{name:"Edit cell"})).toBeNull()
 expect(company.closest('[role="row"]')?.className).toContain("sheet-checked-row")
})

it("rejects pasting over checked row cells",()=>{
 const data=snapshot();data.rows[1][3]=cell("true");const change=vi.fn()
 render(<SheetGrid snapshot={data} changes={[]} onChange={change}/>)
 fireEvent.paste(screen.getByRole("grid"),{clipboardData:{getData:()=>"Changed"}})
 expect(change).not.toHaveBeenCalled()
})

it("deletes a row selected using its row number",()=>{
 const remove=vi.fn()
 render(<SheetGrid snapshot={snapshot()} changes={[]} onChange={vi.fn()} onDeleteRows={remove}/>)
 fireEvent.mouseDown(screen.getByRole("gridcell",{name:"1"}),{button:0,buttons:1});fireEvent.mouseUp(document)
 fireEvent.keyDown(screen.getByRole("grid"),{key:"Delete"})
 expect(remove).toHaveBeenCalledWith([1])
})

it("keeps copying selected editor text from copying the entire job row", () => {
  const setData = vi.fn();
  render(<SheetGrid snapshot={snapshot()} changes={[]} onChange={vi.fn()}/>);
  fireEvent.doubleClick(screen.getByRole("gridcell", {name:"Acme"}));
  const input = screen.getByRole("textbox", {name:"Edit cell"});
  expect(fireEvent.copy(input, {clipboardData:{setData}})).toBe(true);
  expect(setData).not.toHaveBeenCalled();
});

it("keeps pasting text inside the editor from changing whole spreadsheet cells", () => {
  const change = vi.fn();
  render(<SheetGrid snapshot={snapshot()} changes={[]} onChange={change}/>);
  fireEvent.doubleClick(screen.getByRole("gridcell", {name:"Acme"}));
  const input = screen.getByRole("textbox", {name:"Edit cell"});
  expect(fireEvent.paste(input, {clipboardData:{getData:()=>"replacement"}})).toBe(true);
  expect(change).not.toHaveBeenCalled();
});

it("auto-scrolls a held drag beyond the viewport and stops on release", () => {
  const data = snapshot();
  for (let i = 2; i <= 40; i++) {
    data.rows.push([cell(`Company ${i}`), cell("Engineer"), cell(`https://jobs.test/${i}`), cell("false")]);
    data.row_ids.push(`row${i}`);
  }
  data.rows[2][0].style = { wrap: true };
  const selection = vi.fn();
  render(<SheetGrid snapshot={data} changes={[]} onChange={vi.fn()} onSelection={selection}/>);
  const grid = screen.getByRole("grid");
  vi.spyOn(grid, "getBoundingClientRect").mockReturnValue({top:10,bottom:160,left:0,right:900,width:900,height:150,x:0,y:10,toJSON:()=>({})});
  Object.defineProperty(grid,"clientHeight",{value:120,configurable:true});
  Object.defineProperty(grid,"scrollHeight",{value:1262,configurable:true});
  let next = 0;
  const frames = new Map<number,FrameRequestCallback>();
  vi.spyOn(window,"requestAnimationFrame").mockImplementation(callback=>{frames.set(++next,callback);return next});
  vi.spyOn(window,"cancelAnimationFrame").mockImplementation(id=>{frames.delete(id)});
  const tick = (time:number) => act(()=>{
    const callbacks=[...frames.values()];frames.clear();callbacks.forEach(callback=>callback(time));
  });
  fireEvent.mouseDown(screen.getByRole("gridcell",{name:"Acme"}),{button:0,buttons:1,clientX:200,clientY:125});
  // A click-and-hold near the edge is not a drag and must not scroll.
  tick(16);
  expect(grid.scrollTop).toBe(0);
  fireEvent.mouseMove(document,{buttons:1,clientX:200,clientY:160});
  tick(32);
  // The scrollbar is outside the usable body; wrapped row 2 ends at 94px.
  expect(selection.mock.lastCall![0].rows).toEqual([1,2,3]);
  for(let i=3;i<=21;i++)tick(i*16);
  expect(grid.scrollTop).toBeGreaterThan(0);
  const down=grid.scrollTop;
  expect(selection.mock.lastCall![0].rows[0]).toBe(1);
  expect(selection.mock.lastCall![0].rows.at(-1)).toBeGreaterThan(4);
  fireEvent.mouseMove(document,{buttons:1,clientX:200,clientY:20});
  tick(352);
  expect(grid.scrollTop).toBeLessThan(down);
  fireEvent.mouseUp(document);
  expect(frames.size).toBe(0);
  const stopped=grid.scrollTop;
  tick(368);
  expect(grid.scrollTop).toBe(stopped);
  fireEvent.mouseDown(screen.getByRole("gridcell",{name:"Acme"}),{button:0,buttons:1,clientX:200,clientY:60});
  expect(frames.size).toBeGreaterThan(0);
  fireEvent(window,new Event("blur"));
  expect(frames.size).toBe(0);
});

it("preserves the original anchor when extending selection with Shift-click", () => {
  const data=snapshot();
  for(let row=2;row<=3;row++) {
    data.rows.push([cell(`Company ${row}`),cell("Engineer"),cell(`https://jobs.test/${row}`),cell("false")]);
    data.row_ids.push(`row${row}`);
  }
  const selection=vi.fn();
  render(<SheetGrid snapshot={data} changes={[]} onChange={vi.fn()} onSelection={selection}/>);
  fireEvent.mouseDown(screen.getByRole("gridcell",{name:"Acme"}),{button:0,buttons:1});
  fireEvent.mouseUp(document);
  fireEvent.mouseDown(screen.getByRole("gridcell",{name:"Company 3"}),{button:0,buttons:1,shiftKey:true});
  fireEvent.mouseUp(document);
  expect(selection.mock.lastCall![0].rows).toEqual([1,2,3]);
});

it('pastes HTML table rows without splitting a wrapped company from its job link',()=>{
 const data=snapshot();data.rows[1]=data.rows[1].map(()=>cell(''))
 const append=vi.fn()
 render(<SheetGrid snapshot={data} changes={[]} onChange={vi.fn()} onAppendRows={append}/> )
 fireEvent.paste(screen.getByRole('grid'),{clipboardData:{getData:(type:string)=>type==='text/html'?'<table><tr><td>Sem-Sol<br></td><td>Engineer</td><td>https://jobs.test/1</td></tr><tr><td>Acme</td><td>Engineer</td><td>https://jobs.test/2</td></tr></table>':'Sem-Sol\n\tEngineer\thttps://jobs.test/1\nAcme\tEngineer\thttps://jobs.test/2'}})
 expect(append).toHaveBeenCalledWith([['Sem-Sol','Engineer','https://jobs.test/1'],['Acme','Engineer','https://jobs.test/2']])
})
it('reports oversized rich clipboard data without changing the sheet',()=>{
 const change=vi.fn(),append=vi.fn(),alert=vi.spyOn(window,'alert').mockImplementation(()=>{})
 render(<SheetGrid snapshot={snapshot()} changes={[]} onChange={change} onAppendRows={append}/> )
 fireEvent.paste(screen.getByRole('grid'),{clipboardData:{getData:(type:string)=>type==='text/html'?'<table><tr>'+Array(11).fill('<td colspan="1000">x</td>').join('')+'</tr></table>':'x'}})
 expect(alert).toHaveBeenCalledWith('Paste up to 10,000 cells at a time.')
 expect(change).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled()
})
it('leaves the sheet unchanged when quoted clipboard text is incomplete',()=>{
 const change=vi.fn(),append=vi.fn(),alert=vi.spyOn(window,'alert').mockImplementation(()=>{})
 render(<SheetGrid snapshot={snapshot()} changes={[]} onChange={change} onAppendRows={append}/> )
 fireEvent.paste(screen.getByRole('grid'),{clipboardData:{getData:(type:string)=>type==='text/html'?'':'"Acme\nEngineer\thttps://jobs.test/1\nBeta\tEngineer\thttps://jobs.test/2'}})
 expect(alert).toHaveBeenCalledWith('This clipboard text has an unclosed quoted cell.')
 expect(change).not.toHaveBeenCalled();expect(append).not.toHaveBeenCalled()
})
