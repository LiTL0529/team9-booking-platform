"""Run the k6 load test from inside AWS (CodeBuild in the same region) and record auto scaling.

Generating load from AWS keeps the client's own network out of the measurement. While k6 runs,
the script samples the running task count of every ECS service once a minute.

  python scripts/aws_loadtest.py                 # proposal profile: 25 -> 200 rps, ~35 minutes
  python scripts/aws_loadtest.py --profile short # ~3 minute rehearsal

Needs .local/aws.env (python scripts/aws_deploy.py env) and LOAD_PASSWORD for the loadtester user.
Writes .local/loadtest-<timestamp>.json with the k6 summary and the scaling timeline.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import boto3

REPO = Path(__file__).resolve().parents[1]
SERVICES = ["merchant", "catalogue", "availability", "booking", "notification"]
K6_VERSION = "v0.55.0"
BUILDSPEC = f"""version: 0.2
phases:
  install:
    commands:
      - curl -sSL https://github.com/grafana/k6/releases/download/{K6_VERSION}/k6-{K6_VERSION}-linux-amd64.tar.gz | tar xz
      - mv k6-{K6_VERSION}-linux-amd64/k6 /usr/local/bin/k6
  build:
    commands:
      - echo "$K6_SCRIPT_B64" | base64 -d > loadtest.js
      # k6 exposes the build's environment variables (GATEWAY, API_KEY, ID_TOKEN, PROFILE, DAYS, START_DAY) as __ENV
      - k6 run --quiet --summary-export summary.json loadtest.js || true
      - echo K6_SUMMARY_BEGIN; tr -d '\\n' < summary.json; echo; echo K6_SUMMARY_END
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["full", "short"], default="full")
    parser.add_argument("--days", default="2")
    parser.add_argument("--start-day", default="1", help="first date searched, in days from today")
    args = parser.parse_args()

    region = os.environ.get("AWS_REGION", "ap-southeast-1")
    session = boto3.session.Session(region_name=region)
    token = session.client("cognito-idp").initiate_auth(
        ClientId=os.environ["COGNITO_CLIENT_ID"],
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": os.environ.get("LOAD_USER", "loadtester"), "PASSWORD": os.environ["LOAD_PASSWORD"]},
    )["AuthenticationResult"]["IdToken"]
    script = base64.b64encode((REPO / "tests" / "load" / "k6-search-and-book.js").read_bytes()).decode()

    def env(name: str, value: str) -> dict:
        return {"name": name, "value": value, "type": "PLAINTEXT"}

    codebuild, ecs, logs = session.client("codebuild"), session.client("ecs"), session.client("logs")
    build = codebuild.start_build(
        projectName="booking-test-images",
        buildspecOverride=BUILDSPEC,
        timeoutInMinutesOverride=60,
        environmentVariablesOverride=[
            env("K6_SCRIPT_B64", script), env("GATEWAY", os.environ["PLATFORM_GATEWAY"]),
            env("API_KEY", os.environ["LOADTEST_API_KEY"]), env("ID_TOKEN", token),
            env("PROFILE", args.profile), env("DAYS", args.days), env("START_DAY", args.start_day),
        ],
    )["build"]
    print(f"k6 ({args.profile} profile) running in CodeBuild {build['id']}")

    timeline = []
    started = time.time()
    while True:
        services = ecs.describe_services(cluster="booking-test", services=SERVICES)["services"]
        counts = {s["serviceName"]: s["runningCount"] for s in services}
        timeline.append({"minute": round((time.time() - started) / 60, 1), **counts})
        print(f"  t+{timeline[-1]['minute']:5.1f} min  " + "  ".join(f"{k}={v}" for k, v in counts.items()))
        build = codebuild.batch_get_builds(ids=[build["id"]])["builds"][0]
        if build["buildComplete"]:
            break
        time.sleep(60)

    group, stream = build["logs"].get("groupName"), build["logs"].get("streamName")
    lines, token_ = [], None
    while group and stream:
        kwargs = {"logGroupName": group, "logStreamName": stream, "startFromHead": True}
        if token_:
            kwargs["nextToken"] = token_
        page = logs.get_log_events(**kwargs)
        lines += [e["message"] for e in page["events"]]
        if page["nextForwardToken"] == token_:
            break
        token_ = page["nextForwardToken"]
    text = "".join(lines)
    if "K6_SUMMARY_BEGIN" not in text:
        print("\n".join(lines[-40:]))
        sys.exit(f"k6 did not produce a summary (build status {build['buildStatus']})")
    # CodeBuild also echoes the command line, so take the marker that is followed by the JSON itself
    summary = json.loads(text.rsplit("K6_SUMMARY_BEGIN", 1)[1].split("K6_SUMMARY_END", 1)[0].strip())

    m = summary["metrics"]
    reqs = m["http_reqs"]
    print("\n=== k6 results (load generated inside AWS, ap-southeast-1) ===")
    print(f"requests          {reqs['count']:.0f} ({reqs['rate']:.1f}/s average)")
    print(f"search latency    p95 {m['search_latency']['p(95)']:.0f} ms   median {m['search_latency']['med']:.0f} ms")
    print(f"booking latency   p95 {m['booking_latency']['p(95)']:.0f} ms   median {m['booking_latency']['med']:.0f} ms")
    print(f"unexpected errors {m['unexpected_errors']['value'] * 100:.2f} %")
    print(f"bookings made     {m.get('bookings_made', {}).get('count', 0):.0f}")
    print(f"expected 409s     {m.get('booking_conflicts', {}).get('count', 0):.0f}")
    peak = {s: max(t[s] for t in timeline) for s in SERVICES}
    print("peak tasks        " + "  ".join(f"{s}={n}" for s, n in peak.items()))
    checks = {
        "P95 search < 500 ms": m["search_latency"]["p(95)"] < 500,
        "P95 booking < 1 s": m["booking_latency"]["p(95)"] < 1000,
        "unexpected errors < 1%": m["unexpected_errors"]["value"] < 0.01,
    }
    for name, ok in checks.items():
        print(f"target {name:<24} {'met' if ok else 'NOT met'}")

    out = REPO / ".local" / f"loadtest-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps({"profile": args.profile, "summary": summary, "timeline": timeline}, indent=2), encoding="utf-8")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
