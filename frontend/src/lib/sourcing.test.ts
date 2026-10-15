import { describe, expect, it } from "vitest"
import { parseTSV, serializeTSV } from "./sourcing"
describe("spreadsheet clipboard",()=>{
  it("round trips tabs, line breaks and quotes",()=>{
    const rows=[["Acme",'A "role"',"line\nnext"],["tab\there","",""]]
    expect(parseTSV(serializeTSV(rows))).toEqual(rows)
  })
  it("accepts Windows clipboard line endings",()=>expect(parseTSV("a\tb\r\nc\td\r\n")).toEqual([["a","b"],["c","d"]]))
})
