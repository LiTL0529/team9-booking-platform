"""Record Booking task replacement and an independent rolling release under 25 HTTP/s.

Uses the current main revision and dispatches only booking.yml. Other four task
revisions must remain unchanged. Restores the original autoscaling settings.
GitHub authentication uses GH_TOKEN or the user's Git credential helper.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from aws_acceptance import CLUSTER, Acceptance, require, until

ROOT = Path(__file__).resolve().parents[1]
REPO = "LiTL0529/team9-booking-platform"


def github_client():
    token = os.environ.get("GH_TOKEN")
    if not token:
        credential = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=20,
            env={**os.environ, "GCM_INTERACTIVE": "never"},
        )
        token = dict(v.split("=", 1) for v in credential.stdout.splitlines() if "=" in v)["password"]

    def call(path, method="GET", data=None):
        request = urllib.request.Request(
            f"https://api.github.com/repos/{REPO}/{path}",
            method=method,
            headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "Content-Type": "application/json"},
            data=json.dumps(data).encode() if data is not None else None,
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response) if response.status != 204 else None

    return call


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-day", type=int, default=11)
    parser.add_argument("--days", type=int, default=8)
    args = parser.parse_args()
    github = github_client()
    source_sha = github("commits/main")["sha"]
    a = Acceptance("release-under-load")
    cb, logs = a.session.client("codebuild"), a.session.client("logs")
    initial = {name: value["taskDefinition"] for name, value in a.original.items()}
    existing_results = set((ROOT / ".local").glob("loadtest-v2-*.json"))
    load_log = a.path.with_suffix(".load.log")
    child = None
    build_id = None
    dispatch_at = None
    workflow = None
    try:
        a.fixed('booking', 2)
        a.original['booking']['desiredCount'] = 2
        a.stable(['booking'])
        with load_log.open("w", encoding="utf-8") as output:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    "-u",
                    str(ROOT / "scripts/aws_loadtest.py"),
                    "--profile",
                    "short",
                    "--profiles-file",
                    str(ROOT / "tests/load/profiles-resilience.json"),
                    "--start-day",
                    str(args.start_day),
                    "--days",
                    str(args.days),
                ],
                cwd=ROOT,
                stdout=output,
                stderr=subprocess.STDOUT,
            )

            def launched():
                text = load_log.read_text(encoding="utf-8")
                match = re.search(r"CodeBuild (booking-test-images:[a-f0-9-]+)", text)
                if child.poll() is not None and not match:
                    raise RuntimeError("Load runner ended before starting CodeBuild")
                return match.group(1) if match else None

            build_id = until(launched, "CodeBuild did not start", timeout=120, interval=5)

            def measurement_started():
                build = cb.batch_get_builds(ids=[build_id])["builds"][0]
                if build.get("buildComplete"):
                    raise RuntimeError("Load build ended before the measurement marker")
                if not build.get("logs", {}).get("streamName"):
                    return None
                events = logs.get_log_events(
                    logGroupName=build["logs"]["groupName"], logStreamName=build["logs"]["streamName"], startFromHead=True
                )["events"]
                for event in events:
                    match = re.search(r"K6_MEASUREMENT_START=([0-9T:.Z-]+)", event["message"])
                    if match:
                        return datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
                return None

            measured_at = until(measurement_started, "No measurement marker", timeout=300, interval=5)
            a.record(
                "measurement_started",
                at_utc=measured_at.isoformat(),
                build_id=build_id,
                target_http_rps=25,
                booking_share=0.2,
                service_revisions=initial,
            )
            killed = False
            replacement = False
            release_observed = False
            release_completed_under_load = False
            last_sample = -60
            baseline_tasks = set(a.ecs.list_tasks(cluster=CLUSTER, serviceName="booking")["taskArns"])
            deadline = time.monotonic() + 2100
            while time.monotonic() < deadline:
                elapsed = (datetime.now(UTC) - measured_at).total_seconds()
                if elapsed - last_sample >= 60:
                    states = a.services()
                    a.record('service_count_sample', elapsed_seconds=elapsed,
                             counts={v['serviceName']: v['runningCount'] for v in states})
                    last_sample = elapsed
                if elapsed >= 60 and not killed:
                    stopped = sorted(baseline_tasks)[0]
                    a.ecs.stop_task(cluster=CLUSTER, task=stopped, reason="Proposal acceptance: one Booking task replacement")
                    a.record("booking_task_stopped", elapsed_seconds=elapsed, task=stopped)
                    killed = True
                if killed and not replacement:
                    running = a.ecs.list_tasks(cluster=CLUSTER, serviceName="booking", desiredStatus="RUNNING")["taskArns"]
                    tasks = a.ecs.describe_tasks(cluster=CLUSTER, tasks=running)["tasks"] if running else []
                    healthy = {v["taskArn"] for v in tasks if v["lastStatus"] == "RUNNING" and v.get("healthStatus") == "HEALTHY"}
                    if len(healthy) >= 2 and healthy - baseline_tasks:
                        a.record("booking_task_replaced", elapsed_seconds=elapsed, replacement_tasks=sorted(healthy - baseline_tasks))
                        replacement = True
                if elapsed >= 120 and replacement and dispatch_at is None:
                    # Resolve again immediately before dispatch, refusing an unexpected main update.
                    require(github("commits/main")["sha"] == source_sha, "Main changed; resolve the intended source before release")
                    dispatch_at = datetime.now(UTC).replace(microsecond=0)
                    github("actions/workflows/booking.yml/dispatches", "POST", {"ref": "main"})
                    a.record(
                        "independent_release_dispatched",
                        source_sha=source_sha,
                        ref="main",
                        elapsed_seconds=elapsed,
                        workflow="booking.yml",
                    )
                if dispatch_at and workflow is None:
                    candidates = github("actions/workflows/booking.yml/runs?event=workflow_dispatch&per_page=10")["workflow_runs"]
                    workflow = next(
                        (
                            r
                            for r in candidates
                            if r["head_sha"] == source_sha
                            and datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) >= dispatch_at
                        ),
                        None,
                    )
                    if workflow:
                        a.record("release_workflow_identified", run_id=workflow["id"], url=workflow["html_url"])
                if dispatch_at and child.poll() is None:
                    service = a.ecs.describe_services(cluster=CLUSTER, services=["booking"])["services"][0]
                    if service["taskDefinition"] != initial["booking"]:
                        if not release_observed:
                            a.record("rolling_deployment_observed", elapsed_seconds=elapsed, task_definition=service["taskDefinition"])
                            release_observed = True
                        if (
                            not release_completed_under_load
                            and len(service["deployments"]) == 1
                            and service["deployments"][0].get("rolloutState") == "COMPLETED"
                            and service["runningCount"] == service["desiredCount"] == 2
                            and service["pendingCount"] == 0
                        ):
                            a.record(
                                "rolling_release_completed_under_load",
                                elapsed_seconds=elapsed,
                                task_definition=service["taskDefinition"],
                            )
                            release_completed_under_load = True
                if child.poll() is not None:
                    break
                time.sleep(10)
            else:
                raise TimeoutError("Recovery/release workload did not finish")

        require(replacement, "No healthy Booking task replacement was recorded")
        require(release_observed and release_completed_under_load, "Rolling release did not complete during measured traffic")
        require(workflow, "Dispatched Booking workflow was not found")

        def finished():
            value = github(f"actions/runs/{workflow['id']}")
            return value if value["status"] == "completed" else None

        result = until(finished, "Booking pipeline did not finish", timeout=1200, interval=30)
        require(result["conclusion"] == "success", "Booking pipeline failed")
        a.stable()
        final = {v["serviceName"]: v["taskDefinition"] for v in a.services()}
        require(
            all(final[name] == initial[name] for name in initial if name != "booking"),
            "Another service revision changed during the independent release",
        )
        require(final["booking"] != initial["booking"], "Booking task definition did not change")
        definition = a.ecs.describe_task_definition(taskDefinition=final["booking"])["taskDefinition"]
        app = next(v for v in definition["containerDefinitions"] if v["name"] == "app")
        version = next(v["value"] for v in app["environment"] if v["name"] == "SERVICE_VERSION")
        require(version == source_sha, "Released Booking version is not the dispatched main source")
        paths = set((ROOT / ".local").glob("loadtest-v2-*.json")) - existing_results
        require(len(paths) == 1, "Expected one measured recovery workload")
        evidence = paths.pop()
        measured = json.loads(evidence.read_text(encoding="utf-8"))
        summary = measured["summary"]["metrics"]
        unexpected = summary["unexpected_errors"]["values"]["rate"]
        successful = sum(v["successful_bookings"] for v in measured["assessment"]["phase_results"])
        bookings = sum(v["booking_requests"] for v in measured["assessment"]["phase_results"])
        passed = (
            child.returncode == 0
            and measured["assessment"]["workload_valid"]
            and measured["assessment"]["all_thresholds_met"]
            and unexpected == 0
            and successful == bookings
        )
        a.record(
            "independent_release_result",
            passed=passed,
            workflow_url=result["html_url"],
            workload_evidence=str(evidence),
            assessment=measured["assessment"],
            unexpected_error_rate=unexpected,
            service_revisions_after=final,
            limitation="25 HTTP/s controlled recovery/release exercise; separate from 200 HTTP/s performance acceptance",
        )
        a.records.update(completed=True, passed=passed)
        require(passed, "Recovery/release workload did not meet its recorded gates")
    except BaseException as exc:
        a.records.update(passed=False, failure=str(exc))
        a.save()
        raise
    finally:
        if child and child.poll() is None:
            if build_id:
                cb.stop_build(id=build_id)
            child.wait(timeout=90)
        a.restore()
        print("Evidence:", a.path, flush=True)


if __name__ == "__main__":
    main()
