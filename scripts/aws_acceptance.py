"""Recorded capacity and recovery checks against the booking-test environment.

Run one command at a time; each restores the service/scaling settings it changes.
Credentials stay in process memory. Evidence is saved under .local/acceptance/.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import boto3
from platform_client import Api, Config, login

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ['merchant', 'catalogue', 'availability', 'booking', 'notification']
CLUSTER = 'booking-test'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def until(fn, label, timeout=900, interval=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(interval)
    raise TimeoutError(label)


class Acceptance:
    def __init__(self, command):
        self.session = boto3.Session(region_name='ap-southeast-1')
        self.ecs = self.session.client('ecs')
        self.scaling = self.session.client('application-autoscaling')
        self.run = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
        self.path = ROOT / '.local' / 'acceptance' / f'{command}-{self.run}.json'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.records = {'command': command, 'started_at': datetime.now(UTC).isoformat(), 'checks': []}
        self.original = {s['serviceName']: s for s in self.services()}
        self.targets = {t['ResourceId'].split('/')[-1]: t for t in self.scaling.describe_scalable_targets(
            ServiceNamespace='ecs')['ScalableTargets'] if t['ResourceId'].startswith(f'service/{CLUSTER}/')}
        self.changed = set()
        self.expected_counts = {}
        self.expected_deployments = {}
        self.save()

    def services(self):
        response = self.ecs.describe_services(cluster=CLUSTER, services=SERVICES)
        if response.get('failures') or len(response['services']) != 5:
            raise RuntimeError('Expected exactly the five booking-test services')
        return response['services']

    def save(self):
        self.path.write_text(json.dumps(self.records, indent=2, default=str), encoding='utf-8')

    def record(self, name, **values):
        row = {'check': name, 'at': datetime.now(UTC).isoformat(), **values}
        self.records['checks'].append(row)
        self.save()
        print(json.dumps(row, default=str), flush=True)

    def fixed(self, name, count):
        if name not in SERVICES or not 0 <= count <= 6:
            raise ValueError('Invalid test service or task count')
        self.changed.add(name)
        self.scaling.register_scalable_target(
            ServiceNamespace='ecs', ResourceId=f'service/{CLUSTER}/{name}',
            ScalableDimension='ecs:service:DesiredCount', MinCapacity=count, MaxCapacity=count,
            SuspendedState={'DynamicScalingInSuspended': True, 'DynamicScalingOutSuspended': True,
                            'ScheduledScalingSuspended': True})
        self.ecs.update_service(cluster=CLUSTER, service=name, desiredCount=count)
        self.expected_counts[name] = count

    def stable(self, names=SERVICES, timeout=900):
        def ready():
            states = [s for s in self.services() if s['serviceName'] in names]
            return states if all(len(s['deployments']) == 1
                                 and (s['serviceName'] not in self.expected_counts or
                                      s['desiredCount'] == self.expected_counts[s['serviceName']])
                                 and (s['serviceName'] not in self.expected_deployments or
                                      s['deployments'][0]['id'] == self.expected_deployments[s['serviceName']])
                                 and s['deployments'][0].get('rolloutState') == 'COMPLETED'
                                 and s['runningCount'] == s['desiredCount'] and s['pendingCount'] == 0
                                 for s in states) else None
        states = until(ready, 'Services did not stabilize', timeout)
        self.record('stable', services={s['serviceName']: s['runningCount'] for s in states})

    def restore(self):
        for name in self.changed:
            value = self.targets[name]
            self.scaling.register_scalable_target(
                ServiceNamespace='ecs', ResourceId=value['ResourceId'],
                ScalableDimension=value['ScalableDimension'], MinCapacity=value['MinCapacity'],
                MaxCapacity=value['MaxCapacity'], SuspendedState=value.get('SuspendedState', {}))
            self.ecs.update_service(cluster=CLUSTER, service=name, desiredCount=self.original[name]['desiredCount'])
            self.expected_counts.pop(name, None)
        if self.changed:
            self.stable(list(self.changed))
            self.record('settings_restored', services=sorted(self.changed))
        self.records['finished_at'] = datetime.now(UTC).isoformat()
        self.save()

    def clients(self):
        cfg = Config()
        password = os.environ['SMOKE_PASSWORD']
        return Api(cfg), Api(cfg, login(cfg, 'alice', password))

    @staticmethod
    def slot(public, offset=5):
        for day_offset in range(offset, offset + 8):
            day = (date.today() + timedelta(days=day_offset)).isoformat()
            slots = public.call('GET', '/v1/availability/slots', params={'date': day, 'limit': 10}).json()['slots']
            if slots:
                return slots[0]
        raise RuntimeError('Prepare future inventory before recovery tests')

    def recovery(self):
        public, alice = self.clients()
        # Select inventory before taking search offline.
        slot = self.slot(public)
        self.fixed('availability', 0)
        self.stable(['availability'])
        booking = alice.book(slot['slot_id'])
        require(booking.status_code == 201, booking.text)
        value = booking.json()
        cancelled = alice.call('POST', f'/v1/bookings/{value["booking_id"]}/cancel').json()
        require(cancelled['status'] == 'CANCELLED', 'Cancellation did not release booking')
        self.record('availability_offline_booking_and_cancel', passed=True, reference=value['reference'])
        self.fixed('availability', self.original['availability']['desiredCount'])
        self.stable(['availability'])

        slot = self.slot(public)
        self.fixed('notification', 0)
        self.stable(['notification'])
        booking = alice.book(slot['slot_id'])
        require(booking.status_code == 201, booking.text)
        anchor = booking.json()
        self.record('notification_offline_booking', passed=True, reference=anchor['reference'])
        self.fixed('notification', self.original['notification']['desiredCount'])
        self.stable(['notification'])

        def delivered():
            return [n for n in alice.call('GET', '/v1/notifications', params={'limit': 200}).json()
                    if n['booking_id'] == anchor['booking_id'] and n['kind'] == 'BOOKING_CONFIRMED']
        notifications = until(delivered, 'Notification did not catch up', timeout=180, interval=3)
        require(len(notifications) == 1, 'Confirmation delivered more than once')
        self.record('notification_caught_up_once', passed=True, reference=anchor['reference'])

        before = {name: self.ecs.list_tasks(cluster=CLUSTER, serviceName=name)['taskArns'] for name in SERVICES}
        for name in SERVICES:
            updated = self.ecs.update_service(cluster=CLUSTER, service=name, forceNewDeployment=True)['service']
            self.expected_deployments[name] = next(d['id'] for d in updated['deployments'] if d['status'] == 'PRIMARY')
        self.stable()
        after = {name: self.ecs.list_tasks(cluster=CLUSTER, serviceName=name)['taskArns'] for name in SERVICES}
        require(all(not (set(before[name]) & set(after[name])) for name in SERVICES),
                'An old task remained after the restart')
        persisted = alice.call('GET', f'/v1/bookings/{anchor["booking_id"]}').json()
        require(persisted['status'] == 'CONFIRMED' and persisted['reference'] == anchor['reference'],
                'Confirmed booking did not survive restart')
        self.record('all_services_restarted_booking_persisted', passed=True, reference=anchor['reference'],
                    before_task_ids={k: [v.split('/')[-1] for v in values] for k, values in before.items()},
                    after_task_ids={k: [v.split('/')[-1] for v in values] for k, values in after.items()})
        alice.call('POST', f'/v1/bookings/{anchor["booking_id"]}/cancel')

    def rollback(self):
        service = next(x for x in self.services() if x['serviceName'] == 'merchant')
        previous = service['taskDefinition']
        definition = self.ecs.describe_task_definition(taskDefinition=previous)['taskDefinition']
        allowed = self.ecs.meta.service_model.operation_model('RegisterTaskDefinition').input_shape.members
        body = {k: v for k, v in definition.items() if k in allowed}
        app = next(c for c in body['containerDefinitions'] if c['name'] == 'app')
        app['command'] = ['python', '-c', 'raise SystemExit(42)']
        bad = self.ecs.register_task_definition(**body)['taskDefinition']['taskDefinitionArn']
        self.record('failed_revision_started', original=previous, failed_revision=bad)
        updated = self.ecs.update_service(cluster=CLUSTER, service='merchant', taskDefinition=bad)['service']
        deployment_id = next(d['id'].split('/')[-1] for d in updated['deployments'] if d['status'] == 'PRIMARY')
        try:
            def history_arn():
                rows = self.ecs.list_service_deployments(cluster=CLUSTER, service='merchant')['serviceDeployments']
                return next((v['serviceDeploymentArn'] for v in rows
                             if v['targetServiceRevisionArn'].endswith('/' + deployment_id)), None)
            deployment_arn = until(history_arn, 'Deployment history did not appear', timeout=60, interval=5)

            def rolled_back():
                current = next(x for x in self.services() if x['serviceName'] == 'merchant')
                history = self.ecs.describe_service_deployments(
                    serviceDeploymentArns=[deployment_arn])['serviceDeployments'][0]
                return (current, history) if (history['status'] == 'ROLLBACK_SUCCESSFUL'
                                   and current['taskDefinition'] == previous
                                   and len(current['deployments']) == 1
                                   and current['deployments'][0].get('rolloutState') == 'COMPLETED'
                                   and current['runningCount'] == current['desiredCount']
                                   and current['pendingCount'] == 0) else None
            value, history = until(rolled_back, 'Automatic rollback did not complete', timeout=1800)
            self.record('automatic_startup_failure_rollback', passed=True, restored=previous,
                        deployment_history=history,
                        events=[v['message'] for v in value['events'][:10]])
        finally:
            current = next(x for x in self.services() if x['serviceName'] == 'merchant')
            if current['taskDefinition'] != previous:
                self.ecs.update_service(cluster=CLUSTER, service='merchant', taskDefinition=previous)
                self.stable(['merchant'])
            self.ecs.deregister_task_definition(taskDefinition=bad)

    def capacity(self, start_day, days):
        for count in [1, 2, 4]:
            for name in ['availability', 'booking']:
                self.fixed(name, count)
            self.stable(['availability', 'booking'])
            existing = set((ROOT / '.local').glob('loadtest-v2-*.json'))
            result = subprocess.run([sys.executable, '-X', 'utf8', '-u', str(ROOT / 'scripts/aws_loadtest.py'),
                                     '--profile', 'short', '--start-day', str(start_day), '--days', str(days)],
                                    cwd=ROOT, check=False)
            paths = set((ROOT / '.local').glob('loadtest-v2-*.json')) - existing
            if len(paths) != 1:
                raise RuntimeError('Capacity run did not produce exactly one measured result')
            path = paths.pop()
            measured = json.loads(path.read_text(encoding='utf-8'))
            self.record('fixed_capacity', tasks=count, test_exit=result.returncode, evidence=str(path),
                        assessment=measured['assessment'])
            if count == 4:
                race_path = self.path.with_name('concurrency-' + self.run + '.json')
                race = subprocess.run([
                    sys.executable, '-X', 'utf8', '-u', str(ROOT / 'tests/concurrency/same_slot.py'),
                    '--requests', '100', '--min-tasks', '3',
                    '--date', (date.today() + timedelta(days=9)).isoformat(), '--output', str(race_path)],
                    cwd=ROOT, check=False,
                    env={**os.environ, 'PLATFORM_API_KEY': os.environ.get('LOADTEST_API_KEY', os.environ['PLATFORM_API_KEY'])})
                evidence = json.loads(race_path.read_text(encoding='utf-8')) if race_path.is_file() else None
                self.record('multi_task_concurrency', passed=race.returncode == 0, evidence=evidence)
                require(race.returncode == 0, '100-request race did not pass across at least three tasks')

    def scale_in(self):
        names = ['availability', 'booking']
        for name in names:
            require(self.targets[name]['MinCapacity'] == 2, 'Scale-in exercise expects a two-task baseline')
            self.fixed(name, 4)
        self.stable(names)
        self.record('scale_in_baseline', running_tasks_each=4,
                    scope='Controlled idle-scale-in exercise; separate from the full-load scale-out timeline')
        resumed = datetime.now(UTC)
        for name in names:
            target = self.targets[name]
            self.scaling.register_scalable_target(
                ServiceNamespace='ecs', ResourceId=target['ResourceId'],
                ScalableDimension=target['ScalableDimension'], MinCapacity=target['MinCapacity'],
                MaxCapacity=target['MaxCapacity'], SuspendedState=target.get('SuspendedState', {}))
            self.expected_counts.pop(name, None)
        self.record('dynamic_scale_in_resumed', resumed_at=resumed.isoformat())

        def scaled_in():
            states = {v['serviceName']: v for v in self.services() if v['serviceName'] in names}
            causes = {}
            for name in names:
                target = self.targets[name]
                rows = self.scaling.describe_scaling_activities(
                    ServiceNamespace='ecs', ResourceId=target['ResourceId'],
                    ScalableDimension=target['ScalableDimension'])['ScalingActivities']
                causes[name] = [{k: v.get(k) for k in ['StartTime', 'Description', 'Cause', 'StatusCode']}
                                for v in rows if v['StartTime'] >= resumed and 'AlarmLow' in str(v.get('Cause'))
                                and v['StatusCode'] == 'Successful']
            self.record('scale_in_sample', services={n: {'desired': v['desiredCount'], 'running': v['runningCount']}
                                                    for n, v in states.items()})
            ready = all(v['desiredCount'] == v['runningCount'] == 2 and v['pendingCount'] == 0
                        and causes[n] for n, v in states.items())
            return causes if ready else None

        causes = until(scaled_in, 'CPU-driven scale-in did not complete', timeout=1200, interval=30)
        self.record('automatic_idle_scale_in', passed=True, from_tasks_each=4, to_tasks_each=2,
                    activities=causes, scope='No manual desired-count reduction after scaling was resumed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['recovery', 'rollback', 'capacity', 'scale-in'])
    parser.add_argument('--start-day', type=int, default=11)
    parser.add_argument('--days', type=int, default=8)
    args = parser.parse_args()
    checks = Acceptance(args.command)
    try:
        if args.command == 'capacity':
            checks.capacity(args.start_day, args.days)
        else:
            getattr(checks, args.command.replace('-', '_'))()
        checks.records['completed'] = True
        if args.command != 'capacity':
            checks.records['passed'] = True
    except BaseException as exc:
        checks.records.update(passed=False, failure=str(exc))
        checks.save()
        raise
    finally:
        checks.restore()
        print(f'Evidence: {checks.path}', flush=True)


if __name__ == '__main__':
    main()
