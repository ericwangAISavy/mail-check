import { useBlocker } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog"
export default function SourcingDraftGuard({dirty,saving}:{dirty:boolean;saving:boolean}) {
  const blocker=useBlocker(({currentLocation,nextLocation})=>dirty&&(currentLocation.pathname!==nextLocation.pathname||currentLocation.search!==nextLocation.search))
  return <Dialog open={blocker.state==='blocked'} onOpenChange={open=>{if(!open&&blocker.state==='blocked')blocker.reset()}}><DialogContent><DialogTitle>Keep your unsaved edits?</DialogTitle><DialogDescription>{saving?'A save is still in progress. Wait for its result before leaving.':'Your draft has not been saved to Google. Keep editing or discard it to leave this sheet.'}</DialogDescription><div className="sheet-actions"><Button onClick={()=>{if(blocker.state==='blocked')blocker.reset()}}>Keep editing</Button><Button variant="outline" disabled={saving} onClick={()=>{if(blocker.state==='blocked')blocker.proceed()}}>Discard and leave</Button></div></DialogContent></Dialog>
}
