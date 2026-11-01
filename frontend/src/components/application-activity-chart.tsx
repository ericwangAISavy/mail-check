import {useId,useState} from "react"
import {Area,Bar,CartesianGrid,ComposedChart,Rectangle,ResponsiveContainer,Tooltip,XAxis,YAxis} from "recharts"
import "./application-activity-chart.css"

type Category={name:string;label:string;count:number}
type ActivityRow={date:string;total:number;counts:Record<string,number>;partial?:boolean}
const calendarDate=(value:string)=>{const [year,month,day]=value.slice(0,10).split("-").map(Number);return new Date(year,month-1,day)}

export default function ApplicationActivityChart({rows,categories,colors,onFocus}:{rows:ActivityRow[];categories:Category[];colors:string[];onFocus:(day:string,category?:string)=>void}) {
 const id=`activity-${useId().replace(/[^a-zA-Z0-9_-]/g,"")}`
 const [width,setWidth]=useState(0)
 const stackOrder=[...categories.map((category,index)=>({category,index})).filter(item=>item.category.name!=="application_ack"),...categories.map((category,index)=>({category,index})).filter(item=>item.category.name==="application_ack")]
 const detailed=rows.length<=14&&width/Math.max(rows.length,1)>=48
 const segment=(props:any,index:number)=>{
  const {x,y,width:barWidth,height,payload}=props
  if(![x,y,barWidth,height].every(Number.isFinite)||height<=0||barWidth<=0)return <g/>
  const nonempty=stackOrder.filter(({category})=>Number(payload?.counts?.[category.name])>0).map(item=>item.index)
  const top=index===nonempty[nonempty.length-1],bottom=index===nonempty[0]
  const radius:[number,number,number,number]=[top?8:0,top?8:0,bottom?6:0,bottom?6:0]
  const center=x+barWidth/2,total=Number(payload.total)||0
  const label=total.toLocaleString(),labelWidth=Math.max(34,label.length*7+14)
  return <g className="activity-stack-segment">
   <Rectangle x={x} y={y} width={barWidth} height={height} radius={radius} fill={`url(#${id}-stack-${index})`} filter={top&&detailed?`url(#${id}-glow)`:undefined}/>
   <Rectangle x={x} y={y} width={barWidth} height={height} radius={radius} fill={`url(#${id}-sheen)`} pointerEvents="none"/>
   {top&&detailed&&<g className="activity-total-label" pointerEvents="none" aria-hidden="true">
    <line x1={center} x2={center} y1={y-3} y2={y-10} stroke="var(--activity-label-edge)"/>
    <circle cx={center} cy={y-1} r={3} fill="var(--activity-label-dot)"/>
    <rect x={center-labelWidth/2} y={y-35} width={labelWidth} height={23} rx={8} fill="var(--activity-label-bg)" stroke="var(--activity-label-edge)"/>
    <text x={center} y={y-19} textAnchor="middle" fill="var(--foreground)" fontSize={11} fontWeight={650}>{label}</text>
   </g>}
  </g>
 }
 return <div className="chart-wrap application-activity-chart" role="region" aria-label="Applications over time chart">
  <ResponsiveContainer width="100%" height="100%" onResize={value=>setWidth(value)}>
   <ComposedChart accessibilityLayer data={rows} barCategoryGap="12%" margin={{top:42,right:12,left:-16,bottom:4}}>
    <defs>
     {categories.map((category,index)=><linearGradient key={category.name} id={`${id}-stack-${index}`} x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stopColor={`var(--activity-stack-${index}-top, color-mix(in srgb, ${colors[index%colors.length]} 65%, white))`}/>
      <stop offset="40%" stopColor={`var(--activity-stack-${index}-middle, ${colors[index%colors.length]})`}/>
      <stop offset="100%" stopColor={`var(--activity-stack-${index}-bottom, color-mix(in srgb, ${colors[index%colors.length]} 78%, black))`}/>
     </linearGradient>)}
     <linearGradient id={`${id}-sheen`} x1="0" y1="0" x2="1" y2="0"><stop offset="0" stopColor="#fff" stopOpacity=".17"/><stop offset=".2" stopColor="#fff" stopOpacity=".03"/><stop offset=".75" stopColor="#fff" stopOpacity="0"/><stop offset="1" stopColor="#fff" stopOpacity=".1"/></linearGradient>
     <linearGradient id={`${id}-trend`} x1="0" y1="0" x2="1" y2="0"><stop offset="0" stopColor="var(--activity-trend-blue)"/><stop offset="1" stopColor="var(--activity-trend-violet)"/></linearGradient>
     <linearGradient id={`${id}-wash`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--activity-trend-blue)" stopOpacity=".2"/><stop offset="1" stopColor="var(--activity-trend-violet)" stopOpacity="0"/></linearGradient>
     <filter id={`${id}-glow`} x="-25%" y="-20%" width="150%" height="150%" colorInterpolationFilters="sRGB"><feGaussianBlur stdDeviation="4" result="blur"/><feComponentTransfer in="blur" result="soft"><feFuncA type="linear" slope=".3"/></feComponentTransfer><feMerge><feMergeNode in="soft"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>
    <CartesianGrid vertical={false} stroke="var(--activity-grid)" strokeDasharray="4 7"/>
    <XAxis dataKey="date" tickFormatter={(value:string)=>new Intl.DateTimeFormat(undefined,{month:"short",day:"numeric"}).format(calendarDate(value))} tick={{fill:"var(--muted-foreground)",fontSize:12}} tickLine={false} axisLine={false} minTickGap={24} dy={7}/>
    <YAxis tick={{fill:"var(--muted-foreground)",fontSize:12}} allowDecimals={false} tickLine={false} axisLine={false} width={46}/>
    <Tooltip cursor={{fill:"var(--activity-cursor)"}} content={({active,payload,label}:any)=>{
     const row=payload?.find((item:any)=>item.payload?.counts)?.payload as ActivityRow|undefined
     if(!active||!row)return null
     return <div className="activity-tooltip"><div className="activity-tooltip-heading"><span>{new Intl.DateTimeFormat(undefined,{dateStyle:"medium"}).format(calendarDate(String(label)))}</span><strong>{row.total.toLocaleString()} total</strong></div>{categories.map((category,index)=>Number(row.counts[category.name])>0&&<div key={category.name} className="activity-tooltip-item"><span className="activity-series-dot" style={{backgroundColor:colors[index%colors.length]}}/><span>{category.label}</span><strong>{row.counts[category.name].toLocaleString()}</strong></div>)}</div>
    }}/>
    <Area type="monotone" dataKey="total" name="Total" tooltipType="none" stroke={`url(#${id}-trend)`} strokeWidth={1.5} fill={`url(#${id}-wash)`} isAnimationActive={false} dot={false} activeDot={false} style={{pointerEvents:"none"}}/>
    {stackOrder.map(({category,index})=><Bar key={category.name} dataKey={`counts.${category.name}`} name={category.label} stackId="mail" fill={colors[index%colors.length]} maxBarSize={64} shape={(props:any)=>segment(props,index)} isAnimationActive={false} style={{cursor:"pointer"}} onClick={(item:any)=>{if(item?.date)onFocus(item.date,category.name)}}/>)}
   </ComposedChart>
  </ResponsiveContainer>
 </div>
}
