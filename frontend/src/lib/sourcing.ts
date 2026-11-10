export interface CellStyle {
  bold?: boolean;
  italic?: boolean;
  align?: "left" | "center" | "right";
  wrap?: boolean;
}
export interface Cell {
  checked_at?: string | null;
  value: string | number | boolean;
  display: string;
  formula: boolean;
  link: string;
  version: number;
  style: CellStyle;
}
export interface SheetColumn {
  id: string;
  title: string;
  kind: "company" | "role" | "link" | "check" | null;
  width: number;
}
export interface Snapshot {
  filtered?: {duplicates: number; blocked_companies: number; blocked_roles?:number};
  verification?: {day: string; timezone: string; checked: number; future_checked?: number; account_email?:string|null; unmatched_count?:number; unmatched?:{row_id:string;sheet_row:number;work_date:string;company:string;reason:string}[]};
  id: number;
  rows: Cell[][];
  row_ids: string[];
  row_dates?: (string | null)[];
  columns: SheetColumn[];
  title: string;
  revision: string;
  structure_revision: number;
  refreshed_at: number;
  migration_notice?: string;
  properties: { gridProperties: { rowCount: number; columnCount: number } };
}
export interface Tab {
  id: number;
  account_id: number | null;
  account_label?: string;
  title: string;
  header_row: number;
  refreshed_at: number;
  archived?: boolean;
}
export interface Book {
  id: number;
  bidder_id: number;
  title: string;
  name: string;
  tabs: Tab[];
  job_dates?: string[];
}
export interface Index {
  books: Book[];
  bidders?: { id: number; name: string; login_enabled: boolean }[];
  accounts?: { id: number; label: string; email: string }[];
  assignments?: { bidder_id: number; account_id: number }[];
}
export interface Change {
  row: number;
  col: number;
  value?: string;
  style?: CellStyle;
}
export interface Selection {
  rows: number[];
  columns: number[];
}
export interface SheetView {
  day?: string;
  find: string;
  filterColumn: number;
  filter: string;
  sortColumn: number;
  direction: "none" | "asc" | "desc";
}
export const defaultView: SheetView = {
  find: "",
  filterColumn: 0,
  filter: "",
  sortColumn: 0,
  direction: "none",
};
export const normalStyle = (style: CellStyle = {}) => ({
  bold: false,
  italic: false,
  align: "left" as CellStyle["align"],
  wrap: false,
  ...style,
});
export function sourcingColumnTitle(column: Pick<SheetColumn,"kind"|"title">,index=0) {
  const titles:Record<string,string>={company:"Company",role:"Role",link:"Job link",check:"Check"}
  return (column.kind&&titles[column.kind])||column.title||columnName(index)
}
/** Saved checked rows stay locked even if a stale draft tries to clear the check. */
export function checkedSourcingRows(snapshot: Snapshot, changes: Change[] = []) {
  const columns=new Set(snapshot.columns.flatMap((column,index)=>column.kind==="check"?[index]:[]));
  const rows=new Set<number>();
  snapshot.rows.forEach((cells,row)=>{if(row>0&&[...columns].some(col=>String(cells[col]?.value)==="true"))rows.add(row)});
  for(const change of changes)if(columns.has(change.col)&&change.value==="true")rows.add(change.row);
  return rows;
}

export function columnName(index: number) {
  let result = "";
  for (index++; index; index = Math.floor((index - 1) / 26))
    result = String.fromCharCode(65 + ((index - 1) % 26)) + result;
  return result;
}
export function serializeTSV(rows: string[][]) {
  return rows
    .map((row) =>
      row
        .map((value) =>
          /[\t\n\r"]/.test(value)
            ? '"' + value.replaceAll('"', '""') + '"'
            : value,
        )
        .join("\t"),
    )
    .join("\n");
}
function parseDelimited(text: string, delimiter: string, strict = false) {
  const rows: string[][] = [];
  let row: string[] = [],
    value = "",
    quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === '"' && (!value || quoted)) {
      if (quoted && text[i + 1] === '"') {
        value += '"';
        i++;
      } else quoted = !quoted;
    } else if (
      !quoted &&
      (char === delimiter || char === "\n" || char === "\r")
    ) {
      row.push(value);
      value = "";
      if (char !== delimiter) {
        rows.push(row);
        row = [];
        if (char === "\r" && text[i + 1] === "\n") i++;
      }
    } else value += char;
  }
  if (strict && quoted)
    throw new Error("This CSV has an unclosed quoted cell.");
  if (value || row.length || !rows.length) {
    row.push(value);
    rows.push(row);
  }
  return rows;
}
export function parseTSV(text: string) {
  return parseDelimited(text, "\t");
}
function singleLineClipboardCell(value: string) {
  if (!/[\r\n\u2028\u2029]/.test(value)) return value;
  return value.replace(/[ \t]*[\r\n\u2028\u2029]+[ \t]*/g, /^\s*https?:\/\//i.test(value) ? "" : " ").trim();
}
const singleLineClipboardRows = (rows: string[][]) => rows.map(row => row.map(singleLineClipboardCell));
/** Prefer copied table cell boundaries over ambiguous rendered plain text. */
export function parseClipboardRows(text: string, html = ""): string[][] {
  if (text.length > 4 * 1024 * 1024 || html.length > 4 * 1024 * 1024)
    throw new Error("Clipboard data is too large. Paste a smaller selection.");
  if (!/<table(?:\s|>)/i.test(html)) return singleLineClipboardRows(parseTSV(text));
  // Inert template content never enters the live document. Return text only.
  const template = document.createElement("template");
  template.innerHTML = html;
  const table = template.content.querySelector("table");
  if (!table || !table.rows.length) return singleLineClipboardRows(parseTSV(text));
  const sourceRows = Array.from(table.rows);
  const matrix: string[][] = [];
  let cells = 0;
  const cellText = (cell: HTMLTableCellElement) => {
    const parts: string[] = [];
    const walker = document.createTreeWalker(cell, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: node => /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|IFRAME|OBJECT|EMBED|SVG|MATH)$/.test(node.nodeName) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
    });
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (node.nodeType === Node.TEXT_NODE) parts.push(node.textContent || "");
      else if (/^(BR|DIV|P|LI)$/.test(node.nodeName)) parts.push("\n");
    }
    return parts.join("").replace(/^\n+|\n+$/g, "");
  };
  sourceRows.forEach((source, r) => {
    const row = matrix[r] ||= [];
    let col = 0;
    for (const cell of Array.from(source.cells)) {
      while (row[col] !== undefined) col++;
      const height = Math.min(cell.rowSpan || sourceRows.length - r, sourceRows.length - r);
      const width = cell.colSpan;
      if (col + width > 10000 || cells + height * width > 10000)
        throw new Error("Paste up to 10,000 cells at a time.");
      const value = cellText(cell);
      for (let dr = 0; dr < height; dr++) {
        const target = matrix[r + dr] ||= [];
        for (let dc = 0; dc < width; dc++) {
          if (target[col + dc] !== undefined) throw new Error("This table has overlapping merged cells. Copy an unmerged selection instead.");
          target[col + dc] = dr === 0 && dc === 0 ? value : "";
          cells++;
        }
      }
      col += width;
    }
  });
  return singleLineClipboardRows(matrix.map(row => Array.from({ length: row.length }, (_, i) => row[i] ?? "")));
}
export function parseCSV(text: string) {
  return parseDelimited(text.replace(/^\uFEFF/, ""), ",", true);
}
export function mergeChanges(
  snapshot: Snapshot,
  current: Change[],
  values: Change[],
) {
  const next = new Map(current.map((c) => [`${c.row}:${c.col}`, c]));
  for (const change of values) {
    const key = `${change.row}:${change.col}`,
      base = snapshot.rows[change.row]?.[change.col],
      previous = next.get(key);
    const cell = {
      ...previous,
      ...change,
      style: change.style
        ? { ...previous?.style, ...change.style }
        : previous?.style,
    };
    const sameValue =
      cell.value === undefined || String(base?.value ?? "") === cell.value;
    const sameStyle =
      cell.style === undefined ||
      JSON.stringify(normalStyle(base?.style)) ===
        JSON.stringify(normalStyle(cell.style));
    if (sameValue && sameStyle) next.delete(key);
    else next.set(key, cell);
  }
  return [...next.values()];
}
export function nativeChanges(snapshot: Snapshot, changes: Change[]) {
  return changes.map((change) => {
    const row_id = snapshot.row_ids[change.row],
      column_id = snapshot.columns[change.col]?.id;
    if (!row_id || !column_id)
      throw new Error(
        "This row or column is unavailable. Download your draft and reload the sheet.",
      );
    return {
      row_id,
      column_id,
      expected_version: snapshot.rows[change.row]?.[change.col]?.version || 0,
      ...(change.value !== undefined ? { value: change.value } : {}),
      ...(change.style ? { style: change.style } : {}),
    };
  });
}
export function visibleRows(
  snapshot: Snapshot,
  changes: Change[],
  view: SheetView,
) {
  const draft = new Map(
    changes
      .filter((c) => c.value !== undefined)
      .map((c) => [`${c.row}:${c.col}`, c.value!]),
  );
  const value = (r: number, c: number) =>
    draft.get(`${r}:${c}`) ?? String(snapshot.rows[r]?.[c]?.value ?? "");
  const find = view.find.trim().toLocaleLowerCase(),
    filter = view.filter.toLocaleLowerCase();
  const rows = snapshot.rows
    .slice(1)
    .map((_, i) => i + 1)
    .filter(
      (r) =>
        (!view.day ||
          !snapshot.row_dates ||
          snapshot.row_dates[r] ===
            (view.day === "undated" ? null : view.day) ||
          (snapshot.row_dates[r] == null &&
            snapshot.columns.every((column, c) => column.kind === "check" || !value(r, c)))) &&
        (!find ||
          snapshot.columns.some((_, c) =>
            value(r, c).toLocaleLowerCase().includes(find),
          )) &&
        (!filter ||
          value(r, view.filterColumn).toLocaleLowerCase().includes(filter)),
    );
  if (view.direction !== "none")
    rows.sort((a, b) => {
      const left = value(a, view.sortColumn),
        right = value(b, view.sortColumn);
      if (!left || !right) return left ? -1 : right ? 1 : a - b;
      return (
        left.localeCompare(right, undefined, {
          numeric: true,
          sensitivity: "base",
        }) * (view.direction === "asc" ? 1 : -1)
      );
    });
  return [0, ...rows];
}

export function csvDestinations(headers: string[], columns: SheetColumn[]) {
  const normalize = (value: string) =>
    value.toLowerCase().replace(/[^a-z0-9]/g, "");
  const aliases: Record<string, string[]> = {
    company: ["company", "companyname", "employer"],
    role: ["role", "jobtitle", "jobrole", "position"],
    link: [
      "joblink",
      "joburl",
      "url",
      "link",
      "applicationlink",
      "applicationurl",
    ],
  };
  const available = columns.map((c) => ({ ...c }));
  return headers.map((header) => {
    const key = normalize(header),
      match =
        available.find((c) => key && normalize(c.title) === key) ||
        available.find((c) => c.kind && aliases[c.kind]?.includes(key));
    if (match) return { target: match.title, isNew: false };
    const title =
      header.trim().slice(0, 100) || `Column ${available.length + 1}`;
    available.push({
      id: `new-${available.length}`,
      title,
      kind: null,
      width: 220,
    });
    return { target: title, isNew: true };
  });
}
export function hasUnexpectedEdits(
  before: Snapshot,
  after: Snapshot,
  changes: Change[],
) {
  if (
    before.structure_revision !== after.structure_revision ||
    JSON.stringify(before.row_ids) !== JSON.stringify(after.row_ids) ||
    JSON.stringify(before.columns.map((c) => c.id)) !==
      JSON.stringify(after.columns.map((c) => c.id))
  )
    return true;
  const edited = new Set(changes.map((c) => `${c.row}:${c.col}`));
  return before.rows.some(
    (row, r) =>
      r > 0 &&
      before.columns.some(
        (_, c) =>
          (after.rows[r]?.[c]?.version || 0) !==
          (row[c]?.version || 0) + (edited.has(`${r}:${c}`) ? 1 : 0),
      ),
  );
}

export function chicagoDay(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const get = (key: string) => parts.find((p) => p.type === key)!.value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}
export function offsetDay(day: string, delta: number) {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + delta);
  return date.toISOString().slice(0, 10);
}
