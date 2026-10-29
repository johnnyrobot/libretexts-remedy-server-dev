"""The full runtime job must prove its required Linux production profile."""
import os

import pytest


def pytest_sessionstart(session):
    if os.environ.get("REMEDY_FULL_RUNTIME_TESTS") == "1":
        from backend.app.supervisor import probe_adoption
        if not probe_adoption():
            raise pytest.UsageError("Required Linux amd64 pidfd/subreaper production profile is unavailable; full-runtime verification cannot skip it.")
