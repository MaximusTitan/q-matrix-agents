"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { fetchKbBoards, fetchKbSubjects, fetchKbGrades, fetchKbChapters } from "@/lib/api";
import type { RunFormValues, StartRunOptions } from "@/lib/types";

interface RunFormProps {
  form: RunFormValues;
  onFormChange: (form: RunFormValues) => void;
  isRunning: boolean;
  onStart: (options: StartRunOptions) => void;
}

type LoadState = "idle" | "loading" | "done";

function KbSelect({
  label,
  value,
  options,
  state,
  placeholder,
  disabledReason,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  state: LoadState;
  placeholder: string;
  disabledReason?: string;
  onChange: (v: string) => void;
}) {
  const disabled = state !== "done" || options.length === 0;
  const displayPlaceholder =
    state === "loading"
      ? "Loading…"
      : options.length === 0 && disabledReason
        ? disabledReason
        : placeholder;

  return (
    <div className="space-y-1.5">
      <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </Label>
      <Select value={value} onValueChange={(v) => v && onChange(v)} disabled={disabled}>
        <SelectTrigger className="h-8 w-full bg-secondary text-xs">
          <SelectValue placeholder={displayPlaceholder} />
        </SelectTrigger>
        <SelectContent>
          {options.map((opt) => (
            <SelectItem key={opt} value={opt}>
              {opt}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

export function RunForm({ form, onFormChange, isRunning, onStart }: RunFormProps) {
  const [boards, setBoards] = useState<string[]>([]);
  const [subjects, setSubjects] = useState<string[]>([]);
  const [grades, setGrades] = useState<string[]>([]);
  const [chapters, setChapters] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>(
    "anthropic/claude-sonnet-4.5"
  );

  const [boardState, setBoardState] = useState<LoadState>("loading");
  const [subjectState, setSubjectState] = useState<LoadState>("idle");
  const [gradeState, setGradeState] = useState<LoadState>("idle");
  const [chapterState, setChapterState] = useState<LoadState>("idle");

  // Load boards on mount
  useEffect(() => {
    setBoardState("loading");
    fetchKbBoards().then((data) => {
      setBoards(data);
      setBoardState("done");
    });
  }, []);

  // Board changed → clear downstream, reload subjects
  const handleBoardChange = (board: string) => {
    onFormChange({ ...form, board, subject: "", grade: "", chapter: "" });
    setSubjects([]);
    setGrades([]);
    setChapters([]);
    setSubjectState("loading");
    setGradeState("idle");
    setChapterState("idle");
    fetchKbSubjects(board).then((data) => {
      setSubjects(data);
      setSubjectState("done");
    });
  };

  // Subject changed → clear downstream, reload grades
  const handleSubjectChange = (subject: string) => {
    onFormChange({ ...form, subject, grade: "", chapter: "" });
    setGrades([]);
    setChapters([]);
    setGradeState("loading");
    setChapterState("idle");
    fetchKbGrades(form.board, subject).then((data) => {
      setGrades(data);
      setGradeState("done");
    });
  };

  // Grade changed → clear chapters, reload chapters
  const handleGradeChange = (grade: string) => {
    onFormChange({ ...form, grade, chapter: "" });
    setChapters([]);
    setChapterState("loading");
    fetchKbChapters(form.board, form.subject, grade).then((data) => {
      setChapters(data);
      setChapterState("done");
    });
  };

  // Chapter changed
  const handleChapterChange = (chapter: string) => {
    onFormChange({ ...form, chapter });
  };

  const canRun = !isRunning && !!form.board && !!form.subject && !!form.grade && !!form.chapter;

  return (
    <div className="space-y-3 border-b border-border p-4">
      <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
        New Run
      </div>

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

      <KbSelect
        label="Chapter"
        value={form.chapter}
        options={chapters}
        state={chapterState}
        placeholder="Select chapter…"
        disabledReason={form.grade ? "No chapters found" : "Select a grade first"}
        onChange={handleChapterChange}
      />

      <div className="space-y-1.5">
        <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">
          Model
        </Label>
        <Select value={selectedModel} onValueChange={(v) => v && setSelectedModel(v)}>
          <SelectTrigger className="h-8 w-full bg-secondary text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="anthropic/claude-sonnet-4.5">
              anthropic/claude-sonnet-4.5
            </SelectItem>
            <SelectItem value="openai/gpt-4o">openai/gpt-4o</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <Button
        className="w-full text-xs font-bold"
        disabled={!canRun}
        onClick={() => onStart({ ...form, model: selectedModel })}
      >
        ▶ Run Pipeline
      </Button>
    </div>
  );
}
