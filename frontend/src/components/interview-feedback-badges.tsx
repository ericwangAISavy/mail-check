import type {InterviewFeedbackTag} from '@/lib/types'
import {AlertTriangle,CheckCircle2} from 'lucide-react'

export const FEEDBACK_OPTIONS:InterviewFeedbackTag[]=['in-person','linkedin','fuck','normal']
export function FeedbackIndicator({tags=[]}:{tags?:InterviewFeedbackTag[]}){
 const warnings=FEEDBACK_OPTIONS.filter(tag=>tag!=='normal'&&tags.includes(tag))
 if(!warnings.length&&!tags.includes('normal'))return null
 const warning=warnings.length>0,label=warning?`Warning feedback: ${warnings.join(', ')}`:'Normal feedback'
 const Icon=warning?AlertTriangle:CheckCircle2
 return <Icon className={`interview-feedback-indicator ${warning?'is-warning':'is-normal'}`} size={warning?16:13} strokeWidth={warning?2.75:2} role="img" aria-label={label}><title>{label}</title></Icon>
}
export function FeedbackBadges({tags=[]}:{tags?:InterviewFeedbackTag[]}){
 if(!tags.length)return null
 return <span className="interview-feedback-badges" role="group" aria-label="Shared company feedback">{FEEDBACK_OPTIONS.filter(tag=>tags.includes(tag)).map(tag=><span key={tag} className={`interview-feedback-badge feedback-${tag}`}>{tag}</span>)}</span>
}
