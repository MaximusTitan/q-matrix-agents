"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { AgentRecord } from "@/lib/types";
import { cn } from "@/lib/utils";

const AGENT_ICONS: Record<string, string> = {
  Generator: "⚙",
  Eval: "📋",
  Revision: "🔁",
  "Map Extraction": "🗂",
  "Map Extraction + Generator": "⟳",
};

const AGENT_COLORS: Record<string, string> = {
  Generator: "var(--qm-blue)",
  Eval: "var(--qm-amber)",
  Revision: "var(--qm-purple)",
  "Map Extraction": "var(--qm-blue)",
  "Map Extraction + Generator": "var(--qm-blue)",
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

function parseCSVLine(line: string): string[] {
  const result: string[] = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') { current += '"'; i++; }
      else inQuotes = !inQuotes;
    } else if (ch === "," && !inQuotes) {
      result.push(current.trim());
      current = "";
    } else {
      current += ch;
    }
  }
  result.push(current.trim());
  return result;
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
    const row = parseCSVLine(lines[i]);
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

function CsvInlineEntry({ csvText }: { csvText: string }) {
  const [open, setOpen] = useState(false);

  const lines = csvText.split("\n").filter((l) => l.trim());
  const headers = lines.length > 0 ? parseCSVLine(lines[0]) : [];
  const dataRows = lines.slice(1).map(parseCSVLine);
  const rowCount = dataRows.length;

  return (
    <div className="flex flex-col gap-1">
      <div className="text-[11px] leading-relaxed">
        <span className="text-muted-foreground">csv_preview:</span>{" "}
        <span className="text-[var(--qm-green)]">{rowCount} row{rowCount !== 1 ? "s" : ""}</span>
      </div>

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
                    <td
                      key={ci}
                      className="px-2 py-1 text-[10px] text-foreground/80 whitespace-nowrap max-w-[160px] truncate"
                      title={cell}
                    >
                      {cell}
                    </td>
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

// ── CoverageDiff — side-by-side CSV vs CSM (Eval card) ───────────────────────

interface CsmData {
  concepts: string[];
  skills: string[];
}

function CoverageDiff({
  csvText,
  csm,
  missingConcepts,
  missingSkills,
}: {
  csvText: string;
  csm: CsmData;
  missingConcepts: string[];
  missingSkills: string[];
}) {
  const [open, setOpen] = useState(false);
  const { concepts: csvConcepts, skills: csvSkills } = parseCsvSets(csvText);

  const missingConceptSet = new Set(missingConcepts.map((c) => c.toLowerCase()));
  const missingSkillSet = new Set(missingSkills.map((s) => s.toLowerCase()));

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
        <div className="mt-1 grid grid-cols-2 gap-3 rounded border border-border bg-secondary/30 p-3">
          {/* Left: CSV output */}
          <div className="flex flex-col gap-2 min-w-0">
            <div className="text-[9px] font-bold uppercase tracking-widest text-muted-foreground border-b border-border pb-1">
              CSV Output
            </div>

            <div>
              <div className="text-[9px] font-semibold text-muted-foreground mb-1">
                Concepts ({csvConcepts.size})
              </div>
              <div className="thin-scroll max-h-36 overflow-y-auto space-y-0.5">
                {[...csvConcepts].map((c) => (
                  <div key={c} className="text-[10px] text-foreground/80 truncate" title={c}>
                    {c}
                  </div>
                ))}
              </div>
            </div>

            <div>
              <div className="text-[9px] font-semibold text-muted-foreground mb-1">
                Skills ({csvSkills.size})
              </div>
              <div className="thin-scroll max-h-36 overflow-y-auto space-y-0.5">
                {[...csvSkills].map((s) => (
                  <div key={s} className="text-[10px] text-foreground/80 truncate" title={s}>
                    {s}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right: Concept-Skill Map with coverage highlights */}
          <div className="flex flex-col gap-2 min-w-0">
            <div className="text-[9px] font-bold uppercase tracking-widest text-muted-foreground border-b border-border pb-1">
              Concept-Skill Map
            </div>

            <div>
              <div className="text-[9px] font-semibold text-muted-foreground mb-1">
                Concepts ({csm.concepts.length})
              </div>
              <div className="thin-scroll max-h-36 overflow-y-auto space-y-0.5">
                {csm.concepts.map((c) => {
                  const missing = missingConceptSet.has(c.toLowerCase());
                  return (
                    <div
                      key={c}
                      title={missing ? `Not covered: ${c}` : c}
                      className={cn(
                        "text-[10px] truncate",
                        missing
                          ? "text-[var(--qm-red)] font-semibold"
                          : "text-[var(--qm-green)]"
                      )}
                    >
                      {missing ? "✗ " : "✓ "}{c}
                    </div>
                  );
                })}
              </div>
            </div>

            <div>
              <div className="text-[9px] font-semibold text-muted-foreground mb-1">
                Skills ({csm.skills.length})
              </div>
              <div className="thin-scroll max-h-36 overflow-y-auto space-y-0.5">
                {csm.skills.map((s) => {
                  const missing = missingSkillSet.has(s.toLowerCase());
                  return (
                    <div
                      key={s}
                      title={missing ? `Not covered: ${s}` : s}
                      className={cn(
                        "text-[10px] truncate",
                        missing
                          ? "text-[var(--qm-red)] font-semibold"
                          : "text-[var(--qm-green)]"
                      )}
                    >
                      {missing ? "✗ " : "✓ "}{s}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
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

  type CheckResult = { passed?: boolean; feedback?: string[]; missing_concepts?: string[]; missing_skills?: string[] };
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
          />
        </div>
      )}
    </Card>
  );
}

// ── AgentCard ─────────────────────────────────────────────────────────────────

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
              ) : agent.name === "Eval" ? (
                <EvalCard key={`${agent.name}-${agent.attempt}-${i}`} agent={agent} />
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
