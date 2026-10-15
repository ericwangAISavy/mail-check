export interface Cell { value: string | number | boolean; display: string; formula: boolean; link: string }
export interface Snapshot { stale?: boolean; error?:string; rows: Cell[][]; title: string; revision: string; refreshed_at: number; properties: { gridProperties: {rowCount:number; columnCount:number} } }
export interface Tab { id:number; sheet_id:number; account_id:number; account_label?:string; title:string; header_row:number; company_col:number; role_col:number; link_col:number; refreshed_at:number }
export interface Book { id:number; bidder_id:number; spreadsheet_id:string; title:string; name:string; tabs:Tab[] }
export interface Index { books:Book[]; bidders?:{id:number;name:string;login_enabled:boolean}[]; accounts?:{id:number;label:string;email:string}[]; assignments?:{bidder_id:number;account_id:number}[] }
export interface Change {row:number;col:number;value:string}
export function columnName(index:number) { let result=""; for(index++;index;index=Math.floor((index-1)/26)) result=String.fromCharCode(65+(index-1)%26)+result; return result }
export function serializeTSV(rows:string[][]) { return rows.map(row=>row.map(value=>/[\t\n\r"]/.test(value)?'"'+value.replaceAll('"','""')+'"':value).join("\t")).join("\n") }
export function parseTSV(text:string) {
  const rows:string[][]=[];let row:string[]=[],value="",quoted=false
  for(let i=0;i<text.length;i++) {const char=text[i]
    if(char==='"' && (!value || quoted)) {if(quoted && text[i+1]==='"'){value+='"';i++}else quoted=!quoted}
    else if(!quoted && (char==='\t'||char==='\n'||char==='\r')) {row.push(value);value="";if(char!=='\t'){rows.push(row);row=[];if(char==='\r'&&text[i+1]==='\n')i++}}
    else value+=char
  }
  if(value||row.length||!rows.length){row.push(value);rows.push(row)}return rows
}

export function mergeChanges(snapshot:Snapshot,current:Change[],values:Change[]) {
  const next=new Map(current.map(c=>[`${c.row}:${c.col}`,c]))
  for(const cell of values) {const key=`${cell.row}:${cell.col}`;if(String(snapshot.rows[cell.row]?.[cell.col]?.value??'')===cell.value)next.delete(key);else next.set(key,cell)}
  return [...next.values()]
}
