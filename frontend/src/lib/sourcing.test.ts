import { describe, expect, it } from "vitest";
import { parseTSV, serializeTSV } from "./sourcing";
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
