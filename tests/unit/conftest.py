"""The full runtime job must prove its required Linux production profile."""
import os
import json
import signal
import sys

import pytest


def pytest_sessionstart(session):
    if os.environ.get("REMEDY_FULL_RUNTIME_TESTS") == "1":
        from backend.app.supervisor import probe_adoption
        if not probe_adoption():
            # Preserve the actual kernel errno under the shipping filter before
            # refusing collection. An invalid fd distinguishes a denied syscall
            # (EPERM) from an allowed syscall's normal fd validation (EBADF).
            report = {}
            try:
                handle = os.pidfd_open(os.getpid())
            except OSError as error:
                report["pidfd_open_errno"] = error.errno
            else:
                try:
                    report["pidfd_open_errno"] = 0
                    try:
                        signal.pidfd_send_signal(handle, 0)
                        report["pidfd_send_signal_self_errno"] = 0
                    except OSError as error:
                        report["pidfd_send_signal_self_errno"] = error.errno
                finally:
                    os.close(handle)
            try:
                signal.pidfd_send_signal(-1, 0)
            except OSError as error:
                report["pidfd_send_signal_invalid_fd_errno"] = error.errno
            print("shipping-pidfd-probe: " + json.dumps(report, sort_keys=True), file=sys.stderr)
            raise pytest.UsageError("Required Linux amd64 pidfd/subreaper production profile is unavailable; full-runtime verification cannot skip it.")
