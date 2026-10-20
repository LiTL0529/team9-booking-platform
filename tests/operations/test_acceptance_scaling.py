import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import aws_acceptance  # noqa: E402


def test_recovery_wait_tracks_autoscaling_but_enforces_suspended_counts(monkeypatch):
    checks = object.__new__(aws_acceptance.Acceptance)
    checks.expected_counts = {}
    checks.expected_deployments = {}
    checks.services = lambda: [{'serviceName': 'booking', 'desiredCount': 3, 'runningCount': 3,
                                'pendingCount': 0, 'deployments': [{'id': 'current', 'rolloutState': 'COMPLETED'}]}]
    checks.record = lambda *args, **kwargs: None

    def once(fn, label, timeout):
        value = fn()
        if not value:
            raise TimeoutError(label)
        return value

    monkeypatch.setattr(aws_acceptance, 'until', once)
    checks.stable(['booking'])  # A healthy scale-in from the original five tasks is allowed.
    checks.expected_counts['booking'] = 4
    with pytest.raises(TimeoutError):
        checks.stable(['booking'])  # A controlled fixed-four test must actually reach four.
