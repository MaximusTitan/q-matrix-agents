---
type: "query"
date: "2026-06-09T15:16:29.582174+00:00"
question: "Map extraction agent runs only once in the beginning if the concept-skill-map is not present, but in the dashboard its shown under cycle 1 itself as map extraction + generator card together, map extraction should have a separate card which is not a part of the cycle as it happens only once at the beginning. Also the first card status of every run is always running and never changes to done."
contributor: "graphify"
source_nodes: ["orchestrator.py", "pipeline-reducer.ts", "agent-timeline.tsx"]
---

# Q: Map extraction agent runs only once in the beginning if the concept-skill-map is not present, but in the dashboard its shown under cycle 1 itself as map extraction + generator card together, map extraction should have a separate card which is not a part of the cycle as it happens only once at the beginning. Also the first card status of every run is always running and never changes to done.

## Answer

Two bugs fixed. Bug 1 root cause: orchestrator emitted agent_started for Map Extraction + Generator combined inside the attempt_started block, so reducer assigned it attempt:1 (cycle 1). Bug 2 root cause: orchestrator emitted agent_completed for Map Extraction and Generator separately, but the reducer searched for a running agent named exactly Map Extraction + Generator — no match, so the combined card stayed running forever. Fix: (1) orchestrator.py — emit agent_started for Map Extraction BEFORE attempt_started, so state.currentAttempt is still 0 and the reducer assigns attempt:0. Then emit attempt_started, then Generator agent_started/completed normally. Used gen_result=None flag to reuse the parallel-run result without re-running the generator. (2) agent-timeline.tsx — fixed || 1 bug to ?? 1 so attempt:0 is not collapsed into cycle 1. Added a Pre-run section above the cycle groups that renders attempt:0 agents using MapExtractionCard. Cycle AttemptGroups now filter to attempt > 0 only.

## Source Nodes

- orchestrator.py
- pipeline-reducer.ts
- agent-timeline.tsx