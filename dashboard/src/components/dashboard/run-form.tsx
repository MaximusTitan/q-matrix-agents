"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
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
  // Queue the current chapter for a sequential batch run (generate mode only).
  onEnqueue?: (values: RunFormValues) => void;
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

export function RunForm({ form, onFormChange, isRunning, onStart, onEnqueue }: RunFormProps) {
  const [boards, setBoards] = useState<string[]>([]);
  const [subjects, setSubjects] = useState<string[]>([]);
  const [grades, setGrades] = useState<string[]>([]);
  const [chapters, setChapters] = useState<string[]>([]);

  const [boardState, setBoardState] = useState<LoadState>("loading");
  const [subjectState, setSubjectState] = useState<LoadState>("idle");
  const [gradeState, setGradeState] = useState<LoadState>("idle");
  const [chapterState, setChapterState] = useState<LoadState>("idle");

  // "generate" = full pipeline from the KB; "csv" = skip Stage 1, paste/upload a CSV.
  const [mode, setMode] = useState<"generate" | "csv">("generate");
  const [csvText, setCsvText] = useState("");

  const handleCsvFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setCsvText(String(reader.result ?? ""));
    reader.readAsText(file);
    e.target.value = ""; // allow re-selecting the same file
  };

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

  const allFieldsSet = !!form.board && !!form.subject && !!form.grade && !!form.chapter;
  const canRun = !isRunning && allFieldsSet;
  // Queuing is allowed even mid-run so chapters can be piled up while one is processing.
  const canQueue = !!onEnqueue && allFieldsSet;
  const canRunCsv = !isRunning && csvText.trim().length > 0;

  return (
    <div className="space-y-3 border-b border-border p-4">
      <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
        New Run
      </div>

      {/* Mode toggle: generate from KB vs. provide a ready-made curriculum CSV */}
      <div className="flex rounded-lg border border-border bg-secondary/40 p-0.5">
        {([
          ["generate", "Generate from KB"],
          ["csv", "Provide CSV"],
        ] as const).map(([value, label]) => (
          <button
            key={value}
            onClick={() => setMode(value)}
            disabled={isRunning}
            className={cn(
              "flex-1 rounded-md px-2 py-1 text-[10px] font-bold uppercase tracking-wide transition-colors disabled:opacity-50",
              mode === value
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {mode === "generate" ? (
        <>
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

          <div className="flex gap-2">
            <Button
              className="flex-1 text-xs font-bold"
              disabled={!canRun}
              onClick={() => onStart(form)}
            >
              ▶ Run Pipeline
            </Button>
            {onEnqueue && (
              <Button
                variant="secondary"
                className="text-xs font-bold"
                disabled={!canQueue}
                onClick={() => onEnqueue(form)}
                title="Add this chapter to the queue"
              >
                ＋ Queue
              </Button>
            )}
          </div>
        </>
      ) : (
        <>
          <div className="space-y-1.5">
            <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">
              Curriculum CSV
            </Label>
            <p className="text-[10px] leading-relaxed text-muted-foreground">
              Skips generation and runs only prerequisite mapping. Paste or upload a CSV with
              columns: board, subject, grade, chapter, concept, skill.
            </p>
            <Textarea
              value={csvText}
              onChange={(e) => setCsvText(e.target.value)}
              disabled={isRunning}
              placeholder="board,subject,grade,chapter,concept,skill&#10;CBSE,Science,Grade 8,Chapter10_Sound,…"
              className="thin-scroll h-40 font-mono text-[10px]"
            />
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={handleCsvFile}
              disabled={isRunning}
              className="block w-full text-[10px] text-muted-foreground file:mr-2 file:rounded-md file:border-0 file:bg-secondary file:px-2 file:py-1 file:text-[10px] file:font-bold file:text-foreground hover:file:bg-muted"
            />
          </div>

          <Button
            className="w-full text-xs font-bold"
            disabled={!canRunCsv}
            onClick={() => onStart({ ...form, curriculumCsv: csvText })}
          >
            ▶ Run Prerequisite Mapping
          </Button>
        </>
      )}
    </div>
  );
}
