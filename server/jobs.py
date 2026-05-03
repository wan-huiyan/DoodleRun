"""In-memory background-job store for long-running route generation.

Mobile browsers (iOS Safari especially) kill `fetch()` requests as soon as
the user backgrounds the tab — so the long-running fidelity-search path
(15+ OSRM round-trips, easily 30–60 s on the public demo server) can't
live behind a synchronous HTTP request and reliably reach the user.

This module gives the API a fire-and-forget pattern:

  POST /jobs           → returns {id, status: "pending"}
  GET  /jobs/{id}      → returns {status, progress?, result?, error?}

Jobs run in a thread pool. Each job is identified by a UUID and self-
expires after `JOB_TTL_S` seconds — long enough for the user to come
back to the page, short enough not to leak memory if they don't.

Designed to be a no-op in the test client: the executor is `submit`d
synchronously when `JOBS_INLINE=1` is set in env (the API tests run
this way so no extra threads spin up during pytest)."""

from __future__ import annotations

import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


JOB_TTL_S = 30 * 60   # 30 minutes — plenty of time for a user to come back


@dataclass
class Job:
    id: str
    status: str = "pending"          # pending | running | done | error
    progress: float = 0.0            # 0..1; advisory only — many backends won't report
    progress_msg: str = ""
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None


class JobStore:
    """Thread-safe job registry. Holds the future + a Job dataclass that
    callers can read without touching the future directly."""

    def __init__(self, max_workers: int = 4):
        self._jobs: Dict[str, Job] = {}
        self._futures: Dict[str, Future] = {}
        self._lock = threading.Lock()
        # 4 workers ≈ 4 concurrent /generate searches. The OSRM public demo
        # is rate-limited; we serialize calls *within* a single search via
        # the 1.1 s delay in osrm_client, so 4 parallel searches share that
        # budget but don't compound — each user gets their full grid.
        self._executor = ThreadPoolExecutor(max_workers=max_workers,
                                            thread_name_prefix="dr-job")
        self._inline = os.environ.get("JOBS_INLINE", "0") == "1"

    def submit(self, fn: Callable[[Job], dict]) -> Job:
        """Run `fn(job)` in a worker thread. `fn` is responsible for
        catching its own exceptions if it wants to convert them into a
        partial result; uncaught ones are stashed onto the Job."""
        job_id = uuid.uuid4().hex[:12]
        job = Job(id=job_id)
        with self._lock:
            self._jobs[job_id] = job

        def runner():
            job.status = "running"
            try:
                result = fn(job)
                job.result = result
                job.status = "done"
                job.progress = 1.0
            except Exception as e:
                # Surface the full message so the SPA can show it.
                # Don't include the traceback — the server log has it.
                job.error = f"{e.__class__.__name__}: {e}"
                job.status = "error"
            finally:
                job.finished_at = time.time()

        if self._inline:
            runner()
        else:
            fut = self._executor.submit(runner)
            with self._lock:
                self._futures[job_id] = fut
        return job

    def get(self, job_id: str) -> Optional[Job]:
        self._reap()
        with self._lock:
            return self._jobs.get(job_id)

    def _reap(self) -> None:
        now = time.time()
        with self._lock:
            stale = [
                jid for jid, j in self._jobs.items()
                if j.finished_at is not None and now - j.finished_at > JOB_TTL_S
            ]
            for jid in stale:
                self._jobs.pop(jid, None)
                self._futures.pop(jid, None)
