"""A transient proc census row cannot become sandbox success or a live error waiver."""
import errno
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


def observer_with_row(tmp_path, monkeypatch, after_state, after_ticks='123', error_number=errno.ENODEV):
    spec = importlib.util.spec_from_file_location('stack_census_observer', ROOT / '.github/stack-proof/observer.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    proc = tmp_path / '100'
    (proc / 'ns').mkdir(parents=True)
    (proc / 'status').write_text('NSpid:\t100 7\nUid:\t999 999 999 999\nNoNewPrivs:\t1\nCapEff:\t0000000000000000\nSeccomp:\t2\nSeccomp_filters:\t1\n')
    def stat(state, ticks):
        return '100 (synthetic) ' + ' '.join([state, '1', '100', *(['0'] * 16), ticks])
    (proc / 'stat').write_text(stat('R', '123'))
    (proc / 'cmdline').write_bytes(b'node\0')
    monkeypatch.setattr(module, 'Path', lambda value: tmp_path if value == '/proc' else Path(value))
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='PID\n100\n'))
    def unavailable(path):
        if after_state is None:
            (proc / 'stat').unlink(missing_ok=True)
        else:
            (proc / 'stat').write_text(stat(after_state, after_ticks))
        raise OSError(error_number, 'synthetic proc read failure')
    monkeypatch.setattr(module.os, 'readlink', unavailable)
    return module.Observer({})


@pytest.mark.parametrize('after_state,after_ticks', [('Z', '123'), ('X', '123'), (None, '123'), ('R', '124')])
def test_enodev_is_counted_only_after_the_census_identity_has_ended(tmp_path, monkeypatch, after_state, after_ticks):
    observer = observer_with_row(tmp_path, monkeypatch, after_state, after_ticks)
    assert observer.processes('owned-container') == {}
    assert observer.vanished_rows['ENODEVAfterTaskExit'] == 1
    assert observer.records == []  # no fabricated owner/renderer observation


def test_enodev_for_the_same_live_identity_remains_a_hard_error(tmp_path, monkeypatch):
    observer = observer_with_row(tmp_path, monkeypatch, 'R')
    with pytest.raises(OSError) as error:
        observer.processes('owned-container')
    assert error.value.errno == errno.ENODEV
    assert observer.vanished_rows.get('ENODEVAfterTaskExit', 0) == 0
    assert observer.records == []


@pytest.mark.parametrize('error_number', [errno.EACCES, errno.EIO])
def test_unrelated_proc_errors_are_never_reclassified_as_exit_churn(tmp_path, monkeypatch, error_number):
    observer = observer_with_row(tmp_path, monkeypatch, 'Z', error_number=error_number)
    with pytest.raises(OSError) as error:
        observer.processes('owned-container')
    assert error.value.errno == error_number
    assert observer.vanished_rows['ENODEVAfterTaskExit'] == 0


@pytest.mark.parametrize('after_state,after_ticks', [('Z', ''), ('R', 'not-a-number')])
def test_malformed_stat_cannot_certify_an_exited_or_reused_identity(tmp_path, monkeypatch, after_state, after_ticks):
    observer = observer_with_row(tmp_path, monkeypatch, after_state, after_ticks)
    with pytest.raises((ValueError, IndexError)):
        observer.processes('owned-container')
    assert observer.vanished_rows['ENODEVAfterTaskExit'] == 0
    assert observer.records == []
