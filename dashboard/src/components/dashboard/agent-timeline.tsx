"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Copy, Download } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { AgentRecord, Reconciliation, ReconciliationEntry } from "@/lib/types";
import { cn } from "@/lib/utils";
import { copyCsv, downloadCsv } from "@/lib/csv-actions";
import { parseCSVLine } from "@/lib/csv-utils";

const AGENT_ICONS: Record<string, string> = {
  Generator: "⚙",
  Eval: "📋",
  Revision: "🔁",
  Doctor: "🩺",
  "Doctor (rules)": "🩹",
  "Eval (doctored)": "📋",
  Judge: "⚖",
  "Map Extraction": "🗂",
  "Map Extraction + Generator": "⟳",
  Prerequisites: "🔗",
};

const AGENT_COLORS: Record<string, string> = {
  Generator: "var(--qm-blue)",
  Eval: "var(--qm-amber)",
  Revision: "var(--qm-purple)",
  Doctor: "var(--qm-green)",
  "Doctor (rules)": "var(--qm-green)",
  "Eval (doctored)": "var(--qm-amber)",
  Judge: "var(--qm-purple)",
  "Map Extraction": "var(--qm-blue)",
  "Map Extraction + Generator": "var(--qm-blue)",
  Prerequisites: "var(--qm-green)",
};

// Keys filtered from the generic IO display (handled by dedicated sub-components)
const EXCLUDED_KEYS = new Set([
  "csv", "prompt", "csv_preview", "base_prompt", "revised_prompt", "concept_skill_map",
]);

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatValue(v: unknown): string {
  if (Array.isArray(v)) {
    return v.length
      ? `[${v.slice(0, 3).join(", ")}${v.length > 3 ? "…" : ""}]`
      : "[]";
  }
  if (typeof v === "object" && v !== null) {
    const s = JSON.stringify(v);
    return s.slice(0, 80) + (s.length > 80 ? "…" : "");
  }
  const s = String(v);
  return s.slice(0, 80) + (s.length > 80 ? "…" : "");
}

function needsExpand(data: Record<string, unknown>): boolean {
  const entries = Object.entries(data).filter(([k]) => !EXCLUDED_KEYS.has(k));
  if (entries.length > 2) return true;
  return entries.some(([, v]) => {
    if (Array.isArray(v) && v.length > 3) return true;
    if (typeof v === "object" && v !== null) return true;
    if (typeof v === "string" && v.length > 80) return true;
    return false;
  });
}

function parseCsvSets(csvText: string): { concepts: Set<string>; skills: Set<string> } {
  const lines = csvText.split("\n").filter((l) => l.trim());
  const concepts = new Set<string>();
  const skills = new Set<string>();
  if (lines.length < 2) return { concepts, skills };
  const headers = parseCSVLine(lines[0]);
  const conceptIdx = headers.findIndex((h) => h.toLowerCase() === "concept");
  const skillIdx = headers.findIndex((h) => h.toLowerCase() === "skill");
  for (let i = 1; i < lines.length; i++) {
    const row = parseCSVLine(lines[i], headers.length);
    if (conceptIdx >= 0 && row[conceptIdx]) concepts.add(row[conceptIdx].trim());
    if (skillIdx >= 0 && row[skillIdx]) skills.add(row[skillIdx].trim());
  }
  return { concepts, skills };
}

// ── IOSection ─────────────────────────────────────────────────────────────────

function IOSection({
  data,
  label,
}: {
  data: Record<string, unknown>;
  label: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const entries = Object.entries(data).filter(([k]) => !EXCLUDED_KEYS.has(k));
  if (!entries.length) return null;

  const showExpand = needsExpand(data);
  const previewEntries = entries.slice(0, 2);

  return (
    <div className="flex flex-col gap-1">
      <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
        {label}
      </div>

      {!expanded ? (
        <>
          {previewEntries.map(([k, v]) => (
            <div key={k} className="text-[11px] leading-relaxed">
              <span className="text-muted-foreground">{k}:</span>{" "}
              <span>{formatValue(v)}</span>
            </div>
          ))}
          {entries.length > 2 && (
            <div className="text-[10px] text-muted-foreground">
              +{entries.length - 2} more field{entries.length - 2 > 1 ? "s" : ""}
            </div>
          )}
        </>
      ) : (
        <div className="thin-scroll max-h-48 overflow-y-auto rounded bg-secondary/60">
          <pre className="p-2 text-[10px] leading-relaxed whitespace-pre-wrap break-all">
            {JSON.stringify(Object.fromEntries(entries), null, 2)}
          </pre>
        </div>
      )}

      {showExpand && (
        <button
          onClick={() => setExpanded((p) => !p)}
          className="flex items-center gap-0.5 text-[10px] text-primary/70 hover:text-primary transition-colors w-fit"
        >
          {expanded ? (
            <><ChevronUp className="h-3 w-3" /> Collapse</>
          ) : (
            <><ChevronDown className="h-3 w-3" /> View full</>
          )}
        </button>
      )}
    </div>
  );
}

// ── TextExpandEntry — reusable expandable text block ─────────────────────────

function TextExpandEntry({
  label,
  text,
  accentColor = "var(--qm-blue)",
}: {
  label: string;
  text: string;
  accentColor?: string;
}) {
  const [open, setOpen] = useState(false);
  const preview = text.slice(0, 120).trimEnd() + (text.length > 120 ? "…" : "");

  return (
    <div className="flex flex-col gap-1">
      <div className="text-[11px] leading-relaxed">
        <span className="text-muted-foreground">{label}:</span>{" "}
        <span style={{ color: accentColor, opacity: 0.8 }}>{preview}</span>
      </div>

      <button
        onClick={() => setOpen((p) => !p)}
        className="flex items-center gap-0.5 text-[10px] text-primary/70 hover:text-primary transition-colors w-fit"
      >
        {open ? (
          <><ChevronUp className="h-3 w-3" /> Collapse {label}</>
        ) : (
          <><ChevronDown className="h-3 w-3" /> Expand {label}</>
        )}
      </button>

      {open && (
        <div className="thin-scroll mt-1 max-h-64 overflow-y-auto rounded border border-border bg-secondary/60">
          <pre className="p-2 text-[10px] leading-relaxed whitespace-pre-wrap break-words">
            {text}
          </pre>
        </div>
      )}
    </div>
  );
}

// ── CSV inline preview (Generator card) ───────────────────────────────────────

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

function CsvInlineEntry({ csvText }: { csvText: string }) {
  const [open, setOpen] = useState(false);

  const lines = csvText.split("\n").filter((l) => l.trim());
  const headers = lines.length > 0 ? parseCSVLine(lines[0]) : [];
  const dataRows = lines.slice(1).map((l) => parseCSVLine(l, headers.length));
  const rowCount = dataRows.length;

  // Name the download after the chapter column when present, else a generic name.
  const chapterIdx = headers.indexOf("chapter");
  const chapterName = chapterIdx >= 0 ? dataRows[0]?.[chapterIdx] : undefined;
  const filename = `${chapterName?.trim() || "curriculum"}.csv`;

  return (
    <div className="flex flex-col gap-1">
      <div className="text-[11px] leading-relaxed">
        <span className="text-muted-foreground">csv_preview:</span>{" "}
        <span className="text-[var(--qm-green)]">{rowCount} row{rowCount !== 1 ? "s" : ""}</span>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={() => setOpen((p) => !p)}
          className="flex items-center gap-0.5 text-[10px] text-primary/70 hover:text-primary transition-colors w-fit"
        >
          {open ? (
            <><ChevronUp className="h-3 w-3" /> Collapse preview</>
          ) : (
            <><ChevronDown className="h-3 w-3" /> Expand preview</>
          )}
        </button>
        <button
          onClick={() => copyCsv(csvText)}
          title="Copy CSV to clipboard"
          className="flex items-center gap-0.5 text-[10px] text-primary/70 hover:text-primary transition-colors w-fit"
        >
          <Copy className="h-3 w-3" /> Copy
        </button>
        <button
          onClick={() => downloadCsv(csvText, filename)}
          title="Download CSV"
          className="flex items-center gap-0.5 text-[10px] text-primary/70 hover:text-primary transition-colors w-fit"
        >
          <Download className="h-3 w-3" /> Download
        </button>
      </div>

      {open && (
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
      )}
    </div>
  );
}

// ── GeneratorStatsEntry — unique concept + skill counts ───────────────────────

function GeneratorStatsEntry({ csvText }: { csvText: string }) {
  const { concepts, skills } = parseCsvSets(csvText);
  return (
    <div className="flex gap-4 mt-0.5">
      <div className="flex flex-col">
        <span className="text-[9px] uppercase tracking-wide text-muted-foreground">Concepts</span>
        <span className="text-lg font-bold leading-tight" style={{ color: "var(--qm-blue)" }}>
          {concepts.size}
        </span>
        <span className="text-[9px] text-muted-foreground">unique</span>
      </div>
      <div className="w-px bg-border self-stretch" />
      <div className="flex flex-col">
        <span className="text-[9px] uppercase tracking-wide text-muted-foreground">Skills</span>
        <span className="text-lg font-bold leading-tight" style={{ color: "var(--qm-blue)" }}>
          {skills.size}
        </span>
        <span className="text-[9px] text-muted-foreground">unique</span>
      </div>
    </div>
  );
}

// ── CoverageDiff — matched-pairs coverage table (Eval card) ──────────────────

interface CsmData {
  concepts: string[];
  skills: string[];
}


// A single expandable coverage row. Collapsed: truncated single line.
// Expanded (click anywhere): full wrapped text, with multiple CSV items as bullets.
function CoverageRow({
  csmText,
  csvItems,
  status,
  recon,
}: {
  csmText: string;
  csvItems: string[];
  status: "missing" | "covered" | "extra";
  recon?: ReconciliationEntry;
}) {
  const [expanded, setExpanded] = useState(false);

  const tone =
    status === "missing"
      ? "bg-[var(--qm-red)]/5"
      : status === "covered"
      ? "bg-[var(--qm-green)]/5"
      : "bg-muted/30";
  const statusTone =
    status === "missing"
      ? "text-[var(--qm-red)]"
      : status === "covered"
      ? "text-[var(--qm-green)]"
      : "text-muted-foreground/60";
  const statusLabel =
    status === "missing" ? "✗ missing" : status === "covered" ? "✓ covered" : "extra";

  const hasCsv = csvItems.length > 0;
  const csvJoined = csvItems.join("; ");

  // Reconciliation marker (pass-2 similarity audit). "recovered" = was missing,
  // now covered via similarity; "rejected" = had a similar extra but LLM disagreed.
  const reconBadge = recon
    ? recon.outcome === "recovered"
      ? { text: "↺ reconciled", cls: "text-[var(--qm-amber)]" }
      : { text: "↺ checked", cls: "text-muted-foreground/60" }
    : null;

  return (
    <div
      onClick={() => setExpanded((p) => !p)}
      className={cn(
        "flex flex-col rounded px-1 py-0.5 cursor-pointer hover:brightness-110",
        tone
      )}
      title={expanded ? undefined : "Click to expand"}
    >
      <div
        className={cn(
          "grid grid-cols-[1fr_1fr_auto] gap-x-2",
          expanded ? "items-start" : "items-center"
        )}
      >
        {/* CSM (expected) */}
        <div
          className={cn(
            "text-[10px] text-foreground/80 flex items-center gap-1",
            status === "extra" && "text-muted-foreground/40 italic",
            expanded ? "whitespace-normal break-words" : "truncate"
          )}
        >
          {reconBadge && (
            <span className={cn("shrink-0 text-[9px] font-semibold", reconBadge.cls)}>↺</span>
          )}
          <span className={expanded ? "whitespace-normal break-words" : "truncate"}>{csmText}</span>
        </div>

        {/* CSV (actual) */}
        <div
          className={cn(
            "text-[10px]",
            status === "missing" ? "text-muted-foreground/40 italic" : "text-foreground/80",
            status === "extra" && "text-foreground/60",
            expanded ? "whitespace-normal break-words" : "truncate"
          )}
        >
          {!hasCsv ? (
            "—"
          ) : expanded && csvItems.length > 1 ? (
            <ul className="list-disc pl-3 space-y-0.5">
              {csvItems.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          ) : (
            csvJoined
          )}
        </div>

        {/* Status */}
        <div className={cn("text-[10px] font-semibold shrink-0 w-14 text-right", statusTone)}>
          {statusLabel}
        </div>
      </div>

      {/* Reconciliation detail — shown when the row is expanded */}
      {expanded && recon && (
        <div className="mt-1 ml-1 border-l-2 border-[var(--qm-amber)]/40 pl-2 flex flex-col gap-0.5">
          <div className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/70">
            {recon.outcome === "recovered"
              ? "Recovered via similarity — covered by:"
              : "Similar extras checked, not confirmed covered:"}
          </div>
          {recon.candidates.map((c, i) => {
            const confirmed = recon.covered_by.some(
              (cb) => cb.toLowerCase() === c.actual.toLowerCase()
            );
            return (
              <div key={i} className="grid grid-cols-[auto_1fr] gap-x-2 items-baseline text-[10px]">
                <span
                  className={cn(
                    "font-mono tabular-nums",
                    confirmed ? "text-[var(--qm-green)]" : "text-muted-foreground/50"
                  )}
                >
                  {c.score.toFixed(2)}
                </span>
                <span
                  className={cn(
                    "break-words",
                    confirmed ? "text-foreground/80" : "text-muted-foreground/60 line-through decoration-muted-foreground/30"
                  )}
                >
                  {c.actual}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function CoveragePairsTable({
  label,
  csmItems,
  missingSet,
  matched,
  csvExtras,
  recon,
}: {
  label: string;
  csmItems: string[];
  missingSet: Set<string>;
  matched: Record<string, string[] | string>;
  csvExtras: string[];
  recon: Record<string, ReconciliationEntry>;
}) {
  // Build a lookup: csm item (lowercased) → list of matched csv item(s).
  // Values are lists (1:N coverage); tolerate a legacy bare string.
  const matchedLower: Record<string, string[]> = {};
  for (const [k, v] of Object.entries(matched)) {
    const items = Array.isArray(v) ? v : [v];
    matchedLower[k.toLowerCase()] = items.filter(Boolean);
  }

  // Reconciliation entries keyed by lowercased expected item.
  const reconLower: Record<string, ReconciliationEntry> = {};
  for (const [k, v] of Object.entries(recon)) {
    reconLower[k.toLowerCase()] = v;
  }

  const matchedFromCsm = csmItems.filter((item) => !missingSet.has(item.toLowerCase())).length;
  const missingFromCsm = csmItems.filter((item) => missingSet.has(item.toLowerCase())).length;
  const matchedFromCsv = Object.values(matchedLower).reduce((sum, arr) => sum + arr.length, 0);
  const extrasFromCsv = csvExtras.length;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="text-[9px] font-bold uppercase tracking-widest text-muted-foreground border-b border-border pb-1">
        {label}
      </div>

      {/* Analytics summary row */}
      <div className="grid grid-cols-4 gap-1 rounded bg-secondary/50 px-2 py-1.5">
        <div className="flex flex-col items-center gap-0.5">
          <span className="text-[11px] font-bold text-emerald-500">{matchedFromCsm}</span>
          <span className="text-[8px] text-muted-foreground/70 text-center leading-tight">Matched<br/>from CSM</span>
        </div>
        <div className="flex flex-col items-center gap-0.5">
          <span className="text-[11px] font-bold text-rose-500">{missingFromCsm}</span>
          <span className="text-[8px] text-muted-foreground/70 text-center leading-tight">Missing<br/>from CSM</span>
        </div>
        <div className="flex flex-col items-center gap-0.5">
          <span className="text-[11px] font-bold text-sky-500">{matchedFromCsv}</span>
          <span className="text-[8px] text-muted-foreground/70 text-center leading-tight">Matched<br/>from CSV</span>
        </div>
        <div className="flex flex-col items-center gap-0.5">
          <span className="text-[11px] font-bold text-amber-500">{extrasFromCsv}</span>
          <span className="text-[8px] text-muted-foreground/70 text-center leading-tight">Extras<br/>from CSV</span>
        </div>
      </div>

      {/* Header row */}
      <div className="grid grid-cols-[1fr_1fr_auto] gap-x-2 items-center px-1">
        <div className="text-[8px] font-semibold uppercase tracking-widest text-muted-foreground/70">
          CSM (expected)
        </div>
        <div className="text-[8px] font-semibold uppercase tracking-widest text-muted-foreground/70">
          CSV (actual)
        </div>
        <div className="w-14 text-[8px] font-semibold uppercase tracking-widest text-muted-foreground/70 text-right">
          Status
        </div>
      </div>

      {/* One row per CSM item */}
      <div className="thin-scroll max-h-48 overflow-y-auto space-y-px">
        {csmItems.map((item) => {
          const missing = missingSet.has(item.toLowerCase());
          const csvItems = missing ? [] : (matchedLower[item.toLowerCase()] ?? []);
          return (
            <CoverageRow
              key={item}
              csmText={item}
              csvItems={csvItems}
              status={missing ? "missing" : "covered"}
              recon={reconLower[item.toLowerCase()]}
            />
          );
        })}
      </div>

      {/* Extra CSV items not matched to anything in CSM */}
      {csvExtras.length > 0 && (
        <div className="mt-1 flex flex-col gap-0.5">
          <div className="text-[8px] font-semibold uppercase tracking-widest text-muted-foreground/60 pt-1 border-t border-border">
            Extra in CSV ({csvExtras.length})
          </div>
          <div className="thin-scroll max-h-24 overflow-y-auto space-y-px">
            {csvExtras.map((item) => (
              <CoverageRow key={item} csmText="—" csvItems={[item]} status="extra" />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CoverageDiff({
  csvText,
  csm,
  missingConcepts,
  missingSkills,
  matchedConcepts,
  matchedSkills,
  extraConcepts: extraConceptsProp,
  extraSkills: extraSkillsProp,
  reconciliation,
}: {
  csvText: string;
  csm: CsmData;
  missingConcepts: string[];
  missingSkills: string[];
  matchedConcepts: Record<string, string[] | string>;
  matchedSkills: Record<string, string[] | string>;
  extraConcepts?: string[];
  extraSkills?: string[];
  reconciliation?: Reconciliation;
}) {
  const [open, setOpen] = useState(false);
  const { concepts: csvConcepts, skills: csvSkills } = parseCsvSets(csvText);

  const missingConceptSet = new Set(missingConcepts.map((c) => c.toLowerCase()));
  const missingSkillSet = new Set(missingSkills.map((s) => s.toLowerCase()));

  // Prefer the backend-computed extras (they account for 1:N coverage); fall back
  // to deriving from flattened matched values for older runs without the field.
  const flattenValues = (m: Record<string, string[] | string>) =>
    new Set(
      Object.values(m)
        .flatMap((v) => (Array.isArray(v) ? v : [v]))
        .filter(Boolean)
        .map((v) => v.toLowerCase())
    );
  const extraConcepts =
    extraConceptsProp ??
    [...csvConcepts].filter((c) => !flattenValues(matchedConcepts).has(c.toLowerCase()));
  const extraSkills =
    extraSkillsProp ??
    [...csvSkills].filter((s) => !flattenValues(matchedSkills).has(s.toLowerCase()));

  return (
    <div className="flex flex-col gap-1">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex items-center gap-1 text-[10px] text-primary/70 hover:text-primary transition-colors w-fit"
      >
        {open ? (
          <><ChevronUp className="h-3 w-3" /> Collapse coverage comparison</>
        ) : (
          <><ChevronDown className="h-3 w-3" /> View coverage comparison</>
        )}
      </button>

      {open && (
        <div className="mt-1 flex flex-col gap-4 rounded border border-border bg-secondary/30 p-3">
          <CoveragePairsTable
            label="Concepts"
            csmItems={csm.concepts}
            missingSet={missingConceptSet}
            matched={matchedConcepts}
            csvExtras={extraConcepts}
            recon={reconciliation?.concepts ?? {}}
          />
          <CoveragePairsTable
            label="Skills"
            csmItems={csm.skills}
            missingSet={missingSkillSet}
            matched={matchedSkills}
            csvExtras={extraSkills}
            recon={reconciliation?.skills ?? {}}
          />
        </div>
      )}
    </div>
  );
}

// ── MapListSection — expandable list of concepts or skills ────────────────────

function MapListSection({
  label,
  items,
  color,
}: {
  label: string;
  items: string[];
  color: string;
}) {
  const [open, setOpen] = useState(false);
  const PREVIEW = 4;

  return (
    <div className="flex flex-col gap-1">
      {/* Header row: label + count badge */}
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
          {label}
        </span>
        <span
          className="rounded px-1.5 py-0.5 text-[9px] font-bold"
          style={{ background: `${color}22`, color }}
        >
          {items.length}
        </span>
      </div>

      {/* Preview rows (always visible) */}
      <div className="space-y-0.5">
        {(open ? items : items.slice(0, PREVIEW)).map((item, i) => (
          <div
            key={i}
            className="flex items-start gap-1.5 text-[10px] leading-relaxed"
          >
            <span style={{ color }} className="mt-px shrink-0 text-[9px]">▸</span>
            <span className="text-foreground/80">{item}</span>
          </div>
        ))}
      </div>

      {items.length > PREVIEW && (
        <button
          onClick={() => setOpen((p) => !p)}
          className="flex items-center gap-0.5 text-[10px] text-primary/70 hover:text-primary transition-colors w-fit"
        >
          {open ? (
            <><ChevronUp className="h-3 w-3" /> Show less</>
          ) : (
            <><ChevronDown className="h-3 w-3" /> +{items.length - PREVIEW} more</>
          )}
        </button>
      )}
    </div>
  );
}

// ── MapExtractionCard ─────────────────────────────────────────────────────────

function MapExtractionCard({ agent }: { agent: AgentRecord }) {
  const color = AGENT_COLORS[agent.name] ?? "var(--qm-blue)";
  const icon = AGENT_ICONS[agent.name] ?? "●";
  const inp = agent.input as Record<string, unknown>;
  const out = agent.output as Record<string, unknown> | null;

  const guidance = typeof inp.guidance === "string" ? inp.guidance : null;

  const concepts = Array.isArray(out?.concepts) ? (out!.concepts as string[]) : null;
  const skills   = Array.isArray(out?.skills)   ? (out!.skills   as string[]) : null;

  return (
    <Card className="border-border bg-card py-0">
      <CardHeader className="flex flex-row items-center gap-3 border-b border-border px-4 py-2.5">
        <div
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-sm"
          style={{ background: `${color}22`, color }}
        >
          {icon}
        </div>
        <div className="flex-1 text-xs font-bold" style={{ color }}>
          {agent.name}
        </div>
        {agent.status === "running" ? (
          <span className="text-[10px] font-bold text-[var(--qm-amber)]">
            <span className="inline-block animate-spin">⟳</span> RUNNING
          </span>
        ) : (
          <span className="text-[10px] font-bold text-[var(--qm-green)]">✓ DONE</span>
        )}
      </CardHeader>

      <CardContent className="grid grid-cols-2 gap-4 px-4 py-3">
        {/* Input column */}
        <div className="flex flex-col gap-1">
          <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
            INPUT
          </div>
          {(["board", "subject", "grade", "chapter"] as const).map((k) =>
            inp[k] != null ? (
              <div key={k} className="text-[11px] leading-relaxed">
                <span className="text-muted-foreground">{k}:</span>{" "}
                <span>{String(inp[k])}</span>
              </div>
            ) : null
          )}
          {guidance && (
            <TextExpandEntry label="guidance" text={guidance} accentColor={color} />
          )}
        </div>

        {/* Output column */}
        {out ? (
          <div className="flex flex-col gap-3">
            <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
              OUTPUT
            </div>

            {concepts ? (
              <MapListSection label="Concepts" items={concepts} color={color} />
            ) : null}

            {skills ? (
              <MapListSection label="Skills" items={skills} color={color} />
            ) : null}

            <div className="text-[10px] text-muted-foreground italic">
              Saved to knowledge base
            </div>
          </div>
        ) : (
          <div />
        )}
      </CardContent>
    </Card>
  );
}

// ── EvalCard ──────────────────────────────────────────────────────────────────

function EvalCard({ agent }: { agent: AgentRecord }) {
  const color = AGENT_COLORS["Eval"];
  const icon = AGENT_ICONS["Eval"];
  const inp = agent.input as Record<string, unknown>;
  const out = agent.output as Record<string, unknown> | null;

  const csvText = typeof inp.csv_preview === "string" ? inp.csv_preview : null;
  const csm = inp.concept_skill_map as CsmData | null;

  type CheckResult = { passed?: boolean; feedback?: string[]; missing_concepts?: string[]; missing_skills?: string[]; matched_concepts?: Record<string, string[] | string>; matched_skills?: Record<string, string[] | string>; extra_concepts?: string[]; extra_skills?: string[]; reconciliation?: Reconciliation };
  const check1 = out?.check1 as CheckResult | null;
  const check2 = out?.check2 as CheckResult | null;

  const hasDiff = csvText && csm && csm.concepts?.length > 0;

  return (
    <Card className="border-border bg-card py-0">
      <CardHeader className="flex flex-row items-center gap-3 border-b border-border px-4 py-2.5">
        <div
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-sm"
          style={{ background: `${color}22`, color }}
        >
          {icon}
        </div>
        <div className="flex-1 text-xs font-bold" style={{ color }}>
          {agent.name}
        </div>
        {agent.status === "running" ? (
          <span className="text-[10px] font-bold text-[var(--qm-amber)]">
            <span className="inline-block animate-spin">⟳</span> RUNNING
          </span>
        ) : (
          <span className="text-[10px] font-bold text-[var(--qm-green)]">✓ DONE</span>
        )}
      </CardHeader>

      <CardContent className="grid grid-cols-2 gap-4 px-4 py-3">
        {/* Input column */}
        <div className="flex flex-col gap-1">
          <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
            INPUT
          </div>
          {inp.rows != null && (
            <div className="text-[11px] leading-relaxed">
              <span className="text-muted-foreground">rows:</span>{" "}
              <span>{String(inp.rows)}</span>
            </div>
          )}
        </div>

        {/* Output column */}
        {out ? (
          <div className="flex flex-col gap-2">
            <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
              OUTPUT
            </div>

            {check1 && (
              <div className="flex flex-col gap-0.5">
                <div className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      "text-[10px] font-bold",
                      check1.passed ? "text-[var(--qm-green)]" : "text-[var(--qm-red)]"
                    )}
                  >
                    {check1.passed ? "✓" : "✗"} Check 1
                  </span>
                  <span className="text-[10px] text-muted-foreground">rules compliance</span>
                </div>
                {!check1.passed &&
                  check1.feedback?.slice(0, 2).map((f, i) => (
                    <div key={i} className="text-[10px] text-[var(--qm-red)]/80 leading-relaxed pl-3">
                      • {f}
                    </div>
                  ))}
              </div>
            )}

            {check2 && (
              <div className="flex flex-col gap-0.5">
                <div className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      "text-[10px] font-bold",
                      check2.passed ? "text-[var(--qm-green)]" : "text-[var(--qm-red)]"
                    )}
                  >
                    {check2.passed ? "✓" : "✗"} Check 2
                  </span>
                  <span className="text-[10px] text-muted-foreground">CSM coverage</span>
                </div>
                {(check2.missing_concepts?.length ?? 0) > 0 && (
                  <div className="text-[10px] text-[var(--qm-red)]/80 leading-relaxed pl-3">
                    • {check2.missing_concepts!.length} missing concept{check2.missing_concepts!.length !== 1 ? "s" : ""}
                  </div>
                )}
                {(check2.missing_skills?.length ?? 0) > 0 && (
                  <div className="text-[10px] text-[var(--qm-red)]/80 leading-relaxed pl-3">
                    • {check2.missing_skills!.length} missing skill{check2.missing_skills!.length !== 1 ? "s" : ""}
                  </div>
                )}
                {check2.passed && (
                  <div className="text-[10px] text-[var(--qm-green)] pl-3">All concepts and skills covered</div>
                )}
              </div>
            )}
          </div>
        ) : (
          <div />
        )}
      </CardContent>

      {/* Full-width coverage comparison panel */}
      {hasDiff && (
        <div className="border-t border-border px-4 pb-3 pt-2.5">
          <CoverageDiff
            csvText={csvText}
            csm={csm}
            missingConcepts={check2?.missing_concepts ?? []}
            missingSkills={check2?.missing_skills ?? []}
            matchedConcepts={check2?.matched_concepts ?? {}}
            matchedSkills={check2?.matched_skills ?? {}}
            extraConcepts={check2?.extra_concepts}
            extraSkills={check2?.extra_skills}
            reconciliation={check2?.reconciliation}
          />
        </div>
      )}
    </Card>
  );
}

// ── AgentCard ─────────────────────────────────────────────────────────────────

// ── DoctorCard ────────────────────────────────────────────────────────────────
// Surfaces the Doctor agent's surgical patch: the coverage gaps it set out to fix
// (missing items to add, extras it weighed) and the resulting patched CSV. Its
// re-verification is rendered separately by the following "Eval (doctored)" card.

function DoctorCard({ agent }: { agent: AgentRecord }) {
  const color = AGENT_COLORS["Doctor"];
  const icon = AGENT_ICONS["Doctor"];
  const inp = agent.input as Record<string, unknown>;
  const out = agent.output as Record<string, unknown> | null;

  const asList = (v: unknown): string[] => (Array.isArray(v) ? (v as string[]) : []);
  const missingConcepts = asList(inp.missing_concepts);
  const missingSkills   = asList(inp.missing_skills);
  const extraConcepts   = asList(inp.extra_concepts);
  const extraSkills     = asList(inp.extra_skills);

  const doctoredCsv = typeof out?.csv_preview === "string" ? (out.csv_preview as string) : null;
  const error = typeof out?.error === "string" ? (out.error as string) : null;

  return (
    <Card className="border-border bg-card py-0">
      <CardHeader className="flex flex-row items-center gap-3 border-b border-border px-4 py-2.5">
        <div
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-sm"
          style={{ background: `${color}22`, color }}
        >
          {icon}
        </div>
        <div className="flex-1 text-xs font-bold" style={{ color }}>
          {agent.name}
        </div>
        {agent.status === "running" ? (
          <span className="text-[10px] font-bold text-[var(--qm-amber)]">
            <span className="inline-block animate-spin">⟳</span> RUNNING
          </span>
        ) : (
          <span className="text-[10px] font-bold text-[var(--qm-green)]">✓ DONE</span>
        )}
      </CardHeader>

      <CardContent className="grid grid-cols-2 gap-4 px-4 py-3">
        {/* Input column — the coverage gaps being repaired */}
        <div className="flex flex-col gap-3">
          <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
            FIXING
          </div>
          {missingConcepts.length > 0 && (
            <MapListSection label="Add — missing concepts" items={missingConcepts} color="var(--qm-red)" />
          )}
          {missingSkills.length > 0 && (
            <MapListSection label="Add — missing skills" items={missingSkills} color="var(--qm-red)" />
          )}
          {extraConcepts.length > 0 && (
            <MapListSection label="Weigh — extra concepts" items={extraConcepts} color="var(--qm-amber)" />
          )}
          {extraSkills.length > 0 && (
            <MapListSection label="Weigh — extra skills" items={extraSkills} color="var(--qm-amber)" />
          )}
          {missingConcepts.length === 0 && missingSkills.length === 0 &&
            extraConcepts.length === 0 && extraSkills.length === 0 && (
            <div className="text-[10px] text-muted-foreground italic">No gap details</div>
          )}
        </div>

        {/* Output column — the patched CSV */}
        {out ? (
          <div className="flex flex-col gap-2">
            <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
              PATCHED CSV
            </div>
            {error ? (
              <div className="text-[11px] leading-relaxed text-[var(--qm-red)]">
                Doctoring failed: {error}
              </div>
            ) : (
              <>
                {out.rows != null && (
                  <div className="text-[11px] leading-relaxed">
                    <span className="text-muted-foreground">rows:</span>{" "}
                    <span>{String(out.rows)}</span>
                  </div>
                )}
                {doctoredCsv && <CsvInlineEntry csvText={doctoredCsv} />}
              </>
            )}
          </div>
        ) : (
          <div />
        )}
      </CardContent>
    </Card>
  );
}

// ── JudgeCard ─────────────────────────────────────────────────────────────────
// Renders the Judge agent's decision among ≥2 passing CSV candidates: each
// candidate's source/cycle/counts + the judge's note/strengths/concerns, the chosen
// one highlighted, the overall rationale, and an inline preview of the chosen CSV.

type JudgeCandidate = {
  id?: string;
  source?: string;
  cycle?: number;
  concept_count?: number;
  skill_count?: number;
  csv?: string;
  verdict?: string;
  note?: string;
  strengths?: string[];
  concerns?: string[];
};

function JudgeCard({ agent }: { agent: AgentRecord }) {
  const color = AGENT_COLORS["Judge"];
  const icon = AGENT_ICONS["Judge"];
  const out = agent.output as Record<string, unknown> | null;

  const candidates: JudgeCandidate[] = Array.isArray(out?.candidates)
    ? (out!.candidates as JudgeCandidate[])
    : [];
  const rationale = typeof out?.rationale === "string" ? (out.rationale as string) : null;
  const chosen = candidates.find((c) => c.verdict === "chosen");

  return (
    <Card className="border-border bg-card py-0">
      <CardHeader className="flex flex-row items-center gap-3 border-b border-border px-4 py-2.5">
        <div
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-sm"
          style={{ background: `${color}22`, color }}
        >
          {icon}
        </div>
        <div className="flex-1 text-xs font-bold" style={{ color }}>
          {agent.name}
        </div>
        {agent.status === "running" ? (
          <span className="text-[10px] font-bold text-[var(--qm-amber)]">
            <span className="inline-block animate-spin">⟳</span> RUNNING
          </span>
        ) : (
          <span className="text-[10px] font-bold text-[var(--qm-green)]">✓ DONE</span>
        )}
      </CardHeader>

      <CardContent className="flex flex-col gap-3 px-4 py-3">
        <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
          {candidates.length} passing candidate{candidates.length !== 1 ? "s" : ""}
        </div>

        {candidates.map((c, i) => {
          const isChosen = c.verdict === "chosen";
          const accent = isChosen ? "var(--qm-green)" : "var(--qm-red)";
          return (
            <div
              key={c.id ?? i}
              className="rounded border px-3 py-2"
              style={{
                borderColor: isChosen ? "var(--qm-green)" : "var(--border)",
                background: isChosen ? "var(--qm-green)0d" : undefined,
              }}
            >
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-bold text-foreground">{c.id}</span>
                <span
                  className="rounded px-1.5 py-0.5 text-[9px] font-bold uppercase"
                  style={{ background: `${color}22`, color }}
                >
                  {c.source}
                </span>
                <span className="text-[10px] text-muted-foreground">
                  {c.concept_count} concepts · {c.skill_count} skills
                </span>
                <span className="ml-auto text-[10px] font-bold" style={{ color: accent }}>
                  {isChosen ? "✓ CHOSEN" : "rejected"}
                </span>
              </div>

              {c.note && (
                <div className="mt-1 text-[10px] leading-relaxed text-foreground/80">{c.note}</div>
              )}

              {Array.isArray(c.strengths) && c.strengths.length > 0 && (
                <div className="mt-1">
                  <span className="text-[9px] font-bold uppercase tracking-widest text-[var(--qm-green)]">
                    Strengths
                  </span>
                  {c.strengths.map((s, j) => (
                    <div key={j} className="flex items-start gap-1.5 text-[10px] leading-relaxed">
                      <span className="mt-px shrink-0 text-[9px] text-[var(--qm-green)]">+</span>
                      <span className="text-foreground/80">{s}</span>
                    </div>
                  ))}
                </div>
              )}

              {Array.isArray(c.concerns) && c.concerns.length > 0 && (
                <div className="mt-1">
                  <span className="text-[9px] font-bold uppercase tracking-widest text-[var(--qm-red)]">
                    Concerns
                  </span>
                  {c.concerns.map((s, j) => (
                    <div key={j} className="flex items-start gap-1.5 text-[10px] leading-relaxed">
                      <span className="mt-px shrink-0 text-[9px] text-[var(--qm-red)]">−</span>
                      <span className="text-foreground/80">{s}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}

        {rationale && (
          <div className="text-[10px] leading-relaxed text-foreground/80">
            <span className="font-bold" style={{ color }}>Decision: </span>
            {rationale}
          </div>
        )}

        {chosen?.csv && <CsvInlineEntry csvText={chosen.csv} />}
      </CardContent>
    </Card>
  );
}

function AgentCard({ agent }: { agent: AgentRecord }) {
  const color = AGENT_COLORS[agent.name] ?? "var(--qm-blue)";
  const icon = AGENT_ICONS[agent.name] ?? "●";

  const csvPreview =
    agent.output &&
    typeof (agent.output as Record<string, unknown>).csv_preview === "string"
      ? (agent.output as Record<string, unknown>).csv_preview as string
      : null;

  const generatorPrompt =
    agent.name === "Generator" &&
    typeof (agent.input as Record<string, unknown>).prompt === "string"
      ? (agent.input as Record<string, unknown>).prompt as string
      : null;

  const generatorBasePrompt =
    agent.name === "Generator" &&
    typeof (agent.input as Record<string, unknown>).base_prompt === "string"
      ? (agent.input as Record<string, unknown>).base_prompt as string
      : null;

  const revisedPrompt =
    agent.name === "Revision" &&
    agent.output &&
    typeof (agent.output as Record<string, unknown>).revised_prompt === "string"
      ? (agent.output as Record<string, unknown>).revised_prompt as string
      : null;

  return (
    <Card className="border-border bg-card py-0">
      <CardHeader className="flex flex-row items-center gap-3 border-b border-border px-4 py-2.5">
        <div
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded text-sm"
          style={{ background: `${color}22`, color }}
        >
          {icon}
        </div>
        <div className="flex-1 text-xs font-bold" style={{ color }}>
          {agent.name}
        </div>
        {agent.status === "running" ? (
          <span className="text-[10px] font-bold text-[var(--qm-amber)]">
            <span className="inline-block animate-spin">⟳</span> RUNNING
          </span>
        ) : (
          <span className="text-[10px] font-bold text-[var(--qm-green)]">✓ DONE</span>
        )}
      </CardHeader>

      <CardContent className="grid grid-cols-2 gap-4 px-4 py-3">
        {/* Input column */}
        <div className="flex flex-col gap-2">
          <IOSection data={agent.input} label="INPUT" />
          {generatorPrompt && (
            <TextExpandEntry label="prompt" text={generatorPrompt} accentColor="var(--qm-blue)" />
          )}
          {generatorBasePrompt && (
            <TextExpandEntry label="base_prompt" text={generatorBasePrompt} accentColor="var(--qm-blue)" />
          )}
        </div>

        {/* Output column */}
        {agent.output ? (
          <div className="flex flex-col gap-2">
            <IOSection data={agent.output} label="OUTPUT" />
            {agent.name === "Generator" && csvPreview && (
              <GeneratorStatsEntry csvText={csvPreview} />
            )}
            {csvPreview && <CsvInlineEntry csvText={csvPreview} />}
            {revisedPrompt && (
              <TextExpandEntry label="revised_prompt" text={revisedPrompt} accentColor="var(--qm-purple)" />
            )}
          </div>
        ) : (
          <div />
        )}
      </CardContent>
    </Card>
  );
}

// ── AttemptGroup ──────────────────────────────────────────────────────────────

const MAP_EXTRACTION_NAMES = new Set(["Map Extraction", "Map Extraction + Generator"]);
// Both the primary eval and the doctored re-verification render with EvalCard.
const EVAL_NAMES = new Set(["Eval", "Eval (doctored)"]);

function cycleStatus(agents: AgentRecord[]): "running" | "done" | "failed" {
  if (agents.some((a) => a.status === "running")) return "running";
  const evalAgent = agents.find((a) => a.name === "Eval" && a.output);
  if (evalAgent) {
    const c1 = (evalAgent.output as Record<string, unknown>)?.check1 as
      | { passed?: boolean }
      | undefined;
    const c2 = (evalAgent.output as Record<string, unknown>)?.check2 as
      | { passed?: boolean }
      | undefined;
    if (c1?.passed === false || c2?.passed === false) return "failed";
  }
  return "done";
}

function AttemptGroup({
  attempt,
  agents,
  isOpen,
  onToggle,
}: {
  attempt: number;
  agents: AgentRecord[];
  isOpen: boolean;
  onToggle: () => void;
}) {
  const status = cycleStatus(agents);
  const statusColor =
    status === "running"
      ? "text-[var(--qm-amber)]"
      : status === "failed"
        ? "text-[var(--qm-red)]"
        : "text-[var(--qm-green)]";
  const statusLabel =
    status === "running" ? "Running" : status === "failed" ? "Failed" : "Done";

  return (
    <div className="rounded-md border border-border overflow-hidden">
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-3 bg-secondary/40 px-4 py-2.5 text-left hover:bg-secondary/70 transition-colors"
      >
        <span className="text-xs font-bold text-foreground">
          Cycle {attempt} / 3
        </span>
        <span className={cn("text-[10px] font-bold", statusColor)}>
          {status === "running" && (
            <span className="inline-block animate-pulse mr-0.5">●</span>
          )}
          {statusLabel}
        </span>
        <span className="text-[10px] text-muted-foreground">
          {agents.length} agent{agents.length !== 1 ? "s" : ""}
        </span>
        <span className="ml-auto text-muted-foreground">
          {isOpen ? (
            <ChevronUp className="h-3.5 w-3.5" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" />
          )}
        </span>
      </button>

      {isOpen && (
        <div className="relative border-t border-border pl-4">
          <div className="absolute left-[1.4rem] top-0 bottom-0 w-px bg-border" />
          <div className="space-y-3 py-3 pr-3">
            {agents.map((agent, i) =>
              MAP_EXTRACTION_NAMES.has(agent.name) ? (
                <MapExtractionCard key={`${agent.name}-${agent.attempt}-${i}`} agent={agent} />
              ) : EVAL_NAMES.has(agent.name) ? (
                <EvalCard key={`${agent.name}-${agent.attempt}-${i}`} agent={agent} />
              ) : agent.name === "Doctor" ? (
                <DoctorCard key={`${agent.name}-${agent.attempt}-${i}`} agent={agent} />
              ) : agent.name === "Judge" ? (
                <JudgeCard key={`${agent.name}-${agent.attempt}-${i}`} agent={agent} />
              ) : (
                <AgentCard key={`${agent.name}-${agent.attempt}-${i}`} agent={agent} />
              )
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── AgentTimeline ─────────────────────────────────────────────────────────────

interface AgentTimelineProps {
  agents: AgentRecord[];
  currentAttempt: number;
}

export function AgentTimeline({ agents, currentAttempt }: AgentTimelineProps) {
  const [openAttempts, setOpenAttempts] = useState<Set<number>>(
    () => new Set([currentAttempt || 1])
  );
  const prevAttemptRef = useRef(0);

  // Auto-open only when currentAttempt genuinely increments (new cycle started)
  useEffect(() => {
    if (currentAttempt > 0 && currentAttempt !== prevAttemptRef.current) {
      prevAttemptRef.current = currentAttempt;
      setOpenAttempts((prev) => new Set([...prev, currentAttempt]));
    }
  }, [currentAttempt]);

  if (!agents.length) return null;

  const grouped = new Map<number, AgentRecord[]>();
  for (const agent of agents) {
    // Use ?? (not ||) so attempt:0 (pre-run) is kept as 0, not collapsed into 1
    const key = agent.attempt ?? 1;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)!.push(agent);
  }

  const preRunAgents = grouped.get(0) ?? [];
  const cycleEntries = [...grouped.entries()]
    .filter(([k]) => k > 0)
    .sort(([a], [b]) => a - b);

  const toggle = (attempt: number) => {
    setOpenAttempts((prev) => {
      const next = new Set(prev);
      if (next.has(attempt)) next.delete(attempt);
      else next.add(attempt);
      return next;
    });
  };

  return (
    <div className="mb-6">
      <div className="mb-3 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
        Agent Timeline
      </div>
      <div className="space-y-2">
        {/* Pre-run section: Map Extraction runs once before any cycle */}
        {preRunAgents.length > 0 && (
          <div className="rounded-md border border-border overflow-hidden">
            <div className="flex items-center gap-3 bg-secondary/40 px-4 py-2.5">
              <span className="text-xs font-bold text-foreground">Pre-run</span>
              <span className="text-[10px] text-muted-foreground">
                {preRunAgents.length} agent{preRunAgents.length !== 1 ? "s" : ""}
              </span>
              <span className="text-[10px] text-muted-foreground italic">runs once, outside cycle</span>
            </div>
            <div className="relative border-t border-border pl-4">
              <div className="absolute left-[1.4rem] top-0 bottom-0 w-px bg-border" />
              <div className="space-y-3 py-3 pr-3">
                {preRunAgents.map((agent, i) => (
                  <MapExtractionCard key={`prerun-${agent.name}-${i}`} agent={agent} />
                ))}
              </div>
            </div>
          </div>
        )}

        {cycleEntries.map(([attempt, agentList]) => (
          <AttemptGroup
            key={attempt}
            attempt={attempt}
            agents={agentList}
            isOpen={openAttempts.has(attempt)}
            onToggle={() => toggle(attempt)}
          />
        ))}
      </div>
    </div>
  );
}
