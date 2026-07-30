"""
scripts/export_graph.py

Export the confirmed curriculum corpus as a concept-level knowledge graph.

The KB stores curriculum as one CSV per chapter, where each row is a
(concept, skill) pair and prerequisites live as JSON arrays embedded in CSV
cells. References between rows are exact free-text name matches scoped by
(grade, chapter-folder) — there are no IDs anywhere in the KB.

This script does the resolution once, mints stable IDs, and writes a static
JSON contract that a browser can render without re-deriving any of it:

    graph-core.json      nodes + links, everything needed to draw a frame
    concept-details.json per-concept skills and prerequisite rationales
    meta.json            provenance, inventory, and the integrity report

Usage:
    python scripts/export_graph.py --out ../q-matrix-graph-template/public/graph --check
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills.kb_access import KB_ROOT, _PREREQ_SUBJECT_ALIASES  # noqa: E402

SCHEMA_VERSION = 1
BOARD = "CBSE"
CSV_NAME = "confirmed_curriculum.csv"

# Prerequisite columns, in the order they should be resolved. Each entry is
# (level, concept column, skill column). The three levels differ in how a
# reference names its source chapter, which is what resolve_ref() switches on:
#   L1  same chapter        — no chapter/grade on the reference at all
#   L2  cross-chapter       — reference carries {chapter}, grade is implied
#   L3  cross-grade         — reference carries {grade, chapter}
PREREQ_COLUMNS = [
    (1, "prereq_concepts_L1_same_chapter", "prereq_skills_L1_same_chapter"),
    (2, "prereq_concepts_L2_cross_chapter", "prereq_skills_L2_cross_chapter"),
    (3, "prereq_concepts_L3_prior_grade", "prereq_skills_L3_prior_grade"),
]

# Concept edges come from two places: the LLM authored them directly, or code
# lifted them from a skill edge (if skill A precedes skill B, then concept(A)
# precedes concept(B)). The lifted ones self-identify via this reason prefix.
# They are kept but flagged, because they are structurally derived rather than
# independently judged and a reader may want to hide them.
DERIVED_REASON_PREFIX = "Derived from skill prerequisite:"


# ─── Identity ─────────────────────────────────────────────────────────────────

def node_id(subject: str, grade: str, chapter: str, concept: str) -> str:
    """
    Stable, deterministic id for a concept node.

    Keyed on the full (subject, grade, chapter, concept) tuple rather than the
    concept name alone: 97 concept names are reused across chapters (e.g.
    "Law of Conservation of Mass" appears in two), so the name is not unique.
    Truncated to 12 hex chars — collisions are asserted against, not assumed.
    """
    raw = f"{subject}|{grade}|{chapter}|{concept}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def parse_grade(grade_folder: str) -> int | None:
    """Grade number from a "Grade N" folder name."""
    m = re.search(r"(\d+)", grade_folder)
    return int(m.group(1)) if m else None


def parse_chapter(chapter_folder: str) -> tuple[int | None, str]:
    """
    (order, display label) from a chapter folder name.

    Two conventions exist in the corpus: 210 folders are "Chapter06_Name_Here"
    and the 13 Maths Grade 1 folders are a bare "Chapter 1" with no title.
    Both are handled; anything else falls back to the raw folder name.
    """
    m = re.match(r"^Chapter\s*(\d+)(?:[_\s-]+(.*))?$", chapter_folder)
    if not m:
        return None, chapter_folder.replace("_", " ").strip()

    order = int(m.group(1))
    title = (m.group(2) or "").replace("_", " ").strip()
    return order, title or f"Chapter {order}"


# ─── Cell parsing ─────────────────────────────────────────────────────────────

def parse_prereq_cell(raw: str) -> list[dict]:
    """
    Normalise one prerequisite cell into a list of reference dicts.

    Cells hold a JSON array whose entries come in three shapes, all of which
    appear in the live corpus and all of which must be handled:

        "Concept name"                                   bare string (L1)
        {"item": ..., "reason": ...}                     object form (L1)
        {"chapter": ..., "concept"|"skill": ..., ...}    L2, plus "grade" at L3

    The object form of L1 is easy to miss — it accounts for ~1,765 references
    that a string-only parser drops silently. Returns [] for empty or
    unparseable cells; the caller counts those separately.
    """
    raw = (raw or "").strip()
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []

    if not isinstance(parsed, list):
        return []

    refs = []
    for entry in parsed:
        if isinstance(entry, str):
            if entry.strip():
                refs.append({"name": entry.strip(), "reason": None,
                             "grade": None, "chapter": None})
        elif isinstance(entry, dict):
            # "item" is the L1 object form; "concept"/"skill" are L2/L3.
            name = entry.get("concept") or entry.get("skill") or entry.get("item")
            if isinstance(name, str) and name.strip():
                refs.append({
                    "name": name.strip(),
                    "reason": entry.get("reason"),
                    "grade": entry.get("grade"),
                    "chapter": entry.get("chapter"),
                })
    return refs


def is_derived(reason: str | None) -> bool:
    return bool(reason) and reason.lstrip().startswith(DERIVED_REASON_PREFIX)


# ─── Load ─────────────────────────────────────────────────────────────────────

def discover_chapter_csvs(textbooks_root: str) -> list[tuple[str, str, str, str]]:
    """
    Every canonical chapter CSV as (subject, grade, chapter, path).

    Skips anything under a "run/" directory. Those hold per-stage snapshots —
    run/l3/confirmed.csv is byte-identical to the chapter's own file — so
    walking blindly would count each chapter up to three times.
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(textbooks_root):
        if "run" in dirpath.split(os.sep):
            dirnames[:] = []
            continue
        if CSV_NAME not in filenames:
            continue

        rel = os.path.relpath(dirpath, textbooks_root).split(os.sep)
        if len(rel) != 3:
            continue

        subject, grade, chapter = rel
        found.append((subject, grade, chapter, os.path.join(dirpath, CSV_NAME)))

    return sorted(found)


def load_rows(csvs: list[tuple[str, str, str, str]], warnings: list[str]) -> list[dict]:
    """
    Read every chapter CSV, tagging each row with the identity taken from its
    directory path.

    Identity comes from the path, never from the row's own board/subject/
    grade/chapter columns. Two Maths Grade 4 files still carry the chapter
    names they had before their folders were renamed, and trusting the column
    would orphan every inbound edge pointing at them.
    """
    rows = []
    for subject, grade, chapter, path in csvs:
        # Column/folder disagreements are a property of the file, not of each
        # row, so they are reported once per file rather than ~30 times.
        mismatches: set[str] = set()

        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                concept = (row.get("concept") or "").strip()
                skill = (row.get("skill") or "").strip()
                if not concept:
                    warnings.append(f"{subject}/{grade}/{chapter}: row with empty concept, skipped")
                    continue

                for column, folder_value in (("chapter", chapter), ("grade", grade)):
                    value = (row.get(column) or "").strip()
                    if value != folder_value:
                        mismatches.add(
                            f"{subject}/{grade}/{chapter}: {column} column says "
                            f"{value!r} — using folder name"
                        )

                row["_subject"] = subject
                row["_grade"] = grade
                row["_chapter"] = chapter
                row["_concept"] = concept
                row["_skill"] = skill
                rows.append(row)

        warnings.extend(sorted(mismatches))

    return rows


# ─── Build ────────────────────────────────────────────────────────────────────

def build_nodes(rows: list[dict]) -> tuple[dict, dict]:
    """
    Collapse (concept, skill) rows into concept nodes.

    Returns (nodes by id, concept-name index). The index maps
    (subject, grade, chapter) -> {concept name: id} and is what edge
    resolution looks references up in.
    """
    nodes: dict[str, dict] = {}
    index: dict[tuple[str, str, str], dict[str, str]] = defaultdict(dict)
    skills: dict[str, list[str]] = defaultdict(list)

    for row in rows:
        subject, grade, chapter = row["_subject"], row["_grade"], row["_chapter"]
        concept = row["_concept"]
        nid = node_id(subject, grade, chapter, concept)

        if nid not in nodes:
            order, label = parse_chapter(chapter)
            nodes[nid] = {
                "id": nid,
                "label": concept,
                "subject": subject,
                "grade": parse_grade(grade),
                "gradeLabel": grade,
                "chapter": chapter,
                "chapterLabel": label,
                "chapterOrder": order,
            }
            index[(subject, grade, chapter)][concept] = nid
        elif nodes[nid]["label"] != concept:
            raise RuntimeError(
                f"id collision on {nid}: {nodes[nid]['label']!r} vs {concept!r}"
            )

        if row["_skill"] and row["_skill"] not in skills[nid]:
            skills[nid].append(row["_skill"])

    for nid, node in nodes.items():
        node["skillCount"] = len(skills[nid])

    return nodes, {"index": dict(index), "skills": dict(skills)}


def resolve_ref(level: int, row: dict, ref: dict, index: dict) -> str | None:
    """
    Resolve one prerequisite reference to a node id, or None if it dangles.

    Each level scopes its lookup differently. L3 additionally falls back
    through the subject aliases — CBSE splits Science off as its own subject
    at Grade 6, so a Science chapter's cross-grade prerequisites legitimately
    point back into Environmental Science for Grades 3-5.
    """
    subject, grade, chapter = row["_subject"], row["_grade"], row["_chapter"]

    if level == 1:
        candidates = [(subject, grade, chapter)]
    elif level == 2:
        candidates = [(subject, grade, ref["chapter"])]
    else:
        subjects = (subject,) + _PREREQ_SUBJECT_ALIASES.get(subject, ())
        candidates = [(s, ref["grade"], ref["chapter"]) for s in subjects]

    for key in candidates:
        hit = index.get(key, {}).get(ref["name"])
        if hit:
            return hit
    return None


def build_edges(rows: list[dict], index: dict, stats: Counter) -> dict:
    """
    Resolve every concept-level prerequisite reference into a directed edge.

    Direction is source = prerequisite, target = dependent, so arrows point
    forward in learning order. This inverts the CSV, where a row lists what it
    depends on.

    Deduplicated: the same concept pair is often asserted by several rows (one
    per skill under the concept). The first occurrence wins for level, and any
    edge with at least one non-derived assertion counts as authored.
    """
    edges: dict[tuple[str, str], dict] = {}

    for row in rows:
        target = index[(row["_subject"], row["_grade"], row["_chapter"])][row["_concept"]]

        for level, concept_col, _ in PREREQ_COLUMNS:
            for ref in parse_prereq_cell(row.get(concept_col)):
                source = resolve_ref(level, row, ref, index)

                if source is None:
                    stats[f"unresolved_L{level}"] += 1
                    continue
                if source == target:
                    stats[f"selfloop_L{level}"] += 1
                    continue

                derived = is_derived(ref["reason"])
                key = (source, target)
                if key in edges:
                    edges[key]["d"] = edges[key]["d"] and derived
                else:
                    edges[key] = {"s": source, "t": target, "l": level, "d": derived}

    return edges


def build_details(rows: list[dict], nodes: dict, index: dict, skills: dict) -> dict:
    """
    Per-concept payload for the detail panel: the skills taught under the
    concept, and the rationale behind each inbound prerequisite.

    Reasons are kept here rather than in graph-core.json because they are long
    prose and account for most of the corpus's bytes — the graph renders
    without them, so they load only when a node is actually opened.
    """
    details = {
        nid: {"skills": skills.get(nid, []), "prereqs": []}
        for nid in nodes
    }
    seen: set[tuple[str, str, int]] = set()

    for row in rows:
        target = index[(row["_subject"], row["_grade"], row["_chapter"])][row["_concept"]]

        for level, concept_col, _ in PREREQ_COLUMNS:
            for ref in parse_prereq_cell(row.get(concept_col)):
                source = resolve_ref(level, row, ref, index)
                if source is None or source == target:
                    continue

                key = (source, target, level)
                if key in seen:
                    continue
                seen.add(key)

                details[target]["prereqs"].append({
                    "from": source,
                    "level": level,
                    "reason": ref["reason"],
                    "derived": is_derived(ref["reason"]),
                })

    return details


def find_cycles(nodes: dict, edges: dict) -> dict:
    """
    Locate cycles via Tarjan's strongly-connected components.

    A DFS back-edge count would be simpler but is not a stable metric: which
    edges get classified as "back" depends on the order nodes are visited, so
    the same graph reports different totals run to run. Every non-trivial SCC,
    by contrast, is an intrinsic property of the graph.

    This matters because the site offers a topological-depth layout, which is
    only defined on a DAG. Anything reported here has to be broken or bucketed
    before that layout can run.
    """
    adjacency: dict[str, list[str]] = defaultdict(list)
    for source, target in edges:
        adjacency[source].append(target)

    index_of: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    counter = 0
    components: list[list[str]] = []

    for root in nodes:
        if root in index_of:
            continue

        # Iterative Tarjan — the corpus is shallow, but recursion depth is a
        # function of the data and this removes the failure mode entirely.
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, child_pos = work[-1]

            if child_pos == 0:
                index_of[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)

            recursed = False
            children = adjacency[node]
            while child_pos < len(children):
                child = children[child_pos]
                child_pos += 1
                if child not in index_of:
                    work[-1] = (node, child_pos)
                    work.append((child, 0))
                    recursed = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], index_of[child])
            else:
                work[-1] = (node, child_pos)

            if recursed:
                continue

            work.pop()
            if low[node] == index_of[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1:
                    components.append(sorted(component))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])

    # A self-loop would also be a cycle, but build_edges drops those already.
    return {
        "cyclicComponents": len(components),
        "nodesInCycles": sum(len(c) for c in components),
        "largestCycle": max((len(c) for c in components), default=0),
    }


# ─── Output ───────────────────────────────────────────────────────────────────

def write_json(path: str, payload, pretty: bool) -> int:
    """Write JSON and return its size in bytes."""
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
        sort_keys=False,
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return len(text.encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--pretty", action="store_true", help="indent the JSON")
    parser.add_argument(
        "--check", action="store_true",
        help="exit non-zero if any reference fails to resolve",
    )
    args = parser.parse_args()

    textbooks_root = os.path.join(KB_ROOT, "textbooks", BOARD)
    if not os.path.isdir(textbooks_root):
        print(f"error: no textbooks at {textbooks_root}", file=sys.stderr)
        return 1

    warnings: list[str] = []
    stats: Counter = Counter()

    csvs = discover_chapter_csvs(textbooks_root)
    rows = load_rows(csvs, warnings)
    nodes, aux = build_nodes(rows)
    index, skills = aux["index"], aux["skills"]
    edges = build_edges(rows, index, stats)
    details = build_details(rows, nodes, index, skills)

    out_degree: Counter = Counter()
    in_degree: Counter = Counter()
    for edge in edges.values():
        out_degree[edge["s"]] += 1
        in_degree[edge["t"]] += 1
    for nid, node in nodes.items():
        node["inDeg"] = in_degree[nid]
        node["outDeg"] = out_degree[nid]

    node_list = sorted(nodes.values(), key=lambda n: n["id"])
    link_list = sorted(edges.values(), key=lambda e: (e["s"], e["t"]))

    by_level = Counter(e["l"] for e in link_list)
    cross_subject = sum(
        1 for e in link_list if nodes[e["s"]]["subject"] != nodes[e["t"]]["subject"]
    )
    cross_grade = sum(
        1 for e in link_list if nodes[e["s"]]["grade"] != nodes[e["t"]]["grade"]
    )
    isolated = sum(1 for n in node_list if n["inDeg"] == 0 and n["outDeg"] == 0)
    unresolved = sum(v for k, v in stats.items() if k.startswith("unresolved"))
    selfloops = sum(v for k, v in stats.items() if k.startswith("selfloop"))
    cycles = find_cycles(nodes, edges)

    chapters_per = Counter((s, g) for (s, g, _c) in index)
    nodes_per = Counter((n["subject"], n["gradeLabel"]) for n in node_list)
    inventory: dict[str, dict] = defaultdict(dict)
    for (subject, grade), chapter_count in chapters_per.items():
        inventory[subject][grade] = {
            "chapters": chapter_count,
            "concepts": nodes_per[(subject, grade)],
        }

    integrity = {
        "chapterFiles": len(csvs),
        "rows": len(rows),
        "nodes": len(node_list),
        "edges": len(link_list),
        "edgesByLevel": {f"L{k}": v for k, v in sorted(by_level.items())},
        "derivedEdges": sum(1 for e in link_list if e["d"]),
        "crossSubjectEdges": cross_subject,
        "crossGradeEdges": cross_grade,
        "isolatedNodes": isolated,
        "cycles": cycles,
        "unresolvedRefs": unresolved,
        "selfLoops": selfloops,
        "warnings": warnings,
    }

    os.makedirs(args.out, exist_ok=True)

    # graph-core.json carries no timestamp so that repeated exports of an
    # unchanged KB are byte-identical and produce no diff. Provenance that
    # does change every run lives in meta.json instead.
    core_bytes = write_json(
        os.path.join(args.out, "graph-core.json"),
        {"schemaVersion": SCHEMA_VERSION, "nodes": node_list, "links": link_list},
        args.pretty,
    )
    details_bytes = write_json(
        os.path.join(args.out, "concept-details.json"),
        {"schemaVersion": SCHEMA_VERSION, "details": details},
        args.pretty,
    )
    meta_bytes = write_json(
        os.path.join(args.out, "meta.json"),
        {
            "schemaVersion": SCHEMA_VERSION,
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "board": BOARD,
            "subjects": sorted(inventory),
            "inventory": {s: dict(sorted(g.items())) for s, g in sorted(inventory.items())},
            "integrity": integrity,
        },
        args.pretty,
    )

    print(f"{integrity['chapterFiles']} chapter files -> {integrity['rows']} rows")
    print(f"{integrity['nodes']} concept nodes, {integrity['edges']} directed edges")
    print(f"  by level: {integrity['edgesByLevel']}")
    print(f"  derived: {integrity['derivedEdges']}  "
          f"cross-subject: {cross_subject}  cross-grade: {cross_grade}")
    print(f"  isolated nodes: {isolated}  "
          f"cyclic components: {cycles['cyclicComponents']} "
          f"({cycles['nodesInCycles']} nodes, largest {cycles['largestCycle']})")
    print(f"  unresolved refs: {unresolved}  self-loops: {selfloops}")
    print(f"  warnings: {len(warnings)}")
    for warning in sorted(set(warnings))[:10]:
        print(f"    - {warning}")
    print(f"wrote {args.out}")
    print(f"  graph-core.json      {core_bytes / 1024:8.1f} KB")
    print(f"  concept-details.json {details_bytes / 1024:8.1f} KB")
    print(f"  meta.json            {meta_bytes / 1024:8.1f} KB")

    if args.check and unresolved:
        print(f"error: {unresolved} unresolved references", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
