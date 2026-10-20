import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('waiter', Path(__file__).resolve().parents[2] / 'scripts/wait_ecs_deployment.py')
waiter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(waiter)


def service():
    return {'desiredCount': 2, 'runningCount': 2, 'pendingCount': 0, 'taskDefinition': 'new',
            'deployments': [{'taskDefinition': 'new', 'rolloutState': 'COMPLETED'}]}


def test_requested_revision_must_finish_and_old_tasks_must_drain():
    value = service()
    assert waiter.deployed(value, 'new')
    value['deployments'].append({'taskDefinition': 'old', 'rolloutState': 'COMPLETED'})
    assert not waiter.deployed(value, 'new')


def test_successful_rollback_is_not_successful_release():
    value = service()
    value['taskDefinition'] = 'old'
    with pytest.raises(RuntimeError, match='rolled back'):
        waiter.deployed(value, 'new')


def test_circuit_breaker_failure_fails_release():
    value = service()
    value['deployments'][0]['rolloutState'] = 'FAILED'
    with pytest.raises(RuntimeError, match='circuit breaker'):
        waiter.deployed(value, 'new')


def test_parked_environment_cannot_pass_deployment_verification():
    value = service()
    value.update(desiredCount=0, runningCount=0)
    with pytest.raises(RuntimeError, match='at least one'):
        waiter.deployed(value, 'new')
