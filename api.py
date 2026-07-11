"""
api.py

FastAPI backend for the Q-Matrix Live Dashboard.
Runs the pipeline in a background thread and streams events via SSE.

Run API with:
    uvicorn api:app --reload --port 8000

Run dashboard (separate terminal):
    cd dashboard && npm run dev

Then open: http://localhost:3000
"""

import asyncio
import json
import os
import queue
import threading
import time
import traceback
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import re

from utils.events import bus
from orchestrator import (
    run_pipeline,
    handle_reject,
    handle_re_extract,
    run_prerequisite_only,
    _identifiers_from_rows,
)
from skills.csv_utils import validate_csv_schema, parse_csv
from skills import kb_access
from skills.model_stats import compute_model_performance

app = FastAPI(title="Q-Matrix Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (the dashboard HTML)
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ─── Request models ───────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    board:          str
    subject:        str
    grade:          str
    chapter:        str
    human_feedback: str | None = None
    models:         dict[str, str] | None = None  # agent key -> Gateway model id
    no_sync:        bool       = True  # default True for safety in dev


class RejectRequest(BaseModel):
    board:   str
    subject: str
    grade:   str
    chapter: str
    reason:  str
    models:  dict[str, str] | None = None
    no_sync: bool = True


class ReExtractRequest(BaseModel):
    board:        str
    subject:      str
    grade:        str
    chapter:      str
    map_guidance: str
    models:       dict[str, str] | None = None
    no_sync:      bool = True


class PrereqOnlyRequest(BaseModel):
    csv_text: str
    models:   dict[str, str] | None = None
    no_sync:  bool = True


# ─── Run helper ─────────────────────────────────────────────────────────────

def _spawn_run(run_id: str, target, **kwargs) -> None:
    """Run a pipeline entrypoint in a daemon thread.

    Streams lifecycle markers and full tracebacks to stdout so backend crashes are
    visible (the SSE ``error`` event alone is easy to miss in the terminal), and
    always emits a terminal ``done`` event so the dashboard — and any queued batch —
    advances regardless of outcome.
    """
    def emit(event_type, data):
        bus.emit(run_id, event_type, data)

    def run():
        print(f"[api] ▶ START run {run_id}")
        try:
            target(emit=emit, **kwargs)
        except Exception as e:
            print(f"[api] ✗ CRASH run {run_id}: {e}")
            traceback.print_exc()
            emit("error", {"message": str(e)})
        finally:
            print(f"[api] ■ DONE  run {run_id}")
            bus.emit(run_id, "done", {})

    threading.Thread(target=run, daemon=True).start()


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Legacy route — dashboard UI lives in the Next.js app at http://localhost:3000."""
    return HTMLResponse(
        "<h1>Q-Matrix API</h1>"
        "<p>Dashboard UI: <a href='http://localhost:3000'>http://localhost:3000</a> "
        "(run <code>cd dashboard && npm run dev</code>)</p>",
        status_code=200,
    )


_MODELS_CACHE_TTL = 60 * 60  # 1 hour
_models_cache: dict = {"fetched_at": 0.0, "data": None}


@app.get("/models")
async def list_models():
    """
    Proxy the Gateway's model catalog for the dashboard's per-agent model picker.
    Cached in-process for _MODELS_CACHE_TTL so every dashboard load doesn't refetch
    ~300 models from the Gateway. Filtered to language models only (excludes image/
    embedding/reranking/video models, which no agent here can use).
    """
    now = time.time()
    if _models_cache["data"] is not None and now - _models_cache["fetched_at"] < _MODELS_CACHE_TTL:
        return _models_cache["data"]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://ai-gateway.vercel.sh/v1/models",
                headers={"Authorization": f"Bearer {os.getenv('AI_GATEWAY_API_KEY')}"},
            )
            resp.raise_for_status()
            models = resp.json().get("data", [])
    except httpx.HTTPError as e:
        # Serve the last-known catalog rather than breaking the run-start form.
        if _models_cache["data"] is not None:
            print(f"[api] /models fetch failed ({e}); serving stale cache")
            return _models_cache["data"]
        raise HTTPException(status_code=502, detail=f"Failed to fetch model catalog: {e}")

    filtered = [
        {
            "id": m["id"],
            "name": m.get("name", m["id"]),
            "owned_by": m.get("owned_by", "unknown"),
            "context_window": m.get("context_window", 0),
            "tags": m.get("tags", []),
            "pricing": m.get("pricing", {}),
        }
        for m in models
        if m.get("type") == "language"
    ]
    data = {"models": filtered}
    _models_cache["data"] = data
    _models_cache["fetched_at"] = now
    return data


@app.post("/run")
async def start_run(req: RunRequest):
    """Start a pipeline run in a background thread. Returns run_id for SSE streaming."""
    run_id = bus.create_run(req.board, req.subject, req.grade, req.chapter)
    _spawn_run(
        run_id,
        run_pipeline,
        board=req.board,
        subject=req.subject,
        grade=req.grade,
        chapter=req.chapter,
        human_feedback=req.human_feedback,
        models=req.models,
    )
    return {"run_id": run_id}


@app.post("/reject")
async def reject(req: RejectRequest):
    """Reject a passed CSV and encode a new grade rule."""
    run_id = bus.create_run(req.board, req.subject, req.grade, req.chapter)
    _spawn_run(
        run_id,
        handle_reject,
        board=req.board,
        subject=req.subject,
        grade=req.grade,
        chapter=req.chapter,
        reason=req.reason,
        models=req.models,
    )
    return {"run_id": run_id}


@app.post("/run-prerequisite-only")
async def run_prerequisite_only_route(req: PrereqOnlyRequest):
    """
    Skip Stage 1: run only prerequisite mapping on a user-provided curriculum CSV.
    Identifiers (board/subject/grade/chapter) are derived from the CSV itself.
    """
    # Validate + derive identifiers synchronously so a bad CSV returns 400 immediately
    # (rather than failing silently inside the background thread).
    try:
        rows = validate_csv_schema(req.csv_text)
        board, subject, grade, chapter = _identifiers_from_rows(rows)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid curriculum CSV: {e}")

    run_id = bus.create_run(board, subject, grade, chapter)
    _spawn_run(run_id, run_prerequisite_only, csv_text=req.csv_text, models=req.models)
    return {"run_id": run_id}


@app.post("/re-extract")
async def re_extract(req: ReExtractRequest):
    """Re-run map extraction with guidance, then re-run full pipeline."""
    run_id = bus.create_run(req.board, req.subject, req.grade, req.chapter)
    _spawn_run(
        run_id,
        handle_re_extract,
        board=req.board,
        subject=req.subject,
        grade=req.grade,
        chapter=req.chapter,
        map_guidance=req.map_guidance,
        models=req.models,
    )
    return {"run_id": run_id}


@app.get("/stream/{run_id}")
async def stream(run_id: str):
    """SSE endpoint — streams pipeline events for a run."""
    q = bus.get_queue(run_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Run not found")

    async def generate():
        loop = asyncio.get_event_loop()
        while True:
            try:
                event = await loop.run_in_executor(
                    None, lambda: q.get(timeout=1)
                )
                yield f"data: {json.dumps(event)}\n\n"
                if event["type"] == "done":
                    break
            except queue.Empty:
                # Heartbeat to keep connection alive
                yield f"data: {json.dumps({'type': 'heartbeat', 'data': {}})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection":    "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _kb_textbooks_root() -> Path | None:
    kb_root = os.environ.get("KB_ROOT", "")
    if not kb_root:
        return None
    p = Path(kb_root) / "textbooks"
    return p if p.exists() else None


def _list_dirs(path: Path) -> list[str]:
    """Return sorted child directory names, or [] if path doesn't exist."""
    try:
        return sorted(d.name for d in path.iterdir() if d.is_dir())
    except (FileNotFoundError, PermissionError):
        return []


@app.get("/kb/boards")
async def kb_boards():
    """List board folders directly under KB_ROOT/textbooks/."""
    base = _kb_textbooks_root()
    return {"boards": _list_dirs(base) if base else []}


@app.get("/kb/subjects")
async def kb_subjects(board: str):
    """List subject folders under KB_ROOT/textbooks/{board}/."""
    base = _kb_textbooks_root()
    return {"subjects": _list_dirs(base / board) if base else []}


@app.get("/kb/grades")
async def kb_grades(board: str, subject: str):
    """List grade folders under KB_ROOT/textbooks/{board}/{subject}/."""
    base = _kb_textbooks_root()
    return {"grades": _list_dirs(base / board / subject) if base else []}


@app.get("/kb/chapters")
async def kb_chapters(board: str, subject: str, grade: str):
    """List chapter folders under KB_ROOT/textbooks/{board}/{subject}/{grade}/."""
    base = _kb_textbooks_root()
    return {"chapters": _list_dirs(base / board / subject / grade) if base else []}


# ─── KB Analytics ───────────────────────────────────────────────────────────
#
# Read-only reporting over what has actually been run through the pipeline,
# derived from the KB filesystem (there is no manifest). Status per chapter:
#   confirmed  → confirmed_curriculum.csv exists (latest state, supersedes any
#                earlier escalation). has_prereqs distinguishes whether L1
#                prerequisites were actually mapped or the phase was skipped.
#   escalated  → an escalation folder with a report.md exists.
#   mapped     → only a concept-skill-map.json exists (reached extraction).
# Chapters with none of these (an ingested PDF that was never run) are excluded.


def _analytics_key(board: str, subject: str, grade: str, chapter: str) -> tuple:
    """Normalized (board, subject, grade, chapter) key for robust matching across
    inconsistent spacing / underscore spelling between textbook and escalation names."""
    def n(s: str) -> str:
        return re.sub(r"[\s_]+", "", (s or "")).lower()
    return (n(board), n(subject), n(grade), n(chapter))


@app.get("/kb/analytics")
async def kb_analytics():
    """
    Aggregate pipeline history for every chapter that has been run, grouped by
    board → subject → grade. Reads the KB filesystem live on each request.
    """
    try:
        chapters = kb_access.list_textbook_chapters()
        escalations = kb_access.list_escalations()
    except Exception:
        # No KB / unreadable — return an empty but well-formed payload.
        return {
            "summary": {
                "total_chapters": 0, "confirmed": 0, "confirmed_no_prereqs": 0,
                "escalated": 0, "mapped_only": 0,
            },
            "groups": [],
        }

    # Index escalations by normalized key (a chapter may have several across dates).
    esc_by_key: dict[tuple, list[dict]] = {}
    for esc in escalations:
        key = _analytics_key(esc["board"], esc["subject"], esc["grade"], esc["chapter"])
        esc_by_key.setdefault(key, []).append(esc)

    matched_keys: set[tuple] = set()
    entries: list[dict] = []

    for ch in chapters:
        key = _analytics_key(ch["board"], ch["subject"], ch["grade"], ch["chapter"])
        chapter_escs = esc_by_key.get(key, [])
        if chapter_escs:
            matched_keys.add(key)

        # Skip ingested-but-never-run chapters (a PDF with no CSM/confirmed/escalation).
        if not (ch["has_confirmed"] or ch["has_csm"] or chapter_escs):
            continue

        entries.append(_build_chapter_entry(
            ch["board"], ch["subject"], ch["grade"], ch["chapter"],
            has_confirmed=ch["has_confirmed"], has_csm=ch["has_csm"],
            escalations=chapter_escs,
        ))

    # Escalations whose chapter has no textbook folder (spelling drift) — include them.
    for key, chapter_escs in esc_by_key.items():
        if key in matched_keys:
            continue
        first = chapter_escs[0]
        entries.append(_build_chapter_entry(
            first["board"], first["subject"], first["grade"], first["chapter"],
            has_confirmed=False, has_csm=False, escalations=chapter_escs,
        ))

    # Group by (board, subject, grade).
    groups_map: dict[tuple, dict] = {}
    for e in entries:
        gkey = (e["board"], e["subject"], e["grade"])
        group = groups_map.setdefault(gkey, {
            "board": e["board"], "subject": e["subject"], "grade": e["grade"],
            "chapters": [],
        })
        group["chapters"].append({
            "chapter": e["chapter"],
            "status": e["status"],
            "has_prereqs": e["has_prereqs"],
            "escalation_count": e["escalation_count"],
            "latest_failed_check": e["latest_failed_check"],
            "attempts": e["attempts"],
        })

    groups = sorted(groups_map.values(), key=lambda g: (g["board"], g["subject"], g["grade"]))
    for g in groups:
        g["chapters"].sort(key=lambda c: c["chapter"])

    summary = {
        "total_chapters": len(entries),
        "confirmed": sum(1 for e in entries if e["status"] == "confirmed" and e["has_prereqs"]),
        "confirmed_no_prereqs": sum(1 for e in entries if e["status"] == "confirmed" and not e["has_prereqs"]),
        "escalated": sum(1 for e in entries if e["status"] == "escalated"),
        "mapped_only": sum(1 for e in entries if e["status"] == "mapped"),
    }

    return {"summary": summary, "groups": groups}


def _build_chapter_entry(
    board: str, subject: str, grade: str, chapter: str,
    *, has_confirmed: bool, has_csm: bool, escalations: list[dict],
) -> dict:
    """Classify one chapter into a status + roll up its escalation metadata."""
    # Latest escalation wins for the displayed failure metadata.
    latest = None
    if escalations:
        latest = max(escalations, key=lambda e: e.get("date") or "")

    if has_confirmed:
        status = "confirmed"
        has_prereqs = kb_access.confirmed_csv_has_prereqs(board, subject, grade, chapter)
    elif escalations:
        status = "escalated"
        has_prereqs = False
    else:
        status = "mapped"
        has_prereqs = False

    return {
        "board": board, "subject": subject, "grade": grade, "chapter": chapter,
        "status": status,
        "has_prereqs": has_prereqs,
        "escalation_count": len(escalations),
        "latest_failed_check": (latest or {}).get("failed_check") or None,
        "attempts": (latest or {}).get("total_attempts"),
    }


@app.get("/kb/analytics/models")
async def model_performance():
    """
    Model Performance rollup for the analytics dashboard: per-(agent, model) pass/
    fail counts, cost, and token/row averages across every run in the KB (both the
    latest run/ snapshot per chapter and every historical escalations/ snapshot,
    deduped by run_id — see kb_access.list_all_run_records).
    """
    try:
        records = kb_access.list_all_run_records()
    except Exception:
        records = []
    return compute_model_performance(records)


@app.get("/kb/analytics/chapter")
async def kb_analytics_chapter(board: str, subject: str, grade: str, chapter: str):
    """
    Per-chapter drill-down: the confirmed CSV (parsed rows + headers) if the chapter
    succeeded, plus every matching escalation's parsed report.md for failure detail.
    """
    detail: dict = {
        "board": board, "subject": subject, "grade": grade, "chapter": chapter,
        "confirmed": None,
        "escalations": [],
        "concept_skill_map": None,
    }

    # Concept-skill-map (the extraction artifact) — present for every chapter that
    # reached extraction, including "mapped only" chapters with no final outcome.
    try:
        if kb_access.concept_skill_map_exists(board, subject, grade, chapter):
            csm = kb_access.load_concept_skill_map(board, subject, grade, chapter)
            detail["concept_skill_map"] = {
                "concepts": csm.get("concepts", []),
                "skills": csm.get("skills", []),
            }
    except (ValueError, FileNotFoundError):
        pass

    # Confirmed CSV, if present.
    try:
        if kb_access.confirmed_csv_exists(board, subject, grade, chapter):
            csv_text = kb_access.load_confirmed_csv(board, subject, grade, chapter)
            rows, headers = [], []
            try:
                rows = parse_csv(csv_text)
                headers = list(rows[0].keys()) if rows else []
            except ValueError:
                pass
            detail["confirmed"] = {
                "csv_text": csv_text,
                "headers": headers,
                "rows": rows,
                "has_prereqs": kb_access.confirmed_csv_has_prereqs(board, subject, grade, chapter),
            }
    except Exception:
        pass

    # All escalations matching this chapter (normalized), newest first.
    try:
        target = _analytics_key(board, subject, grade, chapter)
        matches = [
            e for e in kb_access.list_escalations()
            if _analytics_key(e["board"], e["subject"], e["grade"], e["chapter"]) == target
        ]
        matches.sort(key=lambda e: e.get("date") or "", reverse=True)
        for e in matches:
            try:
                detail["escalations"].append(kb_access.load_escalation_report(e["folder"]))
            except FileNotFoundError:
                continue
    except Exception:
        pass

    # Structured run record (latest run — present for both passing and escalated
    # chapters once they have been run under the run-record era; None for legacy
    # chapters, in which case the frontend falls back to confirmed/escalations).
    try:
        detail["run"] = kb_access.load_run_record(board, subject, grade, chapter)
    except ValueError:
        detail["run"] = None

    if (
        detail["confirmed"] is None
        and not detail["escalations"]
        and detail["concept_skill_map"] is None
        and detail.get("run") is None
    ):
        raise HTTPException(status_code=404, detail="No analytics found for chapter")

    return detail


@app.get("/kb/analytics/chapter/run/file")
async def kb_analytics_chapter_run_file(
    board: str, subject: str, grade: str, chapter: str, filename: str
):
    """
    Serve one sibling artifact (a CSV / prompt / report) from a chapter's run/ folder.

    ``filename`` must be a bare name taken from run.json's ``*_file`` pointers; it is
    validated against a strict whitelist in kb_access.load_run_artifact before it ever
    touches the filesystem (path-traversal guard). Returns the raw text plus a parsed
    preview, mirroring how the confirmed CSV is returned by /kb/analytics/chapter.
    """
    try:
        csv_text = kb_access.load_run_artifact(board, subject, grade, chapter, filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run artifact not found: {filename}")

    rows, headers = [], []
    if filename.endswith(".csv"):
        try:
            rows = parse_csv(csv_text)
            headers = list(rows[0].keys()) if rows else []
        except ValueError:
            pass

    return {"filename": filename, "csv_text": csv_text, "headers": headers, "rows": rows}


@app.get("/runs")
async def list_runs():
    """List all pipeline runs with their status."""
    return bus.list_runs()


@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Get full details of a specific run including all events."""
    meta = bus.get_metadata(run_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return meta
