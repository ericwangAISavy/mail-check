import { useQueryClient } from "@tanstack/react-query";
import { operationId } from "@/lib/operation-id";
import {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { UNSAFE_DataRouterContext } from "react-router-dom";
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Bold,
  Check,
  Download,
  Filter,
  Italic,
  Plus,
  Redo2,
  RefreshCw,
  Search,
  Trash2,
  Undo2,
  Upload,
  WrapText,
} from "lucide-react";
import { api, request } from "@/lib/api";
import {
  defaultView,
  chicagoDay,
  visibleRows,
  hasUnexpectedEdits,
  mergeChanges,
  nativeChanges,
  normalStyle,
  parseTSV,
  type CellStyle,
  type Change,
  type Selection,
  type SheetView,
  type Snapshot,
  type Tab,
} from "@/lib/sourcing";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import SourcingDraftGuard from "./sourcing-draft-guard";
import SourcingImport from "./sourcing-import";
import SourcingDays from "./sourcing-days";
import { SheetGrid } from "./sourcing-grid";
type History = { undo: Change[]; redo: Change[] };
type StructureAction =
  | "insert_rows"
  | "delete_rows"
  | "add_column"
  | "rename_column"
  | "delete_column";
export default function SourcingEditor({
  tab,
  onDirty,
  highlightId,
  highlightRow,
  initialDay,
  onDayChange,
}: {
  tab: Tab;
  onDirty: (dirty: boolean) => void;
  highlightId?: string;
  highlightRow?: number;
  initialDay?: string;
  onDayChange?: (day: string) => void;
}) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null),
    [changes, setChanges] = useState<Change[]>([]),
    [saving, setSaving] = useState(false),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true);
  const [selection, setSelection] = useState<Selection>({
      rows: [1],
      columns: [0],
    }),
    [view, setView] = useState<SheetView>(defaultView),
    [showFilters, setShowFilters] = useState(false),
    [structureOpen, setStructureOpen] = useState<StructureAction | null>(null),
    [importOpen, setImportOpen] = useState(false),
    [importDirty, setImportDirty] = useState(false),
    [appendOpen, setAppendOpen] = useState(false),
    [appendText, setAppendText] = useState(""),
    [typing, setTyping] = useState(false);
  const client = useQueryClient();
  const compactAfterPaste = useRef(false);
  const [rowDeleteNotice, setRowDeleteNotice] = useState("");
  const [day, setDay] = useState(initialDay || chicagoDay());
  useEffect(() => { onDayChange?.(day); }, [day, onDayChange]);
  const scopedView = useMemo(() => ({ ...view, day }), [view, day]);
  const [headerDraft, setHeaderDraft] = useState<{
    col: number;
    title: string;
  } | null>(null);
  const [assignOpen, setAssignOpen] = useState(false),
    [assignDay, setAssignDay] = useState(chicagoDay());
  const assignContext = useRef<{ revision: string; ids: string[] } | null>(
    null,
  );
  const resolvedHighlight = useRef("");
  const typingRef = useRef(typing);
  typingRef.current = typing;
  const structureContext = useRef<{
      snapshot: Snapshot;
      selection: Selection;
    } | null>(null),
    actionContext = useRef<{ structural: boolean; expected?: Change[] }>({
      structural: false,
    });
  const dataRouter = useContext(UNSAFE_DataRouterContext),
    history = useRef<History[]>([]),
    future = useRef<History[]>([]),
    inFlight = useRef(false),
    alive = useRef(true),
    draft = useRef(changes),
    base = useRef(snapshot),
    auxDirty = useRef(false),
    loadSequence = useRef(0),
    lastAction = useRef<(() => Promise<Snapshot>) | null>(null),
    saveOperation = useRef<{ body: string; id: string } | null>(null),
    resizeTimer = useRef(0);
  draft.current = changes;
  base.current = snapshot;
  auxDirty.current = importDirty || !!appendText || !!headerDraft || assignOpen;
  const dirty =
      changes.length > 0 ||
      importDirty ||
      !!appendText ||
      typing ||
      !!headerDraft ||
      assignOpen,
    locked = saving || !!error || importOpen || appendOpen;
  const load = useCallback(async () => {
    if (
      inFlight.current ||
      draft.current.length ||
      auxDirty.current ||
      typingRef.current
    )
      return;
    const sequence = ++loadSequence.current;
    setLoading(true);
    try {
      const data = await request<Snapshot>(`/api/sourcing/tabs/${tab.id}`);
      if (
        alive.current &&
        sequence === loadSequence.current &&
        !draft.current.length &&
        !inFlight.current &&
        !auxDirty.current &&
        !typingRef.current
      ) {
        if (base.current?.revision !== data.revision) {
          history.current = [];
          future.current = [];
        }
        setSnapshot(data);
        setChanges([]);
        setError("");
        lastAction.current = null;
      }
    } catch (e) {
      if (alive.current)
        setError(e instanceof Error ? e.message : "Could not load sheet.");
    } finally {
      if (alive.current && sequence === loadSequence.current) setLoading(false);
    }
  }, [tab.id]);
  useEffect(() => {
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
      window.clearTimeout(resizeTimer.current);
    };
  }, [load]);
  useEffect(() => {
    onDirty(dirty || saving);
    return () => onDirty(false);
  }, [dirty, saving, onDirty]);
  useEffect(() => {
    const unload = (e: BeforeUnloadEvent) => {
      if (
        draft.current.length ||
        auxDirty.current ||
        inFlight.current ||
        typingRef.current
      ) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", unload);
    return () => window.removeEventListener("beforeunload", unload);
  }, []);
  useEffect(() => {
    const focus = () => {
      if (document.visibilityState === "visible") void load();
    };
    const timer = window.setInterval(focus, 15000);
    window.addEventListener("focus", focus);
    window.addEventListener("mailcheck:check-completed", focus);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", focus);
      window.removeEventListener("mailcheck:check-completed", focus);
    };
  }, [load]);
  const execute = useCallback(
    async (
      action: () => Promise<Snapshot>,
      structural = false,
      expected?: Change[],
    ) => {
      if (inFlight.current) return;
      const starting = base.current;
      loadSequence.current++;
      setLoading(false);
      actionContext.current = { structural, expected };
      inFlight.current = true;
      setSaving(true);
      setError("");
      lastAction.current = action;
      try {
        const result = await action();
        void client.invalidateQueries({queryKey: ["payments"]});
        if (alive.current) {
          if (
            structural ||
            (starting && hasUnexpectedEdits(starting, result, expected || []))
          ) {
            history.current = [];
            future.current = [];
          }
          setSnapshot(result);
          setChanges([]);
          compactAfterPaste.current = false;
          if (structural) setView(defaultView);
          lastAction.current = null;
          saveOperation.current = null;
        }
      } catch (e) {
        if (alive.current)
          setError(
            e instanceof Error
              ? e.message
              : "Save failed. Your draft is preserved.",
          );
      } finally {
        inFlight.current = false;
        if (alive.current) setSaving(false);
      }
    },
    [client],
  );
  const save = useCallback(async () => {
    if (!draft.current.length || !base.current || typingRef.current) return;
    try {
      const changes = nativeChanges(base.current, draft.current),
        body = JSON.stringify(changes);
      if (saveOperation.current?.body !== body)
        saveOperation.current = { body, id: operationId() };
      const payload = {
        operation: saveOperation.current.id,
        changes,
        work_date: day,
        ...(compactAfterPaste.current ? {compact_rows: true} : {}),
      };
      await execute(
        () => api.post<Snapshot>(`/api/sourcing/tabs/${tab.id}/save`, payload),
        false,
        draft.current,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    }
  }, [execute, tab.id, day]);
  useEffect(() => {
    if (
      !changes.length ||
      saving ||
      error ||
      importOpen ||
      appendOpen ||
      typing
    )
      return;
    const timer = window.setTimeout(() => void save(), 1200);
    return () => window.clearTimeout(timer);
  }, [changes, saving, error, save, importOpen, appendOpen, typing]);
  const edit = (next: Change[]) => {
    if (locked || !snapshot) return;
    const keys = new Map(
        [...changes, ...next].map((c) => [`${c.row}:${c.col}`, c]),
      ),
      undo: Change[] = [],
      redo: Change[] = [];
    for (const cell of keys.values()) {
      const original = snapshot.rows[cell.row]?.[cell.col],
        before = changes.find((c) => c.row === cell.row && c.col === cell.col),
        after = next.find((c) => c.row === cell.row && c.col === cell.col);
      const old = {
          row: cell.row,
          col: cell.col,
          value: before?.value ?? String(original?.value ?? ""),
          style: normalStyle({ ...original?.style, ...before?.style }),
        },
        value = {
          row: cell.row,
          col: cell.col,
          value: after?.value ?? String(original?.value ?? ""),
          style: normalStyle({ ...original?.style, ...after?.style }),
        };
      if (JSON.stringify(old) !== JSON.stringify(value)) {
        undo.push(old);
        redo.push(value);
      }
    }
    if (undo.length) {
      history.current.push({ undo, redo });
      future.current = [];
    }
    setChanges(next);
  };
  const undo = () => {
    const item = history.current.pop();
    if (item && snapshot) {
      future.current.push(item);
      setChanges(mergeChanges(snapshot, changes, item.undo));
    }
  };
  const redo = () => {
    const item = future.current.pop();
    if (item && snapshot) {
      history.current.push(item);
      setChanges(mergeChanges(snapshot, changes, item.redo));
    }
  };
  const format = (style: CellStyle) => {
    if (!snapshot || selection.rows.length * selection.columns.length > 10000)
      return;
    const values: Change[] = [];
    for (const row of selection.rows)
      for (const col of selection.columns) {
        const previous = changes.find((c) => c.row === row && c.col === col);
        values.push({
          row,
          col,
          style: normalStyle({
            ...snapshot.rows[row]?.[col]?.style,
            ...previous?.style,
            ...style,
          }),
        });
      }
    edit(mergeChanges(snapshot, changes, values));
  };
  const selectedStyle = normalStyle({
    ...snapshot?.rows[selection.rows[0]]?.[selection.columns[0]]?.style,
    ...changes.find(
      (c) => c.row === selection.rows[0] && c.col === selection.columns[0],
    )?.style,
  });
  const openStructure = (action: StructureAction) => {
    if (snapshot) {
      structureContext.current = {
        snapshot,
        selection: {
          rows: [...selection.rows],
          columns: [...selection.columns],
        },
      };
      setStructureOpen(action);
    }
  };
  const structure = async (command: Record<string, unknown>) => {
    if (!snapshot || dirty || inFlight.current) return;
    setStructureOpen(null);
    const payload = {
      operation: operationId(),
      revision:
        structureContext.current?.snapshot.revision || snapshot.revision,
      work_date: day,
      ...command,
    };
    await execute(
      () =>
        api.post<Snapshot>(`/api/sourcing/tabs/${tab.id}/structure`, payload),
      true,
    );
  };
  const deleteSelectedRows = async (rows = selection.rows) => {
    const current = base.current;
    if (!current || inFlight.current || locked) return;
    if (draft.current.length || typingRef.current || auxDirty.current) {
      setRowDeleteNotice("Wait for Saved before deleting selected rows.");
      return;
    }
    const ids = [...new Set(rows.filter(row => row > 0).map(row => current.row_ids[row]).filter(Boolean))];
    if (!ids.length) return;
    if (ids.length > 1000) {setRowDeleteNotice("Select up to 1,000 rows to delete at a time."); return;}
    setRowDeleteNotice("");
    const payload = {operation: operationId(), revision: current.revision, action: "delete_rows", ids, work_date: day};
    await execute(async () => {
      const result = await api.post<Snapshot>(`/api/sourcing/tabs/${tab.id}/structure`, payload);
      void client.invalidateQueries({queryKey: ["payments"]});
      return result;
    }, true);
  };
  const resize = (col: number, width: number) => {
    window.clearTimeout(resizeTimer.current);
    resizeTimer.current = window.setTimeout(() => {
      const current = base.current;
      if (
        !current ||
        draft.current.length ||
        inFlight.current ||
        auxDirty.current
      )
        return;
      const payload = {
        operation: operationId(),
        revision: current.revision,
        action: "resize_column",
        column_id: current.columns[col].id,
        width: Math.max(70, Math.min(width, 1200)),
      };
      void execute(
        () =>
          api.post<Snapshot>(`/api/sourcing/tabs/${tab.id}/structure`, payload),
        true,
      );
    }, 600);
  };
  const reload = async () => {
    if (
      dirty &&
      !window.confirm(
        "Discard this draft and reload the saved sheet? Download your draft first if needed.",
      )
    )
      return;
    setChanges([]);
    draft.current = [];
    setAppendText("");
    setHeaderDraft(null);
    setImportDirty(false);
    auxDirty.current = false;
    setAppendOpen(false);
    setImportOpen(false);
    saveOperation.current = null;
    history.current = [];
    future.current = [];
    await load();
  };
  const download = () => {
    const url = URL.createObjectURL(
      new Blob(
        [
          JSON.stringify(
            {
              tab: tab.title,
              revision: snapshot?.revision,
              row_ids: snapshot?.row_ids,
              columns: snapshot?.columns,
              changes,
              appendRows: appendText,
              work_date: day,
              headerDraft,
            },
            null,
            2,
          ),
        ],
        { type: "application/json" },
      ),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "mailcheck-sheet-draft.json";
    link.click();
    URL.revokeObjectURL(url);
  };
  const appendJobs = async (pastedRows?: string[][]) => {
    if (!snapshot || (!appendText && !pastedRows)) return;
    const rows = (pastedRows || parseTSV(appendText)).filter(row => row.some(value => value.trim()));
    if (!rows.length) return;
    if (rows.reduce((n, r) => n + r.length, 0) > 10000) {
      setError("Append up to 10,000 cells at a time.");
      return;
    }
    const payload = {
      operation: operationId(),
      revision: snapshot.revision,
      work_date: day,
      rows,
    };
    await execute(async () => {
      const result = await api.post<Snapshot>(
        `/api/sourcing/tabs/${tab.id}/append`,
        payload,
      );
      if (alive.current) {
        setAppendText("");
        setAppendOpen(false);
      }
      return result;
    }, true);
  };
  const checkApplications = async () => {
    if (!snapshot || day === "undated" || day === "all" || dirty || locked || typingRef.current) return;
    const payload = {operation: operationId(), revision: snapshot.revision, work_date: day};
    await execute(async () => {
      const result = await api.post<Snapshot>(`/api/sourcing/tabs/${tab.id}/verify`, payload);
      void client.invalidateQueries({queryKey: ["payments"]});
      return result;
    });
  };
  const focusRow =
    highlightId && snapshot
      ? snapshot.row_ids.indexOf(highlightId)
      : highlightRow;
  useEffect(() => {
    if (!snapshot) return;
    if (highlightId && resolvedHighlight.current !== highlightId) {
      const index = snapshot.row_ids.indexOf(highlightId);
      if (index > 0) {
        setDay(snapshot.row_dates?.[index] || "undated");
        resolvedHighlight.current = highlightId;
      }
    }
    const visible = visibleRows(snapshot, [], { ...defaultView, day }).slice(1);
    setSelection((previous) =>
      previous.rows.length > 0 &&
      previous.rows.every((r) => visible.includes(r))
        ? previous
        : { rows: visible.slice(0, 1), columns: previous.columns },
    );
  }, [day, snapshot, highlightId]);
  const selectedJobs = snapshot
    ? selection.rows.filter(
        (r) =>
          r > 0 &&
          snapshot.rows[r]?.some((c) => String(c.value)) &&
          (!snapshot.row_dates ||
            snapshot.row_dates[r] === (day === "undated" ? null : day)),
      )
    : [];
  const renameHeader = async (col: number, title: string) => {
    const current = base.current;
    if (
      !current ||
      draft.current.length ||
      inFlight.current ||
      title === current.columns[col].title
    )
      return;
    setHeaderDraft({ col, title });
    const payload = {
      operation: operationId(),
      revision: current.revision,
      action: "rename_column",
      column_id: current.columns[col].id,
      title,
    };
    await execute(async () => {
      const result = await api.post<Snapshot>(
        `/api/sourcing/tabs/${tab.id}/structure`,
        payload,
      );
      if (alive.current) setHeaderDraft(null);
      return result;
    }, true);
  };
  const openAssign = () => {
    if (!snapshot || !selectedJobs.length) return;
    assignContext.current = {
      revision: snapshot.revision,
      ids: selectedJobs.map((r) => snapshot.row_ids[r]),
    };
    setAssignDay(day === "undated" ? chicagoDay() : day);
    setAssignOpen(true);
  };
  const assignDate = async () => {
    const context = assignContext.current;
    if (!context || !assignDay) return;
    const payload = {
      operation: operationId(),
      revision: context.revision,
      action: "move_date",
      ids: context.ids,
      work_date: assignDay,
    };
    setAssignOpen(false);
    await execute(async () => {
      const result = await api.post<Snapshot>(
        `/api/sourcing/tabs/${tab.id}/structure`,
        payload,
      );
      if (alive.current) setDay(payload.work_date);
      return result;
    }, true);
  };
  const displaySnapshot =
    snapshot && headerDraft
      ? {
          ...snapshot,
          rows: snapshot.rows.map((row, r) =>
            r === 0
              ? row.map((cell, c) =>
                  c === headerDraft.col
                    ? {
                        ...cell,
                        value: headerDraft.title,
                        display: headerDraft.title,
                      }
                    : cell,
                )
              : row,
          ),
        }
      : snapshot;
  const keyboard = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (
      !(e.metaKey || e.ctrlKey) ||
      (e.target as Element).closest("input,textarea") ||
      locked
    )
      return;
    const key = e.key.toLowerCase();
    if (key === "z") {
      e.preventDefault();
      if (e.shiftKey) redo();
      else undo();
    } else if (key === "b") {
      e.preventDefault();
      format({ bold: !selectedStyle.bold });
    } else if (key === "i") {
      e.preventDefault();
      format({ italic: !selectedStyle.italic });
    }
  };
  return (
    <div className="sheet-editor" onKeyDown={keyboard}>
      {dataRouter && (
        <SourcingDraftGuard dirty={dirty || saving} saving={saving} />
      )}
      <SourcingDays
        day={day}
        onChange={(next) => {
          history.current = [];
          future.current = [];
          setDay(next);
          setView(defaultView);
        }}
        disabled={locked || dirty || loading || !!structureOpen}
        snapshot={snapshot}
        onAssign={openAssign}
        canAssign={selectedJobs.length > 0 && selectedJobs.length <= 1000}
      />
      <div className="sheet-edit-toolbar native-sheet-toolbar">
        <div className="sheet-toolbar-group">
          <Button
            size="icon"
            variant="ghost"
            aria-label="Undo edit"
            disabled={locked || !history.current.length}
            onClick={undo}
          >
            <Undo2 size={16} />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            aria-label="Redo edit"
            disabled={locked || !future.current.length}
            onClick={redo}
          >
            <Redo2 size={16} />
          </Button>
        </div>
        <div className="sheet-toolbar-group">
          <Button
            size="icon"
            variant="ghost"
            aria-label="Bold"
            aria-pressed={selectedStyle.bold}
            disabled={locked || !snapshot}
            onClick={() => format({ bold: !selectedStyle.bold })}
          >
            <Bold size={16} />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            aria-label="Italic"
            aria-pressed={selectedStyle.italic}
            disabled={locked || !snapshot}
            onClick={() => format({ italic: !selectedStyle.italic })}
          >
            <Italic size={16} />
          </Button>
          {(
            [
              ["left", AlignLeft],
              ["center", AlignCenter],
              ["right", AlignRight],
            ] as const
          ).map(([align, Icon]) => (
            <Button
              key={align}
              size="icon"
              variant="ghost"
              aria-label={`Align ${align}`}
              aria-pressed={selectedStyle.align === align}
              disabled={locked || !snapshot}
              onClick={() => format({ align })}
            >
              <Icon size={16} />
            </Button>
          ))}
          <Button
            size="icon"
            variant="ghost"
            aria-label="Wrap text"
            aria-pressed={selectedStyle.wrap}
            disabled={locked || !snapshot}
            onClick={() => format({ wrap: !selectedStyle.wrap })}
          >
            <WrapText size={16} />
          </Button>
        </div>
        <div className="sheet-toolbar-group">
          <Button
            size="sm"
            variant="ghost"
            disabled={locked || dirty || !snapshot}
            onClick={() => openStructure("insert_rows")}
          >
            <Plus size={14} />
            Rows
          </Button>
          <Button size="sm" variant="outline" className="sheet-delete-rows"
            disabled={locked || dirty || !snapshot || !selection.rows.length || selection.rows.length > 1000}
            onClick={() => void deleteSelectedRows()} title="Delete selected job rows (Delete)">
            <Trash2 size={14} />Delete rows{selection.rows.length > 1 ? ` (${selection.rows.length})` : ""}
          </Button>
          <select
            aria-label="Row and column actions"
            value=""
            disabled={locked || dirty || !snapshot}
            onChange={(e) => {
              if (e.target.value === "append_jobs") setAppendOpen(true);
              else openStructure(e.target.value as StructureAction);
            }}
          >
            <option value="" disabled>
              Insert / edit
            </option>
            <option value="insert_rows">Insert rows</option>
            <option value="append_jobs">Append job rows</option>
            <option value="delete_rows">Delete selected rows</option>
            <option value="add_column">Add column</option>
            <option value="rename_column">Rename selected column</option>
            <option value="delete_column">Delete selected column</option>
          </select>
          <Button
            size="icon"
            variant="ghost"
            aria-label="Find and filter sheet"
            aria-pressed={showFilters}
            disabled={dirty || saving}
            onClick={() => setShowFilters(!showFilters)}
          >
            <Filter size={16} />
          </Button>
        </div>
        <Button variant="outline" size="sm" disabled={locked || dirty || loading || !snapshot || day === "undated" || day === "all"}
          title="Match company, role and account over seven days starting on the selected date in America/Chicago. Use company only if the email has no role. Checks are permanent."
          onClick={() => void checkApplications()}><Check size={14} />Check applications</Button>
        {snapshot?.verification && snapshot.verification.day === day && <span className="sheet-verification-result" role="status">
          {snapshot.verification.checked} links checked · 7 days from {day} · Chicago
        </span>}
        <span className="sheet-toolbar-spacer" />
        <span className="sheet-save-status" role="status">
          {saving ? (
            "Saving…"
          ) : error ? (
            "Save unavailable"
          ) : dirty ? (
            "Unsaved changes"
          ) : snapshot ? (
            <>
              <Check size={14} />
              Saved
            </>
          ) : (
            "Loading…"
          )}
        </span>
        <Button
          size="icon"
          variant="ghost"
          aria-label="Import CSV"
          disabled={locked || dirty || !snapshot}
          onClick={() => setImportOpen(true)}
        >
          <Upload size={16} />
        </Button>
        <a
          className={`sheet-export ${dirty || saving ? "is-disabled" : ""}`}
          aria-label="Export CSV"
          aria-disabled={dirty || saving}
          href={`/api/sourcing/tabs/${tab.id}/export?work_date=${encodeURIComponent(day)}`}
          download
          onClick={(e) => {
            if (dirty || saving) e.preventDefault();
          }}
        >
          <Download size={16} />
        </a>
        <Button
          size="icon"
          variant="ghost"
          aria-label="Refresh sheet"
          disabled={dirty || saving || loading}
          onClick={() => void load()}
        >
          <RefreshCw size={16} />
        </Button>
      </div>
      {showFilters && snapshot && (
        <div className="native-sheet-filters">
          <label>
            <Search size={14} />
            <input
              aria-label="Find in sheet"
              placeholder="Find in this sheet"
              value={view.find}
              disabled={dirty || saving}
              onChange={(e) => setView({ ...view, find: e.target.value })}
            />
          </label>
          <select
            aria-label="Filter column"
            disabled={dirty || saving}
            value={view.filterColumn}
            onChange={(e) =>
              setView({ ...view, filterColumn: Number(e.target.value) })
            }
          >
            {snapshot.columns.map((c, i) => (
              <option value={i} key={c.id}>
                {c.title}
              </option>
            ))}
          </select>
          <input
            aria-label="Filter value"
            placeholder="Contains…"
            value={view.filter}
            disabled={dirty || saving}
            onChange={(e) => setView({ ...view, filter: e.target.value })}
          />
          <select
            aria-label="Sort column"
            disabled={dirty || saving}
            value={view.sortColumn}
            onChange={(e) =>
              setView({ ...view, sortColumn: Number(e.target.value) })
            }
          >
            {snapshot.columns.map((c, i) => (
              <option value={i} key={c.id}>
                {c.title}
              </option>
            ))}
          </select>
          <select
            aria-label="Sort direction"
            disabled={dirty || saving}
            value={view.direction}
            onChange={(e) =>
              setView({
                ...view,
                direction: e.target.value as SheetView["direction"],
              })
            }
          >
            <option value="none">Sheet order</option>
            <option value="asc">A → Z</option>
            <option value="desc">Z → A</option>
          </select>
          <Button
            size="sm"
            variant="ghost"
            disabled={dirty || saving}
            onClick={() => setView(defaultView)}
          >
            Clear
          </Button>
        </div>
      )}
      {snapshot?.migration_notice && (
        <details className="native-migration-notice">
          <summary>Imported sheet information</summary>
          <p>{snapshot.migration_notice}</p>
        </details>
      )}
      {error && (
        <div className="sheet-sync-error" role="alert">
          <p>
            {error} {dirty ? "Your draft is preserved." : ""}
          </p>
          <div className="sheet-actions">
            {dirty && (
              <Button size="sm" variant="outline" onClick={download}>
                Download draft
              </Button>
            )}
            {lastAction.current && (
              <Button
                size="sm"
                variant="outline"
                disabled={saving}
                onClick={() =>
                  void execute(
                    lastAction.current!,
                    actionContext.current.structural,
                    actionContext.current.expected,
                  )
                }
              >
                Retry save
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              disabled={saving}
              onClick={() => void reload()}
            >
              {dirty ? "Discard draft and reload" : "Reload sheet"}
            </Button>
          </div>
        </div>
      )}
      {rowDeleteNotice && <p role="status" className="form-hint">{rowDeleteNotice}</p>}
      {snapshot ? (
        <SheetGrid
          snapshot={displaySnapshot!}
          headerRow={1}
          changes={changes}
          onChange={edit}
          disabled={locked}
          highlightRow={focusRow}
          view={scopedView}
          onSelection={next => {setSelection(next); setRowDeleteNotice("")}}
          onDeleteRows={rows => void deleteSelectedRows(rows)}
          onResize={resize}
          onEditingChange={setTyping}
          onHeaderChange={(col, title) => void renameHeader(col, title)}
          headersEditable={!changes.length}
          onPaste={() => {compactAfterPaste.current = true}}
          onAppendRows={rows => void appendJobs(rows)}
        />
      ) : (
        <div className="sourcing-empty">
          {loading ? "Loading your spreadsheet…" : "Sheet is unavailable."}
        </div>
      )}
      {snapshot && (
        <>
          <Dialog open={assignOpen} onOpenChange={setAssignOpen}>
            <DialogContent>
              <DialogTitle>Assign job date</DialogTitle>
              <DialogDescription>
                Move {assignContext.current?.ids.length || 0} selected jobs to
                one day. Other jobs stay where they are.
              </DialogDescription>
              <label>
                Job date
                <input
                  type="date"
                  aria-label="Assign jobs to date"
                  value={assignDay === "undated" ? "" : assignDay}
                  onChange={(e) => setAssignDay(e.target.value)}
                />
              </label>
              <div className="sheet-actions">
                <Button
                  disabled={!assignDay || saving}
                  onClick={() => void assignDate()}
                >
                  Assign date
                </Button>
                <Button
                  variant="outline"
                  disabled={saving}
                  onClick={() => setAssignDay("undated")}
                >
                  Keep undated
                </Button>
              </div>
            </DialogContent>
          </Dialog>
          <Dialog
            open={structureOpen !== null}
            onOpenChange={(open) => {
              if (!open) setStructureOpen(null);
            }}
          >
            {structureOpen && (
              <StructureDialog
                action={structureOpen}
                snapshot={structureContext.current?.snapshot || snapshot}
                selection={structureContext.current?.selection || selection}
                submit={structure}
              />
            )}
          </Dialog>
          <Dialog
            open={importOpen}
            onOpenChange={(open) => {
              if (saving) return;
              if (
                !open &&
                importDirty &&
                !window.confirm("Discard the CSV import you have not saved?")
              )
                return;
              setImportOpen(open);
              if (!open) setImportDirty(false);
            }}
          >
            {importOpen && (
              <SourcingImport
                snapshot={snapshot}
                day={day}
                onBusy={(busy) => {
                  if (busy) loadSequence.current++;
                  inFlight.current = busy;
                  setSaving(busy);
                }}
                onDirty={setImportDirty}
                onSaved={(result) => {
                  setSnapshot(result);
                  setChanges([]);
                  history.current = [];
                  future.current = [];
                  setImportDirty(false);
                  setImportOpen(false);
                  setView(defaultView);
                }}
              />
            )}
          </Dialog>
          <Dialog
            open={appendOpen}
            onOpenChange={(open) => {
              if (saving) return;
              if (
                !open &&
                appendText &&
                !window.confirm("Discard the job rows you have not appended?")
              )
                return;
              setAppendOpen(open);
              if (!open) setAppendText("");
            }}
          >
            <DialogContent>
              <DialogTitle>Append jobs</DialogTitle>
              <DialogDescription>
                Paste job rows in the sheet’s column order.
              </DialogDescription>
              <textarea
                className="append-jobs-input"
                aria-label="Job rows to append"
                value={appendText}
                onChange={(e) => setAppendText(e.target.value)}
              />
              <Button
                disabled={saving || !appendText}
                onClick={() => void appendJobs()}
              >
                Append jobs
              </Button>
            </DialogContent>
          </Dialog>
        </>
      )}
    </div>
  );
}
function StructureDialog({
  action,
  snapshot,
  selection,
  submit,
}: {
  action: StructureAction;
  snapshot: Snapshot;
  selection: Selection;
  submit: (command: Record<string, unknown>) => Promise<void>;
}) {
  const column = snapshot.columns[selection.columns[0] || 0],
    titles = {
      insert_rows: "Insert rows",
      delete_rows: "Delete selected rows",
      add_column: "Add column",
      rename_column: "Rename column",
      delete_column: "Delete column",
    };
  return (
    <DialogContent>
      <DialogTitle>{titles[action]}</DialogTitle>
      <DialogDescription>
        {action === "delete_rows"
          ? "The selected job rows and their values will be deleted."
          : action === "delete_column"
            ? "The selected custom column and its values will be deleted."
            : "Organize this profile sheet."}
      </DialogDescription>
      <form
        className="sourcing-password-form"
        onSubmit={(e) => {
          e.preventDefault();
          const data = new FormData(e.currentTarget);
          void submit({
            action,
            ...(action === "insert_rows"
              ? {
                  count: Number(data.get("count")),
                  at_row_id: snapshot.row_ids[selection.rows[0]] || undefined,
                }
              : {}),
            ...(action === "delete_rows"
              ? {
                  ids: selection.rows
                    .map((r) => snapshot.row_ids[r])
                    .filter(Boolean),
                }
              : {}),
            ...(["rename_column", "delete_column"].includes(action)
              ? { column_id: column?.id }
              : {}),
            ...(["add_column", "rename_column"].includes(action)
              ? { title: data.get("title") }
              : {}),
          });
        }}
      >
        {action === "insert_rows" && (
          <label>
            Number of rows
            <input
              name="count"
              type="number"
              min={1}
              max={1000}
              defaultValue={20}
              required
            />
          </label>
        )}
        {["add_column", "rename_column"].includes(action) && (
          <label>
            Column name
            <input
              name="title"
              maxLength={100}
              defaultValue={action === "rename_column" ? column?.title : ""}
              required
              autoFocus
            />
          </label>
        )}
        {action === "delete_column" && (
          <p>
            {column?.title}
            {column?.kind
              ? " is a required job column and cannot be deleted."
              : ""}
          </p>
        )}
        <Button
          disabled={
            (action === "delete_column" && !!column?.kind) ||
            (action === "delete_rows" && !selection.rows.length)
          }
        >
          {action.startsWith("delete")
            ? "Delete"
            : action === "insert_rows"
              ? "Insert rows"
              : "Save column"}
        </Button>
      </form>
    </DialogContent>
  );
}
