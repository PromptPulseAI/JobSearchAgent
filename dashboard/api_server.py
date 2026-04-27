#!/usr/bin/env python3
"""
Dashboard API server — serves data files and handles Gate 1 approvals.
Runs on http://localhost:8000

Usage: python dashboard/api_server.py [--data-dir data]

Endpoints:
  GET  /api/tracker      → data/application_tracker.json
  GET  /api/run-history  → data/run_history.json
  GET  /api/pending      → data/pending_approval.json
  POST /api/approve      → approve jobs from pending_approval.json
  GET  /api/summary      → data/master_summary.md (as text)
  POST /api/status       → update a job's status (body: {job_id, status})
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

DATA_DIR = Path("data")


def load_json(filename: str) -> dict | list:
    path = DATA_DIR / filename
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(filename: str, data: dict | list) -> None:
    path = DATA_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


class APIHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress access log noise

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text: str, status=200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status, message):
        self.send_json({"error": message}, status=status)

    def read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")
        if path == "/api/tracker":
            self.send_json(load_json("application_tracker.json"))
        elif path == "/api/run-history":
            data = load_json("run_history.json")
            self.send_json(data if isinstance(data, list) else [])
        elif path == "/api/pending":
            self.send_json(load_json("pending_approval.json"))
        elif path == "/api/summary":
            md_path = DATA_DIR / "master_summary.md"
            self.send_text(md_path.read_text(encoding="utf-8") if md_path.exists() else "")
        else:
            self.send_error_json(404, f"Unknown endpoint: {path}")

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        body = self.read_body()

        if path == "/api/approve":
            approved_ids = body.get("approved_ids", [])
            pending = load_json("pending_approval.json")
            if isinstance(pending, dict):
                pending["status"] = "approved"
                pending["approved_ids"] = approved_ids
                save_json("pending_approval.json", pending)
            self.send_json({"ok": True, "approved_count": len(approved_ids)})

        elif path == "/api/status":
            job_id = body.get("job_id", "")
            new_status = body.get("status", "")
            if not job_id or not new_status:
                return self.send_error_json(400, "job_id and status required")
            tracker = load_json("application_tracker.json")
            if not isinstance(tracker, dict):
                return self.send_error_json(500, "tracker not loaded")
            jobs = tracker.get("jobs", [])
            updated = False
            for job in jobs:
                if job.get("job_id") == job_id:
                    job["status"] = new_status
                    import datetime
                    job["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    job["user_override"] = True
                    updated = True
                    break
            if not updated:
                return self.send_error_json(404, f"Job {job_id} not found")
            save_json("application_tracker.json", tracker)
            self.send_json({"ok": True, "job_id": job_id, "status": new_status})

        else:
            self.send_error_json(404, f"Unknown endpoint: {path}")


def main():
    global DATA_DIR
    parser = argparse.ArgumentParser(description="JobSearchAgent Dashboard API")
    parser.add_argument("--data-dir", default="data", help="Path to data directory")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    args = parser.parse_args()
    DATA_DIR = Path(args.data_dir)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    server = HTTPServer(("localhost", args.port), APIHandler)
    print(f"Dashboard API running at http://localhost:{args.port}")
    print(f"Data dir: {DATA_DIR.absolute()}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
