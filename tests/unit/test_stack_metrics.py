"""Actual cgroup samples must precede confirmed owned-container teardown."""
import errno
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def measured(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('stack_lifecycle_metrics', ROOT / '.github/stack-proof/metrics.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    class Thread:
        def __init__(self, **kwargs): pass
        def start(self): pass
        def join(self, *args): pass
        def is_alive(self): return False
    monkeypatch.setattr(module.threading, 'Thread', Thread)
    proc = tmp_path / 'proc'
    (proc / '100').mkdir(parents=True)
    (proc / '100/cgroup').write_text('0::/owned\n')
    cgroups = tmp_path / 'cgroups'
    base = cgroups / 'owned'
    base.mkdir(parents=True)
    for name, raw in {'memory.max': '1024', 'pids.max': '8', 'cpu.max': '100000 100000',
                      'memory.peak': '128', 'pids.peak': '2', 'cpu.stat': 'usage_usec 10\n'}.items():
        (base / name).write_text(raw)
    monkeypatch.setattr(module, 'Path', lambda value: proc if value == '/proc' else cgroups if value == '/sys/fs/cgroup' else Path(value))
    metrics = module.Metrics()
    info = {'Id': 'a' * 64, 'Image': 'sha256:' + 'b' * 64, 'State': {'Status': 'running', 'Pid': 100, 'Running': True}}
    metrics.register('owned-server', info, {'memoryBytes': 1024, 'pids': 8, 'cpus': 1})
    stopped = {**info, 'State': {'Status': 'exited', 'Pid': 0, 'Running': False, 'Paused': False, 'Restarting': False,
                              'Dead': False, 'OOMKilled': False, 'Error': '', 'ExitCode': 143}}
    return metrics, info, stopped, base


def test_removed_cgroup_after_planned_confirmed_stop_retains_real_samples(measured):
    metrics, info, stopped, base = measured
    metrics.begin_stop(info['Id'])
    for path in base.iterdir(): path.unlink()
    base.rmdir()
    metrics.finish_stop(stopped)
    result = metrics.close()[info['Id']]
    assert not metrics.errors
    assert result['samples'] == 1 and result['memoryPeakBytes'] == 128 and result['pidPeak'] == 2
    assert result['stopConfirmed'] is True and result['finalSampleAvailable'] is False


def test_live_cgroup_error_is_never_waived_as_teardown(measured, monkeypatch):
    metrics, info, _, base = measured
    original = Path.read_text
    def fail(path, *args, **kwargs):
        if path == base / 'memory.max': raise OSError(errno.ENODEV, 'synthetic gone cgroup')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', fail)
    with pytest.raises(OSError): metrics.begin_stop(info['Id'])
    metrics.close()
    assert metrics.errors  # no actual samples cannot become acceptance


def test_unconfirmed_stop_and_wrong_identity_fail_closed(measured):
    metrics, info, stopped, _ = measured
    metrics.begin_stop(info['Id'])
    with pytest.raises(ValueError): metrics.finish_stop({**stopped, 'Id': 'c' * 64})
    with pytest.raises(ValueError): metrics.finish_stop(info)
    metrics.close()
    assert any('unconfirmed' in message for message in metrics.errors)


@pytest.mark.parametrize('error_number', [errno.ENODEV, errno.EACCES, errno.EIO])
def test_only_gone_cgroup_errors_can_follow_confirmed_stop(measured, monkeypatch, error_number):
    metrics, info, stopped, base = measured
    metrics.begin_stop(info['Id'])
    original = Path.read_text
    def fail(path, *args, **kwargs):
        if path == base / 'memory.max': raise OSError(error_number, 'synthetic final read failure')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', fail)
    if error_number == errno.ENODEV:
        metrics.finish_stop(stopped)
        assert not metrics.errors
        assert metrics.close()[info['Id']]['finalReadUnavailableErrno'] == errno.ENODEV
    else:
        with pytest.raises(OSError): metrics.finish_stop(stopped)
        metrics.close()
        assert any('unconfirmed' in error for error in metrics.errors)


def test_created_container_is_not_a_confirmed_exit(measured):
    metrics, info, stopped, _ = measured
    metrics.begin_stop(info['Id'])
    with pytest.raises(ValueError):
        metrics.finish_stop({**stopped, 'State': {**stopped['State'], 'Status': 'created'}})


def test_live_collector_cannot_close_as_success_without_a_confirmed_stop(measured):
    metrics, _, _, _ = measured
    metrics.close()
    assert any('unconfirmed' in error for error in metrics.errors)


def test_failed_collector_join_does_not_wait_on_its_lock(measured):
    metrics, _, _, _ = measured
    metrics.thread.is_alive = lambda: True
    class UnavailableLock:
        def __enter__(self): raise AssertionError('hung collector lock must not be acquired')
        def __exit__(self, *args): pass
    metrics.lock = UnavailableLock()
    assert metrics.close() == {}
    assert metrics.errors == ['metrics_collector_did_not_stop']
