"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { fetchKbBoards, fetchKbSubjects, fetchKbGrades, fetchL3EligibleChapters } from "@/lib/api";
import { KbSelect, type EnqueueOptions, type LoadState } from "./run-form";
import type {
  AgentKey,
  L3EligibleChaptersResponse,
  RunFormValues,
  StartRunOptions,
} from "@/lib/types";

interface L3RunFormProps {
  form: RunFormValues;
  onFormChange: (form: RunFormValues) => void;
  isRunning: boolean;
  onStart: (options: StartRunOptions) => void;
  onEnqueue?: (values: RunFormValues, opts?: EnqueueOptions) => void;
  modelsSection: React.ReactNode;
  modelsForStart: Partial<Record<AgentKey, string>> | undefined;
}

export function L3RunForm({
  form,
  onFormChange,
  isRunning,
  onStart,
  onEnqueue,
  modelsSection,
  modelsForStart,
}: L3RunFormProps) {
  const [boards, setBoards] = useState<string[]>([]);
  const [subjects, setSubjects] = useState<string[]>([]);
  const [grades, setGrades] = useState<string[]>([]);

  const [boardState, setBoardState] = useState<LoadState>("loading");
  const [subjectState, setSubjectState] = useState<LoadState>("idle");
  const [gradeState, setGradeState] = useState<LoadState>("idle");

  const [eligibility, setEligibility] = useState<L3EligibleChaptersResponse | null>(null);
  const [eligibilityLoading, setEligibilityLoading] = useState(false);

  // Which target chapters are selected for L3 mapping. Local to this form (not
  // part of the shared `form`, which only carries a single `chapter` string
  // used by the other run modes too).
  const [selectedChapters, setSelectedChapters] = useState<string[]>([]);

  useEffect(() => {
    setBoardState("loading");
    fetchKbBoards().then((data) => {
      setBoards(data);
      setBoardState("done");
    });
  }, []);

  // Whenever board/subject/grade are all set, (re)fetch L3 eligibility for that group.
  useEffect(() => {
    setSelectedChapters([]);
    if (!form.board || !form.subject || !form.grade) {
      setEligibility(null);
      return;
    }
    setEligibilityLoading(true);
    fetchL3EligibleChapters(form.board, form.subject, form.grade)
      .then(setEligibility)
      .catch(() => setEligibility(null))
      .finally(() => setEligibilityLoading(false));
  }, [form.board, form.subject, form.grade]);

  const handleBoardChange = (board: string) => {
    onFormChange({ ...form, board, subject: "", grade: "", chapter: "" });
    setSubjects([]);
    setGrades([]);
    setSubjectState("loading");
    setGradeState("idle");
    fetchKbSubjects(board).then((data) => {
      setSubjects(data);
      setSubjectState("done");
    });
  };

  const handleSubjectChange = (subject: string) => {
    onFormChange({ ...form, subject, grade: "", chapter: "" });
    setGrades([]);
    setGradeState("loading");
    fetchKbGrades(form.board, subject).then((data) => {
      setGrades(data);
      setGradeState("done");
    });
  };

  const handleGradeChange = (grade: string) => {
    onFormChange({ ...form, grade, chapter: "" });
  };

  const canRunNow =
    !isRunning && !!form.board && !!form.subject && !!form.grade && selectedChapters.length === 1;
  const canQueue = !!onEnqueue && !!form.board && !!form.subject && !!form.grade && selectedChapters.length > 0;

  return (
    <>
      <p className="text-[10px] leading-relaxed text-muted-foreground">
        Maps a chapter&apos;s concepts/skills against concepts/skills from chapters in earlier
        grades of the same subject. Only available once the target chapter&apos;s own grade + subject,
        and every earlier grade of the subject, have L1 (within-chapter) prerequisites mapped.
      </p>

      <KbSelect
        label="Board"
        value={form.board}
        options={boards}
        state={boardState}
        placeholder="Select board…"
        disabledReason="No boards found"
        onChange={handleBoardChange}
      />

      <KbSelect
        label="Subject"
        value={form.subject}
        options={subjects}
        state={subjectState}
        placeholder="Select subject…"
        disabledReason={form.board ? "No subjects found" : "Select a board first"}
        onChange={handleSubjectChange}
      />

      <KbSelect
        label="Grade"
        value={form.grade}
        options={grades}
        state={gradeState}
        placeholder="Select grade…"
        disabledReason={form.subject ? "No grades found" : "Select a subject first"}
        onChange={handleGradeChange}
      />

      {form.grade && eligibilityLoading && (
        <p className="text-[10px] text-muted-foreground">Checking L1 eligibility…</p>
      )}

      {form.grade && !eligibilityLoading && eligibility && eligibility.prior_grade_count === 0 && (
        <div className="space-y-1 rounded-md border border-border bg-secondary/40 p-2">
          <p className="text-[10px] font-bold text-foreground">
            L3 mapping unavailable for this grade
          </p>
          <p className="text-[10px] leading-relaxed text-muted-foreground">
            No earlier grades exist yet for this board + subject — there is nothing to map
            cross-grade prerequisites against.
          </p>
        </div>
      )}

      {form.grade &&
        !eligibilityLoading &&
        eligibility &&
        eligibility.prior_grade_count > 0 &&
        !eligibility.eligible && (
          <div className="space-y-1 rounded-md border border-border bg-secondary/40 p-2">
            <p className="text-[10px] font-bold text-foreground">
              L3 mapping unavailable for this grade + subject
            </p>
            <p className="text-[10px] leading-relaxed text-muted-foreground">
              {eligibility.blocking_chapters.length > 0
                ? `${eligibility.blocking_chapters.length} chapter(s) in this grade still need L1 mapping: ${eligibility.blocking_chapters.join(", ")}`
                : `Every chapter in ${eligibility.prior_grade_count} earlier grade(s) needs L1 mapping first.`}
            </p>
          </div>
        )}

      {form.grade && !eligibilityLoading && eligibility?.eligible && (
        <div className="space-y-1.5">
          <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Target Chapter(s)
          </label>
          <Select
            multiple
            value={selectedChapters}
            onValueChange={setSelectedChapters}
            disabled={isRunning}
          >
            <SelectTrigger className="h-8 w-full bg-secondary text-xs">
              <SelectValue placeholder="Select target chapter(s)…">
                {(value: string[]) =>
                  value.length
                    ? `${value.length} chapter${value.length !== 1 ? "s" : ""} selected`
                    : undefined
                }
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {eligibility.chapters.map((c) => (
                <SelectItem key={c.chapter} value={c.chapter}>
                  {c.chapter}
                  {c.has_l3_prereqs ? " (L3 already mapped — re-run?)" : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {selectedChapters.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {selectedChapters.map((chapter) => (
                <span
                  key={chapter}
                  className="flex items-center gap-1 rounded bg-secondary px-1.5 py-0.5 text-[10px]"
                >
                  {chapter}
                  <button
                    onClick={() =>
                      setSelectedChapters((chs) => chs.filter((c) => c !== chapter))
                    }
                    disabled={isRunning}
                    title="Remove"
                    className="text-muted-foreground hover:text-[var(--qm-red)]"
                  >
                    ✕
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {modelsSection}

      <div className="flex gap-2">
        <Button
          className="flex-1 text-xs font-bold"
          disabled={!canRunNow}
          title={
            selectedChapters.length > 1
              ? "Queue multiple chapters instead — Run Now only handles one at a time"
              : undefined
          }
          onClick={() =>
            onStart({ ...form, chapter: selectedChapters[0], l3Prerequisite: true, models: modelsForStart })
          }
        >
          ▶ Run Now
        </Button>
        {onEnqueue && (
          <Button
            variant="secondary"
            className="flex-1 text-xs font-bold"
            disabled={!canQueue}
            title="Add the selected chapter(s) to the queue"
            onClick={() => {
              selectedChapters.forEach((chapter) =>
                onEnqueue({ ...form, chapter }, { l3Prerequisite: true, models: modelsForStart })
              );
              setSelectedChapters([]);
            }}
          >
            ＋ Queue{selectedChapters.length > 1 ? ` (${selectedChapters.length})` : ""}
          </Button>
        )}
      </div>
    </>
  );
}
