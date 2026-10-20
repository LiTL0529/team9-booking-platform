"""Run a measured 80/20 HTTP workload in AWS and save phase-specific evidence.

  python scripts/aws_loadtest.py --profile short --start-day 5
  python scripts/aws_loadtest.py --profile full --days 6

Inventory is checked before k6 starts: short needs 4,950 distinct free slots;
full needs 55,500. This script does not seed or reset business data.
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
SERVICES = ['merchant', 'catalogue', 'availability', 'booking', 'notification']
K6_VERSION = 'v0.55.0'
BUILDSPEC = f'''version: 0.2
phases:
  install:
    commands:
      - curl -fsSL https://github.com/grafana/k6/releases/download/{K6_VERSION}/k6-{K6_VERSION}-linux-amd64.tar.gz | tar xz
      - mv k6-{K6_VERSION}-linux-amd64/k6 /usr/local/bin/k6
  build:
    commands:
      - echo "$K6_SCRIPT_B64" | base64 -d > loadtest.js
      - echo "$PREPARE_SCRIPT_B64" | base64 -d > prepare_load_test.py
      - echo "$PROFILES_B64" | base64 -d > profiles.json
      - >-
          python prepare_load_test.py --profiles-file profiles.json --profile "$PROFILE"
          --days "$DAYS" --start-day "$START_DAY" --manifest load-manifest.json --slot-file load-slots.json
      - |
          if k6 run --quiet loadtest.js; then K6_EXIT=0; else K6_EXIT=$?; fi
          if test -s summary.json; then
            echo K6_SUMMARY_BEGIN
            tr -d '\\n' < summary.json
            echo
            echo K6_SUMMARY_END
          fi
          exit "$K6_EXIT"
'''


def metric(summary: dict, name: str, field: str, default=None):
    item = summary.get('metrics', {}).get(name, {})
    return item.get('values', item).get(field, default)


def parse_summary(log_text: str) -> dict:
    """Ignore CodeBuild's echoed shell blocks and select actual JSON output."""
    for segment in reversed(log_text.split('K6_SUMMARY_BEGIN')[1:]):
        payload, marker, _ = segment.partition('K6_SUMMARY_END')
        if not marker:
            continue
        try:
            value = json.loads(payload.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and 'metrics' in value and 'workload' in value:
            return value
    raise ValueError('No complete measured JSON summary in build logs')


def assess(summary: dict) -> dict:
    workload = summary.get('workload', {})
    rows = []
    for phase in workload.get('phases', []):
        suffix = '{phase:' + phase['name'] + '}'
        searches = metric(summary, 'search_requests' + suffix, 'count', 0)
        bookings = metric(summary, 'booking_requests' + suffix, 'count', 0)
        successes = metric(summary, 'successful_bookings' + suffix, 'count', 0)
        search_p95 = metric(summary, 'search_latency' + suffix, 'p(95)')
        success_p95 = metric(summary, 'successful_booking_latency' + suffix, 'p(95)')
        rows.append({
            'phase': phase['name'], 'target_http_rps': phase['rate'],
            'seconds': phase['seconds'], 'search_requests': searches, 'booking_requests': bookings,
            'successful_bookings': successes, 'actual_http_rps': (searches + bookings) / phase['seconds'],
            'booking_share': bookings / (searches + bookings) if searches + bookings else None,
            'search_p95_ms': search_p95, 'successful_booking_p95_ms': success_p95,
            'workload_delivered': searches >= phase['expected_searches'] * .98 and
                                  bookings >= phase['expected_bookings'] * .98,
            'search_target_met': search_p95 is not None and search_p95 < 500,
            'booking_target_met': successes > 0 and success_p95 is not None and success_p95 < 1000,
        })
    thresholds = [v.get('ok') for m in summary.get('metrics', {}).values()
                  for v in m.get('thresholds', {}).values() if isinstance(v, dict)]
    valid = bool(rows) and all(r['workload_delivered'] for r in rows)
    valid = valid and metric(summary, 'dropped_iterations', 'count', 0) == 0
    valid = valid and metric(summary, 'inventory_errors', 'count', 0) == 0
    return {'workload_valid': valid, 'phase_results': rows,
            'all_thresholds_met': bool(rows) and bool(thresholds) and all(v is True for v in thresholds)
                                  and all(r['search_target_met'] and r['booking_target_met'] for r in rows),
            'peak_phase': rows[-1] if rows else None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=['full', 'short'], default='full')
    parser.add_argument('--days', type=int)
    parser.add_argument('--start-day', type=int, default=1)
    args = parser.parse_args()
    days = args.days if args.days is not None else (6 if args.profile == 'full' else 2)
    if days < 1 or args.start_day < 1:
        parser.error('--days and --start-day must be positive')
    region = os.environ.get('AWS_REGION', 'ap-southeast-1')
    session = boto3.session.Session(region_name=region)
    token = session.client('cognito-idp').initiate_auth(
        ClientId=os.environ['COGNITO_CLIENT_ID'], AuthFlow='USER_PASSWORD_AUTH',
        AuthParameters={'USERNAME': os.environ.get('LOAD_USER', 'loadtester'),
                        'PASSWORD': os.environ['LOAD_PASSWORD']},
    )['AuthenticationResult']['IdToken']

    def env(name: str, value: str) -> dict:
        return {'name': name, 'value': value, 'type': 'PLAINTEXT'}

    def source(name: str, path: str) -> dict:
        return env(name, base64.b64encode((REPO / path).read_bytes()).decode())

    cb, ecs, logs = session.client('codebuild'), session.client('ecs'), session.client('logs')
    build = cb.start_build(
        projectName='booking-test-images', buildspecOverride=BUILDSPEC, timeoutInMinutesOverride=60,
        computeTypeOverride='BUILD_GENERAL1_MEDIUM',
        environmentVariablesOverride=[
            source('K6_SCRIPT_B64', 'tests/load/k6-search-and-book.js'),
            source('PREPARE_SCRIPT_B64', 'scripts/prepare_load_test.py'),
            source('PROFILES_B64', 'tests/load/profiles.json'),
            env('GATEWAY', os.environ['PLATFORM_GATEWAY']), env('API_KEY', os.environ['LOADTEST_API_KEY']),
            env('ID_TOKEN', token), env('PROFILE', args.profile), env('DAYS', str(days)),
            env('START_DAY', str(args.start_day)), env('LOAD_MANIFEST', './load-manifest.json'),
            env('LOAD_SLOTS', './load-slots.json'),
        ],
    )['build']
    print(f"k6 ({args.profile}) in CodeBuild {build['id']}; preflight runs before measurement", flush=True)
    timeline, started = [], time.monotonic()
    while True:
        services = ecs.describe_services(cluster='booking-test', services=SERVICES)['services']
        sample = {'minute': round((time.monotonic() - started) / 60, 2),
                  'at': datetime.now(UTC).isoformat(),
                  **{s['serviceName']: s['runningCount'] for s in services}}
        timeline.append(sample)
        print(f"  t+{sample['minute']:5.1f} min " + ' '.join(f'{s}={sample[s]}' for s in SERVICES), flush=True)
        build = cb.batch_get_builds(ids=[build['id']])['builds'][0]
        if build['buildComplete']:
            break
        time.sleep(30)
    lines, next_token = [], None
    group, stream = build.get('logs', {}).get('groupName'), build.get('logs', {}).get('streamName')
    while group and stream:
        kwargs = {'logGroupName': group, 'logStreamName': stream, 'startFromHead': True}
        if next_token:
            kwargs['nextToken'] = next_token
        page = logs.get_log_events(**kwargs)
        lines += [e['message'] for e in page['events']]
        if page['nextForwardToken'] == next_token:
            break
        next_token = page['nextForwardToken']
    log_text = ''.join(lines)
    if 'K6_SUMMARY_BEGIN' not in log_text or 'K6_SUMMARY_END' not in log_text:
        print('\n'.join(lines[-30:]))
        sys.exit(f"No measured summary; preflight/build failed ({build['buildStatus']}).")
    summary = parse_summary(log_text)
    assessment = assess(summary)
    result = {'schema_version': 2, 'profile': args.profile, 'build_id': build['id'],
              'build_status': build['buildStatus'], 'summary': summary, 'assessment': assessment,
              'timeline': timeline, 'timeline_origin': 'CodeBuild dispatch; includes preparation time'}
    out = REPO / '.local' / f"loadtest-v2-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('\n=== measured phase results (setup traffic excluded) ===')
    for row in assessment['phase_results']:
        print(f"{row['phase']}: {row['actual_http_rps']:.1f} HTTP/s; "
              f"{row['search_requests']} searches, {row['booking_requests']} bookings, "
              f"{row['successful_bookings']} successes; search P95={row['search_p95_ms']} ms; "
              f"successful booking P95={row['successful_booking_p95_ms']} ms")
    print(f"Workload valid: {assessment['workload_valid']}; all thresholds met: {assessment['all_thresholds_met']}")
    print(f'Saved {out}')
    if build['buildStatus'] != 'SUCCEEDED' or not assessment['workload_valid'] or not assessment['all_thresholds_met']:
        sys.exit(1)


if __name__ == '__main__':
    main()
