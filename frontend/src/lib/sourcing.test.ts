import { describe, expect, it } from "vitest";
import { defaultView, parseTSV, serializeTSV } from "./sourcing";
describe("spreadsheet clipboard", () => {
  it("round trips tabs, line breaks and quotes", () => {
    const rows = [
      ["Acme", 'A "role"', "line\nnext"],
      ["tab\there", "", ""],
    ];
    expect(parseTSV(serializeTSV(rows))).toEqual(rows);
  });
  it("accepts Windows clipboard line endings", () =>
    expect(parseTSV("a\tb\r\nc\td\r\n")).toEqual([
      ["a", "b"],
      ["c", "d"],
    ]));
});

import { parseCSV, visibleRows, nativeChanges } from "./sourcing";
it("parses a CSV preview with quoted commas and multiline cells", () => {
  expect(
    parseCSV('Company,Role,Notes\r\nAcme,"Engineer, Platform","one\ntwo"\r\n'),
  ).toEqual([
    ["Company", "Role", "Notes"],
    ["Acme", "Engineer, Platform", "one\ntwo"],
  ]);
  expect(() => parseCSV('a,b\n"unfinished')).toThrow();
});
it("maps edited cells to base identities and versions even if display is sorted", () => {
  const base = {
    rows: [[], [{ value: "B", version: 3 }], [{ value: "A", version: 1 }]],
    row_ids: ["", "row-B", "row-A"],
    columns: [{ id: "company", title: "Company", kind: "company" }],
  } as any;
  expect(
    visibleRows(base, [], {
      find: "",
      filterColumn: 0,
      filter: "",
      sortColumn: 0,
      direction: "asc",
    }),
  ).toEqual([0, 2, 1]);
  expect(nativeChanges(base, [{ row: 2, col: 0, value: "Edited A" }])).toEqual([
    {
      row_id: "row-A",
      column_id: "company",
      expected_version: 1,
      value: "Edited A",
    },
  ]);
  expect(
    visibleRows(base, [], {
      find: "b",
      filterColumn: 0,
      filter: "",
      sortColumn: 0,
      direction: "asc",
    }),
  ).toEqual([0, 1]);
});

import { csvDestinations } from "./sourcing";
it("previews semantic CSV aliases even when reordered and mixed with new columns", () => {
  const columns = [
    { id: "c", title: "Company", kind: "company" },
    { id: "r", title: "Role", kind: "role" },
    { id: "l", title: "Job link", kind: "link" },
  ] as any;
  expect(
    csvDestinations(["Role", "Company", "Job URL", "Notes"], columns).map(
      (c) => c.target,
    ),
  ).toEqual(["Role", "Company", "Job link", "Notes"]);
  expect(
    csvDestinations(["Role", "Company", "Job URL", "Notes"], columns)[3].isNew,
  ).toBe(true);
});

it("shows only the chosen day plus empty template rows, preserving base identities", () => {
  const base = {
    rows: [
      [],
      [{ value: "Old" }],
      [{ value: "Today" }],
      [{ value: "Tomorrow" }],
      [{ value: "" }],
    ],
    row_dates: [null, null, "2026-10-15", "2026-10-16", null],
    columns: [{ id: "company" }],
  } as any;
  expect(visibleRows(base, [], { ...defaultView, day: "2026-10-15" })).toEqual([
    0, 2, 4,
  ]);
  expect(visibleRows(base, [], { ...defaultView, day: "undated" })).toEqual([
    0, 1, 4,
  ]);
  expect(visibleRows(base, [], { ...defaultView, day: "2026-10-16" })).toEqual([
    0, 3, 4,
  ]);
});

import { parseClipboardRows } from './sourcing'
it('keeps wrapped company text in the same job row using clipboard table boundaries',()=>{
 const plain='Sem-Sol\n\tSoftware Engineer\thttps://jobs.test/1\nCaptivation Software\n\tEngineer\thttps://jobs.test/2'
 const html='<table><tr><td><div>Sem-Sol</div></td><td>Software Engineer</td><td>https://jobs.test/1</td></tr><tr><td>Captivation Software<br></td><td>Engineer</td><td>https://jobs.test/2</td></tr></table>'
 expect(parseClipboardRows(plain,html)).toEqual([['Sem-Sol','Software Engineer','https://jobs.test/1'],['Captivation Software','Engineer','https://jobs.test/2']])
})
it('preserves multiline cells, empty cells and Unicode in copied tables',()=>{
 expect(parseClipboardRows('', '<table><tr><td>Acme<br>Labs</td><td></td><td>日本語</td></tr></table>')).toEqual([['Acme\nLabs','','日本語']])
})
it('preserves merged-cell positions instead of shifting job columns',()=>{
 expect(parseClipboardRows('', '<table><tr><td rowspan="2">Acme</td><td>Engineer</td><td>https://jobs.test/1</td></tr><tr><td>Designer</td><td>https://jobs.test/2</td></tr></table>')).toEqual([['Acme','Engineer','https://jobs.test/1'],['','Designer','https://jobs.test/2']])
})
it('falls back to TSV when clipboard HTML is not a table',()=>{
 expect(parseClipboardRows('Acme\tEngineer\thttps://jobs.test/1','<div>Unrelated markup</div>')).toEqual([['Acme','Engineer','https://jobs.test/1']])
})
it('extracts text only and ignores executable or embedded clipboard markup',()=>{
 expect(parseClipboardRows('', '<table><tr><td>Acme<script>window.bad=true</script><style>td{display:none}</style><iframe src="https://tracker.invalid"></iframe></td><td>Engineer</td><td>https://jobs.test/?a=1&amp;b=2</td></tr></table>')).toEqual([['Acme','Engineer','https://jobs.test/?a=1&b=2']])
})
it('bounds merged table expansion',()=>{
 expect(()=>parseClipboardRows('', '<table><tr>'+Array(11).fill('<td colspan="1000">x</td>').join('')+'</tr></table>')).toThrow('10,000 cells')
})
