import {lazy,Suspense,useState} from "react"
import {version} from "../../package.json"
import {Dialog,DialogContent,DialogTitle,DialogDescription} from "./ui/dialog"
import "./release-history.css"

const ReleaseHistoryEntries = lazy(() => import("./release-history-entries"))

export default function ReleaseHistory(){
  const [open,setOpen]=useState(false)
  return <><button type="button" className="brand-version" aria-label={`Version ${version} — view update history`} title="View version history" onClick={()=>setOpen(true)}>v{version}</button>
    <Dialog open={open} onOpenChange={setOpen}>{open&&<DialogContent className="release-history">
      <div className="release-history-heading"><div><DialogTitle>Version history</DialogTitle><DialogDescription>Updates and improvements to OfferPath.</DialogDescription></div><span className="release-current">Current v{version}</span></div>
      <Suspense fallback={<p role="status" className="inline-loading">Loading version history…</p>}><ReleaseHistoryEntries /></Suspense>
    </DialogContent>}</Dialog>
  </>
}
