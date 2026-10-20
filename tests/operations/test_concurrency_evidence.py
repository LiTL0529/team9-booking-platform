import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('same_slot', Path(__file__).parents[1] / 'concurrency' / 'same_slot.py')
race = importlib.util.module_from_spec(spec)
spec.loader.exec_module(race)


def test_network_failures_never_count_as_booking_conflicts():
    result = race.assess_results([(201, 'one'), (409, 'two'), (0, 'network-error')], 3, 2)
    assert not result['passed']


def test_unknown_host_does_not_prove_multiple_booking_tasks():
    assert not race.assess_results([(201, 'one'), (409, '?')], 2, 2)['passed']


def test_one_success_and_all_conflicts_across_known_tasks_passes():
    assert race.assess_results([(201, 'one'), (409, 'two'), (409, 'three')], 3, 3)['passed']
