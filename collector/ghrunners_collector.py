#!/usr/bin/env python3
"""Collect GitHub Actions self-hosted runner status into one JSON file.

The collector polls the GitHub REST API for self-hosted runners and pending
jobs of the configured repositories and organizations, and optionally reads
container stats from a Docker Engine API and free space of local paths. The
result is written atomically to a JSON file that the Webmin module (or anything
else) can render.

Only the Python standard library is used. Configuration comes from environment
variables, optionally overridden by command-line flags; see README.md.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import datetime as dt
import http.client
import json
import logging
import os
import re
import signal
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

__version__ = "0.1.2"
SCHEMA_VERSION = 1
USER_AGENT = f"ghrunners-collector/{__version__}"

log = logging.getLogger("ghrunners")


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

def _split(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r"[,\s]+", value) if part.strip()]


def _read_token(args: argparse.Namespace) -> str:
    if args.token_file:
        with open(args.token_file, encoding="utf-8") as fh:
            return fh.read().strip()
    return (args.token or "").strip()


def build_parser() -> argparse.ArgumentParser:
    env = os.environ.get
    p = argparse.ArgumentParser(
        description="Collect GitHub Actions self-hosted runner status into a JSON file.")
    p.add_argument("--repos", default=env("GHR_REPOS", ""),
                   help="Comma/space separated owner/repo list (env GHR_REPOS)")
    p.add_argument("--orgs", default=env("GHR_ORGS", ""),
                   help="Comma/space separated organizations with org-level runners (env GHR_ORGS)")
    p.add_argument("--token", default=env("GHR_GITHUB_TOKEN") or env("GITHUB_TOKEN", ""),
                   help="GitHub token (env GHR_GITHUB_TOKEN or GITHUB_TOKEN)")
    p.add_argument("--token-file", default=env("GHR_GITHUB_TOKEN_FILE", ""),
                   help="Read the token from this file, e.g. a Docker secret (env GHR_GITHUB_TOKEN_FILE)")
    p.add_argument("--api-url", default=env("GHR_GITHUB_API_URL", "https://api.github.com"),
                   help="GitHub API base URL, change for GitHub Enterprise Server (env GHR_GITHUB_API_URL)")
    p.add_argument("--output", default=env("GHR_OUTPUT", "/var/lib/ghrunners/status.json"),
                   help="Where to write the status JSON (env GHR_OUTPUT)")
    p.add_argument("--interval", type=int, default=int(env("GHR_INTERVAL", "60")),
                   help="Seconds between polls (env GHR_INTERVAL, default 60)")
    p.add_argument("--docker-host", default=env("GHR_DOCKER_HOST", ""),
                   help="Docker Engine API: unix:///var/run/docker.sock or tcp://host:2375; "
                        "empty disables container stats (env GHR_DOCKER_HOST)")
    p.add_argument("--docker-filter", default=env("GHR_DOCKER_FILTER", ""),
                   help="Regex on container names to include; empty includes all (env GHR_DOCKER_FILTER)")
    p.add_argument("--disks", default=env("GHR_DISKS", ""),
                   help="Comma separated label=path pairs to report free space for (env GHR_DISKS)")
    p.add_argument("--proc", default=env("GHR_PROC", "/proc"),
                   help="procfs to read host load and memory from (env GHR_PROC)")
    p.add_argument("--once", action="store_true",
                   help="Collect once and exit (for cron or testing)")
    p.add_argument("--log-level", default=env("GHR_LOG_LEVEL", "INFO"))
    p.add_argument("--version", action="version", version=__version__)
    return p


# --------------------------------------------------------------------------
# GitHub API
# --------------------------------------------------------------------------

class GitHubError(Exception):
    pass


class GitHub:
    """Tiny GitHub REST client with ETag caching.

    Conditional requests that return 304 do not count against the rate limit,
    so an idle fleet costs almost nothing to poll.
    """

    def __init__(self, token: str, api_url: str, timeout: float = 20.0):
        self.token = token
        if urllib.parse.urlsplit(api_url).scheme not in ("https", "http"):
            raise ValueError(f"GitHub API URL must be http(s): {api_url}")
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self._cache: dict[str, tuple[str, object]] = {}
        self.rate_limit: dict[str, int] = {}

    def get(self, path: str, params: dict | None = None) -> object:
        url = self.api_url + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        cached = self._cache.get(url)
        if cached:
            headers["If-None-Match"] = cached[0]
        # The scheme of api_url is checked in __init__.
        req = urllib.request.Request(url, headers=headers)  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                self._note_rate(resp.headers)
                body = json.load(resp)
                etag = resp.headers.get("ETag")
                if etag:
                    self._cache[url] = (etag, body)
                return body
        except urllib.error.HTTPError as err:
            self._note_rate(err.headers)
            if err.code == 304 and cached:
                return cached[1]
            detail = ""
            with contextlib.suppress(Exception):  # best effort error text
                detail = json.load(err).get("message", "")
            raise GitHubError(f"GET {path}: HTTP {err.code} {detail}".strip()) from None
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise GitHubError(f"GET {path}: {err}") from None

    def _note_rate(self, headers) -> None:
        if not headers:
            return
        for key in ("limit", "remaining", "reset", "used"):
            val = headers.get(f"X-RateLimit-{key.capitalize()}")
            if val is not None and val.isdigit():
                self.rate_limit[key] = int(val)


def _runner_record(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "name": r.get("name"),
        "os": r.get("os"),
        "status": r.get("status"),          # online | offline
        "busy": bool(r.get("busy")),
        "labels": [lbl.get("name") for lbl in r.get("labels", [])],
        "job": None,
    }


def _job_record(job: dict, run: dict) -> dict:
    return {
        "id": job.get("id"),
        "name": job.get("name"),
        "status": job.get("status"),
        "workflow": run.get("name") or job.get("workflow_name"),
        "branch": run.get("head_branch") or job.get("head_branch"),
        "event": run.get("event"),
        "labels": job.get("labels", []),
        "runner_name": job.get("runner_name"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "url": job.get("html_url"),
        "run_url": run.get("html_url"),
    }


def collect_repo(gh: GitHub, repo: str) -> dict:
    scope = {"type": "repo", "name": repo, "url": f"https://github.com/{repo}",
             "runners": [], "queued": [], "running": [], "error": None}
    base = f"/repos/{repo}/actions"
    try:
        data = gh.get(f"{base}/runners", {"per_page": 100})
        scope["runners"] = [_runner_record(r) for r in data.get("runners", [])]

        runs: dict[int, dict] = {}
        for status in ("queued", "in_progress"):
            for run in gh.get(f"{base}/runs", {"status": status, "per_page": 50}).get("workflow_runs", []):
                runs[run["id"]] = run
        by_runner = {r["name"]: r for r in scope["runners"]}
        for run in runs.values():
            jobs = gh.get(f"{base}/runs/{run['id']}/jobs", {"filter": "latest", "per_page": 100})
            for job in jobs.get("jobs", []):
                rec = _job_record(job, run)
                if job.get("status") in ("queued", "waiting", "pending", "requested"):
                    scope["queued"].append(rec)
                elif job.get("status") == "in_progress":
                    scope["running"].append(rec)
                    runner = by_runner.get(job.get("runner_name") or "")
                    if runner is not None:
                        runner["job"] = rec
    except GitHubError as err:
        scope["error"] = str(err)
        log.warning("%s: %s", repo, err)
    return scope


def collect_org(gh: GitHub, org: str) -> dict:
    scope = {"type": "org", "name": org, "url": f"https://github.com/{org}",
             "runners": [], "queued": [], "running": [], "error": None}
    try:
        data = gh.get(f"/orgs/{org}/actions/runners", {"per_page": 100})
        scope["runners"] = [_runner_record(r) for r in data.get("runners", [])]
    except GitHubError as err:
        scope["error"] = str(err)
        log.warning("%s: %s", org, err)
    return scope


# --------------------------------------------------------------------------
# Docker Engine API (read-only)
# --------------------------------------------------------------------------

class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._path)
        self.sock = sock


class Docker:
    def __init__(self, host: str, timeout: float = 10.0):
        self.host = host
        self.timeout = timeout
        self._prev: dict[str, tuple[int, int]] = {}

    def _conn(self) -> http.client.HTTPConnection:
        if self.host.startswith("unix://"):
            return _UnixHTTPConnection(self.host[len("unix://"):], self.timeout)
        parsed = urllib.parse.urlparse(self.host.replace("tcp://", "http://", 1))
        return http.client.HTTPConnection(parsed.hostname, parsed.port or 2375, timeout=self.timeout)

    def get(self, path: str) -> object:
        conn = self._conn()
        try:
            conn.request("GET", path, headers={"User-Agent": USER_AGENT})
            resp = conn.getresponse()
            body = resp.read()
            if resp.status != 200:
                raise OSError(f"docker GET {path}: HTTP {resp.status}")
            return json.loads(body)
        finally:
            conn.close()

    def containers(self, name_filter: str) -> list[dict]:
        rx = re.compile(name_filter) if name_filter else None
        out = []
        for c in self.get("/containers/json?all=1"):
            name = (c.get("Names") or ["?"])[0].lstrip("/")
            if rx and not rx.search(name):
                continue
            out.append({
                "id": c.get("Id", "")[:12],
                "name": name,
                "image": c.get("Image"),
                "state": c.get("State"),
                "status": c.get("Status"),
                "compose_service": (c.get("Labels") or {}).get("com.docker.compose.service"),
                "cpu_percent": None,
                "mem_bytes": None,
                "mem_limit": None,
            })
        running = [c for c in out if c["state"] == "running"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for c, stats in zip(running, pool.map(self._stats, running)):
                if stats:
                    c.update(stats)
        return out

    def _stats(self, c: dict) -> dict | None:
        try:
            s = self.get(f"/containers/{c['id']}/stats?stream=false&one-shot=true")
        except OSError as err:
            log.debug("stats %s: %s", c["name"], err)
            return None
        cpu = s.get("cpu_stats", {})
        total = cpu.get("cpu_usage", {}).get("total_usage", 0)
        system = cpu.get("system_cpu_usage", 0)
        ncpu = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage") or []) or 1
        pct = None
        prev = self._prev.get(c["id"])
        if prev and system > prev[1]:
            pct = round((total - prev[0]) / (system - prev[1]) * ncpu * 100.0, 1)
        self._prev[c["id"]] = (total, system)
        mem = s.get("memory_stats", {})
        usage = mem.get("usage")
        if usage is not None:
            # Match `docker stats`: exclude page cache.
            st = mem.get("stats", {})
            usage -= st.get("inactive_file", st.get("total_inactive_file", 0))
        return {"cpu_percent": pct, "mem_bytes": usage, "mem_limit": mem.get("limit")}


# --------------------------------------------------------------------------
# Host
# --------------------------------------------------------------------------

def host_info(proc: str, disks: list[tuple[str, str]]) -> dict:
    info: dict = {"hostname": socket.gethostname(), "load": None, "cpus": os.cpu_count(),
                  "mem_total": None, "mem_available": None, "disks": []}
    try:
        with open(os.path.join(proc, "loadavg"), encoding="ascii") as fh:
            info["load"] = [float(x) for x in fh.read().split()[:3]]
    except OSError:
        pass
    try:
        with open(os.path.join(proc, "meminfo"), encoding="ascii") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    val = int(rest.split()[0]) * 1024
                    info["mem_total" if key == "MemTotal" else "mem_available"] = val
    except OSError:
        pass
    for label, path in disks:
        rec = {"label": label, "path": path, "total": None, "free": None, "used": None, "error": None}
        try:
            st = os.statvfs(path)
            rec["total"] = st.f_blocks * st.f_frsize
            rec["free"] = st.f_bavail * st.f_frsize
            rec["used"] = (st.f_blocks - st.f_bfree) * st.f_frsize
        except OSError as err:
            rec["error"] = str(err)
        info["disks"].append(rec)
    return info


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------

def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_atomic(path: str, data: dict) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".status-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=False)
            fh.write("\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def collect(args: argparse.Namespace, gh: GitHub, docker: Docker | None,
            disks: list[tuple[str, str]]) -> dict:
    started = time.monotonic()
    repos, orgs = _split(args.repos), _split(args.orgs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(collect_org, gh, o) for o in orgs]
        futures += [pool.submit(collect_repo, gh, r) for r in repos]
        scopes = [f.result() for f in futures]

    errors = [f"{s['name']}: {s['error']}" for s in scopes if s["error"]]
    containers = None
    if docker:
        try:
            containers = docker.containers(args.docker_filter)
        except (OSError, ValueError) as err:
            errors.append(f"docker: {err}")
            log.warning("docker: %s", err)

    runners = [r for s in scopes for r in s["runners"]]
    summary = {
        "runners": len(runners),
        "online": sum(1 for r in runners if r["status"] == "online"),
        "busy": sum(1 for r in runners if r["busy"]),
        "offline": sum(1 for r in runners if r["status"] != "online"),
        "queued_jobs": sum(len(s["queued"]) for s in scopes),
        "running_jobs": sum(len(s["running"]) for s in scopes),
    }
    summary["idle"] = summary["online"] - summary["busy"]
    return {
        "schema": SCHEMA_VERSION,
        "collector": __version__,
        "generated_at": _now(),
        "interval": args.interval,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "summary": summary,
        "scopes": scopes,
        "containers": containers,
        "host": host_info(args.proc, disks),
        "rate_limit": dict(gh.rate_limit),
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(message)s")
    token = _read_token(args)
    if not _split(args.repos) and not _split(args.orgs):
        log.error("nothing to watch: set GHR_REPOS and/or GHR_ORGS")
        return 2
    if not token:
        log.warning("no GitHub token set; runner endpoints need one, expect HTTP 401/403")
    disks = []
    for item in _split(args.disks):
        label, sep, path = item.partition("=")
        disks.append((label, path) if sep else (os.path.basename(item.rstrip("/")) or item, item))

    try:
        gh = GitHub(token, args.api_url)
    except ValueError as err:
        sys.exit(f"ghrunners-collector: {err}")
    docker = Docker(args.docker_host) if args.docker_host else None

    stop = False

    def _stop(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while True:
        data = collect(args, gh, docker, disks)
        write_atomic(args.output, data)
        s = data["summary"]
        log.info("runners %d (busy %d, idle %d, offline %d), queued jobs %d, %d ms, rate %s left",
                 s["runners"], s["busy"], s["idle"], s["offline"], s["queued_jobs"],
                 data["duration_ms"], gh.rate_limit.get("remaining", "?"))
        if args.once or stop:
            return 0
        deadline = time.monotonic() + max(args.interval, 10)
        while not stop and time.monotonic() < deadline:
            time.sleep(0.5)
        if stop:
            return 0


if __name__ == "__main__":
    sys.exit(main())
