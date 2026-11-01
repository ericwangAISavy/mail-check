import {useEffect,useId,useMemo,useRef,useState} from "react"
import {ChevronDown,Check} from "lucide-react"
import {browserTimezone,timezoneChoices} from "@/lib/calendar-timezone"

export default function TimezonePicker({value,onChange}:{value:string;onChange:(value:string)=>void}) {
  const [open,setOpen]=useState(false)
  const [query,setQuery]=useState("")
  const [active,setActive]=useState(0)
  const root=useRef<HTMLDivElement>(null)
  const listId=useId()
  const options=useMemo(()=>[
    {value:"local",label:`Browser time (${browserTimezone()})`},
    ...timezoneChoices(value==="local"?browserTimezone():value).map(zone=>({value:zone,label:zone.replaceAll("_"," ")})),
  ],[value])
  const filtered=useMemo(()=>{
    const search=query.trim().toLowerCase().replaceAll("_"," ")
    return options.filter(option=>option.label.toLowerCase().includes(search))
  },[options,query])
  const label=options.find(option=>option.value===value)?.label||value
  const show=()=>{if(!open){setQuery("");setActive(0);setOpen(true)}}
  const choose=(zone:string)=>{onChange(zone);setOpen(false);setQuery("")}
  useEffect(()=>{
    if(!open)return
    const outside=(event:PointerEvent)=>{if(!root.current?.contains(event.target as Node))setOpen(false)}
    document.addEventListener("pointerdown",outside)
    return()=>document.removeEventListener("pointerdown",outside)
  },[open])
  useEffect(()=>{
    if(open)document.getElementById(`${listId}-${active}`)?.scrollIntoView?.({block:"nearest"})
  },[active,open,listId])
  return <div ref={root} className="timezone-picker" onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget))setOpen(false)}}>
    <div className="timezone-picker-input">
      <input role="combobox" aria-label="Calendar timezone" aria-expanded={open} aria-controls={open?listId:undefined} aria-autocomplete="list" aria-activedescendant={open&&filtered[active]?`${listId}-${active}`:undefined} autoComplete="off" spellCheck={false} value={open?query:label} placeholder="Search timezones…" onFocus={show} onClick={show} onChange={event=>{setQuery(event.target.value);setActive(0);setOpen(true)}} onKeyDown={event=>{
        if(event.key==="ArrowDown"||event.key==="ArrowUp"){
          event.preventDefault()
          if(!open){show();return}
          setActive(current=>Math.max(0,Math.min(filtered.length-1,current+(event.key==="ArrowDown"?1:-1))))
        }else if(event.key==="Enter"&&open){
          event.preventDefault()
          if(filtered[active])choose(filtered[active].value)
        }else if(event.key==="Escape"&&open){
          event.preventDefault();event.stopPropagation();setOpen(false)
        }else if(event.key==="Tab")setOpen(false)
      }}/>
      <ChevronDown size={14} aria-hidden="true"/>
    </div>
    {open&&<div className="timezone-picker-popup"><div role="listbox" id={listId} aria-label="Timezones">{filtered.map((option,index)=><button type="button" role="option" id={`${listId}-${index}`} key={option.value} tabIndex={-1} aria-selected={option.value===value} className={active===index?"is-active":""} onMouseDown={event=>event.preventDefault()} onClick={()=>choose(option.value)}>{option.label}{option.value===value&&<Check size={14} aria-hidden="true"/>}</button>)}</div>{!filtered.length&&<p role="status">No matching timezones.</p>}</div>}
  </div>
}
