#!/usr/bin/env python3
"""Write a realistic sample status.json (timestamps relative to now).

Used for screenshots and for rendering tests of the Webmin module.
    python3 tests/make_sample.py tests/fixtures/sample-status.json
"""
import datetime as dt
import json
import sys

now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def ago(**kw):
    return (now - dt.timedelta(**kw)).isoformat().replace("+00:00", "Z")


def runner(name, status, busy, labels, job=None, os_="Linux"):
    return {"id": abs(hash(name)) % 10**6, "name": name, "os": os_, "status": status, "busy": busy,
            "labels": ["self-hosted", os_, "X64" if os_ == "Linux" else "ARM64"] + labels, "job": job}


def job(name, wf, branch, labels, created, started=None, status="in_progress", repo="acme/game", runner=None):
    return {"id": abs(hash(name + wf)) % 10**8, "name": name, "status": status, "workflow": wf,
            "branch": branch, "event": "push", "labels": ["self-hosted"] + labels, "runner_name": runner,
            "created_at": created, "started_at": started,
            "url": f"https://github.com/{repo}/actions/runs/1/job/2", "run_url": f"https://github.com/{repo}/actions/runs/1"}


a_job = job("android-instrumented", "CI", "main", ["android"], ago(minutes=7), ago(minutes=6), runner="server-game-android")
b_job = job("gates", "CI", "feature/login", ["android"], ago(minutes=21), ago(minutes=19), repo="acme/health-app", runner="server-health-android")
scopes = [
    {"type": "repo", "name": "acme/game", "url": "https://github.com/acme/game", "error": None,
     "runners": [runner("server-game", "online", False, ["server", "general"]),
                 runner("server-game-android", "online", True, ["server", "android"], a_job),
                 runner("server-game-android-2", "online", False, ["server", "android"]),
                 runner("mac-game", "online", False, ["apple"], os_="macOS")],
     "running": [a_job],
     "queued": [job("export-android", "Preview", "feature/maps", ["android"], ago(minutes=2), status="queued")]},
    {"type": "repo", "name": "acme/health-app", "url": "https://github.com/acme/health-app", "error": None,
     "runners": [runner("server-health", "online", False, ["server", "general"]),
                 runner("server-health-android", "online", True, ["server", "android"], b_job),
                 runner("mac-health", "offline", False, ["apple"], os_="macOS")],
     "running": [b_job],
     "queued": [job("ios-ui-tests", "CI", "feature/login", ["apple"], ago(minutes=14), status="queued", repo="acme/health-app")]},
    {"type": "repo", "name": "acme/website", "url": "https://github.com/acme/website", "error": None,
     "runners": [runner("server-website", "online", False, ["server", "general"])],
     "running": [], "queued": []},
]
runners = [r for s in scopes for r in s["runners"]]
status = {
    "schema": 1, "collector": "0.1.0", "generated_at": ago(seconds=12), "interval": 60, "duration_ms": 840,
    "summary": {"runners": len(runners), "online": sum(r["status"] == "online" for r in runners),
                "busy": sum(r["busy"] for r in runners), "offline": sum(r["status"] != "online" for r in runners),
                "idle": sum(r["status"] == "online" and not r["busy"] for r in runners),
                "queued_jobs": 2, "running_jobs": 2},
    "scopes": scopes,
    "containers": [
        {"id": "1", "name": "devstack-runner-game-1", "image": "runner:2.338", "state": "running", "status": "Up 2 days",
         "compose_service": "runner-game", "cpu_percent": 0.4, "mem_bytes": 310 * 2**20, "mem_limit": 6 * 2**30},
        {"id": "2", "name": "devstack-runner-game-android-1", "image": "android-runner:1", "state": "running",
         "status": "Up 2 days", "compose_service": "runner-game-android", "cpu_percent": 382.6,
         "mem_bytes": int(4.8 * 2**30), "mem_limit": 10 * 2**30},
        {"id": "3", "name": "devstack-runner-health-android-1", "image": "android-runner:1", "state": "running",
         "status": "Up 2 days", "compose_service": "runner-health-android", "cpu_percent": 511.0,
         "mem_bytes": int(8.9 * 2**30), "mem_limit": 10 * 2**30},
        {"id": "4", "name": "devstack-runner-website-1", "image": "runner:2.338", "state": "exited",
         "status": "Exited (0) 3 hours ago", "compose_service": "runner-website", "cpu_percent": None,
         "mem_bytes": None, "mem_limit": None},
    ],
    "host": {"hostname": "buildbox", "load": [9.42, 7.10, 5.33], "cpus": 16, "mem_total": 31 * 2**30,
             "mem_available": 12 * 2**30,
             "disks": [{"label": "root", "path": "/host/root", "total": 915 * 10**9, "free": 498 * 10**9,
                        "used": 417 * 10**9, "error": None},
                       {"label": "ci-store", "path": "/host/ci-store", "total": 200 * 10**9, "free": 21 * 10**9,
                        "used": 179 * 10**9, "error": None}]},
    "rate_limit": {"limit": 5000, "remaining": 4712, "reset": 0, "used": 288},
    "errors": [],
}
with open(sys.argv[1] if len(sys.argv) > 1 else "/dev/stdout", "w", encoding="utf-8") as fh:
    json.dump(status, fh, indent=1)
