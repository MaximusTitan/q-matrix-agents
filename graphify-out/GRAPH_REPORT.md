# Graph Report - .  (2026-06-06)

## Corpus Check
- Corpus is ~19,151 words - fits in a single context window. You may not need a graph.

## Summary
- 456 nodes · 832 edges · 26 communities (15 shown, 11 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 11 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Map Extraction Agent|Map Extraction Agent]]
- [[_COMMUNITY_Dashboard Agent Timeline UI|Dashboard Agent Timeline UI]]
- [[_COMMUNITY_Revision Agent and API|Revision Agent and API]]
- [[_COMMUNITY_Next.js App Pages|Next.js App Pages]]
- [[_COMMUNITY_Eval Agent|Eval Agent]]
- [[_COMMUNITY_Dashboard Dependencies|Dashboard Dependencies]]
- [[_COMMUNITY_Agent Prompts and Rules|Agent Prompts and Rules]]
- [[_COMMUNITY_Dashboard Config and Aliases|Dashboard Config and Aliases]]
- [[_COMMUNITY_TypeScript Config|TypeScript Config]]
- [[_COMMUNITY_Graphify Metadata|Graphify Metadata]]
- [[_COMMUNITY_Google Drive Sync Script|Google Drive Sync Script]]
- [[_COMMUNITY_Frontend Docs and README|Frontend Docs and README]]
- [[_COMMUNITY_App Layout|App Layout]]
- [[_COMMUNITY_Claude Settings|Claude Settings]]
- [[_COMMUNITY_ESLint Config|ESLint Config]]
- [[_COMMUNITY_Next.js Config|Next.js Config]]
- [[_COMMUNITY_PostCSS Config|PostCSS Config]]
- [[_COMMUNITY_LLM Skill and Anthropic Dep|LLM Skill and Anthropic Dep]]
- [[_COMMUNITY_Skills Init|Skills Init]]
- [[_COMMUNITY_CSV Utils Skill|CSV Utils Skill]]
- [[_COMMUNITY_Diff Skill|Diff Skill]]
- [[_COMMUNITY_File IO Skill|File IO Skill]]
- [[_COMMUNITY_Python Dotenv Dep|Python Dotenv Dep]]

## God Nodes (most connected - your core abstractions)
1. `cn()` - 52 edges
2. `str` - 22 edges
3. `run_pipeline()` - 19 edges
4. `compilerOptions` - 16 edges
5. `file_exists()` - 16 edges
6. `load_prompt()` - 14 edges
7. `call_llm()` - 13 edges
8. `run()` - 12 edges
9. `run()` - 11 edges
10. `RunFormValues` - 10 edges

## Surprising Connections (you probably didn't know these)
- `Human Feedback Input to Revision Agent` --semantically_similar_to--> `Human-in-the-Loop Intervention`  [INFERRED] [semantically similar]
  prompts/revision_prompt.md → README.md
- `Concept Extraction Rules` --conceptually_related_to--> `Concept-Skill Map`  [INFERRED]
  prompts/map_extraction_prompt.md → README.md
- `Skill Extraction Rules (verb-led)` --conceptually_related_to--> `Concept-Skill Map`  [INFERRED]
  prompts/map_extraction_prompt.md → README.md
- `run_check1()` --calls--> `load_rules()`  [EXTRACTED]
  agents/eval.py → skills/kb_access.py
- `run_check2()` --calls--> `load_concept_skill_map()`  [EXTRACTED]
  agents/eval.py → skills/kb_access.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Core Orchestration Pipeline: Generate, Eval, Revise** — readme_orchestrator, readme_generator_agent, readme_eval_agent, readme_revision_agent [EXTRACTED 0.95]
- **Cold Start Prompt Emergence: Rules, Generate, Save** — readme_cold_start, readme_universal_rules, readme_base_prompt, readme_generator_agent, readme_revision_agent [EXTRACTED 0.90]
- **Parallel Map Extraction and Generation Flow** — readme_map_extraction_agent, readme_generator_agent, readme_concept_skill_map, readme_orchestrator [EXTRACTED 0.90]

## Communities (26 total, 11 thin omitted)

### Community 0 - "Map Extraction Agent"
Cohesion: 0.06
Nodes (66): str, agents/map_extraction.py  Map Extraction Agent. Extracts a concept-skill-map fro, Extract a concept-skill-map from a chapter PDF and save it to the KB.      Args:, run(), int, append_file(), create_directory(), directory_exists() (+58 more)

### Community 1 - "Dashboard Agent Timeline UI"
Cohesion: 0.06
Nodes (51): AGENT_COLORS, AGENT_ICONS, AgentTimelineProps, AttemptGroup(), CsvInlineEntry(), cycleStatus(), EXCLUDED_KEYS, IOSection() (+43 more)

### Community 2 - "Revision Agent and API"
Cohesion: 0.06
Nodes (48): str, Rewrite a generation prompt based on eval feedback.      Args:         current_p, run(), dashboard(), get_run(), list_runs(), str, api.py  FastAPI backend for the Q-Matrix Live Dashboard. Runs the pipeline in a (+40 more)

### Community 3 - "Next.js App Pages"
Cohesion: 0.09
Nodes (37): DashboardPage(), DEFAULT_FORM, AgentTimeline(), CheckBlock(), EscalationPanel(), EscalationPanelProps, Header(), HeaderProps (+29 more)

### Community 4 - "Eval Agent"
Cohesion: 0.08
Nodes (34): _parse_llm_json(), str, agents/eval.py  Eval Agent. Runs Check 1 and Check 2 in PARALLEL — both always r, Run Check 1 and Check 2 in parallel.     Both checks always run — neither is ski, Check 1 — Universal rules compliance.      Returns:         Dict with keys: pass, Check 2 — Concept-skill-map coverage.      Returns:         Dict with keys: pass, run(), run_check1() (+26 more)

### Community 5 - "Dashboard Dependencies"
Cohesion: 0.06
Nodes (30): dependencies, @base-ui/react, class-variance-authority, clsx, lucide-react, next, react, react-dom (+22 more)

### Community 6 - "Agent Prompts and Rules"
Cohesion: 0.11
Nodes (30): Eval Check 1: Universal Rules Evaluation, Eval Check 2: Concept-Skill Map Coverage, Eval Agent System Prompt, Generator Agent System Prompt, Concept Extraction Rules, Map Extraction Agent System Prompt, Skill Extraction Rules (verb-led), Human Feedback Input to Revision Agent (+22 more)

### Community 7 - "Dashboard Config and Aliases"
Cohesion: 0.09
Nodes (21): aliases, components, hooks, lib, ui, utils, iconLibrary, menuAccent (+13 more)

### Community 8 - "TypeScript Config"
Cohesion: 0.10
Nodes (19): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+11 more)

### Community 9 - "Graphify Metadata"
Cohesion: 0.14
Nodes (13): files, code, document, image, paper, video, graphifyignore_patterns, needs_graph (+5 more)

### Community 10 - "Google Drive Sync Script"
Cohesion: 0.22
Nodes (13): download_pdf(), get_drive_service(), list_folder_contents(), parse_chapter_folder_name(), bool, str, scripts/sync_textbooks_from_drive.py  One-time (or periodic) script that downl, List all files and folders inside a Drive folder. (+5 more)

### Community 11 - "Frontend Docs and README"
Cohesion: 0.29
Nodes (7): Next.js Breaking Changes Warning, Next.js App (dashboard), Next.js Dashboard, FastAPI Backend, Server-Sent Events (SSE), Dependency: fastapi, Dependency: uvicorn

## Knowledge Gaps
- **111 isolated node(s):** `allow`, `code`, `document`, `paper`, `image` (+106 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **11 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `cn()` connect `Dashboard Agent Timeline UI` to `Next.js App Pages`?**
  _High betweenness centrality (0.028) - this node is a cross-community bridge._
- **Why does `run_pipeline()` connect `Revision Agent and API` to `Map Extraction Agent`, `Eval Agent`?**
  _High betweenness centrality (0.019) - this node is a cross-community bridge._
- **Why does `run()` connect `Eval Agent` to `Map Extraction Agent`, `Revision Agent and API`?**
  _High betweenness centrality (0.009) - this node is a cross-community bridge._
- **What connects `allow`, `code`, `document` to the rest of the system?**
  _181 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Map Extraction Agent` be split into smaller, more focused modules?**
  _Cohesion score 0.06468797564687975 - nodes in this community are weakly interconnected._
- **Should `Dashboard Agent Timeline UI` be split into smaller, more focused modules?**
  _Cohesion score 0.061457418788410885 - nodes in this community are weakly interconnected._
- **Should `Revision Agent and API` be split into smaller, more focused modules?**
  _Cohesion score 0.056107539450613676 - nodes in this community are weakly interconnected._