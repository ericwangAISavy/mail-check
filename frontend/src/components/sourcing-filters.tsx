import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api, request } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog"

export default function SourcingFilters() {
  const client = useQueryClient()
  const query = useQuery({queryKey:["sourcing-filters"],queryFn:()=>request<{companies:string[]}>("/api/sourcing/filters")})
  const [draft,setDraft] = useState<string | null>(null)
  const save = useMutation({mutationFn:()=>api.post<{companies:string[]}>("/api/sourcing/filters",{companies:(draft ?? query.data?.companies.join("\n") ?? "").split("\n").map(s=>s.trim()).filter(Boolean)}),onSuccess:data=>{client.setQueryData(["sourcing-filters"],data);setDraft(null)}})
  return <DialogContent><DialogTitle>Job link filters</DialogTitle>
    <DialogDescription>New job rows are filtered automatically. Duplicate links are removed across all tabs for the same account, including other bidders and dates. Existing rows stay saved.</DialogDescription>
    <label htmlFor="blocked-companies">Blocked companies · one company per line</label>
    <p className="form-hint">Applies to every account. Matches the full Company name, ignoring case, spaces and punctuation.</p>
    <textarea id="blocked-companies" rows={10} maxLength={201000} value={draft ?? query.data?.companies.join("\n") ?? ""} onChange={e=>{setDraft(e.target.value);save.reset()}} disabled={query.isPending || save.isPending} placeholder={"Company One\nCompany Two"} style={{width:"100%",padding:12,background:"var(--background)",color:"var(--foreground)",border:"1px solid var(--border)",borderRadius:6}} />
    {(query.error || save.error) && <p role="alert" className="inline-error">{(query.error || save.error)?.message}</p>}
    {save.isSuccess && draft === null && <p role="status">Company filters saved.</p>}
    <Button disabled={query.isPending || query.isError || save.isPending} onClick={()=>save.mutate()}>{save.isPending ? "Saving…" : "Save company filters"}</Button>
  </DialogContent>
}
