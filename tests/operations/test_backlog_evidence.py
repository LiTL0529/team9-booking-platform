import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from aws_backlog_acceptance import queue_scaled_while_busy  # noqa: E402


def test_requested_or_late_capacity_does_not_prove_backlog_scale_out():
    activity = [{'Cause': 'alarm triggered policy test-notification-sqs-backlog'}]
    assert not queue_scaled_while_busy(activity, [{'running': 2, 'desired': 5, 'visible': 100, 'in_flight': 5}])
    assert not queue_scaled_while_busy(activity, [{'running': 5, 'desired': 5, 'visible': 0, 'in_flight': 0}])


def test_actual_running_capacity_with_outstanding_messages_proves_scale_out():
    assert queue_scaled_while_busy([{'Cause': 'test-notification-sqs-backlog'}],
                                  [{'running': 3, 'visible': 10, 'in_flight': 5}])
