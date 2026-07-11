"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { AGENT_KEYS, type AgentKey, type ModelPerformanceEntry, type ModelPerformanceResponse } from "@/lib/types";
import { AGENT_LABELS } from "@/lib/models";
import { formatCost, formatTokens } from "@/lib/usage";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-[110px] flex-1 flex-col gap-1 rounded-lg border border-border bg-card px-4 py-3">
      <span className="text-2xl font-bold tabular-nums">{value}</span>
      <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
        {label}
      </span>
    </div>
  );
}

function passRateColor(rate: number): string {
  if (rate >= 0.7) return "var(--qm-green)";
  if (rate >= 0.4) return "var(--qm-amber)";
  return "var(--qm-red)";
}

function ModelRow({ entry }: { entry: ModelPerformanceEntry }) {
  return (
    <tr className="border-t border-border/60">
      <td className="whitespace-nowrap px-3 py-2 font-mono text-[11px]">{entry.model}</td>
      <td className="px-3 py-2 text-right tabular-nums">{entry.runs}</td>
      <td className="px-3 py-2 text-right tabular-nums">
        <span style={{ color: passRateColor(entry.pass_rate) }} className="font-bold">
          {Math.round(entry.pass_rate * 100)}%
        </span>
        <span className="ml-1 text-muted-foreground">
          ({entry.passed}/{entry.runs})
        </span>
      </td>
      <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
        {formatTokens(entry.avg_usage)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{formatCost(entry.avg_cost_usd)}</td>
      <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
        {formatCost(entry.total_cost_usd)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">
        {entry.avg_rows != null ? Math.round(entry.avg_rows) : "—"}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right text-muted-foreground">
        {entry.last_used ?? "—"}
      </td>
    </tr>
  );
}

function AgentGroup({
  agentKey,
  entries,
}: {
  agentKey: AgentKey;
  entries: ModelPerformanceEntry[];
}) {
  const [open, setOpen] = useState(entries.length > 0);
  const totalRuns = entries.reduce((sum, e) => sum + e.runs, 0);
  const isGenerator = agentKey === "generator";

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
        )}
        <span className="text-xs font-bold tracking-wide">{AGENT_LABELS[agentKey]}</span>
        <span className="ml-auto text-[10px] text-muted-foreground">
          {entries.length} model{entries.length !== 1 ? "s" : ""} · {totalRuns} run
          {totalRuns !== 1 ? "s" : ""}
        </span>
      </button>
      {open && (
        <div className="overflow-x-auto border-t border-border">
          {entries.length === 0 ? (
            <div className="px-3 py-4 text-center text-[11px] text-muted-foreground">
              No runs yet
            </div>
          ) : (
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-[9px] font-bold uppercase tracking-widest text-muted-foreground">
                  <th className="px-3 py-1.5 text-left">Model</th>
                  <th className="px-3 py-1.5 text-right">Runs</th>
                  <th className="px-3 py-1.5 text-right">Pass rate</th>
                  <th className="px-3 py-1.5 text-right">Avg tokens</th>
                  <th className="px-3 py-1.5 text-right">Avg cost</th>
                  <th className="px-3 py-1.5 text-right">Total cost</th>
                  <th className="px-3 py-1.5 text-right">{isGenerator ? "Avg rows" : "—"}</th>
                  <th className="px-3 py-1.5 text-right">Last used</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <ModelRow key={e.model} entry={e} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

export function ModelPerformancePanel({ data }: { data: ModelPerformanceResponse | null }) {
  const [open, setOpen] = useState(true);

  if (!data) return null;

  const byAgent = new Map<AgentKey, ModelPerformanceEntry[]>();
  for (const key of AGENT_KEYS) byAgent.set(key, []);
  for (const entry of data.entries) {
    byAgent.get(entry.agent)?.push(entry);
  }

  return (
    <div className="space-y-3">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex w-full items-center gap-1.5 text-left text-[10px] font-bold uppercase tracking-widest text-muted-foreground hover:text-foreground"
      >
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        Model Performance
      </button>

      {open && (
        <>
          <div className="flex flex-wrap gap-3">
            <Stat label="Runs Analyzed" value={String(data.total_runs)} />
            <Stat label="Total Spend" value={formatCost(data.total_cost_usd) || "$0"} />
            <Stat label="Models In Use" value={String(data.distinct_models)} />
            {data.by_provider.map((p) => (
              <Stat
                key={p.provider}
                label={p.provider}
                value={formatCost(p.total_cost_usd) || "$0"}
              />
            ))}
          </div>

          <div className="thin-scroll max-h-[420px] space-y-2 overflow-y-auto pr-1">
            {AGENT_KEYS.map((key) => (
              <AgentGroup key={key} agentKey={key} entries={byAgent.get(key) ?? []} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
