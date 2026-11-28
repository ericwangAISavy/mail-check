import {lazy,Suspense,useState} from "react"
import {version} from "../../package.json"
import {Info} from "lucide-react"
import {Dialog,DialogContent,DialogTitle,DialogDescription,DialogTrigger} from "./ui/dialog"
import "./release-history.css"

const ReleaseHistoryEntries = lazy(() => import("./release-history-entries"))

export default function ReleaseHistory(){
  const [open,setOpen]=useState(false)
  return <Dialog open={open} onOpenChange={setOpen}>
    <DialogTrigger asChild><button type="button" className="sidebar-control sidebar-version" aria-label={`Version ${version} — view update history`} title={`OfferPath v${version} · View update history`}>
      <Info size={16} strokeWidth={1.75} aria-hidden="true" /><span>v{version}</span>
    </button></DialogTrigger>
    {open&&<DialogContent className="release-history">
      <div className="release-history-heading"><div><DialogTitle>Version history</DialogTitle><DialogDescription>Updates and improvements to OfferPath.</DialogDescription></div><span className="release-current">Current v{version}</span></div>
      <Suspense fallback={<p role="status" className="inline-loading">Loading version history…</p>}><ReleaseHistoryEntries /></Suspense>
    </DialogContent>}
  </Dialog>
}
