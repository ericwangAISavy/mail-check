import {useState} from "react"
import releases from "../../../releases.json"
import {Dialog,DialogContent,DialogTitle,DialogDescription} from "./ui/dialog"
import "./release-history.css"

const categories=[
  {key:"new",label:"New"},
  {key:"improved",label:"Improved"},
  {key:"fixed",label:"Fixed"},
  {key:"performance",label:"Performance"},
] as const

function categoryFor(note:string){
  if (/\b(fix(?:ed|es)?|correct(?:ed|ion)?|repair(?:ed)?|resolv(?:e|ed))\b/i.test(note)) return categories[2]
  if (/\b(faster|performance|speed|optimi[sz](?:ed|ation))\b/i.test(note)) return categories[3]
  if (/\b(improv(?:e|ed|ement|ements)|refin(?:e|ed)|clearer|redesign(?:ed)?)\b/i.test(note)) return categories[1]
  return categories[0]
}

export default function ReleaseHistory(){
  const [open,setOpen]=useState(false)
  const version=releases[0].version
  return <><button type="button" className="brand-version" aria-label={`Version ${version} — view update history`} title="View version history" onClick={()=>setOpen(true)}>v{version}</button>
    <Dialog open={open} onOpenChange={setOpen}>{open&&<DialogContent className="release-history">
      <div className="release-history-heading"><div><DialogTitle>Version history</DialogTitle><DialogDescription>Updates and improvements to OfferPath.</DialogDescription></div><span className="release-current">Current v{version}</span></div>
      <div className="release-legend" role="group" aria-label="Update categories">{categories.map(category=><span key={category.key} className={`release-category release-category-${category.key}`}><i className="release-dot" aria-hidden="true"/>{category.label}</span>)}</div>
      <div className="release-history-entries">{releases.map((release,releaseIndex)=><article className={`release-entry ${releaseIndex===0?"release-entry-latest":""}`} key={release.version} aria-label={`Version ${release.version}`}>
        <header><div className="release-version"><h3>v{release.version}</h3>{releaseIndex===0&&<span className="release-latest">Latest</span>}</div><time dateTime={release.date}>{new Date(release.date+"T12:00:00Z").toLocaleDateString("en-US",{month:"short",day:"numeric",year:"numeric",timeZone:"UTC"})}</time></header>
        <p className="release-title">{release.title}</p>
        <ul role="list" className="release-change-list">{release.changes.map((note,index)=>{
          const category=categoryFor(note)
          return <li key={index} className={`release-change release-category-${category.key}`}><i className="release-dot" aria-hidden="true"/><div><span className="release-change-type">{category.label}</span><p className="release-note">{note}</p></div></li>
        })}</ul>
      </article>)}</div>
    </DialogContent>}</Dialog>
  </>
}
