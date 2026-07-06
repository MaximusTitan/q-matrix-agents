"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import {
  AnalyticsPanel,
  type SelectedChapter,
} from "@/components/dashboard/analytics-panel";
import { fetchAnalytics, fetchChapterAnalytics } from "@/lib/api";
import type { AnalyticsResponse, ChapterAnalytics } from "@/lib/types";

function AnalyticsHeader() {
  return (
    <header className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-card px-6 py-3.5">
      <div className="flex items-center gap-3 text-sm font-bold tracking-widest">
        <Link
          href="/"
          className="flex items-center gap-1.5 text-muted-foreground hover:text-foreground transition-colors"
          title="Back to pipeline"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        Q-MATRIX ANALYTICS
      </div>
      <div className="text-xs text-muted-foreground">Pipeline history · q-matrix-kb</div>
    </header>
  );
}

function keyOf(c: {
  board: string;
  subject: string;
  grade: string;
  chapter: string;
}): string {
  return `${c.board}/${c.subject}/${c.grade}/${c.chapter}`;
}

function AnalyticsView() {
  const router = useRouter();
  const params = useSearchParams();

  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Detail state is keyed to the selection it belongs to, so a stale fetch or a
  // deselect never shows the wrong chapter. Loading/error are derived, not stored,
  // which keeps the fetch effects free of synchronous setState.
  const [detail, setDetail] = useState<ChapterAnalytics | null>(null);
  const [detailErr, setDetailErr] = useState<{ key: string; message: string } | null>(null);

  // Selected chapter is derived entirely from the URL query string, so views are
  // shareable/bookmarkable.
  const selected: SelectedChapter | null = useMemo(() => {
    const board = params.get("board");
    const subject = params.get("subject");
    const grade = params.get("grade");
    const chapter = params.get("chapter");
    if (board && subject && grade && chapter) {
      return { board, subject, grade, chapter };
    }
    return null;
  }, [params]);

  const loadAnalytics = useCallback(async () => {
    try {
      const res = await fetchAnalytics();
      setData(res);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load analytics");
    }
  }, []);

  useEffect(() => {
    loadAnalytics();
  }, [loadAnalytics]);

  // Monotonic token so a slow detail fetch can't overwrite a newer selection.
  const detailReqId = useRef(0);

  const loadDetail = useCallback(async (sel: SelectedChapter | null) => {
    if (!sel) return;
    const reqId = ++detailReqId.current;
    const key = keyOf(sel);
    try {
      const res = await fetchChapterAnalytics(sel.board, sel.subject, sel.grade, sel.chapter);
      if (reqId === detailReqId.current) {
        setDetail(res);
        setDetailErr(null);
      }
    } catch (e) {
      if (reqId === detailReqId.current)
        setDetailErr({
          key,
          message: e instanceof Error ? e.message : "Failed to load chapter detail",
        });
    }
  }, []);

  useEffect(() => {
    loadDetail(selected);
  }, [selected, loadDetail]);

  // Derived view state — no setState needed for loading/clearing.
  const loading = data === null && error === null;
  const selKey = selected ? keyOf(selected) : null;
  const detailForSel = detail && selKey && keyOf(detail) === selKey ? detail : null;
  const detailError = detailErr && detailErr.key === selKey ? detailErr.message : null;
  const detailLoading = !!selected && !detailForSel && !detailError;

  const onSelect = useCallback(
    (c: SelectedChapter) => {
      const q = new URLSearchParams({
        board: c.board,
        subject: c.subject,
        grade: c.grade,
        chapter: c.chapter,
      });
      router.replace(`/analytics?${q.toString()}`);
    },
    [router]
  );

  const onClear = useCallback(() => {
    router.replace("/analytics");
  }, [router]);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <AnalyticsHeader />
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <AnalyticsPanel
          data={data}
          loading={loading}
          error={error}
          selected={selected}
          detail={detailForSel}
          detailLoading={detailLoading}
          detailError={detailError}
          onSelect={onSelect}
          onClear={onClear}
        />
      </div>
    </div>
  );
}

export default function AnalyticsPage() {
  return (
    <Suspense
      fallback={
        <div className="p-6 text-sm text-muted-foreground">Loading analytics…</div>
      }
    >
      <AnalyticsView />
    </Suspense>
  );
}
