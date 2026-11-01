import {useState} from "react"
import {api} from "@/lib/api"
import {useAuth} from "./auth"
import {Button} from "./ui/button"
import {Dialog,DialogContent,DialogTitle,DialogDescription} from "./ui/dialog"
export default function ChangePassword(){
  const {signOut}=useAuth()
  const [open,setOpen]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState("")
  return <><Button variant="ghost" size="sm" onClick={()=>{setError("");setOpen(true)}}>Change password</Button><Dialog open={open} onOpenChange={value=>{if(!busy)setOpen(value)}}>{open&&<DialogContent><DialogTitle>Change your password</DialogTitle><DialogDescription>This changes only your login password. You will sign in again afterward.</DialogDescription><form className="form-stack" onSubmit={async event=>{
    event.preventDefault();setError("");const data=new FormData(event.currentTarget)
    if(data.get("password")!==data.get("confirm")){setError("Passwords do not match.");return}
    setBusy(true)
    try{await api.post("/api/auth/password",{role:"admin",password:data.get("password")});await signOut()}
    catch(e){setError(e instanceof Error?e.message:"Could not change password.")}
    finally{setBusy(false)}
  }}><label>New password<input type="password" name="password" required minLength={12} maxLength={256} autoComplete="new-password"/></label><label>Confirm password<input type="password" name="confirm" required minLength={12} maxLength={256} autoComplete="new-password"/></label>{error&&<p role="alert" className="inline-error">{error}</p>}<Button disabled={busy}>{busy?"Saving…":"Update password"}</Button></form></DialogContent>}</Dialog></>
}
