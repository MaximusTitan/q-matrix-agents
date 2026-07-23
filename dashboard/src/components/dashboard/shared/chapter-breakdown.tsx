"use client";

// A bucket entry is either a bare chapter name (L2, same grade as the target) or
// a {grade, chapter} pair (L3, spans multiple grades) — rendered accordingly.
export type ChapterGroupItem = string | { grade: string; chapter: string };

function itemKey(item: ChapterGroupItem): string {
  return typeof item === "string" ? item : `${item.grade}:${item.chapter}`;
}

function itemLabel(item: ChapterGroupItem): string {
  return typeof item === "string" ? item : `${item.chapter} (${item.grade})`;
}

function ChapterGroup({
  label,
  reason,
  color,
  items,
}: {
  label: string;
  reason: string;
  color: string;
  items: ChapterGroupItem[];
}) {
  return (
    <div>
      <div className="mb-1 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
        <span style={{ color }}>{label}</span>
        <span className="font-normal normal-case tracking-normal text-muted-foreground">
          ({items.length})
        </span>
      </div>
      {items.length === 0 ? (
        <div className="text-[11px] text-muted-foreground">—</div>
      ) : (
        <ul className="space-y-0.5">
          {items.map((item) => (
            <li key={itemKey(item)} className="text-[11px] text-foreground/80" title={reason}>
              {itemLabel(item)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface ChapterBreakdownProps {
  withEdges?: ChapterGroupItem[];
  screenedNoEdges?: ChapterGroupItem[];
  excludedByScreen?: ChapterGroupItem[];
}

// Coarse "which chapters do/don't relate to this target" view, shown above the
// specific concept/skill edge detail — both live (prerequisite-mapping-summary)
// and historical (analytics-panel's RunInsightsCard) reuse this, for both L2
// (same-grade siblings) and L3 (cross-grade candidates). Renders nothing when
// all three fields are undefined, distinguishing "no breakdown persisted" (a run
// from before this feature existed) from a real empty bucket.
export function ChapterBreakdown({
  withEdges,
  screenedNoEdges,
  excludedByScreen,
}: ChapterBreakdownProps) {
  if (withEdges === undefined && screenedNoEdges === undefined && excludedByScreen === undefined) {
    return null;
  }

  return (
    <div className="mb-3 grid grid-cols-1 gap-3 rounded border border-border bg-background p-3 md:grid-cols-3">
      <ChapterGroup
        label="Contributed prerequisites"
        reason="Contributed at least one concept or skill prerequisite to the target chapter."
        color="var(--qm-green)"
        items={withEdges ?? []}
      />
      <ChapterGroup
        label="Screened, none found"
        reason="Flagged as topically related by the relevance screen, but the fine-grained mapping pass found no genuine prerequisite from it."
        color="var(--qm-amber)"
        items={screenedNoEdges ?? []}
      />
      <ChapterGroup
        label="Not flagged as related"
        reason="Not flagged as topically related by the relevance screen — never passed to the fine-grained mapping pass."
        color="var(--qm-blue)"
        items={excludedByScreen ?? []}
      />
    </div>
  );
}
