import { request } from "@/lib/api";

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
  /** Seconds since the epoch when each row first held a job; null for blank rows. */
  row_created?: (number | null)[];
  columns: SheetColumn[];
  title: string;
  revision: string;
  structure_revision: number;
  refreshed_at: number;
  migration_notice?: string;
  properties: { gridProperties: { rowCount: number; columnCount: number } };
}

type CompactSnapshot = Omit<Snapshot, "rows"> & {
  cell_entries: [row: number, column: number, value: string, version: number, style: CellStyle][];
  confirmation_times: [row: number, timestamp: string][];
};

export async function readSourcingSheet(tabId: number, signal: AbortSignal): Promise<Snapshot> {
  const data = await request<Snapshot | CompactSnapshot>(`/api/sourcing/tabs/${tabId}?compact=true`, { signal });
  // Existing servers return the full snapshot when the parameter is unknown.
  if ("rows" in data) return data;
  const { cell_entries, confirmation_times, ...snapshot } = data;
  const confirmed = new Map(confirmation_times);
  const rows: Cell[][] = snapshot.row_ids.map((_, row) => snapshot.columns.map(column => {
    if (row === 0) {
      return { value: column.title, display: column.title, formula: false, link: "", version: 0, style: { bold: true } };
    }
    const cell: Cell = { value: "", display: "", formula: false, link: "", version: 0, style: {} };
    if (column.kind === "check") cell.checked_at = confirmed.get(row) ?? null;
    return cell;
  }));
  for (const [row, column, value, version, style] of cell_entries) {
    const cell = rows[row][column];
    cell.value = cell.display = value;
    cell.version = version;
    cell.style = style;
    if (snapshot.columns[column].kind === "link" && /^https?:\/\//i.test(value)) cell.link = value;
  }
  return { ...snapshot, rows };
}
export interface Tab {
  id: number;
  account_id: number | null;
  account_label?: string;
  title: string;
  header_row: number;
  refreshed_at: number;
  archived?: boolean;
  /** Server counts for this sheet's work queue. */
  queue?: QueueCounts | null;
}
export interface Book {
  removed_at?: string | null;
  id: number;
  bidder_id: number;
  title: string;
  name: string;
  tabs: Tab[];
  job_dates?: string[];
  queue?: Pick<QueueCounts, "todo" | "new_today" | "carryover" | "expiring">;
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
  queue?: QueueView;
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
/* Work queue. Matches mailcheck/native_sourcing.py: a job is any row with company,
   role or link text; it is completed once checked; an unfinished job expires 168 hours
   after it was first created, and is "expiring soon" in its last 48 hours. */
export const QUEUE_LIFETIME_MS = 7 * 24 * 3600_000
export const QUEUE_WARNING_MS = 48 * 3600_000
export type QueueStatus = "todo" | "completed" | "expired" | "all"
export type QueueFocus = "new" | "carryover" | "expiring"
export interface QueueView { status: QueueStatus; focus: QueueFocus | null; now: number; dayStart: number; keep?: ReadonlySet<string> }
export interface RowLifecycle { job: boolean; done: boolean; expired: boolean; expiring: boolean; isNew: boolean; created: number }
export interface QueueCounts { todo: number; new_today: number; carryover: number; expiring: number; completed: number; expired: number; all: number }

export function rowLifecycle(snapshot: Snapshot, row: number, value: (row: number, col: number) => string, now: number, dayStart: number): RowLifecycle {
  const job = snapshot.columns.some((column, col) => column.kind !== "check" && value(row, col).trim() !== "")
  const done = snapshot.columns.some((column, col) => column.kind === "check" && value(row, col) === "true")
  const created = createdAt(snapshot, row, now)
  const left = created + QUEUE_LIFETIME_MS - now
  const expired = !done && left <= 0
  return { job, done, expired, expiring: !done && !expired && left <= QUEUE_WARNING_MS, isNew: created >= dayStart, created }
}

/** When a job started its seven days. When the server sends no stamps at all (an
 * older server, or one still upgrading), a saved job starts at the beginning of its sourcing day in
 * Chicago, exactly like the server's upgrade backfill; only an unsaved, undated draft
 * starts now. */
function createdAt(snapshot: Snapshot, row: number, now: number) {
  if (snapshot.row_created) {
    const stamp = snapshot.row_created[row]
    return stamp == null ? now : stamp * 1000
  }
  const day = snapshot.row_dates?.[row]
  if (day && /^\d{4}-\d{2}-\d{2}$/.test(day)) {
    const [year, month, date] = day.split("-").map(Number)
    return chicagoDayStart(Date.UTC(year, month - 1, date, 12))
  }
  return now
}

function draftValues(snapshot: Snapshot, changes: Change[]) {
  const draft = new Map(changes.filter(c => c.value !== undefined).map(c => [`${c.row}:${c.col}`, c.value!]))
  return (r: number, c: number) => draft.get(`${r}:${c}`) ?? String(snapshot.rows[r]?.[c]?.value ?? "")
}

function inQueue(life: RowLifecycle, queue: QueueView) {
  if (!life.job) return queue.status === "todo" || queue.status === "all" // blank input rows
  const todo = !life.done && !life.expired
  const status = queue.status === "all" || (queue.status === "todo" ? todo : queue.status === "completed" ? life.done : life.expired)
  if (!status || !queue.focus) return status
  return todo && (queue.focus === "expiring" ? life.expiring : queue.focus === "new" ? life.isNew : !life.isNew)
}

export function queueCounts(snapshot: Snapshot, changes: Change[], now: number, dayStart: number): QueueCounts {
  const value = draftValues(snapshot, changes), counts: QueueCounts = { todo: 0, new_today: 0, carryover: 0, expiring: 0, completed: 0, expired: 0, all: 0 }
  for (let row = 1; row < snapshot.rows.length; row++) {
    const life = rowLifecycle(snapshot, row, value, now, dayStart)
    if (!life.job) continue
    counts.all++
    if (life.done) counts.completed++
    else if (life.expired) counts.expired++
    else { counts.todo++; if (life.isNew) counts.new_today++; else counts.carryover++; if (life.expiring) counts.expiring++ }
  }
  return counts
}

/** The next moment a row crosses into "expiring soon" or "expired", so the view can refresh itself then. */
export function nextQueueBoundary(snapshot: Snapshot, changes: Change[], now: number, dayStart: number) {
  const value = draftValues(snapshot, changes)
  // Shortly after the next Chicago midnight, when "New today" rolls over (23 or 25 hours on clock-change days).
  let next = chicagoDayStart(dayStart + 36 * 3600_000) + 60_000
  for (let row = 1; row < snapshot.rows.length; row++) {
    const life = rowLifecycle(snapshot, row, value, now, dayStart)
    if (!life.job || life.done || life.expired) continue
    for (const at of [life.created + QUEUE_LIFETIME_MS - QUEUE_WARNING_MS, life.created + QUEUE_LIFETIME_MS]) if (at > now && at < next) next = at
  }
  return next
}

/** Midnight in Chicago for the day containing `now`, exact across daylight-saving changes. */
/** The site a job link points to ("boards.greenhouse.io"), so a long URL reads at a glance. */
export function jobSite(url: string) {
  try { return new URL(url).hostname.replace(/^www\./, "") || url } catch { return url }
}

export function chicagoDayStart(now: number) {
  const offset = (at: number) => {
    const name = new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", timeZoneName: "longOffset" }).formatToParts(new Date(at)).find(p => p.type === "timeZoneName")?.value || "GMT"
    const match = name.match(/GMT([+-])(\d{2}):(\d{2})/)
    return match ? (match[1] === "-" ? -1 : 1) * (Number(match[2]) * 60 + Number(match[3])) * 60_000 : 0
  }
  const [year, month, day] = chicagoDay(new Date(now)).split("-").map(Number)
  const midnightUtc = Date.UTC(year, month - 1, day)
  let start = midnightUtc - offset(midnightUtc)
  start = midnightUtc - offset(start)
  return start
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
    throw new Error(`This ${delimiter === "\t" ? "clipboard text" : "CSV"} has an unclosed quoted cell.`);
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
  if (!/<table(?:\s|>)/i.test(html)) return singleLineClipboardRows(parseDelimited(text, "\t", true));
  // Inert template content never enters the live document. Return text only.
  const template = document.createElement("template");
  template.innerHTML = html;
  const table = template.content.querySelector("table");
  if (!table || !table.rows.length) return singleLineClipboardRows(parseDelimited(text, "\t", true));
  const sourceRows = Array.from(table.rows);
  const matrix: string[][] = [];
  let cells = 0;
  const cellText = (cell: HTMLTableCellElement) => {
    const copy = cell.cloneNode(true) as HTMLTableCellElement;
    copy.querySelectorAll("script,style,noscript,template,iframe,object,embed,svg,math,img,video,audio,source,link,meta").forEach(node => node.remove());
    copy.querySelectorAll("br").forEach(node => node.replaceWith("\n"));
    copy.querySelectorAll("div,p,li").forEach(node => { node.prepend("\n"); node.append("\n"); });
    return copy.textContent || "";
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
  const queue = view.queue;
  const life = new Map<number, RowLifecycle>();
  const lifecycle = (r: number) => {
    let known = life.get(r);
    if (!known && queue) life.set(r, known = rowLifecycle(snapshot, r, value, queue.now, queue.dayStart));
    return known!;
  };
  const rows = snapshot.rows
    .slice(1)
    .map((_, i) => i + 1)
    .filter(
      (r) =>
        (!queue || inQueue(lifecycle(r), queue) || !!queue.keep?.has(snapshot.row_ids[r])) &&
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
  if (queue && view.direction === "none") {
    // To do runs oldest first, so jobs closest to expiring lead; history runs newest
    // first. Row position breaks ties, and blank input rows stay last.
    const oldestFirst = queue.status === "todo";
    rows.sort((a, b) => {
      const left = lifecycle(a), right = lifecycle(b);
      if (left.job !== right.job) return left.job ? -1 : 1;
      if (!left.job) return a - b;
      return (oldestFirst ? left.created - right.created : right.created - left.created) || a - b;
    });
  }
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
