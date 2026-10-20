import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('smoke', Path(__file__).parents[1] / 'e2e' / 'smoke_test.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_smoke_retries_competing_reservations_with_distinct_keys(monkeypatch):
    monkeypatch.setattr(smoke.random.SystemRandom, 'shuffle', lambda self, slots: None)
    public = SimpleNamespace(call=lambda *a, **k: SimpleNamespace(json=lambda: {
        'slots': [{'slot_id': 'taken'}, {'slot_id': 'free'}]}))
    requests = []

    def book(slot, key):
        requests.append((slot, key))
        return SimpleNamespace(status_code=409 if slot == 'taken' else 201, text='test')

    day, slot, key, response = smoke.reserve_slot(public, SimpleNamespace(book=book), 1)
    assert slot['slot_id'] == 'free' and response.status_code == 201
    assert len(requests) == 2 and requests[0][1] != requests[1][1]


def test_smoke_does_not_retry_permission_or_server_failures():
    public = SimpleNamespace(call=lambda *a, **k: SimpleNamespace(json=lambda: {'slots': [{'slot_id': 's'}]}))
    for status in [403, 500]:
        customer = SimpleNamespace(book=lambda *a, code=status: SimpleNamespace(status_code=code, text=str(code)))
        with pytest.raises(AssertionError, match=str(status)):
            smoke.reserve_slot(public, customer, 1)
