import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

spec = importlib.util.spec_from_file_location('deploy', Path(__file__).parents[2] / 'scripts' / 'aws_deploy.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def test_parking_and_resuming_preserves_tuned_service_limits(monkeypatch, tmp_path):
    aas = MagicMock()
    ecs = MagicMock()
    maxima = {'merchant': 2, 'catalogue': 2, 'availability': 12, 'booking': 8, 'notification': 5}
    aas.describe_scalable_targets.return_value = {'ScalableTargets': [
        {'ResourceId': f'service/booking-test/{name}', 'MaxCapacity': value} for name, value in maxima.items()]}
    monkeypatch.setattr(deploy, 'REPO', tmp_path)
    monkeypatch.setattr(deploy, 'tf_outputs', lambda: {'ecs_cluster': 'booking-test'})
    monkeypatch.setattr(deploy, 'session', lambda: SimpleNamespace(
        client=lambda name: aas if name == 'application-autoscaling' else ecs))
    deploy.step_scale(SimpleNamespace(tasks=0))
    aas.describe_scalable_targets.return_value = {'ScalableTargets': [
        {'ResourceId': f'service/booking-test/{name}', 'MaxCapacity': 0} for name in maxima]}
    aas.register_scalable_target.reset_mock()
    deploy.step_scale(SimpleNamespace(tasks=2))
    observed = {v.kwargs['ResourceId'].split('/')[-1]: v.kwargs['MaxCapacity']
                for v in aas.register_scalable_target.call_args_list}
    assert observed == maxima
