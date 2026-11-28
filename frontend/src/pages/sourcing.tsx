import { isPageDate, usePageState } from "@/lib/page-state";
import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import {
  TriangleAlert,
  ExternalLink,
  Filter,
  ChevronDown,
  FileSpreadsheet,
  Mail,
  MoreHorizontal,
  Settings2,
  Search,
  SlidersHorizontal,
  Trash2,
  UserRound,
} from "lucide-react";
import { api, request } from "@/lib/api";
import type { Index, QueueCounts, Snapshot, Tab } from "@/lib/sourcing";
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
/** fullToolbar shows the sheet editor's own tool row; the app keeps it hidden. */
export default function SourcingPage({ fullToolbar = false }: { fullToolbar?: boolean } = {}) {
  // The sheet editor renders its day controls into this top-toolbar slot.
  const [daySlot, setDaySlot] = useState<HTMLDivElement | null>(null);
  const { role } = useAuth(),
    admin = role === "admin";
  const [params, setParams] = useSearchParams(),
    [bookId, setBookId] = usePageState("/sourcing", "book", 0, value => Number.isSafeInteger(value) && value >= 0),
    [settings, setSettings] = useState(false),
    [toolsOpen, setToolsOpen] = usePageState("/sourcing", "tools-open", false),
    [filtersOpen, setFiltersOpen] = usePageState("/sourcing", "filters-open", false),
    [dirty, setDirty] = useState(false);
  const index = useQuery({
    queryKey: ["sourcing-index"],
    queryFn: ({ signal }) => request<Index>("/api/sourcing", { signal }),
    refetchInterval: admin ? 15_000 : false,
    refetchOnWindowFocus: admin,
    refetchOnReconnect:admin,
  });
  const client = useQueryClient();
  // The queue shows every unfinished job; a saved day is only an optional history filter.
  const [workDay, setWorkDay] = usePageState("/sourcing", "work-day", "", value => value === "" || value === "undated" || isPageDate(value));
  const [liveQueue, setLiveQueue] = useState<{tab: number; counts: QueueCounts} | null>(null);
  const reportQueue = useCallback((tabId: number, counts: QueueCounts) => setLiveQueue(previous =>
    previous?.tab === tabId && JSON.stringify(previous.counts) === JSON.stringify(counts) ? previous : {tab: tabId, counts}), []);
  const previousDirty = useRef(false);
  const updateDirty = useCallback((value: boolean) => {
    setDirty(value);
    if (previousDirty.current && !value) void client.invalidateQueries({queryKey: ["sourcing-index"]});
    previousDirty.current = value;
  }, [client]);
  const linkDay = workDay || chicagoDay();
  const missingLinks = admin && /^\d{4}-\d{2}-\d{2}$/.test(linkDay)
    ? index.data?.books.filter(book => !book.removed_at && book.job_dates && !book.job_dates.includes(linkDay)) || []
    : [];
  const [deleting, setDeleting] = useState<Tab | null>(null);
  const deletePreview = useQuery({
    queryKey: ["sourcing-delete-preview", deleting?.id],
    queryFn: ({ signal }) => request<Snapshot>(`/api/sourcing/tabs/${deleting!.id}`, { signal }),
    enabled: !!deleting,
    staleTime: 0,
    gcTime: 0,
  });
  const deletion = useMutation({
    mutationFn: ({id, revision}: {id: number; revision: string}) => api.post(`/api/sourcing/tabs/${id}/delete`, {revision}),
    onSuccess: async (_, {id}) => {
      const remaining = book?.tabs.find(t => t.id !== id && (!t.archived || admin && !!book.removed_at));
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
      b.tabs.some((t) => t.id === requestedTab && (!t.archived || admin && !!b.removed_at)),
    ) ||
    index.data?.books.find((b) => b.id === bookId) ||
    index.data?.books[0];
  const tabs = book?.tabs.filter((t) => !t.archived || admin && !!book.removed_at) || [],
    tab = tabs.find((t) => t.id === requestedTab) || tabs[0];
  const tabTodo = tab ? (liveQueue?.tab === tab.id ? liveQueue.counts.todo : tab.queue?.todo) : undefined;
  const search = params.get("q") || "",
    account = params.get("account") || "";
  const [input, setInput] = useState(search);
  // Filters stay hidden until asked for; applying a search or date opens them.
  const filtering = !!search || !!workDay;
  useEffect(() => { if (filtering) setToolsOpen(true); }, [filtering, setToolsOpen]);
  const showTools = toolsOpen;
  useEffect(() => setInput(search), [search]);
  const results = useQuery({
    queryKey: ["sourcing-search", search, account],
    enabled: !!search,
    refetchOnWindowFocus:admin,
    refetchOnReconnect:admin,
    queryFn: ({ signal }) =>
      request<{ results: SearchResult[] }>(
        `/api/sourcing/search?q=${encodeURIComponent(search)}${account ? `&account=${encodeURIComponent(account)}` : ""}`, { signal }
      ),
  });
  // Search covers the selected applicant account.
  const searchForm = (
        <form
          className="sourcing-search"
          onSubmit={(e) => {
            e.preventDefault();
            if (dirty) return;
            const here: Record<string, string> = tab ? { tab: String(tab.id) } : {};
            setParams(input ? { q: input, ...here, ...(tab?.account_id ? { account: String(tab.account_id) } : {}) } : here);
          }}
        >
          <Search size={16} />
          <input
            aria-label="Find application"
            placeholder={tab ? "Search this account’s jobs…" : admin ? "Search all applications" : "Search your applications"}
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
        </form>
  );
  // With a sheet open, Filter and its panel belong to the table's own toolbar.
  // Without a sheet (search results, or none yet) Filter sits in the top bar; never while loading.
  const pageFilters = !!search || (!!index.data && !tab);
  const filterToggle = (
    <Button variant="ghost" size="sm" className="sourcing-tools-toggle" aria-expanded={showTools} aria-controls="sourcing-tools"
      onClick={() => setToolsOpen(!showTools)} title={filtering ? "A search or date is applied" : undefined}>
      <Filter size={14} aria-hidden="true" />Filter
      {filtering && <span className="sourcing-tools-active" role="img" aria-label="Filters applied" />}
    </Button>
  );
  const filterPanel = (
    <div className="sourcing-filter-panel" id="sourcing-tools" hidden={!showTools}>
      {searchForm}
      <div className="sourcing-toolbar-days" ref={setDaySlot} />
    </div>
  );
  return (
    <div className="sourcing-page">
      {/* Scope bar: who and which account; account-level settings and alerts on the right.
          Table-level controls (status, filters, order) live with the table below. */}
      <div className="sourcing-toolbar sourcing-topbar">
        <div className="sourcing-scope">
          <label className="sourcing-select">
            <UserRound size={14} aria-hidden="true" />
            <span className="sourcing-select-label">Bidder</span>
            <select
              aria-label="Bidder workbook"
              value={book?.id || ""}
              disabled={dirty}
              onChange={(e) => {
                setBookId(Number(e.target.value));
                const selected = index.data?.books.find(book => book.id === Number(e.target.value));
                if (selected?.removed_at) setWorkDay(selected.job_dates?.at(-1) || "undated");
                setParams({});
              }}
            >
              <option value="" disabled>
                Job sourcing
              </option>
              {index.data?.books.map((b) => (
                <option value={b.id} key={b.id} className={b.removed_at ? "sourcing-deleted-bidder" : undefined}>
                  {b.name}{b.removed_at ? " (Deleted)" : ""}
                </option>
              ))}
            </select>
            <ChevronDown size={14} aria-hidden="true" />
          </label>
          {book && <>
            <span className="sourcing-scope-sep" aria-hidden="true">/</span>
            <label className="sourcing-select is-account">
              <Mail size={14} aria-hidden="true" />
              <span className="sourcing-select-label">Account</span>
              <select
                aria-label="Applicant account"
                value={tab?.id || ""}
                disabled={dirty || !tabs.length}
                onChange={(e) => setParams({ tab: e.target.value })}
              >
                {!tabs.length && <option value="">No profile sheets yet</option>}
                {tabs.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
              </select>
              {tabTodo != null && <span className="sourcing-select-count" aria-label={`${tabTodo} to do`}>{tabTodo.toLocaleString()}</span>}
              <ChevronDown size={14} aria-hidden="true" />
            </label>
          </>}
        </div>
        <div className="sourcing-topbar-end">
          {missingLinks.length > 0 && <MissingLinks day={linkDay} names={missingLinks.map(book => book.name)} />}
          {admin && (
            <Button variant="ghost" size="sm" className="sourcing-topbar-button" disabled={dirty} onClick={() => setFiltersOpen(true)}>
              <SlidersHorizontal size={14} aria-hidden="true" />Job link filters
            </Button>
          )}
          {admin && <SheetMenu disabled={dirty} canDelete={!!tab && !deletion.isPending} sheet={tab?.title}
            onDelete={() => {if (tab) {deletion.reset(); setDeleting(tab)}}} onSettings={() => setSettings(true)} />}
          {pageFilters && filterToggle}
        </div>
      </div>
      {pageFilters && filterPanel}
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
        <SourcingViewer key={tab.id} tab={tab} initialDay={workDay} onDayChange={setWorkDay} onQueueCounts={counts => reportQueue(tab.id, counts)} queueEnd={filterToggle} filterBar={{open: showTools, content: searchForm}} highlightId={params.get("row_id")||undefined} highlightRow={params.has("row")?Number(params.get("row")):undefined}/>
      ) : tab ? (
        <SourcingEditor
          key={tab.id}
          tab={tab}
          initialDay={workDay}
          onDirty={updateDirty}
          onDayChange={setWorkDay}
          onQueueCounts={counts => reportQueue(tab.id, counts)}
          daySlot={daySlot}
          queueEnd={filterToggle}
          queueBelow={filterPanel}
          fullToolbar={fullToolbar}
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
      <Dialog open={filtersOpen} onOpenChange={setFiltersOpen}>{filtersOpen && <SourcingFilters accountId={tab?.account_id}/>}</Dialog>
      <Dialog open={deleting !== null} onOpenChange={open => {if (!open && !deletion.isPending) setDeleting(null)}}>
        {deleting && <DialogContent><DialogTitle>Delete {deleting.title} tab?</DialogTitle>
          <DialogDescription>This permanently deletes this tab and its job rows. This cannot be undone.</DialogDescription>
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

/** Bidders with no job links on the working day: a compact warning that opens the list. */
function MissingLinks({ day, names }: { day: string; names: string[] }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: Event) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", close); };
  }, [open]);
  return (
    <div className="sourcing-missing-links" ref={root} role="status" aria-live="polite">
      <button type="button" aria-expanded={open} aria-controls="sourcing-missing-list" onClick={() => setOpen(value => !value)}
        title={`No job links · ${day}: ${names.join(", ")}`}>
        <TriangleAlert size={14} aria-hidden="true" />
        {names.length} missing {names.length === 1 ? "submission" : "submissions"}
      </button>
      {open && (
        <div className="sourcing-missing-popover" id="sourcing-missing-list">
          <p>No job links on {day}</p>
          <ul>{names.map(name => <li key={name}>{name}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

/** Sheet-level actions kept out of the way: workbook settings and the destructive delete. */
function SheetMenu({ disabled, canDelete, sheet, onDelete, onSettings }: { disabled: boolean; canDelete: boolean; sheet?: string; onDelete: () => void; onSettings: () => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: Event) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", close); };
  }, [open]);
  return (
    <div className="sourcing-sheet-menu" ref={root}>
      <Button variant="ghost" size="icon" aria-label="Sheet actions" aria-expanded={open} aria-controls="sourcing-sheet-menu" disabled={disabled} onClick={() => setOpen(!open)}>
        <MoreHorizontal size={16} />
      </Button>
      {open && (
        <div className="sourcing-menu" id="sourcing-sheet-menu" role="menu">
          <button type="button" role="menuitem" onClick={() => { setOpen(false); onSettings(); }}><Settings2 size={14} aria-hidden="true" />Manage workbooks and sheets</button>
          <button type="button" role="menuitem" className="is-danger" disabled={!canDelete} onClick={() => { setOpen(false); onDelete(); }} aria-label="Delete current profile sheet">
            <Trash2 size={14} aria-hidden="true" />Delete {sheet ? `“${sheet}”` : "sheet"}…
          </button>
        </div>
      )}
    </div>
  );
}
