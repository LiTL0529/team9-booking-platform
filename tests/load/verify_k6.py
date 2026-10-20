import importlib.util
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
build = repo / ".local/defense-build/k6-verification"
build.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location("prepare", repo / "scripts/prepare_load_test.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
state = {"posts": [], "searches": 0, "preflight": True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, data):
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if state["preflight"]:
            return self.reply(200, {"slots": [{"slot_id": f"slot-{i}", "merchant_id": "m1"} for i in range(6)], "has_more": False})
        state["searches"] += 1
        self.reply(200, {"slots": []})

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        state["posts"].append(data["slot_id"])
        n = len(state["posts"])
        self.reply(409 if n == 4 else (403 if n == 5 else 201), {"booking_id": str(n)})


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
gateway = f"http://127.0.0.1:{server.server_port}"
try:
    manifest, slots = p.prepare(
        gateway, "dummy", [{"name": "first", "rate": 5, "seconds": 2}, {"name": "peak", "rate": 10, "seconds": 2}], 1, 1
    )
    (build / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (build / "slots.json").write_text(json.dumps(slots), encoding="utf-8")
    state["preflight"] = False
    env = os.environ.copy()
    env.update(
        LOAD_MANIFEST=str(build / "manifest.json"),
        LOAD_SLOTS=str(build / "slots.json"),
        ID_TOKEN="test-token",
        GATEWAY=gateway,
        API_KEY="dummy",
    )
    r = subprocess.run(  # noqa: S603 - trusted local k6 binary, no shell
        [
            os.environ.get("K6") or shutil.which("k6") or str(repo / ".local/tools/k6/k6.exe"),
            "run",
            "--quiet",
            str(repo / "tests/load/k6-search-and-book.js"),
        ],
        cwd=build,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=50,
    )
    (build / "run.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    print(r.stdout[-1500:] + r.stderr[-1500:])
    summary = json.loads((build / "summary.json").read_text(encoding="utf-8"))
    metrics = summary["metrics"]
    def count(name):
        return metrics.get(name, {}).get("values", {}).get("count", 0)
    assert count("search_requests") == 24, "Unexpected number of search requests"
    assert count("booking_requests") == 6
    assert count('search_requests{phase:first}') == 8
    assert count('booking_requests{phase:first}') == 2
    assert metrics['search_latency{phase:first}']['values']['p(95)'] >= 0
    assert metrics['successful_booking_latency{phase:first}']['values']['p(95)'] >= 0
    assert len(set(state["posts"])) == 6
    assert count("successful_bookings") == 4
    assert count("booking_conflicts") == 1
    assert metrics["unexpected_responses"]["values"]["rate"] > 0
    assert r.returncode != 0, "403 must fail response thresholds"
    print(
        "PASS: k6 sends 80/20 requests; empty searches do not skip bookings; "
        "phase inventory is unique; 409 is separate; 403 fails."
    )
finally:
    server.shutdown()
    server.server_close()
