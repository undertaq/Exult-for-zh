"""Local-only review actions with approval/state guards."""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..db import AssetStore
from ..models import JobState, ReviewDecision
from .writer import write_run_index


VALID_DECISIONS = {"APPROVE", "REJECT", "RETRY"}


@dataclass
class ReviewServer:
    store_path: Path
    report_root: Path

    def record_review(self, candidate_id: str, decision: ReviewDecision) -> None:
        normalized = decision.decision.upper().replace(" ", "_")
        if normalized == "NEEDS_RETRY":
            normalized = "RETRY"
        if normalized not in VALID_DECISIONS:
            raise ValueError(f"unsupported review decision {decision.decision!r}")
        if normalized in {"REJECT", "RETRY"} and not decision.notes.strip():
            raise ValueError("a rejection or retry decision requires a reason")
        store = AssetStore.open(Path(self.store_path))
        try:
            store.migrate()
            candidate = store.get_candidate(candidate_id)
            job = store.get_generation_job(candidate.job_id)
            if job.state != JobState.VALIDATED:
                raise ValueError(f"candidate {candidate_id!r} is not pending review: {job.state}")
            row = store._connection.execute(
                "SELECT passed FROM validation_results WHERE candidate_id = ?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise ValueError("candidate has no validation result")
            if normalized == "APPROVE" and not bool(row[0]):
                raise ValueError("failed candidates cannot be approved")
            with store._connection:
                store._connection.execute(
                    """INSERT INTO review_decisions(candidate_id, decision, reviewer, notes, created_at)
                    VALUES (?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(candidate_id) DO UPDATE SET decision=excluded.decision,
                    reviewer=excluded.reviewer, notes=excluded.notes, created_at=excluded.created_at""",
                    (candidate_id, normalized, decision.reviewer, decision.notes),
                )
                if normalized == "APPROVE":
                    cursor = store._connection.execute(
                        "UPDATE generation_jobs SET state = 'APPROVED', updated_at = datetime('now') WHERE job_id = ? AND state = 'VALIDATED'",
                        (candidate.job_id,),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError("candidate state changed while recording approval")
        finally:
            store.close()

    def serve_forever(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    index = Path(owner.report_root) / "index.html"
                    if not index.is_file():
                        write_run_index("review", Path(owner.report_root))
                    self._send_file(index)
                    return
                self.send_error(404)

            def do_POST(self):  # noqa: N802
                if urlparse(self.path).path != "/review":
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                values = parse_qs(self.rfile.read(length).decode("utf-8"))
                try:
                    owner.record_review(
                        values.get("candidate_id", [""])[0],
                        ReviewDecision(values.get("candidate_id", [""])[0], values.get("decision", [""])[0], values.get("reviewer", [""])[0], values.get("reason", [""])[0]),
                    )
                except (KeyError, ValueError) as exc:
                    self.send_error(400, str(exc))
                    return
                self.send_response(303)
                self.send_header("Location", "/")
                self.end_headers()

            def _send_file(self, path: Path):
                payload = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                return

        with ThreadingHTTPServer((host, port), Handler) as server:
            server.serve_forever()
