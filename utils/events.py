"""
utils/events.py

Thread-safe event bus for streaming pipeline events to the frontend.
One queue per run. The orchestrator emits events; the API streams them via SSE.
"""

import queue
import threading
import uuid


class EventBus:
    def __init__(self):
        self._queues: dict[str, queue.Queue] = {}
        self._metadata: dict[str, dict]     = {}
        self._lock = threading.Lock()

    def create_run(self, board: str, subject: str, grade: str, chapter: str) -> str:
        """Create a new run, return its run_id."""
        run_id = str(uuid.uuid4())[:8]
        with self._lock:
            self._queues[run_id]  = queue.Queue()
            self._metadata[run_id] = {
                "run_id":  run_id,
                "board":   board,
                "subject": subject,
                "grade":   grade,
                "chapter": chapter,
                "status":  "running",
                "events":  [],
            }
        return run_id

    def emit(self, run_id: str, event_type: str, data: dict) -> None:
        """Emit an event for a run. Thread-safe."""
        event = {"type": event_type, "data": data}
        with self._lock:
            q    = self._queues.get(run_id)
            meta = self._metadata.get(run_id)
        if q:
            q.put(event)
        if meta is not None:
            meta["events"].append(event)
            if event_type == "pipeline_passed":
                meta["status"] = "passed"
            elif event_type == "pipeline_escalated":
                meta["status"] = "escalated"

    def get_queue(self, run_id: str) -> queue.Queue | None:
        with self._lock:
            return self._queues.get(run_id)

    def get_metadata(self, run_id: str) -> dict | None:
        with self._lock:
            return self._metadata.get(run_id)

    def list_runs(self) -> list[dict]:
        with self._lock:
            return [
                {k: v for k, v in m.items() if k != "events"}
                for m in self._metadata.values()
            ]


# Singleton — shared between orchestrator and API
bus = EventBus()
