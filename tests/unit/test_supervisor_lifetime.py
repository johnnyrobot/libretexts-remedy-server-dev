"""Actual HTTP/store/spawn regressions for LT-144's persistent supervisor."""
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import replace

import httpx
import pytest

from backend.app.supervisor import supported
from tests.unit.process_observer import process_snapshot
from tests.unit.test_execution_http import execution_settings, get_terminal, post_mode, wait_for_file

linux = pytest.mark.skipif(not supported(), reason="requires Linux amd64 subreaper/pidfds")


@pytest.mark.skipif(os.environ.get("REMEDY_FULL_RUNTIME_TESTS") != "1", reason="requires the actual shipping seccomp profile")
def test_shipping_pidfd_calls_work_and_unused_flag_variants_remain_denied():
    import errno
    assert supported()
    handle = os.pidfd_open(os.getpid())
    try:
        signal.pidfd_send_signal(handle, 0)
    finally:
        os.close(handle)
    with pytest.raises(OSError) as invalid:
        signal.pidfd_send_signal(-1, 0)
    assert invalid.value.errno == errno.EBADF  # reached kernel fd validation
    with pytest.raises(PermissionError):
        os.pidfd_open(os.getpid(), 1)  # unused flags refused by the filter
    with pytest.raises(PermissionError):
        signal.pidfd_send_signal(-1, 0, None, 1)


def _helper(state):
    # Independent OS lock remains held for the helper's whole actual lifetime.
    # A subsequent engine would record overlap if capacity were released early.
    source = """
import fcntl,json,os,pathlib,signal,sys,time
state=pathlib.Path(sys.argv[1])
lock=(state/'actual-work.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
(state/'helper.ready').write_text(str(os.getpid()))
time.sleep(8)
(state/'late-write').write_text('synthetic late write')
time.sleep(30)
"""
    child = subprocess.Popen([sys.executable, "-c", source, str(state)], start_new_session=True)
    until = time.monotonic() + 2
    while not (state / "helper.ready").exists():
        if child.poll() is not None or time.monotonic() >= until:
            raise RuntimeError("Synthetic helper failed to start.")
        time.sleep(.005)
    current = process_snapshot()[child.pid]
    (state / "helper.identity").write_text(json.dumps({"pid": child.pid, "created": current.identity.created}))


async def lifetime_engine(job, settings, *, emit):
    from pathlib import Path
    state = settings.backup_dir
    state.mkdir(parents=True, exist_ok=True)
    (state / (job.id + ".started")).write_text(str(os.getpid()))
    (state / "supervisor.pid").write_text(str(os.getppid()))
    mode = Path(job.input_path).read_text()
    if "term-spawn" in mode:
        def terminate(_sig, _frame):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            _helper(state)
            (state / "term-helper-created").touch()
            time.sleep(.35)
            os._exit(0)
        signal.signal(signal.SIGTERM, terminate)
        (state / "handler.ready").touch()
        await asyncio.sleep(30)
    elif "rapid-orphan" in mode or "buffer-result" in mode:
        if "buffer-result" in mode:
            emit(("update", {"stage": "buffer-parent"}))
        # This intermediary is born AND exits before the supervisor's first
        # cleanup census. Its setsid grandchild must be adopted by the kernel.
        intermediate = os.fork()
        if intermediate == 0:
            try:
                _helper(state)
            finally:
                os._exit(0)
        os.waitpid(intermediate, 0)
        (state / "intermediary-exited").touch()
    elif "supervisor-crash" in mode:
        await asyncio.sleep(30)
    elif "hold-second" in mode:
        while not (state / "release-second").exists():
            await asyncio.sleep(.01)
    else:
        import fcntl
        with (state / "actual-work.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                (state / "overlap").touch()
    output = Path(job.input_path).with_name("result.html")
    output.write_text("<html><body>synthetic retained sentinel</body></html>")
    return {"status": "done", "stage": "complete", "progress": 1.,
            "output_path": str(output), "result_media_type": "text/html"}


def _same_process(info):
    current = process_snapshot().get(info.identity.pid)
    return current is not None and not current.zombie and current.identity == info.identity


async def _guarded_cleanup(info):
    # Only a test's known process may be killed. The production implementation
    # uses unreaped children + pidfds and never this snapshot-based adapter.
    if _same_process(info):
        handle = os.pidfd_open(info.identity.pid)
        try:
            if _same_process(info):
                signal.pidfd_send_signal(handle, signal.SIGKILL)
        finally:
            os.close(handle)
    async with asyncio.timeout(5):
        while _same_process(info):
            await asyncio.sleep(.02)


@linux
@pytest.mark.parametrize("mode", ["buffer-result", "term-spawn", "rapid-orphan"])
async def test_descendants_stop_before_terminal_and_next_actual_engine(execution_settings, monkeypatch, mode):
    from backend.app.main import create_app
    # Startup has a declared bound, independent of the TERM-phase deadline.
    # The preserved 1s red case expired before any compute/handler entry.
    settings = replace(execution_settings, job_total_timeout_seconds=30 if mode == "term-spawn" else 12)
    app = create_app(settings, job_entrypoint=lifetime_engine)
    if mode == "buffer-result":
        update = app.state.store.update
        async def delayed_update(*args, **kwargs):
            if kwargs.get("stage") == "buffer-parent":
                await asyncio.sleep(1.2)  # compute returns/exits while parent cannot consume IPC
            return await update(*args, **kwargs)
        monkeypatch.setattr(app.state.store, "update", delayed_update)
    helper = None
    job_id = None
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                         headers={"X-API-Key": "fixture-key"}) as client:
                job_id = (await post_mode(client, mode)).json()["id"]
                if mode == "term-spawn":
                    await wait_for_file(settings.backup_dir / "handler.ready")
                    assert (settings.backup_dir / (job_id + ".started")).exists()
                    assert (await client.get("/v1/jobs/" + job_id)).json()["status"] == "running"
                    reservation = app.state.worker.reservation_for(job_id)
                    assert reservation.deadline > time.monotonic()
                    reservation.deadline = time.monotonic() - 1
                    await wait_for_file(settings.backup_dir / "term-helper-created")
                await wait_for_file(settings.backup_dir / "helper.identity")
                record = json.loads((settings.backup_dir / "helper.identity").read_text())
                helper = process_snapshot().get(record["pid"])
                job = await get_terminal(client, job_id)
                assert job["stage"] == ("timed_out" if mode == "term-spawn" else "complete"), job
                current = process_snapshot().get(record["pid"])
                assert current is None or current.zombie or list(current.identity.created) != record["created"]
                assert not (settings.backup_dir / "late-write").exists()
                next_id = (await post_mode(client, "fast")).json()["id"]
                assert (await get_terminal(client, next_id))["status"] == "done"
                assert not (settings.backup_dir / "overlap").exists()
                assert not (settings.backup_dir / "late-write").exists()
                assert not list(app.state.execution._unresolved.iterdir())
    finally:
        try:
            if os.environ.get("REMEDY_SANDBOX_AUDIT_DIR") and job_id is not None:
                from pathlib import Path
                job = await app.state.store.get(job_id)
                (Path(os.environ["REMEDY_SANDBOX_AUDIT_DIR"]) / f"supervisor-{mode}-diagnostic.json").write_text(
                    json.dumps({"job": job.to_dict() if job else None,
                                "markers": sorted(path.name for path in settings.backup_dir.glob("*"))}, indent=2))
        finally:
            if helper is not None:
                await _guarded_cleanup(helper)


@linux
async def test_diagnostic_write_failure_still_invokes_known_identity_cleanup(execution_settings, monkeypatch, tmp_path):
    """Run the real lifetime fixture, fault only its diagnostic filesystem I/O."""
    from pathlib import Path
    audit = tmp_path / "audit"
    audit.mkdir()
    monkeypatch.setenv("REMEDY_SANDBOX_AUDIT_DIR", str(audit))
    cleaned = []
    original_cleanup = _guarded_cleanup
    async def observed_cleanup(info):
        cleaned.append(info.identity)
        await original_cleanup(info)
    monkeypatch.setattr(sys.modules[__name__], "_guarded_cleanup", observed_cleanup)
    write = Path.write_text
    def unavailable(path, *args, **kwargs):
        if path == audit / "supervisor-buffer-result-diagnostic.json":
            raise OSError("synthetic diagnostic storage failure")
        return write(path, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", unavailable)
    with pytest.raises(OSError, match="synthetic diagnostic storage failure"):
        await test_descendants_stop_before_terminal_and_next_actual_engine(execution_settings, monkeypatch, "buffer-result")
    assert len(cleaned) == 1


@linux
@pytest.mark.parametrize("concurrency", [1, 2])
async def test_supervisor_crash_quarantines_running_and_queued_work_and_restart(execution_settings, concurrency):
    from backend.app.execution import CleanupUnresolved
    from backend.app.main import create_app
    settings = replace(execution_settings, worker_concurrency=concurrency)
    app = create_app(settings, job_entrypoint=lifetime_engine)
    compute = None
    try:
        with pytest.raises(CleanupUnresolved, match="Shutdown incomplete"):
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                             headers={"X-API-Key": "fixture-key"}) as client:
                    job_id = (await post_mode(client, "supervisor-crash")).json()["id"]
                    await wait_for_file(settings.backup_dir / "supervisor.pid")
                    compute_pid = int((settings.backup_dir / (job_id + ".started")).read_text())
                    compute = process_snapshot()[compute_pid]
                    supervisor = int((settings.backup_dir / "supervisor.pid").read_text())
                    second = None
                    if concurrency == 2:
                        second = (await post_mode(client, "hold-second")).json()["id"]
                        await wait_for_file(settings.backup_dir / (second + ".started"))
                    queued = (await post_mode(client, "fast")).json()["id"]
                    descriptor = os.pidfd_open(supervisor)
                    try:
                        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                    finally:
                        os.close(descriptor)
                    started = time.monotonic()
                    async with asyncio.timeout(15):
                        while (await client.get("/readyz")).status_code != 503:
                            await asyncio.sleep(.02)
                    if second is not None:
                        (settings.backup_dir / "release-second").touch()
                        assert (await get_terminal(client, second))["status"] == "done"
                    assert (await client.get("/healthz")).status_code == 200
                    assert (await post_mode(client, "fast")).status_code == 503
                    assert (await client.get("/v1/jobs/" + job_id)).json()["status"] == "running"
                    assert (await client.get("/v1/jobs/" + queued)).json()["status"] == "queued"
                    assert (await client.get("/v1/jobs/" + job_id + "/result")).status_code == 409
                    assert (await client.delete("/v1/jobs/" + job_id)).status_code == 409
                    assert _same_process(compute)  # unknown cleanup is NOT certified stopped
        assert time.monotonic() - started < 30
    finally:
        if compute is not None:
            await _guarded_cleanup(compute)
        # Simulate API process exit closing locks, while preserving its durable
        # crash evidence. A fresh API still must not recover/requeue anything.
        for lock in (app.state.execution._ownership_lock, app.state.execution._owner_lock):
            if lock is not None:
                lock.close()
    replacement = create_app(settings, job_entrypoint=lifetime_engine)
    with pytest.raises(RuntimeError, match="Unresolved engine ownership"):
        async with replacement.router.lifespan_context(replacement):
            pass
    assert (await replacement.state.store.get(job_id)).status == "running"
    assert (await replacement.state.store.get(queued)).status == "queued"


@pytest.mark.parametrize("force_unsupported", [True] if supported() else [True, False])
async def test_unsupported_runtime_refuses_before_staging_and_reports_not_ready(execution_settings, monkeypatch, force_unsupported):
    from backend.app import execution
    from backend.app.main import create_app
    if force_unsupported:
        monkeypatch.setattr(execution, "strict_execution_supported", lambda: False)
    app = create_app(execution_settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            before = set(execution_settings.job_dir.rglob("*"))
            for route in ["/v1/convert/html-to-pdf", "/v1/pdf/check", "/v1/quality/audit/pdf"]:
                response = await client.post(route, files={"file": ("fixture.html", b"<html>fixture</html>")})
                assert response.status_code == 503 and response.headers["retry-after"] == "5"
            assert set(execution_settings.job_dir.rglob("*")) == before
            assert not await app.state.store.list_by_statuses({"queued", "running", "done", "failed"})
            assert (await client.get("/readyz")).status_code == 503
            assert (await client.get("/healthz")).status_code == 200


def test_signals_use_pinned_kernel_handle_despite_numeric_pid_and_group_reuse(monkeypatch):
    from backend.app import supervisor
    # Deterministic kernel adapter: an opened handle pins the old birth even
    # if a numeric PID/PGID is reused before the signal syscall. A group/PID
    # based implementation would signal the unrelated replacement here.
    old_birth, unrelated_birth = object(), object()
    numeric_pid = {101: old_birth}
    handles, signalled, closed = {}, [], []
    class Children:
        def read_text(self):
            return "101"
    class Task:
        def __truediv__(self, name):
            assert name == "children"
            return Children()
    class Tasks:
        def iterdir(self):
            return [Task()]
    def open_handle(pid):
        handles[777] = numeric_pid[pid]
        numeric_pid[pid] = unrelated_birth
        return 777
    def signal_handle(handle, sig):
        signalled.append((handles[handle], sig))
    def forbid_numeric(*args):
        pytest.fail("numeric PID/group signal could target a reused unrelated process")
    monkeypatch.setattr(supervisor, "Path", lambda _: Tasks())
    monkeypatch.setattr(os, "pidfd_open", open_handle, raising=False)
    monkeypatch.setattr(signal, "pidfd_send_signal", signal_handle, raising=False)
    monkeypatch.setattr(os, "close", closed.append)
    monkeypatch.setattr(os, "kill", forbid_numeric)
    monkeypatch.setattr(os, "killpg", forbid_numeric)
    supervisor._signal_children(signal.SIGKILL)
    assert signalled == [(old_birth, signal.SIGKILL)]
    assert numeric_pid[101] is unrelated_birth
    assert closed == [777]


def test_empty_census_is_not_completion_and_wait_includes_clone_children(monkeypatch):
    from backend.app import supervisor
    def live_child(pid, options):
        assert pid == -1
        assert options & 0x40000000  # Linux __WALL, including non-SIGCHLD clones
        return 0, 0
    monkeypatch.setattr(os, "waitpid", live_child)
    assert supervisor._reap() is False
    def no_children(pid, options):
        raise ChildProcessError()
    monkeypatch.setattr(os, "waitpid", no_children)
    assert supervisor._reap() is True


async def test_failed_subreaper_probe_prevents_admission_and_queue_recovery(execution_settings, monkeypatch):
    from backend.app import execution, supervisor
    from backend.app.jobs import JobStore
    from backend.app.main import create_app
    monkeypatch.setattr(execution, "strict_execution_supported", lambda: True)
    monkeypatch.setattr(supervisor, "probe_adoption", lambda: False, raising=False)
    settings = execution_settings
    settings.job_dir.mkdir()
    source = settings.job_dir / "retained.html"
    source.write_text("<html>synthetic fixture</html>")
    store = JobStore(settings.job_store_path)
    running = await store.create(source, kind="convert_html_to_pdf")
    await store.update(running.id, status="running")
    queued = await store.create(source, kind="convert_html_to_pdf")
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        assert (await store.get(running.id)).status == "running"
        assert (await store.get(queued.id)).status == "queued"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            assert (await client.get("/readyz")).status_code == 503
            assert (await post_mode(client, "fast")).status_code == 503
            assert (await client.post("/v1/pdf/check", content=b"fixture")).status_code == 503
        assert len(await store.list_by_statuses({"queued", "running"})) == 2
        assert not list(settings.job_dir.glob("_staging-*"))
        assert source.is_file()
