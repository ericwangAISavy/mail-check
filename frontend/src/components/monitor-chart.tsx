import {memo,useLayoutEffect,useMemo,useRef,useState,type KeyboardEvent,type PointerEvent} from 'react'

export type ChartSeries={key:string;label:string;color:string;values:(number|null)[];type:'bar'|'line'}
type Props={title:string;buckets:number[];step:number;series:ChartSeries[];format:(value:number)=>string;height?:number;summary?:string}

const PAD={top:10,right:10,bottom:24,left:46}
const time=(at:number)=>new Date(at*1000).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'})
function niceMax(value:number){
 if(value<=0)return 1
 const power=10**Math.floor(Math.log10(value)),n=value/power
 return (n<=1?1:n<=2?2:n<=2.5?2.5:n<=5?5:10)*power
}
/** Bar with a 2px rounded data end and a square baseline. */
function barPath(x:number,y:number,w:number,h:number,round:boolean){
 const r=round?Math.min(2,w/2,h):0
 return `M${x},${y+h}V${y+r}${r?`Q${x},${y} ${x+r},${y}`:''}H${x+w-r}${r?`Q${x+w},${y} ${x+w},${y+r}`:''}V${y+h}Z`
}
const present=(v:number|null|undefined):v is number=>v!==null&&v!==undefined&&Number.isFinite(v)
function linePath(values:(number|null)[],x:(i:number)=>number,y:(v:number)=>number){
 let d='',open=false
 values.forEach((value,i)=>{if(!present(value)){open=false;return}d+=`${open?'L':'M'}${x(i).toFixed(1)},${y(value).toFixed(1)}`;open=true})
 return d
}
/** Points with no neighbour: a line cannot show them, so they get a marker. */
const isolated=(values:(number|null)[])=>values.flatMap((v,i)=>present(v)&&!present(values[i-1])&&!present(values[i+1])?[i]:[])

function MonitorChart({title,buckets,step,series,format,height=180,summary}:Props){
 const wrap=useRef<HTMLDivElement>(null)
 const [width,setWidth]=useState(0),[active,setActive]=useState<number|null>(null),[table,setTable]=useState(false)
 useLayoutEffect(()=>{
  const node=wrap.current;if(!node)return
  setWidth(node.clientWidth)
  const observer=new ResizeObserver(([entry])=>setWidth(Math.round(entry.contentRect.width)))
  observer.observe(node);return()=>observer.disconnect()
 },[])
 const count=buckets.length,bars=series.filter(s=>s.type==='bar'),lines=series.filter(s=>s.type==='line')
 const top=useMemo(()=>{
  let max=0
  for(let i=0;i<count;i++){
   let stack=0
   for(const s of series){const v=s.values[i]??0;if(s.type==='bar')stack+=v;else max=Math.max(max,v)}
   max=Math.max(max,stack)
  }
  return niceMax(max)
 },[series,count])
 const plotW=Math.max(0,width-PAD.left-PAD.right),plotH=height-PAD.top-PAD.bottom,band=count?plotW/count:0
 const x=(i:number)=>PAD.left+band*(i+.5),y=(v:number)=>PAD.top+plotH-(v/top)*plotH
 const ticks=[0,top/2,top]
 const every=Math.max(1,Math.ceil(count/Math.max(2,Math.floor(plotW/86))))
 const barW=Math.max(1,Math.min(24,band*(band>=6?.72:.9)))
 const empty=!series.some(s=>s.values.some(v=>(v??0)>0))
 const pick=(clientX:number)=>{
  const box=wrap.current?.getBoundingClientRect();if(!box||!band)return
  setActive(Math.max(0,Math.min(count-1,Math.floor((clientX-box.left-PAD.left)/band))))
 }
 const onKey=(event:KeyboardEvent)=>{
  if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();setActive(i=>Math.max(0,Math.min(count-1,(i??count-1)+(event.key==='ArrowLeft'?-1:1))))}
  else if(event.key==='Escape')setActive(null)
 }
 const tipLeft=active===null?0:Math.min(Math.max(x(active)+12,0),Math.max(0,width-190))
 return <figure className="monitor-chart" aria-label={title}>
  <figcaption className="monitor-chart-head">
   <h3>{title}</h3>
   {summary&&<span className="monitor-chart-summary">{summary}</span>}
   <span className="monitor-chart-tools">
    {series.length>1&&<ul className="monitor-legend">{series.map(s=><li key={s.key}><i className={s.type==='line'?'is-line':''} style={{background:s.color}} aria-hidden="true"/>{s.label}</li>)}</ul>}
    <button type="button" className="monitor-chart-toggle" aria-pressed={table} aria-label={`${table?'Show chart':'Show table'}: ${title}`} onClick={()=>setTable(!table)}>{table?'Chart':'Table'}</button>
   </span>
  </figcaption>
  {table?<div className="monitor-chart-table"><table><thead><tr><th>Time</th>{series.map(s=><th key={s.key}>{s.label}</th>)}</tr></thead><tbody>{buckets.map((at,i)=>series.some(s=>(s.values[i]??0)>0)&&<tr key={at}><td>{time(at)}</td>{series.map(s=><td key={s.key}>{s.values[i]===null?'—':format(s.values[i] as number)}</td>)}</tr>)}</tbody></table>{empty&&<p className="monitor-chart-empty">No activity in this range.</p>}</div>:
  <div ref={wrap} className="monitor-chart-plot" style={{height}} tabIndex={0} role="img" aria-label={`${title}. Use the left and right arrow keys to read values.`}
   onPointerMove={(e:PointerEvent)=>pick(e.clientX)} onPointerLeave={()=>setActive(null)} onKeyDown={onKey} onBlur={()=>setActive(null)}>
   {width>0&&<svg width={width} height={height} aria-hidden="true">
    {ticks.map(t=><g key={t}><line x1={PAD.left} x2={PAD.left+plotW} y1={y(t)} y2={y(t)} className={t===0?'monitor-axis':'monitor-grid'}/><text x={PAD.left-8} y={y(t)+4} textAnchor="end" className="monitor-tick">{format(t)}</text></g>)}
    {buckets.map((at,i)=>i%every===0&&<text key={at} x={x(i)} y={height-6} textAnchor="middle" className="monitor-tick">{time(at)}</text>)}
    {bars.length>0&&buckets.map((_,i)=>{
     let base=0
     const parts=bars.map(s=>({s,v:s.values[i]??0})).filter(p=>p.v>0)
     return <g key={i}>{parts.map((p,index)=>{
      const y0=y(base+p.v),h=Math.max(1,y(base)-y0-(index>0&&band>=6?1:0))
      base+=p.v
      return <path key={p.s.key} d={barPath(x(i)-barW/2,y0,barW,h,index===parts.length-1)} fill={p.s.color} className={active===i?'is-active':undefined}/>
     })}</g>
    })}
    {lines.map(s=><g key={s.key}><path d={linePath(s.values,x,y)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"/>
     {isolated(s.values).map(i=><circle key={i} cx={x(i)} cy={y(s.values[i] as number)} r={3} fill={s.color}/>)}</g>)}
    {active!==null&&<line x1={x(active)} x2={x(active)} y1={PAD.top} y2={PAD.top+plotH} className="monitor-crosshair"/>}
    {active!==null&&lines.map(s=>s.values[active]!==null&&<circle key={s.key} cx={x(active)} cy={y(s.values[active] as number)} r={4} fill={s.color} className="monitor-dot"/>)}
   </svg>}
   {empty&&width>0&&<p className="monitor-chart-empty">No activity in this range.</p>}
   {active!==null&&<div className="monitor-tooltip" style={{left:tipLeft}} role="status">
    <span className="monitor-tooltip-time">{time(buckets[active])} – {time(buckets[active]+step)}</span>
    {series.map(s=><span key={s.key} className="monitor-tooltip-row"><i className={s.type==='line'?'is-line':''} style={{background:s.color}} aria-hidden="true"/><strong>{s.values[active]===null?'—':format(s.values[active] as number)}</strong><span>{s.label}</span></span>)}
   </div>}
  </div>}
 </figure>
}
export default memo(MonitorChart)

/** Small trend line for stat tiles; null values leave a gap. */
export function Sparkline({values,color}:{values:(number|null)[];color:string}){
 const w=120,h=28,max=Math.max(1,...values.map(v=>v??0))
 const x=(i:number)=>values.length>1?i/(values.length-1)*w:w,y=(v:number)=>h-2-(v/max)*(h-4)
 return <svg className="monitor-spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
  <path d={linePath(values,x,y)+isolated(values).map(i=>`M${Math.max(0,x(i)-3)},${y(values[i] as number)}h3`).join('')} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round"/>
 </svg>
}
