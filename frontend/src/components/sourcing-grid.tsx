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
  defaultView,
  mergeChanges,
  normalStyle,
  parseTSV,
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
  highlightRow,
  view = defaultView,
  onSelection,
  onResize,
  onEditingChange,
  onHeaderChange,
  headersEditable = true,
  onPaste,
  onAppendRows,
  onDeleteRows,
}: {
  snapshot: Snapshot;
  headerRow?: number;
  changes: Change[];
  onChange: (changes: Change[]) => void;
  disabled?: boolean;
  highlightRow?: number;
  view?: SheetView;
  onSelection?: (selection: Selection) => void;
  onResize?: (col: number, width: number) => void;
  onEditingChange?: (active: boolean) => void;
  onHeaderChange?: (col: number, title: string) => void;
  headersEditable?: boolean;
  onPaste?: () => void;
  onAppendRows?: (rows: string[][]) => void;
  onDeleteRows?: (rows: number[]) => void;
}) {
  const grid = useRef<DataGridHandle>(null),
    anchor = useRef({ row: 1, col: 0 }),
    selected = useRef(anchor.current),
    extending = useRef(false),
    stopDrag = useRef<() => void>(() => {});
  const [position, setPosition] = useState(anchor.current);
  const count = snapshot.columns.length;
  const visible = useMemo(
    () => visibleRows(snapshot, changes, view),
    [snapshot, changes, view],
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
  const notify = (
    a: { row: number; col: number },
    b: { row: number; col: number },
  ) => {
    const columns = [];
    for (let c = Math.min(a.col, b.col); c <= Math.max(a.col, b.col); c++)
      columns.push(c);
    onSelection?.({
      rows: visible
        .slice(Math.min(a.row, b.row), Math.max(a.row, b.row) + 1)
        .filter((r) => r > 0),
      columns,
    });
  };
  const select = (next: { row: number; col: number }, extend: boolean) => {
    if (!extend) anchor.current = next;
    selected.current = next;
    setPosition(next);
    notify(anchor.current, next);
  };
  const rowOrder = visible.map(row => snapshot.row_ids[row]).join(":");
  useEffect(() => {
    const index =
      highlightRow === undefined ? -1 : visible.indexOf(highlightRow);
    const rowIdx = index >= 0 ? index : Math.min(1, visible.length - 1);
    anchor.current = { row: rowIdx, col: 0 };
    selected.current = anchor.current;
    setPosition(anchor.current);
    notify(anchor.current, anchor.current);
    grid.current?.scrollToCell({ rowIdx, idx: 1 });
    grid.current?.setActivePosition({ rowIdx, idx: 1 });
  }, [highlightRow, view.day, rowOrder]);
  useEffect(() => () => stopDrag.current(), []);
  const apply = (values: Change[]) => {
    if (disabled) return;
    const valid = values.filter(
      (c) => c.row > 0 && c.col >= 0 && c.col < count,
    );
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
    if ((Math.abs(a.row - b.row) + 1) * (Math.abs(a.col - b.col) + 1) > 10000) {
      window.alert("Select up to 10,000 cells at a time.");
      return result;
    }
    for (let r = Math.min(a.row, b.row); r <= Math.max(a.row, b.row); r++)
      for (let c = Math.min(a.col, b.col); c <= Math.max(a.col, b.col); c++)
        if (visible[r] !== undefined)
          result.push({ row: visible[r], col: c, value: "" });
    return result;
  };
  const columns: Column<Row>[] = [
    {
      key: "id",
      name: "",
      width: 48,
      frozen: true,
      renderCell: ({ row }) => (
        <span className="sheet-row-number">
          {row.id === 0 ? "" : (indices.get(row.id) ?? row.id)}
        </span>
      ),
    },
    ...snapshot.columns.map((definition, c): Column<Row> => ({
      key: String(c),
      name: columnName(c),
      width: definition.width || 220,
      resizable: !disabled,
      editable: (row) =>
        !disabled && definition.kind !== "check" && (row.id > 0 || (!!onHeaderChange && headersEditable)),
      renderEditCell: (props) => (
        <NativeCellEditor {...props} onEditingChange={onEditingChange} />
      ),
      cellClass: (row) => {
        const index = indices.get(row.id) ?? 0;
        return index >= Math.min(anchor.current.row, position.row) &&
          index <= Math.max(anchor.current.row, position.row) &&
          c >= Math.min(anchor.current.col, position.col) &&
          c <= Math.max(anchor.current.col, position.col)
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
          type="checkbox" aria-label={`Check row ${indices.get(row.id) ?? row.id}`}
          title={cell?.checked_at ? `Confirmation received ${new Intl.DateTimeFormat("en-US", {timeZone:"America/Chicago",dateStyle:"medium",timeStyle:"short"}).format(new Date(cell.checked_at))} · Chicago` : text === "true" ? "Checked; no matching confirmation timestamp recorded" : "Not checked"}
          className="sourcing-check" checked={text === "true"} disabled={disabled || text === "true" || !snapshot.columns.some((column, index) => column.kind === "link" && String(row[String(index)]).trim())}
          onClick={event => event.stopPropagation()}
          onChange={event => { if (!disabled && text !== "true") apply([{row: row.id, col: c, value: String(event.target.checked)}]); }}
        />;
        return (
          <span
            className={`native-cell-content ${style.wrap ? "is-wrapped" : ""}`}
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
                onClick={(e) => e.stopPropagation()}
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
      <div className="sheet-formula-bar">
        <span>
          {columnName(position.col)}
          {position.row || ""}
        </span>
        <i>fx</i>
        <span>{String(rows[position.row]?.[String(position.col)] ?? "")}</span>
      </div>
      <DataGrid
        ref={grid}
        aria-label="Job sourcing spreadsheet"
        className="sourcing-grid"
        columns={columns}
        rows={rows}
        rowKeyGetter={(r) => snapshot.row_ids[r.id] || "header"}
        rowHeight={(row) =>
          snapshot.columns.some(
            (_, c) =>
              ({
                ...snapshot.rows[row.id]?.[c]?.style,
                ...drafts.get(`${row.id}:${c}`)?.style,
              }).wrap,
          )
            ? 64
            : 30
        }
        headerRowHeight={28}
        rowClass={(row) => {
          const index = indices.get(row.id) ?? -1;
          return [row.id === highlightRow ? "sheet-highlight-row" : "",
            row.id > 0 && index >= Math.min(anchor.current.row, position.row) && index <= Math.max(anchor.current.row, position.row) ? "sheet-row-selected" : ""].filter(Boolean).join(" ") || undefined;
        }}
        onActivePositionChange={({ rowIdx, column }) => {
          if (rowIdx >= 0 && column && column.key !== "id")
            select({ row: rowIdx, col: Number(column.key) }, extending.current);
        }}
        onCellMouseDown={({ rowIdx, column }, event) => {
          if (column.key === "id") return;
          extending.current = event.shiftKey;
          select({ row: rowIdx, col: Number(column.key) }, event.shiftKey);
          if (event.button !== 0 || (event.target as Element).closest("input"))
            return;
          stopDrag.current();
          const move = (e: MouseEvent) => {
            if (!e.buttons) return;
            const cell = (e.target as Element).closest('[role="gridcell"]');
            const row = cell?.closest('[role="row"]');
            if (!cell || !row || !grid.current?.element?.contains(cell)) return;
            const r = Number(row.getAttribute("aria-rowindex")) - 2,
              c = Number(cell.getAttribute("aria-colindex")) - 2;
            if (r < 0 || r >= visible.length || c < 0 || c >= count) return;
            extending.current = true;
            select({ row: r, col: c }, true);
          };
          const stop = () => {
            document.removeEventListener("mousemove", move);
            document.removeEventListener("mouseup", stop);
          };
          stopDrag.current = stop;
          document.addEventListener("mousemove", move);
          document.addEventListener("mouseup", stop);
        }}
        onRowsChange={(next, { indexes, column }) => {
          if (indexes.length === 1 && next[indexes[0]].id === 0) {
            const title = String(next[indexes[0]][column.key]).trim();
            if (!title) {
              window.alert("Enter a column title of 1–100 characters.");
              return;
            }
            onHeaderChange?.(Number(column.key), title);
          } else
            apply(
              indexes.map((index) => ({
                row: next[index].id,
                col: Number(column.key),
                value: String(next[index][column.key]),
              })),
            );
        }}
        onColumnResize={(column, width) => {
          if (column.key !== "id")
            onResize?.(Number(column.key), Math.round(width));
        }}
        onCellCopy={(_, event) => {
          const a = anchor.current,
            b = selected.current;
          if (
            (Math.abs(a.row - b.row) + 1) * (Math.abs(a.col - b.col) + 1) >
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
              let c = Math.min(a.col, b.col);
              c <= Math.max(a.col, b.col);
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
          if (disabled) return row;
          if (row.id === 0) {
            window.alert(
              "Double-click a column title to rename it. Paste job rows below the titles.",
            );
            return row;
          }
          const matrix = parseTSV(event.clipboardData.getData("text/plain")).filter(values => values.some(value => value.trim())),
            start = indices.get(row.id) ?? 0;
          if (matrix.reduce((n, r) => n + r.length, 0) > 10000) {
            window.alert("Paste up to 10,000 cells at a time.");
            return row;
          }
          if (!matrix.length) return row;
          if (matrix.length + start > rows.length && Number(column.key) === 0 &&
              snapshot.columns.every((_, c) => !String(row[String(c)] ?? "").trim()) && onAppendRows) {
            if (changes.length) {window.alert("Save current edits before appending pasted rows."); return row;}
            onAppendRows(matrix);
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
          const values: Change[] = [];
          matrix.forEach((r, ri) =>
            r.forEach((value, ci) =>
              values.push({
                row: visible[start + ri],
                col: Number(column.key) + ci,
                value,
              }),
            ),
          );
          onPaste?.();
          apply(values);
          return row;
        }}
        onCellKeyDown={(args, event) => {
          extending.current = event.shiftKey;
          if (
            disabled || args.mode !== "ACTIVE" ||
            !args.column ||
            args.column.key === "id"
          )
            return;
          if (event.key === "Delete" && onDeleteRows) {
            event.preventDefault();
            event.preventGridDefault();
            if (event.repeat) return;
            onDeleteRows(visible.slice(Math.min(anchor.current.row, selected.current.row), Math.max(anchor.current.row, selected.current.row) + 1).filter(row => row > 0));
            return;
          }
          if (event.key === "Delete" || event.key === "Backspace") {
            event.preventDefault();
            apply(range());
          }
        }}
      />
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
      onChange={(e) => onRowChange({ ...row, [column.key]: e.target.value })}
      onBlur={() => onClose(true, false)}
    />
  );
}
