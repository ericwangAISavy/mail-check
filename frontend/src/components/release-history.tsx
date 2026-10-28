import {useState} from "react"
import releases from "../../../releases.json"
import {Dialog,DialogContent,DialogTitle,DialogDescription} from "./ui/dialog"
import "./release-history.css"

export default function ReleaseHistory(){
  const [open,setOpen]=useState(false)
  const version=releases[0].version
  return <><button type="button" className="brand-version" aria-label={`Version ${version} — view update history`} title="View version history" onClick={()=>setOpen(true)}>v{version}</button>
    <Dialog open={open} onOpenChange={setOpen}>{open&&<DialogContent className="release-history"><DialogTitle>Version history</DialogTitle><DialogDescription>What changed in OfferPath. Current version: {version}.</DialogDescription>
      <div className="release-history-entries">{releases.map(release=><article key={release.version}><header><h3>v{release.version}</h3><time dateTime={release.date}>{new Date(release.date+"T12:00:00Z").toLocaleDateString("en-US",{month:"short",day:"numeric",year:"numeric",timeZone:"UTC"})}</time></header><p>{release.title}</p><ul>{release.changes.map((note,index)=><li key={index}>{note}</li>)}</ul></article>)}</div>
    </DialogContent>}</Dialog>
  </>
}
