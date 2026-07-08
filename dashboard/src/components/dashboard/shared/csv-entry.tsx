"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, Copy, Download, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { copyCsv, downloadCsv } from "@/lib/csv-actions";
import { parseCSVLine } from "@/lib/csv-utils";

// A CSV whose text is either already in hand (live SSE run) or must be fetched on
// demand from the run/ folder (historical analytics). One component renders both so
// the live and analytics surfaces look identical.
export type CsvSourceInput =
  | { kind: "text"; text: string; filename?: string; label?: string; rows?: number | null }
  | {
      kind: "ref";
      file: string;
      rows?: number | null;
      label?: string;
      load: (file: string) => Promise<string>;
    };

// A CSV table cell that truncates by default and expands to full wrapped text on click.
function CsvCell({ cell }: { cell: string }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <td
      onClick={() => setExpanded((p) => !p)}
      className={cn(
        "px-2 py-1 text-[10px] text-foreground/80 cursor-pointer align-top",
        expanded ? "whitespace-normal break-words" : "whitespace-nowrap max-w-[160px] truncate"
      )}
      title={expanded ? undefined : cell}
    >
      {cell}
    </td>
  );
}

function CsvTable({ csvText }: { csvText: string }) {
  const lines = csvText.split("\n").filter((l) => l.trim());
  const headers = lines.length > 0 ? parseCSVLine(lines[0]) : [];
  const dataRows = lines.slice(1).map((l) => parseCSVLine(l, headers.length));

  return (
    <div className="thin-scroll mt-1 max-h-52 overflow-auto rounded border border-border">
      <table className="min-w-full text-[10px]">
        <thead>
          <tr className="bg-secondary">
            {headers.map((h, i) => (
              <th
                key={i}
                className="px-2 py-1 text-left text-[9px] font-bold uppercase tracking-wide text-muted-foreground whitespace-nowrap"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dataRows.map((row, ri) => (
            <tr key={ri} className={ri % 2 === 0 ? "bg-card" : "bg-secondary/30"}>
              {row.map((cell, ci) => (
                <CsvCell key={ci} cell={cell} />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function actionButtonClass() {
  return "flex items-center gap-0.5 text-[10px] text-primary/70 hover:text-primary transition-colors w-fit disabled:opacity-40 disabled:cursor-not-allowed";
}

// Renders one CSV: a collapsed header (label + row count), then expand / copy /
// download actions. For `ref` sources the text is fetched lazily on the first
// action that needs it and cached so preview / copy / download share one request.
export function CsvEntry({ source }: { source: CsvSourceInput }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState<string | null>(source.kind === "text" ? source.text : null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const label = source.label ?? (source.kind === "ref" ? source.file : source.filename ?? "curriculum.csv");
  const filename = source.kind === "ref" ? source.file : source.filename ?? "curriculum.csv";
  const knownRows = source.rows ?? undefined;
  const rowCount = text != null ? text.split("\n").filter((l) => l.trim()).length - 1 : knownRows;

  // Ensure the CSV text is available, fetching it once for ref sources.
  async function ensureText(): Promise<string | null> {
    if (text != null) return text;
    if (source.kind === "text") return source.text;
    setLoading(true);
    setError(null);
    try {
      const fetched = await source.load(source.file);
      setText(fetched);
      return fetched;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load CSV");
      return null;
    } finally {
      setLoading(false);
    }
  }

  async function toggleOpen() {
    if (!open) await ensureText();
    setOpen((p) => !p);
  }

  async function handleCopy() {
    const t = await ensureText();
    if (t != null) copyCsv(t);
  }

  async function handleDownload() {
    const t = await ensureText();
    if (t != null) downloadCsv(t, filename);
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2 text-[11px] leading-relaxed">
        <span className="font-mono text-foreground/80">{label}</span>
        {rowCount != null && rowCount >= 0 && (
          <span className="text-[var(--qm-green)]">
            {rowCount} row{rowCount !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      <div className="flex items-center gap-3">
        <button onClick={toggleOpen} className={actionButtonClass()}>
          {loading ? (
            <><Loader2 className="h-3 w-3 animate-spin" /> Loading</>
          ) : open ? (
            <><ChevronUp className="h-3 w-3" /> Collapse preview</>
          ) : (
            <><ChevronDown className="h-3 w-3" /> Expand preview</>
          )}
        </button>
        <button onClick={handleCopy} title="Copy CSV to clipboard" disabled={loading} className={actionButtonClass()}>
          <Copy className="h-3 w-3" /> Copy
        </button>
        <button onClick={handleDownload} title="Download CSV" disabled={loading} className={actionButtonClass()}>
          <Download className="h-3 w-3" /> Download
        </button>
      </div>

      {error && <div className="text-[10px] text-[var(--qm-red)]">{error}</div>}
      {open && text != null && <CsvTable csvText={text} />}
    </div>
  );
}
