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

// Keys filtered from the generic IO display
const EXCLUDED_KEYS = new Set(["csv", "prompt", "csv_preview"]);

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
        <div
          className="thin-scroll max-h-48 overflow-y-auto rounded bg-secondary/60"
        >
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

// ── CSV inline preview (Generator card) ───────────────────────────────────────

function CsvInlineEntry({ csvText }: { csvText: string }) {
  const [open, setOpen] = useState(false);

  const lines = csvText.split("\n").filter((l) => l.trim());
  const headers = lines.length > 0 ? parseCSVLine(lines[0]) : [];
  const dataRows = lines.slice(1).map(parseCSVLine);
  const rowCount = dataRows.length;

  return (
    <div className="flex flex-col gap-1">
      {/* Always-visible entry row */}
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

// ── AgentCard ─────────────────────────────────────────────────────────────────

function AgentCard({ agent }: { agent: AgentRecord }) {
  const color = AGENT_COLORS[agent.name] ?? "var(--qm-blue)";
  const icon = AGENT_ICONS[agent.name] ?? "●";

  const csvPreview =
    agent.output &&
    typeof (agent.output as Record<string, unknown>).csv_preview === "string"
      ? (agent.output as Record<string, unknown>).csv_preview as string
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
        <IOSection data={agent.input} label="INPUT" />

        {/* Output column */}
        {agent.output ? (
          <div className="flex flex-col gap-2">
            <IOSection data={agent.output} label="OUTPUT" />
            {csvPreview && <CsvInlineEntry csvText={csvPreview} />}
          </div>
        ) : (
          <div />
        )}
      </CardContent>
    </Card>
  );
}

// ── AttemptGroup ──────────────────────────────────────────────────────────────

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
            {agents.map((agent, i) => (
              <AgentCard key={`${agent.name}-${agent.attempt}-${i}`} agent={agent} />
            ))}
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
    const key = agent.attempt || 1;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key)!.push(agent);
  }
  const attempts = [...grouped.entries()].sort(([a], [b]) => a - b);

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
        {attempts.map(([attempt, agentList]) => (
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
