import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
