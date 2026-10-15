import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { csvDestinations, parseCSV, type Snapshot } from "@/lib/sourcing";
import { Button } from "@/components/ui/button";
import {
  DialogContent,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
export default function SourcingImport({
  snapshot,
  onSaved,
  onDirty,
  onBusy,
}: {
  snapshot: Snapshot;
  onSaved: (snapshot: Snapshot) => void;
  onDirty: (dirty: boolean) => void;
  onBusy: (busy: boolean) => void;
}) {
  const [text, setText] = useState(""),
    [header, setHeader] = useState(true),
    [mode, setMode] = useState<"append" | "replace">("append"),
    [confirmed, setConfirmed] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [reading, setReading] = useState(false);
  const operation = useRef<{ payload: string; id: string } | null>(null),
    alive = useRef(true),
    readSequence = useRef(0),
    busyRef = useRef(false),
    busyCallback = useRef(onBusy);
  busyCallback.current = onBusy;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      readSequence.current++;
      if (busyRef.current) busyCallback.current(false);
    };
  }, []);
  const preview = useMemo(() => {
    try {
      return { rows: parseCSV(text), error: "" };
    } catch (e) {
      return {
        rows: [],
        error: e instanceof Error ? e.message : "Invalid CSV",
      };
    }
  }, [text]);
  const destinations =
    header && text && !preview.error
      ? csvDestinations(preview.rows[0] || [], snapshot.columns)
      : [];
  const change = (value: string) => {
    if (!alive.current) return;
    setText(value);
    setError("");
    operation.current = null;
    onDirty(!!value);
  };
  const fileRead = async (file: File) => {
    if (file.size > 2_000_000) {
      setError("Choose a CSV file up to 2 MB.");
      return;
    }
    const sequence = ++readSequence.current;
    setReading(true);
    busyRef.current = true;
    onDirty(true);
    onBusy(true);
    try {
      const value = await file.text();
      if (alive.current && sequence === readSequence.current) change(value);
    } catch {
      if (alive.current) {
        setError("Could not read the CSV file. Choose it again.");
        onDirty(!!text);
      }
    } finally {
      if (alive.current && sequence === readSequence.current) {
        setReading(false);
        busyRef.current = false;
        onBusy(false);
      }
    }
  };
  const submit = async () => {
    if (!text || preview.error) return;
    setBusy(true);
    busyRef.current = true;
    onBusy(true);
    setError("");
    const payload = {
      revision: snapshot.revision,
      text,
      mode,
      has_header: header,
    };
    const key = JSON.stringify(payload);
    if (operation.current?.payload !== key)
      operation.current = { payload: key, id: crypto.randomUUID() };
    try {
      const result = await api.post<Snapshot>(
        `/api/sourcing/tabs/${snapshot.id}/import`,
        { ...payload, operation: operation.current.id },
      );
      if (alive.current) {
        onDirty(false);
        onSaved(result);
      }
    } catch (e) {
      if (alive.current)
        setError(
          e instanceof Error
            ? e.message
            : "Import failed. Your source is preserved.",
        );
    } finally {
      busyRef.current = false;
      if (alive.current) setBusy(false);
      onBusy(false);
    }
  };
  const locked = busy || reading;
  return (
    <DialogContent className="sourcing-import">
      <DialogTitle>Import jobs from CSV</DialogTitle>
      <DialogDescription>
        Preview the rows and destination columns before importing. Company, Role
        and Job URL header aliases are recognized.
      </DialogDescription>
      <label className="setting-field">
        CSV file
        <input
          aria-label="CSV file"
          type="file"
          accept=".csv,text/csv"
          disabled={locked}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void fileRead(file);
          }}
        />
      </label>
      {reading && <p role="status">Reading file…</p>}
      <textarea
        aria-label="CSV content"
        value={text}
        disabled={locked}
        maxLength={2000000}
        onChange={(e) => change(e.target.value)}
        placeholder={
          "Company,Role,Job link\nAcme,Engineer,https://jobs.example.com/1"
        }
      />
      <div className="sheet-actions">
        <label>
          <input
            type="checkbox"
            checked={header}
            disabled={locked}
            onChange={(e) => setHeader(e.target.checked)}
          />
          First row contains column names
        </label>
        <label>
          Import mode
          <select
            aria-label="Import mode"
            value={mode}
            disabled={locked}
            onChange={(e) => {
              setMode(e.target.value as "append" | "replace");
              setConfirmed(false);
            }}
          >
            <option value="append">Append jobs</option>
            <option value="replace">Replace existing rows</option>
          </select>
        </label>
      </div>
      {!!destinations.length && (
        <div className="csv-column-map">
          {destinations.map((destination, i) => (
            <span key={i}>
              {preview.rows[0][i] || "(unnamed)"} →{" "}
              <strong>{destination.target}</strong>
              {destination.isNew ? " (new column)" : ""}
            </span>
          ))}
        </div>
      )}
      {text && !preview.error && (
        <>
          <p>
            {Math.max(0, preview.rows.length - (header ? 1 : 0))} data rows ·
            Preview of first 5 rows
          </p>
          <div className="csv-preview">
            <table>
              <tbody>
                {preview.rows.slice(0, 5).map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, c) => (
                      <td key={c}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {mode === "replace" && (
        <label className="sheet-actions">
          <input
            type="checkbox"
            checked={confirmed}
            disabled={locked}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          Replace all existing job rows in this sheet
        </label>
      )}
      {(error || preview.error) && (
        <p className="inline-error" role="alert">
          {error || preview.error}
        </p>
      )}
      <Button
        disabled={
          locked ||
          !text ||
          !!preview.error ||
          (mode === "replace" && !confirmed)
        }
        onClick={() => void submit()}
      >
        {busy ? "Importing…" : "Import jobs"}
      </Button>
    </DialogContent>
  );
}
