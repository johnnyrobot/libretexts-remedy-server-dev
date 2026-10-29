"""Linux subreaper lifetime, isolated from engine code and its threads.

Only this single thread forks/reaps. A child PID cannot recycle before we
reap it; pidfds target a kernel process, never a numeric PID or process group.
ECHILD after adoption is the completion proof, not an empty process census.
"""
from __future__ import annotations

import asyncio
import ctypes
import fcntl
import inspect
import multiprocessing
import os
import platform
import queue
import signal
import sys
import threading
import time
from pathlib import Path


def supported() -> bool:
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "amd64"}:
        return False
    try:
        handle = os.pidfd_open(os.getpid())
        try:
            signal.pidfd_send_signal(handle, 0)
        finally:
            os.close(handle)
        return Path("/proc/self/task").is_dir()
    except (AttributeError, OSError):
        return False


def receive_messages(connection, messages, closed) -> None:
    """Daemon reader: a partial IPC frame must never block lifetime cleanup."""
    try:
        while not closed.is_set():
            message = connection.recv()
            while not closed.is_set():
                try:
                    messages.put(message, timeout=.02)
                    break
                except queue.Full:
                    pass
    except (EOFError, OSError):
        while not closed.is_set():
            try:
                messages.put(("eof", None), timeout=.02)
                break
            except queue.Full:
                pass


def _send_messages(connection, messages, finished) -> None:
    try:
        while True:
            message = messages.get()
            connection.send(message)
            if message[0] in {"clean", "unresolved"}:
                break
    except (EOFError, OSError):
        pass
    finally:
        finished.set()


def _enable_adoption() -> None:
    library = ctypes.CDLL(None, use_errno=True)
    if library.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise RuntimeError("Kernel adoption unavailable.")
    enabled = ctypes.c_int()
    if library.prctl(37, ctypes.byref(enabled), 0, 0, 0) != 0 or enabled.value != 1:
        raise RuntimeError("Kernel adoption not established.")
    # Automatic SIGCHLD reaping would break the no-reuse invariant.
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)


def _reap() -> bool:
    """True iff the kernel confirms that no child remains, including zombies."""
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG | 0x40000000)  # __WALL: clone and SIGCHLD children
        except ChildProcessError:
            return True
        if pid == 0:
            return False


def _signal_children(sig: int) -> None:
    # All direct children are ours. Dead ones remain unreaped throughout this
    # loop, so pidfd_open cannot race PID reuse; later forks/adoptions are handled
    # on the next iteration. No /proc ancestry/group inference is involved.
    children = set()
    for task in Path("/proc/self/task").iterdir():
        try:
            children.update((task / "children").read_text().split())
        except FileNotFoundError:
            continue  # an IO thread retired; adoption remains in the thread group
    for raw_pid in children:
        try:
            descriptor = os.pidfd_open(int(raw_pid))
        except ProcessLookupError:
            continue
        try:
            try:
                signal.pidfd_send_signal(descriptor, sig)
            except ProcessLookupError:
                pass
        finally:
            os.close(descriptor)


def _cleanup() -> bool:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        until = time.monotonic() + 5
        while True:
            if _reap():
                return True
            # Discover/signal on EVERY iteration, including TERM-time forks and
            # subreaper adoptions after a fast double-fork, setsid or root exit.
            _signal_children(sig)
            if time.monotonic() >= until:
                break
            time.sleep(.02)
    return _reap()


def _compute(connection, function, args) -> None:
    from backend.app import execution
    execution._OWNED_CHILD = True
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGHUP, signal.SIG_DFL)
    os.setsid()

    async def invoke():
        result = function(*args, emit=connection.send)
        if inspect.isawaitable(result):
            result = await result
        connection.send(("result", result))
    try:
        asyncio.run(invoke())
    except BaseException:
        # No engine/provider error text crosses IPC or appears in tracebacks.
        try:
            connection.send(("error", None))
        except (EOFError, OSError):
            pass
    finally:
        os._exit(0)


def supervise(connection, function, args, parent_pid: int, ownership_path, deadline: float) -> None:
    """Keep adoption, lock and cleanup authority alive beyond compute return."""
    from backend.app import execution
    execution._OWNED_CHILD = True
    outgoing = queue.Queue(maxsize=64)
    sent = threading.Event()
    closed = threading.Event()
    sender = None
    lifetime = None
    compute_receive = None
    stopping = False
    def stop(_signal, _frame):
        nonlocal stopping
        stopping = True
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, stop)
    outcome, result = "error", None
    clean = False
    try:
        os.setsid()
        if not supported():
            raise RuntimeError("Strict execution unavailable.")
        _enable_adoption()
        lifetime = open(ownership_path, "a")
        fcntl.flock(lifetime, fcntl.LOCK_SH | fcntl.LOCK_NB)
        if os.getppid() != parent_pid:
            raise RuntimeError("Owner disappeared during handshake.")
        connection.send(("ready", None))
        dispatched = False
        while not stopping and time.monotonic() < deadline:
            if connection.poll(.02):
                command, _ = connection.recv()
                dispatched = command == "dispatch"
                break
            if os.getppid() != parent_pid:
                break
        # No compute or engine import before both ownership and parent handshake.
        if dispatched and not stopping and time.monotonic() < deadline and os.getppid() == parent_pid:
            compute_receive, compute_send = multiprocessing.Pipe(duplex=False)
            pid = os.fork()  # single-threaded supervisor at fork; compute never owns adoption
            if pid == 0:
                connection.close()
                lifetime.close()
                compute_receive.close()
                _compute(compute_send, function, args)
            compute_send.close()
            messages = queue.Queue(maxsize=64)
            threading.Thread(target=receive_messages, args=(compute_receive, messages, closed), daemon=True).start()
            sender = threading.Thread(target=_send_messages, args=(connection, outgoing, sent), daemon=True)
            sender.start()
            while not stopping and time.monotonic() < deadline:
                if os.getppid() != parent_pid:
                    break
                if connection.poll():
                    command, _ = connection.recv()
                    if command == "stop":
                        break
                try:
                    kind, data = messages.get(timeout=.01)
                except queue.Empty:
                    continue
                if kind == "update":
                    # Backpressure failure is a failed operation followed by
                    # cleanup, never an unbounded queue or a blocked supervisor.
                    outgoing.put_nowait((kind, data))
                elif kind == "result":
                    outcome, result = "ok", data
                    break
                elif kind in {"error", "eof"}:
                    break
            if time.monotonic() >= deadline:
                outcome, result = "timed_out", None
    except BaseException:
        outcome, result = "error", None
    try:
        clean = _cleanup()
    except BaseException:
        clean = False
    # A certificate is sent only after waitpid reports ECHILD. Even an unexpected
    # supervisor failure leaves the parent's durable unresolved marker intact.
    try:
        if sender is None:
            sender = threading.Thread(target=_send_messages, args=(connection, outgoing, sent), daemon=True)
            sender.start()
        outgoing.put(("clean", (outcome, result)) if clean else ("unresolved", None), timeout=.1)
        sent.wait(1)
    except BaseException:
        pass
    finally:
        closed.set()
        connection.close()
        if compute_receive is not None:
            compute_receive.close()
        if lifetime is not None:
            lifetime.close()
        os._exit(0 if clean and sent.is_set() else 70)
