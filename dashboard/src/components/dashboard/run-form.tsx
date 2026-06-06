"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { RunFormValues, StartRunOptions } from "@/lib/types";

const GRADES = Array.from({ length: 12 }, (_, i) => `Grade ${i + 1}`);

interface RunFormProps {
  form: RunFormValues;
  onFormChange: (form: RunFormValues) => void;
  isRunning: boolean;
  onStart: (options: StartRunOptions) => void;
}

export function RunForm({ form, onFormChange, isRunning, onStart }: RunFormProps) {
  const update = (field: keyof RunFormValues, value: string) => {
    onFormChange({ ...form, [field]: value });
  };

  return (
    <div className="space-y-3 border-b border-border p-4">
      <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
        New Run
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="board" className="text-[10px] uppercase tracking-wide text-muted-foreground">
          Board
        </Label>
        <Input
          id="board"
          value={form.board}
          onChange={(e) => update("board", e.target.value)}
          className="h-8 bg-secondary text-xs"
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="subject" className="text-[10px] uppercase tracking-wide text-muted-foreground">
          Subject
        </Label>
        <Input
          id="subject"
          placeholder="e.g. Science"
          value={form.subject}
          onChange={(e) => update("subject", e.target.value)}
          className="h-8 bg-secondary text-xs"
        />
      </div>

      <div className="space-y-1.5">
        <Label className="text-[10px] uppercase tracking-wide text-muted-foreground">Grade</Label>
        <Select value={form.grade} onValueChange={(v) => v && update("grade", v)}>
          <SelectTrigger className="h-8 w-full bg-secondary text-xs">
            <SelectValue placeholder="Select grade..." />
          </SelectTrigger>
          <SelectContent>
            {GRADES.map((g) => (
              <SelectItem key={g} value={g}>
                {g}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="chapter" className="text-[10px] uppercase tracking-wide text-muted-foreground">
          Chapter (folder name)
        </Label>
        <Input
          id="chapter"
          placeholder="e.g. Chapter10_Sound"
          value={form.chapter}
          onChange={(e) => update("chapter", e.target.value)}
          className="h-8 bg-secondary text-xs"
        />
      </div>

      <Button
        className="w-full text-xs font-bold"
        disabled={isRunning}
        onClick={() => onStart(form)}
      >
        ▶ Run Pipeline
      </Button>
    </div>
  );
}
