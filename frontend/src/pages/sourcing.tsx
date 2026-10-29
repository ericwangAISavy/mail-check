import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import {
  TriangleAlert,
  ExternalLink,
  FileSpreadsheet,
  Search,
  Settings2,
  Trash2,
} from "lucide-react";
import { api, request } from "@/lib/api";
import type { Index, Snapshot, Tab } from "@/lib/sourcing";
import { chicagoDay } from "@/lib/sourcing";
import { useAuth } from "@/components/auth";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import SourcingViewer from "@/components/sourcing-viewer";
import SourcingEditor from "@/components/sourcing-editor";
import SourcingFilters from "@/components/sourcing-filters";
import SourcingSettings from "@/components/sourcing-settings";
import "./sourcing.css";
interface SearchResult {
  tab_id: number;
  row_id: string;
  work_date?: string | null;
  bidder: string;
  profile: string;
  company: string;
  role: string;
  link: string;
  row: number;
  refreshed_at: number;
}
export default function SourcingPage() {
  const { role } = useAuth(),
    admin = role === "admin";
  const [params, setParams] = useSearchParams(),
    [bookId, setBookId] = useState(0),
    [settings, setSettings] = useState(false),
    [filtersOpen, setFiltersOpen] = useState(false),
    [dirty, setDirty] = useState(false);
  const index = useQuery({
    queryKey: ["sourcing-index"],
    queryFn: () => request<Index>("/api/sourcing"),
    refetchInterval: admin ? 15_000 : false,
    refetchOnWindowFocus: admin,
    refetchOnReconnect:admin,
  });
  const client = useQueryClient();
  const [workDay, setWorkDay] = useState(chicagoDay);
  const previousDirty = useRef(false);
  const updateDirty = useCallback((value: boolean) => {
    setDirty(value);
    if (previousDirty.current && !value) void client.invalidateQueries({queryKey: ["sourcing-index"]});
    previousDirty.current = value;
  }, [client]);
  const missingLinks = admin && /^\d{4}-\d{2}-\d{2}$/.test(workDay)
    ? index.data?.books.filter(book => book.job_dates && !book.job_dates.includes(workDay)) || []
    : [];
  const [deleting, setDeleting] = useState<Tab | null>(null);
  const deletePreview = useQuery({
    queryKey: ["sourcing-delete-preview", deleting?.id],
    queryFn: () => request<Snapshot>(`/api/sourcing/tabs/${deleting!.id}`),
    enabled: !!deleting,
    staleTime: 0,
    gcTime: 0,
  });
  const deletion = useMutation({
    mutationFn: ({id, revision}: {id: number; revision: string}) => api.post(`/api/sourcing/tabs/${id}/delete`, {revision}),
    onSuccess: async (_, {id}) => {
      const remaining = book?.tabs.find(t => t.id !== id && !t.archived);
      client.setQueryData<Index>(["sourcing-index"], previous => previous ? {...previous, books: previous.books.map(book => ({...book, tabs: book.tabs.filter(tab => tab.id !== id)}))} : previous);
      setDeleting(null);
      setParams(remaining ? {tab: String(remaining.id)} : {});
      await Promise.all([
        client.invalidateQueries({queryKey: ["sourcing-index"]}),
        client.invalidateQueries({queryKey: ["sourcing-search"]}),
        client.invalidateQueries({queryKey: ["payments"]}),
      ]);
    },
  });
  const requestedTab = Number(params.get("tab")) || 0;
  const book =
    index.data?.books.find((b) =>
      b.tabs.some((t) => t.id === requestedTab && !t.archived),
    ) ||
    index.data?.books.find((b) => b.id === bookId) ||
    index.data?.books[0];
  const tabs = book?.tabs.filter((t) => !t.archived) || [],
    tab = tabs.find((t) => t.id === requestedTab) || tabs[0];
  const search = params.get("q") || "",
    account = params.get("account") || "";
  const [input, setInput] = useState(search);
  useEffect(() => setInput(search), [search]);
  const results = useQuery({
    queryKey: ["sourcing-search", search, account],
    enabled: !!search,
    refetchOnWindowFocus:admin,
    refetchOnReconnect:admin,
    queryFn: () =>
      request<{ results: SearchResult[] }>(
        `/api/sourcing/search?q=${encodeURIComponent(search)}${account ? `&account=${encodeURIComponent(account)}` : ""}`,
      ),
  });
  return (
    <div className="sourcing-page">
      <div className="sourcing-toolbar">
        <FileSpreadsheet size={22} />
        <select
          aria-label="Bidder workbook"
          value={book?.id || ""}
          disabled={dirty}
          onChange={(e) => {
            setBookId(Number(e.target.value));
            setParams({});
          }}
        >
          <option value="" disabled>
            Job sourcing
          </option>
          {index.data?.books.map((b) => (
            <option value={b.id} key={b.id}>
              {b.name}
            </option>
          ))}
        </select>
        <span className="sourcing-book-title">{book?.title}</span>
        {missingLinks.length > 0 && <div className="sourcing-missing-links" role="status" aria-live="polite">
          <TriangleAlert size={16} aria-hidden="true" />
          <span><strong>No job links · {workDay}:</strong> {missingLinks.map(book => book.name).join(", ")}</span>
        </div>}
        <form
          className="sourcing-search"
          onSubmit={(e) => {
            e.preventDefault();
            if (!dirty) setParams(input ? { q: input } : {});
          }}
        >
          <Search size={16} />
          <input
            aria-label="Find application"
            placeholder={
              admin ? "Search all applications" : "Search your applications"
            }
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          <Button size="sm" variant="ghost" disabled={dirty}>
            Search
          </Button>
        </form>
        {admin && <Button variant="outline" size="sm" disabled={dirty} onClick={() => setFiltersOpen(true)}>Job link filters</Button>}
        {admin && <Button size="icon" variant="ghost" aria-label="Sourcing settings" disabled={dirty} onClick={()=>setSettings(true)}><Settings2 size={18}/></Button>}
      </div>
      {index.error && (
        <p className="inline-error" role="alert">
          {index.error.message}
        </p>
      )}
      {search ? (
        <div className="sourcing-search-results">
          <div className="sheet-actions">
            <h2>Applications matching “{search}”</h2>
            {admin && <Button variant="outline" onClick={() => void results.refetch()}>
              Refresh results
            </Button>}
            <Button variant="ghost" onClick={() => setParams({})}>
              Back to sheet
            </Button>
          </div>
          {account && (
            <p>
              Showing the interview’s profile.{" "}
              <button onClick={() => setParams({ q: search })}>
                Search all profiles
              </button>
            </p>
          )}
          {results.error && (
            <p className="inline-error" role="alert">
              {results.error.message}
            </p>
          )}
          {results.isPending ? (
            <p>Searching saved jobs…</p>
          ) : !results.data?.results.length ? (
            <p>No matching applications.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Role</th>
                  <th>Bidder / profile</th>
                  <th>Date</th>
                  <th>Application</th>
                  <th>Last updated</th>
                </tr>
              </thead>
              <tbody>
                {results.data?.results.map((r) => (
                  <tr key={`${r.tab_id}:${r.row_id}`}>
                    <td>{r.company}</td>
                    <td>{r.role}</td>
                    <td>
                      <button
                        onClick={() =>
                          setParams({ tab: String(r.tab_id), row_id: r.row_id })
                        }
                      >
                        {r.bidder} · {r.profile} · row {r.row}
                      </button>
                    </td>
                    <td>{r.work_date || "Undated"}</td>
                    <td>
                      {/^https?:\/\//i.test(r.link) ? (
                        <a href={r.link} target="_blank" rel="noreferrer">
                          Open job <ExternalLink size={13} />
                        </a>
                      ) : (
                        r.link
                      )}
                    </td>
                    <td>{new Date(r.refreshed_at * 1000).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : tab && !admin ? (
        <SourcingViewer key={tab.id} tab={tab} onDayChange={setWorkDay} highlightId={params.get("row_id")||undefined} highlightRow={params.has("row")?Number(params.get("row")):undefined}/>
      ) : tab ? (
        <SourcingEditor
          key={tab.id}
          tab={tab}
          onDirty={updateDirty}
          onDayChange={setWorkDay}
          highlightId={params.get("row_id") || undefined}
          highlightRow={
            params.has("row") ? Number(params.get("row")) : undefined
          }
        />
      ) : (
        <div className="sourcing-empty">
          <FileSpreadsheet size={40} />
          <h2>
            {index.isPending
              ? "Loading sheets…"
              : admin
                ? "Create your job sourcing sheets"
                : "Your profile sheet is not ready yet"}
          </h2>
          <p>
            {admin
              ? "Create a bidder workbook, then add its assigned profile sheets. Paste jobs straight into the grid or import a CSV file."
              : "Ask your admin to create your workbook and profile sheets."}
          </p>
          {admin && (
            <Button onClick={() => setSettings(true)}>
              Set up job sourcing
            </Button>
          )}
        </div>
      )}
      {!search && book && (
        <div
          className="sourcing-tabs"
          role="tablist"
          aria-label="Profile sheets"
        >
          {tabs.map((t) => (
            <button
              role="tab"
              key={t.id}
              aria-selected={tab?.id === t.id}
              disabled={dirty}
              onClick={() => setParams({ tab: String(t.id) })}
            >
              {t.title}
            </button>
          ))}
          {admin && (
            <button
              aria-label="Add profile sheet"
              disabled={dirty}
              onClick={() => setSettings(true)}
            >
              +
            </button>
          )}
          {admin && tab && <button className="sourcing-delete-tab" aria-label="Delete current profile sheet"
            disabled={dirty || deletion.isPending} onClick={() => {deletion.reset(); setDeleting(tab)}}>
            <Trash2 size={14} />Delete tab
          </button>}
        </div>
      )}
      <Dialog open={filtersOpen} onOpenChange={setFiltersOpen}>{filtersOpen && <SourcingFilters />}</Dialog>
      <Dialog open={deleting !== null} onOpenChange={open => {if (!open && !deletion.isPending) setDeleting(null)}}>
        {deleting && <DialogContent><DialogTitle>Delete {deleting.title} tab?</DialogTitle>
          <DialogDescription>This permanently deletes this tab and all its job rows. Its checked links will be removed from payment breakdowns. Received emails and recorded payments stay saved. This cannot be undone.</DialogDescription>
          {deletePreview.isPending ? <p>Loading tab details…</p> : deletePreview.error ? <p role="alert" className="inline-error">{deletePreview.error.message}</p> : <p>{deletePreview.data?.rows.slice(1).filter(row => row.some((cell, i) => deletePreview.data?.columns[i]?.kind !== "check" && String(cell.value).trim())).length || 0} job rows in this tab.</p>}
          {deletion.error && <p role="alert" className="inline-error">{deletion.error.message}</p>}
          <div className="sheet-actions"><Button variant="ghost" disabled={deletion.isPending} onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="destructive" disabled={dirty || !deletePreview.data || deletePreview.isFetching || deletion.isPending} onClick={() => deletion.mutate({id: deleting.id, revision: deletePreview.data!.revision})}>
              {deletion.isPending ? "Deleting…" : "Delete tab permanently"}
            </Button></div>
        </DialogContent>}
      </Dialog>
      <Dialog open={settings} onOpenChange={setSettings}>
        {settings && index.data && (
          <SourcingSettings
            index={index.data}
            refresh={() => void index.refetch()}
          />
        )}
      </Dialog>
    </div>
  );
}
