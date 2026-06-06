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
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from utils.events import bus
from orchestrator import run_pipeline, handle_reject, handle_re_extract

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
    no_sync:        bool       = True  # default True for safety in dev


class RejectRequest(BaseModel):
    board:   str
    subject: str
    grade:   str
    chapter: str
    reason:  str
    no_sync: bool = True


class ReExtractRequest(BaseModel):
    board:        str
    subject:      str
    grade:        str
    chapter:      str
    map_guidance: str
    no_sync:      bool = True


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


@app.post("/run")
async def start_run(req: RunRequest):
    """Start a pipeline run in a background thread. Returns run_id for SSE streaming."""
    run_id = bus.create_run(req.board, req.subject, req.grade, req.chapter)

    def emit(event_type, data):
        bus.emit(run_id, event_type, data)

    def run():
        try:
            run_pipeline(
                board=req.board,
                subject=req.subject,
                grade=req.grade,
                chapter=req.chapter,
                human_feedback=req.human_feedback,
                emit=emit,
            )
        except Exception as e:
            emit("error", {"message": str(e)})
        finally:
            bus.emit(run_id, "done", {})

    threading.Thread(target=run, daemon=True).start()
    return {"run_id": run_id}


@app.post("/reject")
async def reject(req: RejectRequest):
    """Reject a passed CSV and encode a new grade rule."""
    run_id = bus.create_run(req.board, req.subject, req.grade, req.chapter)

    def emit(event_type, data):
        bus.emit(run_id, event_type, data)

    def run():
        try:
            handle_reject(req.board, req.subject, req.grade, req.chapter, req.reason, emit=emit)
        except Exception as e:
            emit("error", {"message": str(e)})
        finally:
            bus.emit(run_id, "done", {})

    threading.Thread(target=run, daemon=True).start()
    return {"run_id": run_id}


@app.post("/re-extract")
async def re_extract(req: ReExtractRequest):
    """Re-run map extraction with guidance, then re-run full pipeline."""
    run_id = bus.create_run(req.board, req.subject, req.grade, req.chapter)

    def emit(event_type, data):
        bus.emit(run_id, event_type, data)

    def run():
        try:
            handle_re_extract(req.board, req.subject, req.grade, req.chapter, req.map_guidance, emit=emit)
        except Exception as e:
            emit("error", {"message": str(e)})
        finally:
            bus.emit(run_id, "done", {})

    threading.Thread(target=run, daemon=True).start()
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
