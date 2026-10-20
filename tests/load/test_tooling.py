"""Regression checks for workload inventory and evidence classification."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


prepare = module('prepare_load_test')
runner = module('aws_loadtest')


def test_preflight_pages_deduplicates_and_keeps_disjoint_phase_inventory(monkeypatch):
    calls = []

    def page(gateway, key, params):
        calls.append(params)
        return {'slots': [{'slot_id': f's{i}', 'merchant_id': 'm1'} for i in
                          ([0, 1] if params['offset'] == 0 else [1, 2, 3])],
                'has_more': params['offset'] == 0}

    monkeypatch.setattr(prepare, 'get_json', page)
    manifest, slots = prepare.prepare('http://localhost', 'not-logged',
                                     [{'name': 'a', 'rate': 5, 'seconds': 2},
                                      {'name': 'b', 'rate': 5, 'seconds': 2}], 1, 1)
    assert slots == ['s0', 's1', 's2', 's3']
    assert [p['booking_offset'] for p in manifest['phases']] == [0, 2]
    assert manifest['required_booking_slots'] == 4
    assert [c['offset'] for c in calls] == [0, 2]
    assert 'not-logged' not in str(manifest)


def test_preflight_refuses_to_silently_reduce_booking_load(monkeypatch):
    monkeypatch.setattr(prepare, 'get_json', lambda *a: {'slots': [], 'has_more': False})
    with pytest.raises(ValueError, match='insufficient free inventory'):
        prepare.prepare('http://localhost', 'key', [{'name': 'a', 'rate': 5, 'seconds': 2}], 1, 1)


def test_preflight_rejects_inconsistent_pagination(monkeypatch):
    monkeypatch.setattr(prepare, 'get_json', lambda *a: {'slots': [], 'has_more': True})
    with pytest.raises(ValueError, match='another page'):
        prepare.prepare('http://localhost', 'key', [{'name': 'a', 'rate': 5, 'seconds': 2}], 1, 1)


def summary(successes=2):
    return {'workload': {'phases': [{'name': 'peak', 'rate': 5, 'seconds': 2,
                                    'expected_searches': 8, 'expected_bookings': 2}]},
            'metrics': {
                'search_requests{phase:peak}': {'values': {'count': 8}},
                'booking_requests{phase:peak}': {'values': {'count': 2}},
                'successful_bookings{phase:peak}': {'values': {'count': successes}},
                'search_latency{phase:peak}': {'values': {'p(95)': 100}},
                'booking_latency{phase:peak}': {'values': {'p(95)': 50}},
                'successful_booking_latency{phase:peak}': {'values': {'p(95)': 1500}},
                'unexpected_errors': {'thresholds': {'rate<0.01': {'ok': True}}}}}


def test_conflict_or_overall_latency_cannot_prove_success_latency_target():
    result = runner.assess(summary())
    assert result['workload_valid']
    assert result['peak_phase']['actual_http_rps'] == 5
    assert result['peak_phase']['booking_share'] == .2
    assert not result['peak_phase']['booking_target_met']


def test_no_successes_cannot_pass_even_with_zero_latency():
    data = summary(0)
    data['metrics']['successful_booking_latency{phase:peak}']['values']['p(95)'] = 0
    assert not runner.assess(data)['peak_phase']['booking_target_met']


def test_dropped_iterations_invalidate_workload():
    data = summary()
    data['metrics']['dropped_iterations'] = {'values': {'count': 1}}
    assert not runner.assess(data)['workload_valid']


def test_missing_measurement_does_not_report_targets_met():
    result = runner.assess({'metrics': {}})
    assert not result['workload_valid']
    assert not result['all_thresholds_met']
    with pytest.raises(ValueError, match='No complete measured'):
        runner.parse_summary('echo K6_SUMMARY_BEGIN\necho K6_SUMMARY_END')
    import json
    echo = 'echo K6_SUMMARY_BEGIN\ntr -d newline\necho K6_SUMMARY_END\n'
    measured = 'K6_SUMMARY_BEGIN\n' + json.dumps(summary()) + '\nK6_SUMMARY_END\n'
    assert runner.parse_summary(echo + measured + echo + echo) == summary()


def test_inventory_exhaustion_invalidates_workload():
    data = summary()
    data['metrics']['inventory_errors'] = {'values': {'count': 1}}
    assert not runner.assess(data)['workload_valid']
