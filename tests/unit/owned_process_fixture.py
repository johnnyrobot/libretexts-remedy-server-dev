"""Test cleanup targets a pinned kernel identity, never a recyclable PID."""
import os
import signal
from pathlib import Path


def start_ticks(pid):
    return int(Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[19])


def pin_process(pid, expected_ticks):
    descriptor = os.pidfd_open(pid)
    try:
        if start_ticks(pid) != expected_ticks:
            raise RuntimeError("Owned child identity changed before pinning")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def cleanup_pinned(descriptor):
    try:
        try:
            signal.pidfd_send_signal(descriptor, signal.SIGKILL)
        except ProcessLookupError:
            pass  # the pinned process exited; never fall back to its old PID
    finally:
        os.close(descriptor)
