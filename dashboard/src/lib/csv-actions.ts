// Shared copy/download helpers for CSV text, used by both the final-CSV viewer
// (csv-preview.tsx) and the inline per-agent previews (agent-timeline.tsx).

export function copyCsv(text: string): void {
  navigator.clipboard.writeText(text);
}

export function downloadCsv(text: string, filename = "curriculum.csv"): void {
  const blob = new Blob([text], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}
