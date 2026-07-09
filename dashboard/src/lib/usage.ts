import type { Usage } from "./types";

export const ZERO_USAGE: Usage = {
  input_tokens: 0,
  output_tokens: 0,
  cache_creation_input_tokens: 0,
  cache_read_input_tokens: 0,
};

export function sumUsage(usages: (Usage | undefined | null)[]): Usage {
  return usages.reduce<Usage>(
    (acc, u) => ({
      input_tokens: acc.input_tokens + (u?.input_tokens ?? 0),
      output_tokens: acc.output_tokens + (u?.output_tokens ?? 0),
      cache_creation_input_tokens:
        acc.cache_creation_input_tokens + (u?.cache_creation_input_tokens ?? 0),
      cache_read_input_tokens:
        acc.cache_read_input_tokens + (u?.cache_read_input_tokens ?? 0),
    }),
    { ...ZERO_USAGE }
  );
}

function formatCount(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

export function hasUsage(usage: Usage | undefined | null): boolean {
  if (!usage) return false;
  return (
    usage.input_tokens > 0 ||
    usage.output_tokens > 0 ||
    usage.cache_creation_input_tokens > 0 ||
    usage.cache_read_input_tokens > 0
  );
}

export function formatTokens(usage: Usage | undefined | null): string {
  if (!hasUsage(usage)) return "";
  return `${formatCount(usage!.input_tokens)} in / ${formatCount(usage!.output_tokens)} out`;
}

export function formatCost(costUsd: number | undefined | null): string {
  if (costUsd == null) return "";
  if (costUsd === 0) return "$0";
  if (costUsd < 0.01) return `$${costUsd.toFixed(4)}`;
  return `$${costUsd.toFixed(2)}`;
}
