// Shared CSV parsing + diffing helpers.
// parseCSVLine is the single source of truth (previously duplicated in
// csv-preview.tsx and agent-timeline.tsx).

// maxCols caps the number of columns: once the first (maxCols-1) are filled, any
// further unquoted commas stay in the last field. This recovers malformed rows
// where the trailing column (e.g. a skill) contains unquoted commas.
export function parseCSVLine(line: string, maxCols?: number): string[] {
  const result: string[] = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') { current += '"'; i++; }
      else inQuotes = !inQuotes;
    } else if (ch === "," && !inQuotes && (maxCols === undefined || result.length < maxCols - 1)) {
      result.push(current.trim());
      current = "";
    } else {
      current += ch;
    }
  }
  result.push(current.trim());
  return result;
}

/** Non-empty lines of a CSV string. */
function csvLines(csv: string): string[] {
  return csv.split("\n").filter((l) => l.trim());
}

/** Header (first-row) column names of a CSV. */
export function csvHeaders(csv: string): string[] {
  const lines = csvLines(csv);
  return lines.length > 0 ? parseCSVLine(lines[0]) : [];
}

/**
 * All values in a given column (by header name, case-insensitive), trimmed and
 * with blanks dropped. Order preserved; duplicates kept (callers that want a set
 * can dedupe). Returns [] if the column is absent.
 */
export function csvColumnValues(csv: string, column: string): string[] {
  const lines = csvLines(csv);
  if (lines.length < 2) return [];
  const headers = parseCSVLine(lines[0]);
  const idx = headers.findIndex((h) => h.toLowerCase() === column.toLowerCase());
  if (idx < 0) return [];
  const values: string[] = [];
  for (let i = 1; i < lines.length; i++) {
    const cell = parseCSVLine(lines[i], headers.length)[idx];
    const v = (cell ?? "").trim();
    if (v) values.push(v);
  }
  return values;
}

export interface ColumnSetDiff {
  onlyA: string[];
  onlyB: string[];
  both: string[];
}

/**
 * Set difference between two columns' values (trimmed, exact match, deduped).
 * onlyA = in A not B, onlyB = in B not A, both = in both. Results are sorted.
 */
export function diffColumnSets(aVals: string[], bVals: string[]): ColumnSetDiff {
  const a = new Set(aVals.map((v) => v.trim()).filter(Boolean));
  const b = new Set(bVals.map((v) => v.trim()).filter(Boolean));
  const onlyA: string[] = [];
  const onlyB: string[] = [];
  const both: string[] = [];
  for (const v of a) (b.has(v) ? both : onlyA).push(v);
  for (const v of b) if (!a.has(v)) onlyB.push(v);
  const sort = (xs: string[]) => xs.sort((x, y) => x.localeCompare(y));
  return { onlyA: sort(onlyA), onlyB: sort(onlyB), both: sort(both) };
}
