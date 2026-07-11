"use client";

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import type { AgentKey, ModelInfo } from "@/lib/types";
import { AGENT_LABELS, supportsToolUse, TOOL_CALLING_AGENTS } from "@/lib/models";

// One agent's model dropdown, grouped by provider. Tool-calling agents (Generator,
// Eval, Doctor, Doctor (rules)) only show models tagged "tool-use" — they force a
// single tool call for schema-shaped output, which requires it.
export function AgentModelPicker({
  agentKey,
  models,
  value,
  defaultModel,
  onChange,
}: {
  agentKey: AgentKey;
  models: ModelInfo[];
  value: string | undefined;
  defaultModel: string;
  onChange: (modelId: string | undefined) => void;
}) {
  const eligible = TOOL_CALLING_AGENTS.has(agentKey) ? models.filter(supportsToolUse) : models;

  const byProvider = new Map<string, ModelInfo[]>();
  for (const m of eligible) {
    if (!byProvider.has(m.owned_by)) byProvider.set(m.owned_by, []);
    byProvider.get(m.owned_by)!.push(m);
  }
  const providers = [...byProvider.keys()].sort();

  return (
    <div className="space-y-1.5">
      <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {AGENT_LABELS[agentKey]}
      </Label>
      <Select
        value={value ?? "__default__"}
        onValueChange={(v) => onChange(!v || v === "__default__" ? undefined : v)}
      >
        <SelectTrigger className="h-8 w-full bg-secondary text-xs">
          <SelectValue placeholder={defaultModel} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__default__">Default ({defaultModel})</SelectItem>
          {providers.map((provider) => (
            <SelectGroup key={provider}>
              <SelectLabel>{provider}</SelectLabel>
              {byProvider.get(provider)!.map((m) => (
                <SelectItem key={m.id} value={m.id}>
                  {m.name}
                </SelectItem>
              ))}
            </SelectGroup>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
