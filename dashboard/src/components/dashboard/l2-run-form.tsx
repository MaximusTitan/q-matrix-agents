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
import { fetchKbBoards, fetchKbSubjects, fetchKbGrades, fetchL2EligibleChapters } from "@/lib/api";
import { KbSelect, type LoadState } from "./run-form";
import type {
  AgentKey,
  L2EligibleChaptersResponse,
  RunFormValues,
  StartRunOptions,
} from "@/lib/types";

interface L2RunFormProps {
  form: RunFormValues;
  onFormChange: (form: RunFormValues) => void;
  isRunning: boolean;
  onStart: (options: StartRunOptions) => void;
  modelsSection: React.ReactNode;
  modelsForStart: Partial<Record<AgentKey, string>> | undefined;
}

export function L2RunForm({
  form,
  onFormChange,
  isRunning,
  onStart,
  modelsSection,
  modelsForStart,
}: L2RunFormProps) {
  const [boards, setBoards] = useState<string[]>([]);
  const [subjects, setSubjects] = useState<string[]>([]);
  const [grades, setGrades] = useState<string[]>([]);

  const [boardState, setBoardState] = useState<LoadState>("loading");
  const [subjectState, setSubjectState] = useState<LoadState>("idle");
  const [gradeState, setGradeState] = useState<LoadState>("idle");

  const [eligibility, setEligibility] = useState<L2EligibleChaptersResponse | null>(null);
  const [eligibilityLoading, setEligibilityLoading] = useState(false);

  useEffect(() => {
    setBoardState("loading");
    fetchKbBoards().then((data) => {
      setBoards(data);
      setBoardState("done");
    });
  }, []);

  // Whenever board/subject/grade are all set, (re)fetch L2 eligibility for that group.
  useEffect(() => {
    if (!form.board || !form.subject || !form.grade) {
      setEligibility(null);
      return;
    }
    setEligibilityLoading(true);
    fetchL2EligibleChapters(form.board, form.subject, form.grade)
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

  const handleChapterChange = (chapter: string) => {
    onFormChange({ ...form, chapter });
  };

  const canRun = !isRunning && !!form.board && !!form.subject && !!form.grade && !!form.chapter;

  return (
    <>
      <p className="text-[10px] leading-relaxed text-muted-foreground">
        Maps a chapter&apos;s concepts/skills against concepts/skills from other chapters in the
        same grade + subject. Only available once every chapter in the grade + subject has L1
        (within-chapter) prerequisites mapped.
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

      {form.grade && !eligibilityLoading && eligibility && !eligibility.eligible && (
        <div className="space-y-1 rounded-md border border-border bg-secondary/40 p-2">
          <p className="text-[10px] font-bold text-foreground">
            L2 mapping unavailable for this grade + subject
          </p>
          <p className="text-[10px] leading-relaxed text-muted-foreground">
            {eligibility.blocking_chapters.length > 0
              ? `${eligibility.blocking_chapters.length} chapter(s) still need L1 mapping: ${eligibility.blocking_chapters.join(", ")}`
              : "No chapters found in this grade + subject."}
          </p>
        </div>
      )}

      {form.grade && !eligibilityLoading && eligibility?.eligible && (
        <div className="space-y-1.5">
          <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Target Chapter
          </label>
          <Select
            value={form.chapter}
            onValueChange={(v) => v && handleChapterChange(v)}
            disabled={isRunning}
          >
            <SelectTrigger className="h-8 w-full bg-secondary text-xs">
              <SelectValue placeholder="Select target chapter…" />
            </SelectTrigger>
            <SelectContent>
              {eligibility.chapters.map((c) => (
                <SelectItem key={c.chapter} value={c.chapter}>
                  {c.chapter}
                  {c.has_l2_prereqs ? " (L2 already mapped — re-run?)" : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {modelsSection}

      <Button
        className="w-full text-xs font-bold"
        disabled={!canRun}
        onClick={() => onStart({ ...form, l2Prerequisite: true, models: modelsForStart })}
      >
        ▶ Run L2 Prerequisite Mapping
      </Button>
    </>
  );
}
