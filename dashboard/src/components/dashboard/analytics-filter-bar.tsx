"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, X } from "lucide-react";
import type { AnalyticsFilters } from "@/lib/api";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export interface AnalyticsFolderOptions {
  boards: string[];
  subjects: string[];
  grades: string[];
}

const FILTER_FIELDS: { key: "board" | "subject" | "grade"; label: string }[] = [
  { key: "board", label: "Board" },
  { key: "subject", label: "Subject" },
  { key: "grade", label: "Grade" },
];

function ModelMultiSelect({
  options,
  selected,
  onChange,
}: {
  options: string[];
  selected: string[];
  onChange: (models: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDocMouseDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [open]);

  const toggle = (model: string) => {
    onChange(
      selected.includes(model) ? selected.filter((m) => m !== model) : [...selected, model]
    );
  };

  const label =
    selected.length === 0
      ? "All models"
      : selected.length === 1
        ? selected[0]
        : `${selected.length} models`;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        className="flex h-8 w-[180px] items-center justify-between rounded-md border border-input bg-secondary px-3 text-xs"
      >
        <span className="truncate">{label}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      </button>
      {open && (
        <div className="thin-scroll absolute z-20 mt-1 max-h-64 w-[240px] overflow-y-auto rounded-md border border-border bg-popover p-1 shadow-md">
          {options.length === 0 ? (
            <div className="px-2 py-1.5 text-[11px] text-muted-foreground">No models</div>
          ) : (
            options.map((model) => (
              <label
                key={model}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-[11px] hover:bg-accent"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(model)}
                  onChange={() => toggle(model)}
                  className="h-3.5 w-3.5"
                />
                <span className="truncate font-mono">{model}</span>
              </label>
            ))
          )}
          {selected.length > 0 && (
            <button
              type="button"
              onClick={() => onChange([])}
              className="mt-1 w-full rounded px-2 py-1 text-left text-[10px] font-bold uppercase tracking-widest text-muted-foreground hover:text-foreground"
            >
              Clear models
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// Global filter bar for the analytics page — board/subject/grade/model, each
// optional and independent. Drives both /kb/analytics and /kb/analytics/models,
// so summary cards, model performance, and the grouped chapter tree all narrow
// to the same selection at once.
export function AnalyticsFilterBar({
  filters,
  onFiltersChange,
  folderOptions,
  allModelOptions,
}: {
  filters: AnalyticsFilters;
  onFiltersChange: (filters: AnalyticsFilters) => void;
  folderOptions: AnalyticsFolderOptions;
  allModelOptions: string[];
}) {
  const optionsByField: Record<"board" | "subject" | "grade", string[]> = {
    board: folderOptions.boards,
    subject: folderOptions.subjects,
    grade: folderOptions.grades,
  };
  const hasActiveFilter =
    FILTER_FIELDS.some(({ key }) => !!filters[key]) || (filters.models?.length ?? 0) > 0;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {FILTER_FIELDS.map(({ key, label }) => {
        const options = optionsByField[key];
        return (
          <Select
            key={key}
            value={filters[key] ?? "__all__"}
            onValueChange={(v) =>
              onFiltersChange({ ...filters, [key]: v === "__all__" ? undefined : v })
            }
          >
            <SelectTrigger className="h-8 w-[160px] bg-secondary text-xs">
              <SelectValue placeholder={label} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">All {label.toLowerCase()}s</SelectItem>
              {options.map((opt) => (
                <SelectItem key={opt} value={opt}>
                  {opt}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        );
      })}
      <ModelMultiSelect
        options={allModelOptions}
        selected={filters.models ?? []}
        onChange={(models) =>
          onFiltersChange({ ...filters, models: models.length ? models : undefined })
        }
      />
      {hasActiveFilter && (
        <button
          onClick={() => onFiltersChange({})}
          className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground hover:text-foreground"
        >
          <X className="h-3 w-3" />
          Clear filters
        </button>
      )}
    </div>
  );
}
