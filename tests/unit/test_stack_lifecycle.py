"""No host isolation or state teardown before every owned stop is confirmed."""
import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('stack_lifecycle', Path(__file__).resolve().parents[2]/'.github/stack-proof/lifecycle.py')
lifecycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lifecycle)


@pytest.mark.parametrize('failure', ['first', 'last', None])
def test_owned_shutdown_retains_isolation_and_state_after_any_unconfirmed_stop(failure):
    owned = ['last', 'middle', 'first']; attempts = []; released = []; errors = []
    def stop(name):
        attempts.append(name)
        if name == failure:
            raise RuntimeError('synthetic stop remains unconfirmed')
        owned.remove(name)
    result = lifecycle.shutdown_owned(owned, stop, lambda: released.append('isolation-and-state'), errors.append)
    assert attempts == ['first', 'middle', 'last']
    assert result is (failure is None)
    assert released == (['isolation-and-state'] if failure is None else [])
    assert len(errors) == (0 if failure is None else 1)


def test_resource_release_failure_is_reported_without_claiming_completion():
    events = []; errors = []
    def release():
        events.append('release-attempt')
        raise OSError('synthetic resource release failed')
    result = lifecycle.shutdown_owned(['owned'], lambda name: events.append('stop-confirmed'), release, errors.append)
    assert result is True  # Stops confirmed; the recorded release error still fails the caller's proof.
    assert events == ['stop-confirmed', 'release-attempt']
    assert len(errors) == 1
