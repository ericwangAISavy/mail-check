import { useInfiniteQuery } from "@tanstack/react-query"
import { ExternalLink } from "lucide-react"
import { request } from "@/lib/api"
import type { InterviewJobMatchesResponse } from "@/lib/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

function safeJobUrl(value: string) {
  try { const url = new URL(value); return ["http:", "https:"].includes(url.protocol) ? url.href : null } catch { return null }
}

export function InterviewJobMatches({ id }: { id: number }) {
  const query = useInfiniteQuery({
    queryKey: ["interviews", "job-matches", id],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams({ limit: "25" })
      if (pageParam) params.set("cursor", pageParam)
      return request<InterviewJobMatchesResponse>(`/api/interviews/${id}/job-matches?${params}`, { signal })
    },
    getNextPageParam: page => page.next_cursor || undefined,
    retry: false,
  })
  const matches = [...new Map((query.data?.pages || []).flatMap(page => page.matches || []).map(match => [match.row_id, match])).values()]
  return <section className="interview-job-matches" aria-label="Possible job matches">
    <h3>Possible job matches</h3>
    {query.isPending ? <p role="status">Loading job matches…</p> : query.isError && !query.data ? <div><p role="alert" className="inline-error">Could not load job matches. {query.error.message}</p><Button variant="outline" onClick={() => void query.refetch()}>Retry job matches</Button></div> : <>
      {query.isRefetchError && !query.isFetchNextPageError && <div><p role="alert" className="inline-error">Could not refresh job matches.</p><Button variant="outline" disabled={query.isFetching} onClick={() => void query.refetch()}>Retry job matches</Button></div>}
      {!matches.length && <p>No possible job matches found.</p>}
      <ul className="interview-job-match-list">{matches.map(match => {
        const url = safeJobUrl(match.link)
        const day = match.application_date || match.work_date
        const date = day ? new Date(day + "T00:00:00") : null
        return <li key={match.row_id}>
          <div className="interview-job-match-head">
            <strong>{match.company || "Company unknown"}{match.role ? ` · ${match.role}` : ""}</strong>
            {date && !Number.isNaN(date.getTime()) && <time dateTime={day!} title={match.application_date ? "Recorded application date" : "Date the job was saved"}>
              {date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}</time>}
          </div>
          <div className="interview-job-match-meta">
            <Badge variant={match.applied ? "default" : "muted"} title={match.applied ? "Application confirmed" : "Saved link; application not confirmed"}>
              {match.applied ? "Applied by" : "Saved by"} {match.bidder_name || "unknown bidder"}</Badge>
            {match.archived && <Badge variant="outline">Archived</Badge>}
          </div>
          {url ? <a className="interview-explicit-link" href={url} target="_blank" rel="noopener noreferrer">{url}<ExternalLink size={14} aria-hidden="true"/></a> : <span className="form-hint">Job link unavailable</span>}
        </li>
      })}</ul>
      {query.isFetchNextPageError && <p role="alert" className="inline-error">Could not load more job matches.</p>}
      {query.hasNextPage && <Button variant="outline" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>{query.isFetchingNextPage ? "Loading more job matches…" : query.isFetchNextPageError ? "Retry loading more job matches" : "Load more job matches"}</Button>}
    </>}
  </section>
}
