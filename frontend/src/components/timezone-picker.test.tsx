import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import TimezonePicker from './timezone-picker'
afterEach(cleanup)
it('searches timezone names without committing partial text and selects with the keyboard',()=>{
 const change=vi.fn()
 render(<TimezonePicker value="UTC" onChange={change}/> )
 const input=screen.getByRole('combobox',{name:'Calendar timezone'})
 fireEvent.focus(input);fireEvent.change(input,{target:{value:'chicago'}})
 expect(screen.getAllByRole('option')).toHaveLength(1)
 expect(change).not.toHaveBeenCalled()
 fireEvent.keyDown(input,{key:'ArrowDown'});fireEvent.keyDown(input,{key:'Enter'})
 expect(change).toHaveBeenCalledWith('America/Chicago')
})
it('allows spaces in searches and restores the chosen value after cancelling an unmatched query',()=>{
 render(<TimezonePicker value="UTC" onChange={vi.fn()}/> )
 const input=screen.getByRole('combobox',{name:'Calendar timezone'}) as HTMLInputElement
 fireEvent.focus(input);fireEvent.change(input,{target:{value:'new york'}})
 expect(screen.getByRole('option',{name:'America/New York'})).toBeTruthy()
 fireEvent.change(input,{target:{value:'not a timezone'}})
 expect(screen.getByRole('status').textContent).toBe('No matching timezones.')
 fireEvent.keyDown(input,{key:'Escape'})
 expect(input.value).toBe('UTC')
 expect(screen.queryByRole('listbox')).toBeNull()
})
it('closes an unfinished search when focus leaves the picker',()=>{
 const change=vi.fn()
 render(<TimezonePicker value="Asia/Tokyo" onChange={change}/>)
 const input=screen.getByRole('combobox',{name:'Calendar timezone'}) as HTMLInputElement
 fireEvent.focus(input);fireEvent.change(input,{target:{value:'Chicago'}})
 fireEvent.blur(input,{relatedTarget:document.body})
 expect(input.value).toBe('Asia/Tokyo')
 expect(change).not.toHaveBeenCalled()
})
