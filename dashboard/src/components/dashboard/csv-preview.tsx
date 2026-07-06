"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { copyCsv, downloadCsv } from "@/lib/csv-actions";
import { parseCSVLine } from "@/lib/csv-utils";

interface CsvPreviewProps {
  csv: string;
  chapter: string;
  selectedBy?: "single" | "judge";
  source?: "generated" | "doctored" | "user_provided";
  candidateCount?: number;
}

const PREVIEW_ROWS = 10;

// A CSV table cell that truncates by default and expands to full wrapped text on click.
function CsvCell({ cell }: { cell: string }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <td
      onClick={() => setExpanded((p) => !p)}
      className={cn(
        "px-3 py-1.5 text-[11px] text-foreground/80 cursor-pointer align-top",
        expanded ? "whitespace-normal break-words" : "whitespace-nowrap max-w-[200px] truncate"
      )}
      title={expanded ? undefined : cell}
    >
      {cell}
    </td>
  );
}

export function CsvPreview({ csv, chapter, selectedBy, source, candidateCount }: CsvPreviewProps) {
  const [expanded, setExpanded] = useState(false);

  const selectionNote =
    selectedBy === "judge"
      ? `Chosen by Judge from ${candidateCount ?? 0} candidates`
      : source === "doctored"
        ? "Doctored CSV"
        : null;

  const lines = csv.split("\n").filter((l) => l.trim());
  const headers = lines.length > 0 ? parseCSVLine(lines[0]) : [];
  const dataRows = lines.slice(1).map((l) => parseCSVLine(l, headers.length));
  const visibleRows = expanded ? dataRows : dataRows.slice(0, PREVIEW_ROWS);
  const hasMore = dataRows.length > PREVIEW_ROWS;

  const copyCSV = () => copyCsv(csv);
  const downloadCSV = () => downloadCsv(csv, `${chapter || "curriculum"}.csv`);

  return (
    <div className="mb-6 rounded-md border border-border bg-card p-4">
      <div className="mb-3 flex items-center gap-2 flex-wrap">
        <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
          Final CSV — {dataRows.length} row{dataRows.length !== 1 ? "s" : ""} × {headers.length} columns
        </span>
        <Badge variant="outline" className="border-[var(--qm-green)]/40 text-[var(--qm-green)]">
          VALIDATED
        </Badge>
        {selectionNote && (
          <Badge variant="outline" className="border-[var(--qm-purple)]/40 text-[var(--qm-purple)]">
            {selectionNote}
          </Badge>
        )}
      </div>

      <div className={cn(
        "thin-scroll overflow-auto rounded border border-border",
        expanded ? "max-h-[600px]" : "max-h-[340px]"
      )}>
          <table className="min-w-full text-[11px]">
            <thead>
              <tr className="border-b border-border bg-secondary">
                {headers.map((h, i) => (
                  <th
                    key={i}
                    className="px-3 py-2 text-left text-[10px] font-bold uppercase tracking-wide text-muted-foreground whitespace-nowrap"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row, ri) => (
                <tr
                  key={ri}
                  className={ri % 2 === 0 ? "bg-card" : "bg-secondary/30"}
                >
                  {row.map((cell, ci) => (
                    <CsvCell key={ci} cell={cell} />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
      </div>

      <div className="mt-2 flex items-center justify-between flex-wrap gap-2">
        <div className="flex gap-2">
          <Button size="sm" className="text-xs" onClick={copyCSV}>
            Copy CSV
          </Button>
          <Button size="sm" variant="secondary" className="text-xs" onClick={downloadCSV}>
            Download
          </Button>
        </div>
        {hasMore && (
          <button
            onClick={() => setExpanded((p) => !p)}
            className="flex items-center gap-1 text-[10px] text-primary/70 hover:text-primary transition-colors"
          >
            {expanded ? (
              <>
                <ChevronUp className="h-3 w-3" /> Collapse
              </>
            ) : (
              <>
                <ChevronDown className="h-3 w-3" /> Show all {dataRows.length} rows
              </>
            )}
          </button>
        )}
      </div>
    </div>
  );
}
