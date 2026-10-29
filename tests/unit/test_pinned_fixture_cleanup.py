"""Deterministic replacement-identity models; no actual process is signalled."""
import pytest
from tests.unit import owned_process_fixture as owned


def adapters(monkeypatch, current_ticks):
    closed, signals = [], []
    monkeypatch.setattr(owned.os, "pidfd_open", lambda pid: 101, raising=False)
    monkeypatch.setattr(owned, "start_ticks", lambda pid: current_ticks[0])
    monkeypatch.setattr(owned.os, "close", closed.append)
    monkeypatch.setattr(owned.signal, "pidfd_send_signal", lambda fd, sig: signals.append((fd, sig)), raising=False)
    return closed, signals


def test_matching_handle_stays_cleanup_target_after_numeric_pid_replacement(monkeypatch):
    identity = [123]
    closed, signals = adapters(monkeypatch, identity)
    handle = owned.pin_process(4242, 123)
    identity[0] = 999  # numeric PID now denotes an unrelated replacement
    owned.cleanup_pinned(handle)
    assert signals == [(101, owned.signal.SIGKILL)]
    assert closed == [101]


def test_replacement_before_pinning_is_never_signalled(monkeypatch):
    closed, signals = adapters(monkeypatch, [999])
    with pytest.raises(RuntimeError, match="identity changed"):
        owned.pin_process(4242, 123)
    assert closed == [101] and signals == []


def test_cleanup_diagnostic_error_still_closes_handle(monkeypatch):
    closed, _ = adapters(monkeypatch, [123])
    def denied(*args):
        raise PermissionError("synthetic handle failure")
    monkeypatch.setattr(owned.signal, "pidfd_send_signal", denied)
    with pytest.raises(PermissionError):
        owned.cleanup_pinned(101)
    assert closed == [101]
