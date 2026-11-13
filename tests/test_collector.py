"""End-to-end tests for ghrunners_collector against fake GitHub and Docker APIs.

Run: python3 -m unittest discover -s tests
"""

import http.server
import json
import os
import socketserver
import sys
import tempfile
import threading
import unittest
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "collector"))

import ghrunners_collector as collector  # noqa: E402

NOW = "2026-11-10T17:00:00Z"


def runner(rid, name, status, busy, labels):
    return {"id": rid, "name": name, "os": "Linux", "status": status, "busy": busy,
            "labels": [{"name": n} for n in labels]}


GITHUB = {
    "/repos/acme/game/actions/runners": {"total_count": 3, "runners": [
        runner(1, "srv-game", "online", False, ["self-hosted", "Linux", "X64", "server", "general"]),
        runner(2, "srv-game-android", "online", True, ["self-hosted", "Linux", "X64", "server", "android"]),
        runner(3, "mac-game", "offline", False, ["self-hosted", "macOS", "ARM64", "apple"]),
    ]},
    "/repos/acme/game/actions/runs?status=queued": {"workflow_runs": [
        {"id": 11, "name": "CI", "head_branch": "main", "event": "push",
         "html_url": "https://github.com/acme/game/actions/runs/11"}]},
    "/repos/acme/game/actions/runs?status=in_progress": {"workflow_runs": [
        {"id": 10, "name": "CI", "head_branch": "feature/x", "event": "pull_request",
         "html_url": "https://github.com/acme/game/actions/runs/10"}]},
    "/repos/acme/game/actions/runs/10/jobs": {"jobs": [
        {"id": 100, "name": "android-tests", "status": "in_progress", "runner_name": "srv-game-android",
         "labels": ["self-hosted", "android"], "created_at": NOW, "started_at": NOW,
         "html_url": "https://github.com/acme/game/actions/runs/10/job/100"},
        {"id": 101, "name": "lint", "status": "completed", "runner_name": "srv-game",
         "labels": ["self-hosted", "general"], "created_at": NOW, "started_at": NOW}]},
    "/repos/acme/game/actions/runs/11/jobs": {"jobs": [
        {"id": 110, "name": "android-export", "status": "queued", "runner_name": None,
         "labels": ["self-hosted", "android"], "created_at": NOW, "started_at": None,
         "html_url": "https://github.com/acme/game/actions/runs/11/job/110"},
        {"id": 111, "name": "ios", "status": "queued", "runner_name": None,
         "labels": ["self-hosted", "apple"], "created_at": NOW, "started_at": None}]},
    "/orgs/acme-org/actions/runners": {"total_count": 1, "runners": [
        runner(5, "org-runner", "online", False, ["self-hosted", "Linux", "X64"])]},
}

DOCKER = {
    "/containers/json?all=1": [
        {"Id": "a" * 64, "Names": ["/runner-game"], "Image": "runner:1", "State": "running",
         "Status": "Up 2 hours", "Labels": {"com.docker.compose.service": "runner-game"}},
        {"Id": "b" * 64, "Names": ["/postgres"], "Image": "postgres", "State": "running",
         "Status": "Up 3 days", "Labels": {}},
        {"Id": "c" * 64, "Names": ["/runner-old"], "Image": "runner:1", "State": "exited",
         "Status": "Exited (0)", "Labels": {}},
    ],
}
STATS_CALLS = {"n": 0}


def docker_stats():
    STATS_CALLS["n"] += 1
    n = STATS_CALLS["n"]
    return {"cpu_stats": {"cpu_usage": {"total_usage": 1_000_000 * n}, "system_cpu_usage": 10_000_000 * n,
                          "online_cpus": 4},
            "memory_stats": {"usage": 600 * 2**20, "limit": 6 * 2**30, "stats": {"inactive_file": 100 * 2**20}}}


class GitHubHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        key = parsed.path
        if "status" in params:
            key += "?status=" + params["status"]
        if self.headers.get("Authorization") != "Bearer test-token":
            return self._send(401, {"message": "Bad credentials"})
        if parsed.path == "/repos/acme/private/actions/runners":
            return self._send(403, {"message": "Resource not accessible by personal access token"})
        body = GITHUB.get(key)
        if body is None:
            return self._send(404, {"message": "Not Found"})
        etag = '"%x"' % (hash(json.dumps(body, sort_keys=True)) & 0xFFFFFFFF)
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.end_headers()
            return None
        return self._send(200, body, {"ETag": etag})

    def _send(self, code, body, headers=None):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-RateLimit-Limit", "5000")
        self.send_header("X-RateLimit-Remaining", "4990")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class DockerHandler(GitHubHandler):
    def address_string(self):
        return "docker"

    def do_GET(self):  # noqa: N802
        if "/stats" in self.path:
            return self._send(200, docker_stats())
        body = DOCKER.get(self.path)
        return self._send(200 if body is not None else 404, body or {"message": "nope"})


class UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def get_request(self):
        req, _ = super().get_request()
        return req, ("docker", 0)


class CollectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.gh = http.server.ThreadingHTTPServer(("127.0.0.1", 0), GitHubHandler)
        threading.Thread(target=cls.gh.serve_forever, daemon=True).start()
        cls.sock = os.path.join(cls.tmp.name, "docker.sock")
        cls.docker = UnixServer(cls.sock, DockerHandler)
        threading.Thread(target=cls.docker.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.gh.shutdown()
        cls.docker.shutdown()
        cls.tmp.cleanup()

    def run_collector(self, *extra):
        out = os.path.join(self.tmp.name, "out", "status.json")
        argv = ["--once", "--repos", "acme/game, acme/private", "--orgs", "acme-org",
                "--token", "test-token", "--api-url", f"http://127.0.0.1:{self.gh.server_port}",
                "--output", out, "--docker-host", f"unix://{self.sock}",
                "--docker-filter", "^runner", "--disks", f"tmp={self.tmp.name}", "--log-level", "ERROR",
                *extra]
        self.assertEqual(collector.main(argv), 0)
        with open(out, encoding="utf-8") as fh:
            return json.load(fh)

    def test_status_file(self):
        st = self.run_collector()
        self.assertEqual(st["schema"], 1)
        s = st["summary"]
        self.assertEqual((s["runners"], s["online"], s["busy"], s["idle"], s["offline"]), (4, 3, 1, 2, 1))
        self.assertEqual(s["queued_jobs"], 2)
        self.assertEqual(s["running_jobs"], 1)

        scopes = {sc["name"]: sc for sc in st["scopes"]}
        game = scopes["acme/game"]
        busy = [r for r in game["runners"] if r["busy"]][0]
        self.assertEqual(busy["job"]["name"], "android-tests")
        self.assertEqual(busy["job"]["workflow"], "CI")
        self.assertEqual(busy["job"]["branch"], "feature/x")
        self.assertEqual(sorted(j["name"] for j in game["queued"]), ["android-export", "ios"])
        self.assertIn("server", busy["labels"])

        self.assertIn("HTTP 403", scopes["acme/private"]["error"])
        self.assertTrue(any("acme/private" in e for e in st["errors"]))
        self.assertEqual(scopes["acme-org"]["type"], "org")

        names = [c["name"] for c in st["containers"]]
        self.assertEqual(sorted(names), ["runner-game", "runner-old"])
        running = [c for c in st["containers"] if c["state"] == "running"][0]
        self.assertEqual(running["mem_bytes"], 500 * 2**20)
        self.assertEqual(st["host"]["disks"][0]["label"], "tmp")
        self.assertGreater(st["host"]["disks"][0]["total"], 0)
        self.assertEqual(st["rate_limit"]["remaining"], 4990)

    def test_api_url_must_be_http(self):
        with self.assertRaises(ValueError):
            collector.GitHub("test-token", "file:///etc/passwd")

    def test_cpu_percent_from_two_samples(self):
        gh = collector.GitHub("test-token", f"http://127.0.0.1:{self.gh.server_port}")
        docker = collector.Docker(f"unix://{self.sock}")
        first = docker.containers("^runner-game$")[0]
        self.assertIsNone(first["cpu_percent"])
        second = docker.containers("^runner-game$")[0]
        # (1e6 / 1e7) * 4 cpus * 100 = 40 %
        self.assertEqual(second["cpu_percent"], 40.0)
        del gh

    def test_etag_cache_returns_cached_body(self):
        gh = collector.GitHub("test-token", f"http://127.0.0.1:{self.gh.server_port}")
        a = gh.get("/repos/acme/game/actions/runners")
        b = gh.get("/repos/acme/game/actions/runners")
        self.assertEqual(a, b)
        self.assertEqual(len(b["runners"]), 3)

    def test_bad_token_is_reported_not_fatal(self):
        st = self.run_collector("--token", "wrong")
        self.assertTrue(all("HTTP 401" in sc["error"] for sc in st["scopes"]))
        self.assertEqual(st["summary"]["runners"], 0)

    def test_requires_targets(self):
        self.assertEqual(collector.main(["--once", "--repos", "", "--orgs", "", "--log-level", "CRITICAL"]), 2)


if __name__ == "__main__":
    unittest.main()
