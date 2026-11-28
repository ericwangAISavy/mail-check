import {useCallback,useState,type ComponentProps} from 'react'
import {useMutation,useQueries,useQueryClient} from '@tanstack/react-query'
import {api,request} from '@/lib/api'
import type {InterviewFeedbackTag} from '@/lib/types'
import {Button} from '@/components/ui/button'
import InterviewCalendar from './interview-calendar'
import {FEEDBACK_OPTIONS,FeedbackBadges} from './interview-feedback-badges'
import './interview-feedback.css'

type Entry={tags:InterviewFeedbackTag[];mine:InterviewFeedbackTag[]}
type Feedback={companies:Record<string,Entry>}
const validCompany=(company:string)=>!!company.trim()&&company.length<=200&&!['unknown','unknown company','not provided','other','interview','meeting'].includes(company.trim().toLowerCase())

export function feedbackChunks(companies:string[]){
 const chunks:string[][]=[]
 for(const company of [...new Set(companies.filter(validCompany))].sort()){
  const last=chunks.at(-1)
  if(!last||last.length>=40||encodeURIComponent(JSON.stringify([...last,company])).length>6000)chunks.push([company])
  else last.push(company)
 }
 return chunks
}

function useCompanyFeedback(companies:string[]){
 const chunks=feedbackChunks(companies)
 const queries=useQueries({queries:chunks.map(chunk=>({queryKey:['interview-feedback',chunk],queryFn:({signal}:{signal:AbortSignal})=>request<Feedback>(`/api/interview-feedback?${new URLSearchParams({companies:JSON.stringify(chunk)})}`,{signal}),staleTime:15000,refetchInterval:30000,retry:false}))})
 const data:Record<string,Entry>={}
 for(const query of queries)Object.assign(data,query.data?.companies||{})
 return {data,pending:queries.some(query=>query.isPending),error:queries.find(query=>query.error)?.error,retry:()=>Promise.all(queries.map(query=>query.refetch()))}
}

export function InterviewFeedback({eventId,company}:{eventId:number;company:string|null}){
 const client=useQueryClient()
 const usable=company!==null&&validCompany(company)
 const shared=useCompanyFeedback(usable?[company!]:[])
 const entry=company?shared.data[company]:undefined
 const save=useMutation({mutationFn:(tags:InterviewFeedbackTag[])=>api.post('/api/interview-feedback',{event_id:eventId,company,tags}),onSuccess:()=>client.invalidateQueries({queryKey:['interview-feedback']})})
 const toggle=(tag:InterviewFeedbackTag)=>{const mine=entry?.mine||[];save.mutate(FEEDBACK_OPTIONS.filter(value=>value===tag?!mine.includes(tag):mine.includes(value)))}
 return <section className="interview-feedback-panel" aria-label="Interview feedback">
  <div className="interview-feedback-heading"><strong>Shared feedback</strong><FeedbackBadges tags={entry?.tags}/></div>
  {!usable?<p className="form-hint">Set the company in event details to share feedback.</p>:shared.pending?<p className="form-hint" role="status">Loading feedback…</p>:shared.error?<p role="alert" className="inline-error">Feedback is temporarily unavailable. <Button size="sm" variant="outline" onClick={()=>void shared.retry()}>Retry feedback</Button></p>:<>
   <span className="interview-feedback-label">Your feedback</span>
   <div className="interview-feedback-options" role="group" aria-label="Your company feedback">{FEEDBACK_OPTIONS.map(tag=><button type="button" key={tag} className={`interview-feedback-choice feedback-${tag}`} aria-pressed={!!entry?.mine.includes(tag)} disabled={save.isPending} onClick={()=>toggle(tag)}>{tag}</button>)}</div>
   {save.error&&<p className="inline-error" role="alert">{save.error.message}</p>}
  </>}
 </section>
}

export function SharedInterviewCalendar(props:ComponentProps<typeof InterviewCalendar>){
 const [companies,setCompanies]=useState<string[]>([])
 const onVisibleCompaniesChange=useCallback((next:string[])=>setCompanies(previous=>JSON.stringify(previous)===JSON.stringify(next)?previous:next),[])
 const shared=useCompanyFeedback(companies)
 const events=props.events.map(event=>({...event,feedback_tags:event.company?shared.data[event.company]?.tags:undefined}))
 return <><InterviewCalendar {...props} events={events} onVisibleCompaniesChange={onVisibleCompaniesChange}/>{shared.error&&<p className="form-hint" role="status">Shared feedback is temporarily unavailable. <Button size="sm" variant="ghost" onClick={()=>void shared.retry()}>Retry feedback</Button></p>}</>
}
