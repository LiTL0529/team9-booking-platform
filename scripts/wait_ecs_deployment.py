"""Wait for the requested ECS revision, and fail if ECS rolls it back."""
from __future__ import annotations

import argparse
import json
import subprocess
import time


def deployed(service: dict, expected: str) -> bool:
    if service['desiredCount'] < 1:
        raise RuntimeError('Deployment verification requires at least one running task')
    if service['taskDefinition'] != expected:
        raise RuntimeError('ECS replaced the requested revision; deployment may have rolled back')
    deployments = service['deployments']
    if any(d.get('rolloutState') == 'FAILED' and d['taskDefinition'] == expected for d in deployments):
        raise RuntimeError('ECS deployment circuit breaker reported failure')
    return (len(deployments) == 1 and deployments[0].get('rolloutState') == 'COMPLETED'
            and service['runningCount'] == service['desiredCount'] and service['pendingCount'] == 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cluster', required=True)
    parser.add_argument('--service', required=True)
    parser.add_argument('--task-definition', required=True)
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            ['aws', 'ecs', 'describe-services', '--cluster', args.cluster, '--services', args.service],
            check=True, capture_output=True, text=True, encoding='utf-8',
        )
        response = json.loads(result.stdout)
        if response.get('failures') or len(response.get('services', [])) != 1:
            raise RuntimeError('ECS service lookup failed')
        service = response['services'][0]
        if deployed(service, args.task_definition):
            print(f'{args.service}: requested revision stable with {service["runningCount"]} running tasks')
            return
        print(f'{args.service}: running={service["runningCount"]}, pending={service["pendingCount"]}', flush=True)
        time.sleep(15)
    raise TimeoutError('Requested ECS deployment did not stabilize before the deadline')


if __name__ == '__main__':
    main()
