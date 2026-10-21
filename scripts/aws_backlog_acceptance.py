"""Measure a 5,000-event burst, booking probes and actual queue-driven scaling.

The default uses normal processing. A nonzero --processing-delay-ms models delivery
cost and must be disclosed as a separate stress configuration. Always restores the
original task definition and autoscaling settings. Run without other cloud tests.
"""

import argparse
import importlib.util
import json
import math
import os
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from aws_acceptance import Acceptance, require, until
from platform_client import Api, Config, login
from prepare_load_test import prepare

ROOT = Path(__file__).resolve().parents[1]


def queue_scaled_while_busy(activities, timeline):
    return (any('sqs-backlog' in str(v.get('Cause', '')) for v in activities)
            and any(v['running'] > 2 and v['visible'] + v['in_flight'] > 2 for v in timeline))


def booking_probes_can_stop(sample):
    # Two-per-second probes can keep a one/two-message tail alive after the burst.
    # Stop that producer near the end, then independently require a quiet queue
    # and all 5,000 persisted synthetic notifications before accepting delivery.
    return sample['visible'] == 0 and sample['in_flight'] <= 2


def notification_count(checks, task_definition, customer_id):
    """Read only the synthetic customer's own inbox count using the existing task role."""
    query = (
        "import os;from sqlalchemy import create_engine,text;"
        "engine=create_engine(os.environ['DATABASE_URL']);c=engine.connect();"
        "c.exec_driver_sql('SET TRANSACTION READ ONLY');"
        "n=c.execute(text('SELECT count(*) FROM notifications WHERE customer_id = :u'),"
        "{'u':" + repr(customer_id) + "}).scalar_one();"
        "print('NOTIFICATION_COUNT='+str(n));c.close();engine.dispose()"
    )
    task = checks.ecs.run_task(
        cluster="booking-test",
        taskDefinition=task_definition,
        launchType="FARGATE",
        networkConfiguration=checks.original["notification"]["networkConfiguration"],
        overrides={"containerOverrides": [{"name": "app", "command": ["python", "-c", query]}]},
    )
    require(not task.get("failures"), "Read-only notification count task did not start")
    task_arn = task["tasks"][0]["taskArn"]

    def stopped():
        value = checks.ecs.describe_tasks(cluster="booking-test", tasks=[task_arn])["tasks"][0]
        return value if value["lastStatus"] == "STOPPED" else None

    try:
        ended = until(stopped, "Notification count task did not stop", timeout=300, interval=5)
    except TimeoutError:
        checks.ecs.stop_task(cluster="booking-test", task=task_arn, reason="Read-only acceptance task timeout")
        raise
    require(
        next(v for v in ended["containers"] if v["name"] == "app").get("exitCode") == 0, "Read-only notification count command failed"
    )
    logs = checks.session.client("logs")

    def count_logged():
        try:
            events = logs.get_log_events(
                logGroupName="/ecs/test-notification", logStreamName="app/app/" + task_arn.split("/")[-1], startFromHead=True
            )["events"]
        except logs.exceptions.ResourceNotFoundException:
            return None
        for event in events:
            if "NOTIFICATION_COUNT=" in event["message"]:
                return {"count": int(event["message"].split("NOTIFICATION_COUNT=")[1].strip())}
        return None

    result = until(count_logged, "Read-only count was not logged", timeout=60, interval=5)
    checks.record("notification_count_verified", customer_id=customer_id, count=result["count"], read_only_task=task_arn)
    return result["count"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-day", type=int, default=9)
    parser.add_argument("--days", type=int, default=2)
    parser.add_argument(
        "--processing-delay-ms",
        type=int,
        default=0,
        help="Optional simulated per-event delivery cost; report separately from normal processing",
    )
    args = parser.parse_args()
    if not 0 <= args.processing_delay_ms <= 1000:
        parser.error("processing delay must be between zero and 1000 ms")
    spec = importlib.util.spec_from_file_location("event_backlog", ROOT / "tests/load/event_backlog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    a = Acceptance("backlog")
    s = a.session
    sns = s.client("sns")
    sqs = s.client("sqs")
    queue = sqs.get_queue_url(QueueName="booking-test-notification-events")["QueueUrl"]
    topic = next(v["TopicArn"] for v in sns.list_topics()["Topics"] if v["TopicArn"].endswith(":booking-test-booking-events"))
    cfg = Config()
    api = Api(cfg, login(cfg, "loadtester", os.environ["LOAD_PASSWORD"]))
    _, slots = prepare(cfg.gateway, cfg.api_key, [{"name": "probes", "rate": 5, "seconds": 2000}], args.days, args.start_day)
    original = a.original["notification"]["taskDefinition"]
    definition = a.ecs.describe_task_definition(taskDefinition=original)["taskDefinition"]
    app = next(c for c in definition["containerDefinitions"] if c["name"] == "app")
    settings = {v["name"]: v["value"] for v in app.get("environment", [])}
    require(
        int(settings.get("NOTIFICATION_PROCESSING_DELAY_MS", "0")) == 0,
        "The original notification revision must use normal processing",
    )
    temporary = None
    stop = threading.Event()
    rows = []
    state = {"phase": "baseline", "index": 0}

    def probe():
        while not stop.is_set() and state["index"] < len(slots):
            index = state["index"]
            state["index"] += 1
            phase = state["phase"]
            started = time.perf_counter()
            status = 0
            error = None
            try:
                status = api.book(slots[index]).status_code
            except Exception as exc:  # noqa: BLE001 - preserve network failures as failed probes
                error = type(exc).__name__
            rows.append({"phase": phase, "status": status, "error": error, "ms": (time.perf_counter() - started) * 1000})
            stop.wait(max(0, 0.5 - (time.perf_counter() - started)))

    def p95(values):
        return sorted(values)[math.ceil(len(values) * 0.95) - 1] if values else None

    try:
        attrs = sqs.get_queue_attributes(
            QueueUrl=queue, AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"]
        )["Attributes"]
        require(all(int(v) == 0 for v in attrs.values()), "Drain the existing queue before a controlled burst")
        a.fixed("notification", 2)
        if args.processing_delay_ms:
            definition = a.ecs.describe_task_definition(taskDefinition=original)["taskDefinition"]
            allowed = a.ecs.meta.service_model.operation_model("RegisterTaskDefinition").input_shape.members
            body = {k: v for k, v in definition.items() if k in allowed}
            app = next(c for c in body["containerDefinitions"] if c["name"] == "app")
            app["environment"] = [v for v in app["environment"] if v["name"] != "NOTIFICATION_PROCESSING_DELAY_MS"] + [
                {"name": "NOTIFICATION_PROCESSING_DELAY_MS", "value": str(args.processing_delay_ms)}
            ]
            temporary = a.ecs.register_task_definition(**body)["taskDefinition"]["taskDefinitionArn"]
            update = a.ecs.update_service(cluster="booking-test", service="notification", taskDefinition=temporary)["service"]
            a.expected_deployments["notification"] = next(d["id"] for d in update["deployments"] if d["status"] == "PRIMARY")
        a.stable(["notification"])
        a.record(
            "test_configuration",
            processing_delay_ms=args.processing_delay_ms,
            consumer_concurrency=int(settings.get("CONSUMER_CONCURRENCY", "1")),
            task_vcpu=int(definition["cpu"]) / 1024,
            synthetic_events=5000,
            booking_probe_rate=2,
            description=(
                "Simulated notification delivery cost; not the normal zero-delay drain time"
                if args.processing_delay_ms
                else "Normal notification processing; no artificial delivery delay"
            ),
        )
        worker = threading.Thread(target=probe, daemon=True)
        worker.start()
        time.sleep(30)
        target = a.targets["notification"]
        a.scaling.register_scalable_target(
            ServiceNamespace="ecs",
            ResourceId=target["ResourceId"],
            ScalableDimension=target["ScalableDimension"],
            MinCapacity=2,
            MaxCapacity=target["MaxCapacity"],
            SuspendedState=target.get("SuspendedState", {}),
        )
        a.expected_counts.pop("notification", None)
        run = uuid.uuid4().hex[:8]
        batches = []
        for i in range(0, 5000, 10):
            batches.append(
                [
                    {
                        "Id": str(j),
                        "Message": json.dumps(module.envelope(i + j, run)),
                        "MessageAttributes": {"event_type": {"DataType": "String", "StringValue": "BookingConfirmed"}},
                    }
                    for j in range(10)
                ]
            )
        state["phase"] = "burst"
        started = time.perf_counter()
        at = datetime.now(UTC)
        failed = []
        with ThreadPoolExecutor(max_workers=16) as pool:
            for r in pool.map(lambda b: sns.publish_batch(TopicArn=topic, PublishBatchRequestEntries=b), batches):
                failed.extend(r.get("Failed", []))
        require(not failed, "SNS rejected some of the 5000 entries")
        a.record("burst_published", published=5000, publish_seconds=time.perf_counter() - started)
        empty = 0
        timeline = []
        while time.perf_counter() - started < 900:
            q = sqs.get_queue_attributes(
                QueueUrl=queue, AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"]
            )["Attributes"]
            service = a.ecs.describe_services(cluster="booking-test", services=["notification"])["services"][0]
            sample = {
                "seconds": round(time.perf_counter() - started, 1),
                "visible": int(q["ApproximateNumberOfMessages"]),
                "in_flight": int(q["ApproximateNumberOfMessagesNotVisible"]),
                "desired": service["desiredCount"],
                "running": service["runningCount"],
            }
            timeline.append(sample)
            print(json.dumps(sample), flush=True)
            if not stop.is_set() and booking_probes_can_stop(sample):
                stop.set()
                worker.join(35)
                a.record('booking_probes_stopped_for_quiet_check',
                         elapsed_seconds=time.perf_counter() - started,
                         reason='Visible burst ended; stop the probe producer before checking queue quietness')
            empty = empty + 1 if sample["visible"] == 0 and sample["in_flight"] == 0 else 0
            if empty >= 3:
                break
            time.sleep(5)
        drained_seconds = time.perf_counter() - started
        stop.set()
        worker.join(35)
        activities = a.scaling.describe_scaling_activities(
            ServiceNamespace="ecs", ResourceId=target["ResourceId"], ScalableDimension=target["ScalableDimension"]
        )["ScalingActivities"]
        activity = [
            {k: v.get(k) for k in ["StartTime", "Description", "Cause", "StatusCode"]} for v in activities if v["StartTime"] >= at
        ]
        groups = {phase: [r["ms"] for r in rows if r["phase"] == phase and r["status"] == 201] for phase in ["baseline", "burst"]}
        summary = {
            p: {
                "requests": sum(r["phase"] == p for r in rows),
                "status_counts": dict(Counter(r["status"] for r in rows if r["phase"] == p)),
                "successful_booking_p95_ms": p95(v),
            }
            for p, v in groups.items()
        }
        scale = queue_scaled_while_busy(activity, timeline)
        # Verify persisted output, rather than treating approximate queue emptiness as delivery proof.
        persisted = notification_count(a, original, "backlog-" + run)
        passed = (
            empty >= 3
            and persisted == 5000
            and scale
            and all(r["status"] == 201 for r in rows)
            and all(v["successful_booking_p95_ms"] and v["successful_booking_p95_ms"] < 1000 for v in summary.values())
        )
        a.record(
            "backlog_result",
            passed=passed,
            drain_seconds=drained_seconds,
            drain_timing_method=(
                'Three quiet queue samples after stopping probes near the end; exact synthetic inbox count checked separately'
            ),
            queue_scale_out_observed=scale,
            booking=summary,
            timeline=timeline,
            scaling_activities=activity,
            persisted_notifications=persisted,
            limitation=(
                "Low-rate booking probes test the 1s latency budget; baseline/burst difference is disclosed, "
                "not proof of zero latency impact. Probes stop when the visible burst ends with at most two in flight, "
                "before the final queue-quiet check; persisted synthetic count must still equal 5000."
            ),
        )
        a.records.update(completed=True, passed=passed, normal_processing=(args.processing_delay_ms == 0))
        require(passed, "Backlog acceptance did not meet all recorded gates; inspect delivery and scaling separately")
    except BaseException as exc:
        a.records.update(passed=False, failure=str(exc))
        a.save()
        raise
    finally:
        stop.set()
        if temporary:
            update = a.ecs.update_service(cluster="booking-test", service="notification", taskDefinition=original)["service"]
            a.expected_deployments["notification"] = next(d["id"] for d in update["deployments"] if d["status"] == "PRIMARY")
        a.restore()
        if temporary:
            a.ecs.deregister_task_definition(taskDefinition=temporary)
        print("Evidence:", a.path, flush=True)


if __name__ == "__main__":
    main()
