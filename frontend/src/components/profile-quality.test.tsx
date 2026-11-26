import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import type { Outcomes, Point } from '@/lib/profile-outcomes'
import ProfileQuality from './profile-quality'

const chart=vi.hoisted(()=>({row:null as Point|null}))
vi.mock('recharts',()=>({
 ResponsiveContainer:({children}:any)=><div>{children}</div>,
 LineChart:({data,children}:any)=>{chart.row=data.at(-1);return <div>{children}</div>},
 BarChart:({data,children}:any)=>{chart.row=data.at(-1);return <div>{children}</div>},
 Tooltip:({content}:any)=><div data-testid="quality-tooltip">{content({active:true,payload:[{payload:chart.row}]})}</div>,
 CartesianGrid:()=>null,XAxis:()=>null,YAxis:()=>null,Line:()=>null,Bar:()=>null,
}))
afterEach(cleanup)
it('keeps suppressed small samples out of the tooltip until explicitly enabled',()=>{
 const data:Outcomes={version:1,history_since:'2026-11-01',timezone:'America/Chicago',mature_through:{'14':'2026-11-20'},accounts:
  [100,1].map((n,i)=>({id:i+1,label:`profile-${i+1}`,duplicates:0,unmatched:{interview:0,rejection:0},daily:{
   '2026-11-01':{applications:n,windows:{'14':{eligible:n,interview:1,rejection:0,answered:1}}},
  }}))}
 render(<ProfileQuality outcomes={data}/>);
 expect(within(screen.getByTestId('quality-tooltip')).getByText(/profile-1/)).toBeTruthy()
 expect(within(screen.getByTestId('quality-tooltip')).queryByText(/profile-2/)).toBeNull()
 fireEvent.click(screen.getByText('Options'))
 fireEvent.click(screen.getByRole('checkbox',{name:'Show samples below 20'}))
 expect(within(screen.getByTestId('quality-tooltip')).getByText(/profile-2/)).toBeTruthy()
})
