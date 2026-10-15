import { useEffect, useMemo, useRef, useState } from "react"
import { DataGrid, renderTextEditor, type Column, type DataGridHandle } from "react-data-grid"
import "react-data-grid/lib/styles.css"
import { columnName, parseTSV, serializeTSV, type Change, type Snapshot } from "@/lib/sourcing"
type Row = { id:number; [key:string]:string|number }
export function SheetGrid({snapshot,headerRow,changes,onChange,disabled=false,highlightRow}:{snapshot:Snapshot;headerRow:number;changes:Change[];onChange:(changes:Change[])=>void;disabled?:boolean;highlightRow?:number}) {
  const grid=useRef<DataGridHandle>(null)
  useEffect(()=>{if(highlightRow!==undefined){grid.current?.scrollToCell({rowIdx:highlightRow,idx:1});grid.current?.setActivePosition({rowIdx:highlightRow,idx:1})}},[highlightRow])
  const [position,setPosition]=useState({row:headerRow,col:0})
  const extending=useRef(false)
  const anchor=useRef(position)
  const selected=useRef(position)
  const count=Math.min(snapshot.properties.gridProperties.columnCount,101)
  const rows=useMemo(()=>{
    const result=Array.from({length:snapshot.properties.gridProperties.rowCount},(_,r)=>{const row:Row={id:r};for(let c=0;c<count;c++)row[String(c)]=snapshot.rows[r]?.[c]?.display||"";return row})
    for(const change of changes)if(result[change.row])result[change.row][String(change.col)]=change.value
    return result
  },[snapshot,changes,count])

  const editable=(r:number,c:number)=>!disabled&&r>=headerRow&&!snapshot.rows[r]?.[c]?.formula
  const apply=(values:Change[])=>{
    if(disabled)return
    const next=new Map(changes.map(c=>[`${c.row}:${c.col}`,c]))
    for(const change of values) if(editable(change.row,change.col)) {
      const key=`${change.row}:${change.col}`
      if(String(snapshot.rows[change.row]?.[change.col]?.value??"")===change.value)next.delete(key);else next.set(key,change)
    }
    if(next.size>10000){window.alert("Save the current edits before changing more than 10,000 cells.");return}
    onChange([...next.values()])
  }
  const columns:Column<Row>[]=[{key:"id",name:"",width:48,frozen:true,renderCell:({row})=><span className="sheet-row-number">{row.id+1}</span>},...Array.from({length:count},(_,c):Column<Row>=>({
    key:String(c),name:columnName(c),width:c===2?320:220,resizable:true,editable:row=>editable(row.id,c),renderEditCell:renderTextEditor,
    cellClass:row=>row.id>=Math.min(anchor.current.row,position.row)&&row.id<=Math.max(anchor.current.row,position.row)&&c>=Math.min(anchor.current.col,position.col)&&c<=Math.max(anchor.current.col,position.col)?"sheet-range-cell":row.id<headerRow?"sheet-heading-cell":snapshot.rows[row.id]?.[c]?.formula?"sheet-formula-cell":undefined,
    renderCell:({row})=>{const cell=snapshot.rows[row.id]?.[c];const text=String(row[String(c)]);return cell?.link&&/^https?:\/\//i.test(cell.link)?<a href={cell.link} target="_blank" rel="noreferrer" onClick={e=>e.stopPropagation()}>{text}</a>:<span title={cell?.formula?`Formula: ${cell.value}`:text}>{text}</span>}
  }))]
  return <><div className="sheet-formula-bar"><span>{columnName(position.col)}{position.row+1}</span><i>fx</i><span>{String(rows[position.row]?.[String(position.col)]??"")}</span></div><DataGrid ref={grid} rowClass={row=>row.id===highlightRow?"sheet-highlight-row":undefined} aria-label="Job sourcing spreadsheet" className="sourcing-grid" columns={columns} rows={rows} rowKeyGetter={r=>r.id} rowHeight={30} headerRowHeight={28}
    onActivePositionChange={({rowIdx,column})=>{if(rowIdx>=0&&column&&column.key!=="id"){const next={row:rowIdx,col:Number(column.key)};setPosition(next);selected.current=next;if(!extending.current)anchor.current=next}}}
    onCellMouseDown={({rowIdx,column},event)=>{if(column.key==="id")return;const next={row:rowIdx,col:Number(column.key)};extending.current=event.shiftKey;if(!event.shiftKey)anchor.current=next;selected.current=next}}
    onRowsChange={(next,{indexes,column})=>apply(indexes.map(r=>({row:r,col:Number(column.key),value:String(next[r][column.key])})))}
    onCellCopy={(_,event)=>{const a=anchor.current,b=selected.current;const values=[];for(let r=Math.min(a.row,b.row);r<=Math.max(a.row,b.row);r++){const row=[];for(let c=Math.min(a.col,b.col);c<=Math.max(a.col,b.col);c++)row.push(String(rows[r]?.[String(c)]??""));values.push(row)}event.clipboardData.setData("text/plain",serializeTSV(values));event.preventDefault()}}
    onCellPaste={({row,column},event)=>{event.preventDefault();if(disabled)return row;const matrix=parseTSV(event.clipboardData.getData("text/plain"));if(matrix.reduce((n,r)=>n+r.length,0)>10000){window.alert("Paste up to 10,000 cells at a time.");return row}if(matrix.length+row.id>rows.length||matrix.some(r=>r.length+Number(column.key)>count)){window.alert("This paste extends beyond the available rows or columns. Use Append jobs or add columns in Google Sheets first.");return row}const values:Change[]=[];matrix.forEach((r,ri)=>r.forEach((value,ci)=>{const col=Number(column.key)+ci;if(col<count&&row.id+ri<rows.length)values.push({row:row.id+ri,col,value})}));apply(values);return row}}
    onCellKeyDown={(args,event)=>{extending.current=event.shiftKey;if(args.mode!=="ACTIVE"||!args.column||args.column.key==="id")return;if(event.key==="Delete"||event.key==="Backspace"){event.preventDefault();const a=anchor.current,b=selected.current;const values=[];if((Math.abs(a.row-b.row)+1)*(Math.abs(a.col-b.col)+1)>10000){window.alert("Clear up to 10,000 cells at a time.");return}for(let r=Math.min(a.row,b.row);r<=Math.max(a.row,b.row);r++)for(let c=Math.min(a.col,b.col);c<=Math.max(a.col,b.col);c++)values.push({row:r,col:c,value:""});apply(values)}}}
  /></>
}
