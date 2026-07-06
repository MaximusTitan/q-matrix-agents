"use client";

import { useMemo, useState } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { copyCsv, downloadCsv } from "@/lib/csv-actions";
import {
  csvColumnValues,
  csvHeaders,
  diffColumnSets,
  parseCSVLine,
} from "@/lib/csv-utils";
import type { PipelineState } from "@/lib/types";
import { Copy, Download } from "lucide-react";

interface CsvSource {
  id: string;
  label: string;
  csv: string;
}

interface JudgeCandidate {
  id?: string;
  verdict?: string;
  csv?: unknown;
}

// Collect every CSV the current run produced, from all attempts, as labeled
// sources the user can pick. Producers only (agents that emit a csv) + the final
// CSV. Exact-duplicate CSV strings are dropped to keep the list short.
export function collectCsvSources(state: PipelineState): CsvSource[] {
  const sources: CsvSource[] = [];
  const seen = new Set<string>();
  let n = 0;

  const add = (label: string, csv: unknown) => {
    if (typeof csv !== "string" || !csv.trim() || seen.has(csv)) return;
    seen.add(csv);
    sources.push({ id: `src-${n++}`, label, csv });
  };

  for (const att of state.attempts) {
    if (!att?.agents) continue;
    for (const agent of att.agents) {
      const out = agent.output as Record<string, unknown> | null;
      if (!out) continue;
      if (agent.name === "Judge" && Array.isArray(out.candidates)) {
        for (const c of out.candidates as JudgeCandidate[]) {
          const chosen = c.verdict === "chosen" ? " (chosen)" : "";
          add(`Judge: ${c.id ?? "candidate"}${chosen} · attempt ${att.attempt}`, c.csv);
        }
      } else {
        add(`${agent.name} · attempt ${att.attempt}`, out.csv_preview);
      }
    }
  }

  add("Final CSV", state.csv);
  return sources;
}

const DEFAULT_COLUMN = "concept";

function pickDefaultColumn(headers: string[]): string {
  const exact = headers.find((h) => h.toLowerCase() === DEFAULT_COLUMN);
  return exact ?? headers[0] ?? "";
}

// ── A labeled <Select> used for both source and column pickers ─────────────────
function PickSelect({
  label,
  value,
  options,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</Label>
      <Select value={value} onValueChange={(v) => v && onChange(v)}>
        <SelectTrigger className="h-8 w-full bg-secondary text-xs">
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

// ── A simple scrollable CSV table + copy/download (used in side-by-side view) ──
function CompareTable({ source }: { source: CsvSource }) {
  const lines = source.csv.split("\n").filter((l) => l.trim());
  const headers = lines.length > 0 ? parseCSVLine(lines[0]) : [];
  const rows = lines.slice(1).map((l) => parseCSVLine(l, headers.length));

  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[11px] font-bold text-foreground/80" title={source.label}>
          {source.label}
        </span>
        <div className="flex shrink-0 gap-2">
          <button
            onClick={() => copyCsv(source.csv)}
            title="Copy CSV"
            className="flex items-center gap-0.5 text-[10px] text-primary/70 hover:text-primary transition-colors"
          >
            <Copy className="h-3 w-3" /> Copy
          </button>
          <button
            onClick={() => downloadCsv(source.csv, "comparison.csv")}
            title="Download CSV"
            className="flex items-center gap-0.5 text-[10px] text-primary/70 hover:text-primary transition-colors"
          >
            <Download className="h-3 w-3" /> Download
          </button>
        </div>
      </div>
      <div className="thin-scroll max-h-[420px] overflow-auto rounded border border-border">
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
            {rows.map((row, ri) => (
              <tr key={ri} className={ri % 2 === 0 ? "bg-card" : "bg-secondary/30"}>
                {row.map((cell, ci) => (
                  <td
                    key={ci}
                    className="px-2 py-1 align-top text-[10px] text-foreground/80 whitespace-normal break-words"
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── One column of the diff (Only in A / In both / Only in B) ───────────────────
function DiffColumn({ title, items, color }: { title: string; items: string[]; color: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex items-center gap-1.5 border-b border-border pb-1">
        <span className="text-[9px] font-bold uppercase tracking-widest" style={{ color }}>
          {title}
        </span>
        <span className="text-[9px] font-bold" style={{ color }}>{items.length}</span>
      </div>
      <div className="thin-scroll max-h-[420px] space-y-px overflow-y-auto">
        {items.length === 0 ? (
          <div className="px-1 py-0.5 text-[10px] text-muted-foreground/50">—</div>
        ) : (
          items.map((v, i) => (
            <div key={i} className="px-1 py-0.5 text-[10px] text-foreground/80 break-words">
              {v}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export function ComparePanel({ state }: { state: PipelineState }) {
  const sources = useMemo(() => collectCsvSources(state), [state]);

  const [aId, setAId] = useState<string>(sources[0]?.id ?? "");
  const [bId, setBId] = useState<string>(sources[1]?.id ?? sources[0]?.id ?? "");
  const [aCol, setACol] = useState<string>("");
  const [bCol, setBCol] = useState<string>("");
  const [view, setView] = useState<"diff" | "side">("diff");

  const sourceA = sources.find((s) => s.id === aId) ?? sources[0];
  const sourceB = sources.find((s) => s.id === bId) ?? sources[1] ?? sources[0];

  const headersA = useMemo(() => (sourceA ? csvHeaders(sourceA.csv) : []), [sourceA]);
  const headersB = useMemo(() => (sourceB ? csvHeaders(sourceB.csv) : []), [sourceB]);

  // Resolve the effective column for each side, falling back to a sensible default
  // whenever the current pick isn't a column of the selected source.
  const colA = headersA.includes(aCol) ? aCol : pickDefaultColumn(headersA);
  const colB = headersB.includes(bCol) ? bCol : pickDefaultColumn(headersB);

  const diff = useMemo(() => {
    if (!sourceA || !sourceB || !colA || !colB) return null;
    return diffColumnSets(csvColumnValues(sourceA.csv, colA), csvColumnValues(sourceB.csv, colB));
  }, [sourceA, sourceB, colA, colB]);

  if (sources.length < 2) {
    return (
      <div className="flex h-[200px] items-center justify-center text-center text-[11px] text-muted-foreground">
        Run the pipeline to generate at least two CSVs, then compare any agent&apos;s CSV or column here.
      </div>
    );
  }

  const srcOptions = sources.map((s) => ({ value: s.id, label: s.label }));
  const colOptionsA = headersA.map((h) => ({ value: h, label: h }));
  const colOptionsB = headersB.map((h) => ({ value: h, label: h }));

  return (
    <div className="flex flex-col gap-4">
      {/* Selectors */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="space-y-2 rounded-md border border-border bg-card p-3">
          <div className="text-[10px] font-bold uppercase tracking-widest text-[var(--qm-blue)]">
            Selection A
          </div>
          <PickSelect label="Source" value={aId} options={srcOptions} onChange={setAId} placeholder="Pick a CSV…" />
          <PickSelect label="Column" value={colA} options={colOptionsA} onChange={setACol} placeholder="Pick a column…" />
        </div>
        <div className="space-y-2 rounded-md border border-border bg-card p-3">
          <div className="text-[10px] font-bold uppercase tracking-widest text-[var(--qm-purple)]">
            Selection B
          </div>
          <PickSelect label="Source" value={bId} options={srcOptions} onChange={setBId} placeholder="Pick a CSV…" />
          <PickSelect label="Column" value={colB} options={colOptionsB} onChange={setBCol} placeholder="Pick a column…" />
        </div>
      </div>

      {/* View toggle */}
      <div className="flex w-fit rounded-lg border border-border bg-secondary/40 p-0.5">
        {([
          ["diff", "Column diff"],
          ["side", "Side by side"],
        ] as const).map(([value, label]) => (
          <button
            key={value}
            onClick={() => setView(value)}
            className={cn(
              "rounded-md px-3 py-1 text-[10px] font-bold uppercase tracking-wide transition-colors",
              view === value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {view === "diff" ? (
        <div className="rounded-md border border-border bg-card p-3">
          <div className="mb-2 text-[10px] text-muted-foreground">
            Comparing <span className="text-[var(--qm-blue)]">{sourceA?.label} · {colA}</span> against{" "}
            <span className="text-[var(--qm-purple)]">{sourceB?.label} · {colB}</span>
          </div>
          {diff && (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <DiffColumn title="Only in A" items={diff.onlyA} color="var(--qm-blue)" />
              <DiffColumn title="In both" items={diff.both} color="var(--qm-green)" />
              <DiffColumn title="Only in B" items={diff.onlyB} color="var(--qm-purple)" />
            </div>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {sourceA && <CompareTable source={sourceA} />}
          {sourceB && <CompareTable source={sourceB} />}
        </div>
      )}
    </div>
  );
}
