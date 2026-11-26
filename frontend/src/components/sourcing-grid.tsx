import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  DataGrid,
  type Column,
  type DataGridHandle,
  type RenderEditCellProps,
} from "react-data-grid";
import "react-data-grid/lib/styles.css";
import {
  columnName,
  checkedSourcingRows,
  sourcingColumnTitle,
  defaultView,
  mergeChanges,
  normalStyle,
  parseClipboardRows,
  serializeTSV,
  visibleRows,
  type Change,
  type Selection,
  type SheetView,
  type Snapshot,
} from "@/lib/sourcing";
type Row = { id: number; [key: string]: string | number };
export function SheetGrid({
  snapshot,
  changes,
  onChange,
  disabled = false,
  rowMode = false,
  highlightRow,
  view = defaultView,
  onSelection,
  onResize,
  onEditingChange,
  onPaste,
  onAppendRows,
  ariaLabel = "Job sourcing spreadsheet",
}: {
  snapshot: Snapshot;
  changes: Change[];
  onChange: (changes: Change[]) => void;
  disabled?: boolean;
  /** Browse/select whole rows; bulk paste appends jobs instead of editing cells. */
  rowMode?: boolean;
  highlightRow?: number;
  view?: SheetView;
  onSelection?: (selection: Selection) => void;
  onResize?: (col: number, width: number) => void;
  onEditingChange?: (active: boolean) => void;
  onPaste?: () => void;
  onAppendRows?: (rows: string[][]) => void;
  ariaLabel?: string;
}) {
  const grid = useRef<DataGridHandle>(null),
    anchor = useRef({ row: 0, col: 0 }),
    selected = useRef(anchor.current),
    extending = useRef(false),
    stopDrag = useRef<() => void>(() => {});
  const [position, setPosition] = useState(anchor.current);
  const count = snapshot.columns.length;
  const checkedRows = useMemo(()=>checkedSourcingRows(snapshot,changes),[snapshot,changes]);
  const visible = useMemo(
    () => visibleRows(snapshot, changes, view).filter(row=>row>0 && (!rowMode || snapshot.columns.some((column,c)=>column.kind!=='check' && String(snapshot.rows[row]?.[c]?.value ?? '').trim()))),
    [snapshot, changes, view, rowMode],
  );
  const indices = useMemo(
    () => new Map(visible.map((row, index) => [row, index])),
    [visible],
  );
  const drafts = useMemo(
    () =>
      new Map(changes.map((change) => [`${change.row}:${change.col}`, change])),
    [changes],
  );
  const rows = useMemo(
    () =>
      visible.map((r) => {
        const row: Row = { id: r };
        for (let c = 0; c < count; c++)
          row[String(c)] =
            drafts.get(`${r}:${c}`)?.value ??
            String(snapshot.rows[r]?.[c]?.value ?? "");
        return row;
      }),
    [visible, snapshot, drafts, count],
  );
  const rowOffsets = useMemo(() => {
    const offsets = [0];
    for (const row of visible) {
      const wrapped = !rowMode && snapshot.columns.some((_, col) => ({
        ...snapshot.rows[row]?.[col]?.style,
        ...drafts.get(`${row}:${col}`)?.style,
      }).wrap);
      offsets.push(offsets[offsets.length - 1] + (wrapped ? 64 : 30));
    }
    return offsets;
  }, [visible, snapshot, drafts, rowMode]);
  const notify = (
    a: { row: number; col: number },
    b: { row: number; col: number },
  ) => {
    const columns = [];
    for (let c = 0; c < count; c++) columns.push(c);
    onSelection?.({
      rows: visible
        .slice(Math.min(a.row, b.row), Math.max(a.row, b.row) + 1)
        .filter((r) => r > 0),
      columns,
    });
  };
  const select = (requested: { row: number; col: number }, extend: boolean) => {
    const next = rowMode ? {row:requested.row,col:0} : requested;
    if (!extend) anchor.current = next;
    selected.current = next;
    setPosition(previous=>previous.row===next.row && previous.col===next.col ? previous : next);
    notify(anchor.current, next);
  };
  const rowOrder = visible.map(row => snapshot.row_ids[row]).join(":");
  useEffect(() => {
    stopDrag.current();
    const index =
      highlightRow === undefined ? -1 : visible.indexOf(highlightRow);
    const rowIdx = index >= 0 ? index : 0;
    anchor.current = { row: rowIdx, col: 0 };
    selected.current = anchor.current;
    setPosition(anchor.current);
    notify(anchor.current, anchor.current);
    if(visible.length){
      grid.current?.scrollToCell({ rowIdx, idx: 1 });
      grid.current?.setActivePosition({ rowIdx, idx: 1 });
    }
  }, [highlightRow, view.day, rowOrder]);
  useEffect(() => () => stopDrag.current(), []);
  const apply = (values: Change[]) => {
    if (disabled) return;
    const valid = values.filter(
      (c) => c.row > 0 && c.col >= 0 && c.col < count && !checkedRows.has(c.row),
    );
    if(!valid.length)return;
    const next = mergeChanges(snapshot, changes, valid);
    if (next.length > 10000) {
      window.alert(
        "Save the current edits before changing more than 10,000 cells.",
      );
      return;
    }
    onChange(next);
  };
  const range = () => {
    const result: Change[] = [];
    const a = anchor.current,
      b = selected.current;
    if ((Math.abs(a.row - b.row) + 1) * count > 10000) {
      window.alert("Select up to 10,000 cells at a time.");
      return result;
    }
    for (let r = Math.min(a.row, b.row); r <= Math.max(a.row, b.row); r++)
      for (let c = 0; c < count; c++)
        if (visible[r] !== undefined)
          result.push({ row: visible[r], col: c, value: "" });
    return result;
  };
  /** Copied rows start unchecked: blank every Check column value. */
  const withoutChecks = (matrix: string[][], offset: number) =>
    matrix.map(r => r.map((value, ci) => snapshot.columns[offset + ci]?.kind === "check" ? "" : value));
  // With no job rows there is no cell to paste into (the field names are
  // fixed headings), so a paste into the empty table adds the copied rows.
  const empty = rows.length === 0 && !disabled && !!onAppendRows;
  const pasteIntoEmptyDay = (event: {clipboardData: DataTransfer | null; defaultPrevented: boolean; preventDefault: () => void}) => {
    if ((!empty && !rowMode) || disabled || !onAppendRows || event.defaultPrevented || !event.clipboardData) return;
    event.preventDefault();
    let matrix: string[][];
    try {
      matrix = parseClipboardRows(event.clipboardData.getData("text/plain"), event.clipboardData.getData("text/html")).filter(values => values.some(value => value.trim()));
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "Could not read the copied rows. Try copying them again.");
      return;
    }
    if (!matrix.length) return;
    if (matrix.reduce((n, r) => n + r.length, 0) > 10000) {window.alert("Paste up to 10,000 cells at a time."); return;}
    if (matrix.some(r => r.length > count)) {window.alert("The copied rows have more columns than this sheet."); return;}
    if (changes.length) {window.alert("Save current edits before appending pasted rows."); return;}
    onAppendRows(withoutChecks(matrix, 0));
  };
  const pasteRef = useRef(pasteIntoEmptyDay);
  pasteRef.current = pasteIntoEmptyDay;
  // Ctrl+V after clicking the empty table area (which holds no focusable
  // cell) lands on the page body; treat it as a paste into this empty day.
  useEffect(() => {
    if (!empty) return;
    const onPaste = (event: ClipboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest?.("input,textarea,select,[contenteditable=''],[contenteditable='true'],[role='dialog']")) return;
      if (target && target !== document.body && !target.closest?.(".sheet-grid-paste")) return;
      pasteRef.current(event);
    };
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  }, [empty]);
  const [viewportWidth, setViewportWidth] = useState(0);
  useLayoutEffect(() => {
    const element = grid.current?.element;
    if (!element) return;
    const measure = () => setViewportWidth(element.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const flexible = (col: Snapshot["columns"][number]) =>
    col.kind !== "check" && (!col.width || col.width === 220);
  const fixedWidth = snapshot.columns.reduce((sum, col) => sum + (flexible(col) ? 0 : col.width || 76), 48);
  const flexibleCount = snapshot.columns.filter(flexible).length;
  const textWidth = viewportWidth && flexibleCount
    ? Math.max(140, Math.floor((viewportWidth - fixedWidth) / flexibleCount))
    : 220;
  const columns: Column<Row>[] = [
    {
      key: "id",
      name: "",
      width: 48,
      frozen: true,
      renderCell: ({ row }) => (
        <span className="sheet-row-number">
          {(indices.get(row.id) ?? 0)+1}
        </span>
      ),
    },
    ...snapshot.columns.map((definition, c): Column<Row> => ({
      key: String(c),
      name: sourcingColumnTitle(definition,c),
      width: flexible(definition) ? textWidth : definition.width || 76,
      resizable: !disabled && !rowMode,
      editable: (row) =>
        !disabled && !rowMode && !checkedRows.has(row.id) && definition.kind !== "check" && row.id > 0,
      renderEditCell: rowMode ? undefined : (props) => (
        <NativeCellEditor {...props} onEditingChange={onEditingChange} />
      ),
      cellClass: (row) => {
        const index = indices.get(row.id) ?? 0;
        return index >= Math.min(anchor.current.row, position.row) &&
          index <= Math.max(anchor.current.row, position.row) &&
          c >= 0 && c < count
          ? "sheet-range-cell"
          : row.id === 0
            ? "sheet-heading-cell"
            : undefined;
      },
      renderCell: ({ row }) => {
        const cell = snapshot.rows[row.id]?.[c],
          change = drafts.get(`${row.id}:${c}`),
          style = normalStyle({ ...cell?.style, ...change?.style }),
          text = String(row[String(c)]);
        if (definition.kind === "check" && row.id > 0) return <input
          type="checkbox" aria-label={`Check row ${(indices.get(row.id) ?? 0)+1}`}
          title={cell?.checked_at ? `Confirmation received ${new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago",dateStyle:"medium",timeStyle:"short"}).format(new Date(cell.checked_at))} · Chicago` : text === "true" ? "Checked; no matching confirmation timestamp recorded" : "Not checked"}
          className="sourcing-check" checked={text === "true"} disabled={disabled || text === "true" || !snapshot.columns.some((column, index) => column.kind === "link" && String(row[String(index)]).trim())}
          onClick={event => event.stopPropagation()}
          onChange={event => { if (!disabled && text !== "true") apply([{row: row.id, col: c, value: String(event.target.checked)}]); }}
        />;
        return (
          <span
            className={`native-cell-content ${!rowMode && style.wrap ? "is-wrapped" : ""}`}
            onDragStart={event=>event.preventDefault()}
            style={{
              fontWeight: style.bold ? 700 : undefined,
              fontStyle: style.italic ? "italic" : undefined,
              textAlign: style.align,
            }}
            title={text}
          >
            {definition.kind === "link" && /^https?:\/\//i.test(text) ? (
              <a
                href={text}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => { e.stopPropagation(); if(!e.ctrlKey&&!e.metaKey)e.preventDefault(); }}
                title={checkedRows.has(row.id)?"Checked job · read only. Ctrl/Cmd+click to open.":"Click to select row. Ctrl/Cmd+click to open."}
              >
                {text}
              </a>
            ) : (
              text
            )}
          </span>
        );
      },
    })),
  ];
  return (
    <>
      {!rowMode && <div className="sheet-formula-bar">
        <span>
          {columnName(position.col)}
          {position.row+1}
        </span>
        <i>fx</i>
        <span>{String(rows[position.row]?.[String(position.col)] ?? "")}</span>
      </div>}
      <div className="sheet-grid-paste" style={{display: "contents"}} onPaste={pasteIntoEmptyDay}>
      <DataGrid
        ref={grid}
        aria-label={ariaLabel}
        className={`sourcing-grid${rowMode ? ' is-row-mode' : ''}`}
        columns={columns}
        rows={rows}
        rowKeyGetter={(r) => snapshot.row_ids[r.id] || "header"}
        rowHeight={(row) => {
          const index = indices.get(row.id) ?? 0;
          return rowOffsets[index + 1] - rowOffsets[index];
        }}
        headerRowHeight={28}
        renderers={empty ? {noRowsFallback: (
          <div role="row" className="sheet-paste-row">
            <div role="gridcell" tabIndex={0} className="sheet-paste-target" aria-label="Paste copied job rows here"
              onClick={(event) => event.currentTarget.focus()}>
              Paste copied job rows here <kbd>Ctrl</kbd>+<kbd>V</kbd>
            </div>
          </div>
        )} : undefined}
        rowClass={(row) => {
          const index = indices.get(row.id) ?? -1;
          return [row.id === highlightRow ? "sheet-highlight-row" : "", checkedRows.has(row.id)?"sheet-checked-row":"",
            row.id > 0 && index >= Math.min(anchor.current.row, position.row) && index <= Math.max(anchor.current.row, position.row) ? "sheet-row-selected" : ""].filter(Boolean).join(" ") || undefined;
        }}
        onActivePositionChange={({ rowIdx, column }) => {
          if (rowIdx >= 0 && column)
            select({ row: rowIdx, col: column.key==="id"?0:Number(column.key) }, extending.current);
        }}
        onCellMouseDown={({ rowIdx, column }, event) => {
          stopDrag.current();
          extending.current = event.shiftKey;
          select({ row: rowIdx, col: column.key==="id"?0:Number(column.key) }, event.shiftKey);
          if (event.button !== 0 || (event.target as Element).closest("input"))
            return;
          const start = { x: event.clientX, y: event.clientY };
          let pointer = start, dragging = false;
          let frame = 0, lastTime = 0, active = true;
          const move = (e: MouseEvent) => {
            if (!(e.buttons & 1)) { stop(); return; }
            pointer = { x: e.clientX, y: e.clientY };
            if (Math.hypot(pointer.x - start.x, pointer.y - start.y) >= 3) dragging = true;
            const cell = (e.target as Element).closest?.('[role="gridcell"]');
            const row = cell?.closest('[role="row"]');
            if (!cell || !row || !grid.current?.element?.contains(cell)) return;
            const r = Number(row.getAttribute("aria-rowindex")) - 2,
              c = Math.max(0,Number(cell.getAttribute("aria-colindex")) - 2);
            if (r < 0 || r >= visible.length || c < 0 || c >= count) return;
            extending.current = true;
            select({ row: r, col: c }, true);
          };
          const scroll = (time: number) => {
            if (!active) return;
            const elapsed = lastTime ? Math.min(32, time - lastTime) : 16;
            lastTime = time;
            const element = grid.current?.element;
            if (dragging && element && visible.length) {
              const rect = element.getBoundingClientRect();
              const viewportTop = rect.top + element.clientTop;
              const bodyTop = viewportTop + 28;
              const top = Math.max(0, bodyTop), bottom = Math.min(window.innerHeight, viewportTop + element.clientHeight);
              const band = Math.min(40, (bottom - top) / 3);
              if (band > 0 && pointer.x >= rect.left && pointer.x <= rect.right) {
                const direction = pointer.y > bottom - band ? 1 : pointer.y < top + band ? -1 : 0;
                if (direction) {
                  const depth = direction > 0 ? pointer.y - (bottom - band) : top + band - pointer.y;
                  const speed = 2 + 12 * Math.min(1, depth / band);
                  element.scrollTop = Math.max(0, Math.min(element.scrollHeight - element.clientHeight,
                    element.scrollTop + direction * speed * elapsed / 16));
                  // Hit testing the DOM alone misses virtualized rows and does
                  // not advance while the pointer is held still at the edge.
                  const offset = element.scrollTop + Math.max(0, Math.min(bottom - 1, Math.max(top, pointer.y)) - bodyTop);
                  let low = 0, high = visible.length;
                  while (low < high) {
                    const mid = (low + high) >>> 1;
                    if (rowOffsets[mid + 1] <= offset) low = mid + 1;
                    else high = mid;
                  }
                  const row = Math.min(visible.length - 1, low);
                  if (row !== selected.current.row) {
                    extending.current = true;
                    select({ row, col: selected.current.col }, true);
                  }
                }
              }
            }
            frame = window.requestAnimationFrame(scroll);
          };
          const stop = () => {
            active = false;
            window.cancelAnimationFrame(frame);
            extending.current = false;
            document.removeEventListener("mousemove", move);
            document.removeEventListener("mouseup", stop);
            window.removeEventListener("blur", stop);
          };
          stopDrag.current = stop;
          document.addEventListener("mousemove", move);
          document.addEventListener("mouseup", stop);
          window.addEventListener("blur", stop);
          frame = window.requestAnimationFrame(scroll);
        }}
        onRowsChange={(next, { indexes, column }) => {
          apply(indexes.map(index=>({row:next[index].id,col:Number(column.key),value:String(next[index][column.key])})));
        }}
        onColumnResize={(column, width) => {
          if (column.key !== "id")
            onResize?.(Number(column.key), Math.round(width));
        }}
        onCellCopy={(_, event) => {
          const a = anchor.current,
            b = selected.current;
          if (
            (Math.abs(a.row - b.row) + 1) * count >
            10000
          ) {
            event.preventDefault();
            window.alert("Copy up to 10,000 cells at a time.");
            return;
          }
          const values = [];
          for (
            let r = Math.min(a.row, b.row);
            r <= Math.max(a.row, b.row);
            r++
          ) {
            const row = [];
            for (
              let c = 0;
              c < count;
              c++
            )
              row.push(String(rows[r]?.[String(c)] ?? ""));
            values.push(row);
          }
          event.clipboardData.setData("text/plain", serializeTSV(values));
          event.preventDefault();
        }}
        onCellPaste={({ row, column }, event) => {
          event.preventDefault();
          if (disabled || (!rowMode && checkedRows.has(row.id))) return row;
          let matrix: string[][];
          try {
            matrix = parseClipboardRows(event.clipboardData.getData("text/plain"), event.clipboardData.getData("text/html")).filter(values => values.some(value => value.trim()));
          } catch (error) {
            window.alert(error instanceof Error ? error.message : "Could not read the copied rows. Try copying them again.");
            return row;
          }
          const start = indices.get(row.id) ?? 0;
          if (matrix.reduce((n, r) => n + r.length, 0) > 10000) {
            window.alert("Paste up to 10,000 cells at a time.");
            return row;
          }
          if (!matrix.length) return row;
          if (rowMode) {
            if (matrix.some(values=>values.length>count)) {window.alert("The copied rows have more columns than this sheet.");return row;}
            if (changes.length) {window.alert("Save current changes before adding pasted rows.");return row;}
            onAppendRows?.(withoutChecks(matrix,0));
            return row;
          }
          if (matrix.length + start > rows.length && Number(column.key) === 0 &&
              snapshot.columns.every((_, c) => !String(row[String(c)] ?? "").trim()) && onAppendRows) {
            if (changes.length) {window.alert("Save current edits before appending pasted rows."); return row;}
            onAppendRows(withoutChecks(matrix, 0));
            return row;
          }
          if (
            matrix.length + start > rows.length ||
            matrix.some((r) => r.length + Number(column.key) > count)
          ) {
            window.alert(
              "This paste extends beyond the available rows or columns. Add rows or columns first, or use Import CSV.",
            );
            return row;
          }
          if(visible.slice(start,start+matrix.length).some(id=>checkedRows.has(id))){
            window.alert("Checked rows are read-only. Paste into unchecked rows instead.");return row;
          }
          const values: Change[] = [];
          matrix.forEach((r, ri) =>
            r.forEach((value, ci) => {
              const col = Number(column.key) + ci;
              // A copied check belongs to the source account; this row is
              // checked only by its own confirmation or a deliberate click.
              if (snapshot.columns[col]?.kind === "check") return;
              values.push({row: visible[start + ri], col, value});
            }),
          );
          onPaste?.();
          apply(values);
          return row;
        }}
        onCellKeyDown={(args, event) => {
          extending.current = event.shiftKey;
          if (
            disabled || args.mode !== "ACTIVE" ||
            !args.column
          )
            return;
          // Clear selected contents; autosave compacts empty rows and retains
          // a trailing input row for the next paste.
          if (event.key === "Delete" || event.key === "Backspace") {
            event.preventDefault();
            event.preventGridDefault();
            if (event.repeat) return;
            apply(range());
          }
        }}
      />
      </div>
    </>
  );
}

function NativeCellEditor({
  row,
  column,
  onRowChange,
  onClose,
  onEditingChange,
}: RenderEditCellProps<Row> & { onEditingChange?: (active: boolean) => void }) {
  const input = useRef<HTMLInputElement>(null);
  useLayoutEffect(() => {
    input.current?.focus();
    input.current?.select();
    onEditingChange?.(true);
    return () => onEditingChange?.(false);
  }, [onEditingChange]);
  return (
    <input
      ref={input}
      className="native-cell-input"
      aria-label="Edit cell"
      maxLength={row.id === 0 ? 100 : 50000}
      value={String(row[column.key])}
      onCopy={(event) => event.stopPropagation()}
      onPaste={(event) => event.stopPropagation()}
      onChange={(e) => onRowChange({ ...row, [column.key]: e.target.value })}
      onBlur={() => onClose(true, false)}
    />
  );
}
