import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import {CategoryBadge} from './common'

afterEach(cleanup)
it('marks matched application receipts separately from their category',()=>{
 render(<CategoryBadge message={{category:'application_ack',category_label:'Application received',tier:'info',deadline_display:'',application_matched:true}}/>);
 expect(screen.getByText('Matched')).toBeTruthy();expect(screen.getByText('Application received')).toBeTruthy()
})
it('leaves unmatched receipts and other categories without the mark',()=>{
 const {rerender}=render(<CategoryBadge message={{category:'application_ack',category_label:'Application received',tier:'info',deadline_display:'',application_matched:false}}/>);
 expect(screen.queryByText('Matched')).toBeNull()
 rerender(<CategoryBadge message={{category:'interview_invite',category_label:'Interview',tier:'act',deadline_display:'',application_matched:true}}/>);
 expect(screen.queryByText('Matched')).toBeNull()
})
