"""Bounded work through HTTP, persisted jobs, and actual spawned children."""
import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from backend.app.supervisor import supported, supervise as original_supervise
pytestmark = pytest.mark.skipif(not supported(), reason="strict execution requires Linux amd64 with pidfds")


@pytest.fixture
def execution_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "10000/minute")
    monkeypatch.setenv("RATE_LIMIT_UPLOADS", "10000/minute")
    monkeypatch.setenv("JOB_STORE_PATH", str(tmp_path / "import.db"))
    monkeypatch.setenv("JOB_DIR", str(tmp_path / "import-jobs"))
    from backend.app.config import Settings
    return Settings(api_key="fixture-key", job_store_path=tmp_path / "jobs.db",
                    job_dir=tmp_path / "jobs", backup_dir=tmp_path / "backups")


async def test_overload_is_rejected_before_staging_or_persistence(execution_settings):
    from backend.app.main import create_app
    app = create_app(execution_settings)
    entered, release = asyncio.Event(), asyncio.Event()
    async def blocked(job):
        entered.set()
        await release.wait()
    app.state.worker.runner = blocked
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            upload = {"file": ("source.html", b"<html><body>fixture</body></html>")}
            try:
                first = await client.post("/v1/convert/html-to-pdf", files=upload)
                assert first.status_code == 202
                await asyncio.wait_for(entered.wait(), 5)
                for _ in range(8):
                    assert (await client.post("/v1/convert/html-to-pdf", files=upload)).status_code == 202
                before = set(execution_settings.job_dir.rglob("*"))
                excess = await client.post("/v1/convert/html-to-pdf", files=upload)
                assert excess.status_code == 503
                assert excess.headers["retry-after"] == "5"
                assert set(execution_settings.job_dir.rglob("*")) == before
                assert len(await app.state.store.list_by_statuses({"queued", "running"})) == 9
                assert (await client.get("/healthz")).status_code == 200
            finally:
                release.set()


async def controlled_job(job, settings, *, emit):
    """A real child-process engine adapter with deterministic local failure modes."""
    mode = Path(job.input_path).read_text()
    state = settings.backup_dir
    state.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (state / "actual-work.lock").open("a") as lock:
        # An independent OS lock detects excess actual work across children.
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            (state / "overlapped").touch()
            raise RuntimeError("overlapping actual work")
        (state / (job.id + ".started")).write_text(str(os.getpid()))
        if "hang" in mode or "orphan" in mode:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            child = subprocess.Popen([sys.executable, "-c",
                "import signal,time,pathlib,sys; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                "time.sleep(12); pathlib.Path(sys.argv[1]).write_text('late')", str(state / "late")], start_new_session="detached" in mode)
            (state / (job.id + ".descendant")).write_text(str(child.pid))
            if "hang" in mode:
                await asyncio.sleep(30)
        elif "crash" in mode:
            os._exit(9)
        elif "slow" in mode:
            await asyncio.sleep(1)
        output = Path(job.input_path).with_name("result.html")
        output.write_text("<html><body>Retained sentinel</body></html>")
        return {"status": "done", "stage": "complete", "progress": 1.0,
                "output_path": str(output), "result_media_type": "text/html"}


async def controlled_direct(settings, wire_scope, body, *, emit):
    (settings.backup_dir / "direct.started").write_text(str(os.getpid()))
    await asyncio.sleep(1)
    return 200, [(b"content-type", b"application/json")], b'{"ok":true}'


async def wait_for_file(path):
    async with asyncio.timeout(10):
        while not path.exists():
            await asyncio.sleep(0.01)


async def get_terminal(client, job_id):
    async with asyncio.timeout(15):
        while True:
            response = await client.get("/v1/jobs/" + job_id)
            job = response.json()
            if job["status"] in {"done", "failed"}:
                return job
            await asyncio.sleep(0.025)


async def post_mode(client, mode):
    return await client.post("/v1/convert/html-to-pdf", files={"file": ("source.html", f"<html>{mode}</html>".encode())})


async def test_timeout_keeps_ownership_until_process_group_stops_and_recovers(execution_settings):
    from dataclasses import replace
    from backend.app.main import create_app
    settings = replace(execution_settings, job_total_timeout_seconds=0.7)
    app = create_app(settings, job_entrypoint=controlled_job)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            response = await post_mode(client, "hang")
            job_id = response.json()["id"]
            await wait_for_file(settings.backup_dir / (job_id + ".descendant"))
            await asyncio.sleep(0.8)
            # TERM was ignored. Capacity/state remain owned throughout grace.
            assert (await client.get("/v1/jobs/" + job_id)).json()["status"] == "running"
            assert (await client.delete("/v1/jobs/" + job_id)).status_code == 409
            assert (await client.get("/v1/jobs/" + job_id + "/result")).status_code == 409
            assert (await asyncio.wait_for(client.get("/healthz"), 0.5)).status_code == 200
            failed = await get_terminal(client, job_id)
            assert failed["status"] == "failed" and failed["stage"] == "timed_out"
            table = process_table()
            owned = [int((settings.backup_dir / (job_id + suffix)).read_text()) for suffix in [".started", ".descendant"]]
            assert all(pid not in table or table[pid][1].startswith("Z") for pid in owned)
            assert not (settings.backup_dir / "late").exists()
            succeeding = (await post_mode(client, "fast")).json()["id"]
            job = await get_terminal(client, succeeding)
            assert job["status"] == "done", job
            assert (await client.get("/v1/jobs/" + succeeding + "/result")).status_code == 200
            await asyncio.sleep(0.2)
            assert not (settings.backup_dir / "late").exists()
            assert not (settings.backup_dir / "overlapped").exists()


async def test_direct_operations_share_admission_and_leave_health_responsive(execution_settings):
    from dataclasses import replace
    from backend.app.main import create_app
    settings = replace(execution_settings, worker_max_pending=1)
    settings.backup_dir.mkdir()
    app = create_app(settings, job_entrypoint=controlled_job, direct_entrypoint=controlled_direct)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            checking = asyncio.create_task(client.post("/v1/pdf/check", content=b"fixture"))
            await wait_for_file(settings.backup_dir / "direct.started")
            queued = await post_mode(client, "fast")
            assert queued.status_code == 202
            before = set(settings.job_dir.rglob("*"))
            excess = await client.post("/v1/office/check", content=b"fixture")
            assert excess.status_code == 503 and excess.headers["retry-after"] == "5"
            assert set(settings.job_dir.rglob("*")) == before
            assert (await asyncio.wait_for(client.get("/healthz"), .5)).status_code == 200
            assert not (settings.backup_dir / (queued.json()["id"] + ".started")).exists()
            assert (await checking).json() == {"ok": True}
            assert (await get_terminal(client, queued.json()["id"]))["status"] == "done"
            assert not list(settings.job_dir.glob("_request-*"))


async def test_queued_job_expiry_does_not_start_actual_work(execution_settings):
    from dataclasses import replace
    from backend.app.main import create_app
    settings = replace(execution_settings, job_total_timeout_seconds=.7)
    app = create_app(settings, job_entrypoint=controlled_job)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            running = (await post_mode(client, "hang")).json()["id"]
            await wait_for_file(settings.backup_dir / (running + ".started"))
            queued = (await post_mode(client, "fast")).json()["id"]
            assert (await get_terminal(client, running))["status"] == "failed"
            expired = await get_terminal(client, queued)
            assert expired["stage"] == "timed_out"
            assert not (settings.backup_dir / (queued + ".started")).exists()
            assert (settings.job_dir / queued / "input.html").is_file()


async def test_real_office_check_is_bounded_process_and_retains_contract(execution_settings, tmp_path):
    from backend.app.main import create_app
    from tests.unit.office_fixtures import make_docx
    app = create_app(execution_settings)
    source = make_docx(tmp_path / "fixture.docx", body_paragraphs=["Retained sentinel"])
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            response = await client.post("/v1/office/check", files={"file": (source.name, source.read_bytes())})
            assert response.status_code == 200, response.text
            assert response.json()["file_type"] == "docx"
            assert response.json()["package_valid"] is True
            assert not list(execution_settings.job_dir.glob("_request-*"))


async def test_shutdown_kills_owned_work_preserves_queue_and_restart_recovers(execution_settings):
    from backend.app.main import create_app
    settings = execution_settings
    app = create_app(settings, job_entrypoint=controlled_job)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                 headers={"X-API-Key": "fixture-key"}) as client:
        async with app.router.lifespan_context(app):
            running = (await post_mode(client, "hang")).json()["id"]
            await wait_for_file(settings.backup_dir / (running + ".started"))
            queued = (await post_mode(client, "fast")).json()["id"]
            started = time.monotonic()
        assert time.monotonic() - started < 12
        assert (await client.get("/v1/jobs/" + running)).json()["status"] == "failed"
        assert (await client.get("/v1/jobs/" + queued)).json()["status"] == "queued"
        assert not (settings.backup_dir / (queued + ".started")).exists()
        assert (await post_mode(client, "fast")).status_code == 503
    replacement = create_app(settings, job_entrypoint=controlled_job)
    async with replacement.router.lifespan_context(replacement):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=replacement), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            assert (await get_terminal(client, queued))["status"] == "done"
            assert (settings.job_dir / running / "input.html").is_file()
            assert not (settings.backup_dir / "overlapped").exists()
            assert not (settings.backup_dir / "late").exists()


async def test_crashed_child_does_not_wedge_subsequent_jobs(execution_settings):
    from backend.app.main import create_app
    app = create_app(execution_settings, job_entrypoint=controlled_job)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            crashed = (await post_mode(client, "crash")).json()["id"]
            assert (await get_terminal(client, crashed))["status"] == "failed"
            fast = (await post_mode(client, "fast")).json()["id"]
            assert (await get_terminal(client, fast))["status"] == "done"


async def test_direct_cancellation_waits_for_exit_and_releases_admission(execution_settings):
    from backend.app.main import create_app
    settings = execution_settings
    settings.backup_dir.mkdir()
    app = create_app(settings, job_entrypoint=controlled_job, direct_entrypoint=controlled_direct)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            checking = asyncio.create_task(client.post("/v1/pdf/check", content=b"fixture"))
            await wait_for_file(settings.backup_dir / "direct.started")
            pid = int((settings.backup_dir / "direct.started").read_text())
            checking.cancel()
            with pytest.raises(asyncio.CancelledError):
                await checking
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
            assert not list(settings.job_dir.glob("_request-*"))
            fast = (await post_mode(client, "fast")).json()["id"]
            assert (await get_terminal(client, fast))["status"] == "done"


async def test_restart_respects_persisted_expiry_and_single_owner(execution_settings):
    from datetime import datetime, timedelta, timezone
    from backend.app.jobs import JobStore
    from backend.app.main import create_app
    settings = execution_settings
    settings.job_dir.mkdir()
    source = settings.job_dir / "recovery.html"
    source.write_text("<html>fast</html>")
    store = JobStore(settings.job_store_path)
    expired = await store.create(source, kind="convert_html_to_pdf", deadline_at=(
        datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    interrupted = await store.create(source, kind="convert_html_to_pdf")
    await store.update(interrupted.id, status="running")
    app = create_app(settings, job_entrypoint=controlled_job)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            assert (await get_terminal(client, expired.id))["stage"] == "timed_out"
            assert (await client.get("/v1/jobs/" + interrupted.id)).json()["stage"] == "interrupted"
            assert source.is_file()
            second = create_app(settings)
            with pytest.raises(RuntimeError, match="already has an owner"):
                async with second.router.lifespan_context(second):
                    pass
            assert not (settings.backup_dir / (expired.id + ".started")).exists()


@pytest.mark.parametrize("field,value", [("worker_max_pending", 0), ("worker_concurrency", 0),
                                         ("job_total_timeout_seconds", 0),
                                         ("job_total_timeout_seconds", float("inf")),
                                         ("job_total_timeout_seconds", float("nan"))])
def test_limits_reject_unbounded_or_nonpositive_values(execution_settings, field, value):
    from dataclasses import replace
    assert replace(execution_settings, **{field: value}).validation_errors()


def process_table():
    """Independent OS observation: no engine/controller implementation imports."""
    with subprocess.Popen(["/bin/ps", "-axo", "pid=,ppid=,stat="],
                          stdout=subprocess.PIPE, text=True) as process:
        output, _ = process.communicate(timeout=2)
        assert process.returncode == 0
        return {int(pid): (int(parent), state) for pid, parent, state in
                (line.split() for line in output.splitlines()) if int(pid) != process.pid}


def process_descendants(table, parent):
    descendants = {parent}
    for _ in range(20):
        descendants |= {pid for pid, (ppid, state) in table.items() if ppid in descendants and not state.startswith("Z")}
    return descendants - {parent}


@pytest.mark.skipif(os.environ.get("REMEDY_FULL_RUNTIME_TESTS") != "1", reason="requires installed Chromium/full runtime")
async def test_real_chromium_timeout_stops_all_observed_driver_browser_descendants(execution_settings):
    from dataclasses import replace
    from backend.app.main import create_app
    settings = replace(execution_settings, job_total_timeout_seconds=4)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            # Warm the multiprocessing tracker before measuring descendants.
            warm = await client.post("/v1/convert/html-to-pdf", files={"file": ("bad.html", b"<html>\xff</html>")})
            assert (await get_terminal(client, warm.json()["id"]))["status"] == "failed"
            baseline = process_descendants(process_table(), os.getpid())
            running = await client.post("/v1/convert/html-to-pdf", files={"file": (
                "loop.html", b"<html><body><script>while(true){}</script></body></html>")})
            job_id = running.json()["id"]
            observed = set()
            async with asyncio.timeout(3.8):
                while len(observed) < 4:
                    observed |= process_descendants(process_table(), os.getpid()) - baseline
                    await asyncio.sleep(.02)
            assert (await asyncio.wait_for(client.get("/healthz"), .5)).status_code == 200
            failed = await get_terminal(client, job_id)
            assert failed["status"] == "failed" and failed["stage"] == "timed_out", failed
            after = process_table()
            assert not {pid for pid in observed if pid in after and not after[pid][1].startswith("Z")}
            assert (await client.get("/v1/jobs/" + job_id + "/result")).status_code == 409
            # A fresh actual renderer still works after forcibly stopped work.
            good = await post_mode(client, "fast")
            done = await get_terminal(client, good.json()["id"])
            assert done["status"] == "done", done
            result = await client.get("/v1/jobs/" + done["id"] + "/result")
            from pypdf import PdfReader
            from io import BytesIO
            assert len(PdfReader(BytesIO(result.content)).pages) == 1
            assert not (process_descendants(process_table(), os.getpid()) - baseline)


async def test_real_http_transport_runs_store_worker_child_and_download(execution_settings):
    import socket
    import uvicorn
    from backend.app.main import create_app
    app = create_app(execution_settings, job_entrypoint=controlled_job)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    address = listener.getsockname()
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on",
                                           timeout_graceful_shutdown=15))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                await asyncio.sleep(.01)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{address[1]}",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            job_id = (await post_mode(client, "fast")).json()["id"]
            assert (await get_terminal(client, job_id))["status"] == "done"
            downloaded = await client.get("/v1/jobs/" + job_id + "/result")
            assert downloaded.status_code == 200
            assert b"Retained sentinel" in downloaded.content
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 15)
        listener.close()


@pytest.mark.parametrize("operation", ["fix", "rebuild"])
async def test_direct_pdf_token_download_is_published_by_parent_after_child_exit(execution_settings, tmp_path, monkeypatch, operation):
    from io import BytesIO
    from pypdf import PdfReader
    from reportlab.pdfgen.canvas import Canvas
    from backend.app.main import create_app
    # A local synthetic provider is the only external service this engine may call.
    async def external(reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            length = next((int(line.split(b":", 1)[1]) for line in headers.split(b"\r\n")
                           if line.lower().startswith(b"content-length:")), 0)
            if length:
                await reader.readexactly(length)
            data = b'{"choices":[{"message":{"content":"No additional issues."}}],"usage":{"prompt_tokens":1,"completion_tokens":1}}'
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: " + str(len(data)).encode() + b"\r\n\r\n" + data)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
    server = await asyncio.start_server(external, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setenv("OLLAMA_BASE_URL", f"http://127.0.0.1:{port}/v1")
    monkeypatch.setenv("VISION_BASE_URL", f"http://127.0.0.1:{port}/v1")
    monkeypatch.setenv("OLLAMA_API_KEY", "fixture-provider-key")
    monkeypatch.setenv("MAX_RETRIES", "1")
    monkeypatch.setenv("GHOSTSCRIPT_ENABLED", "false")
    source = tmp_path / "fixture.pdf"
    canvas = Canvas(str(source))
    canvas.drawString(72, 720, "Retained sentinel")
    canvas.save()
    app = create_app(execution_settings)
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                         headers={"X-API-Key": "fixture-key"}) as client:
                response = await client.post("/v1/pdf/" + operation, files={"file": (source.name, source.read_bytes())})
                assert response.status_code == 200, response.text
                token = response.json()["download_token"]
                result = await client.get(f"/v1/pdf/{operation}/download/{token}")
                assert result.status_code == 200, result.text
                assert len(PdfReader(BytesIO(result.content)).pages) == 1
                assert not list(execution_settings.job_dir.glob("_request-*"))
                client.headers.pop("X-API-Key")
                assert (await client.get(f"/v1/pdf/{operation}/download/{token}")).status_code == 401
    finally:
        server.close()
        await server.wait_closed()


def crashable_owner(settings):
    async def serve():
        from backend.app.main import create_app
        app = create_app(settings, job_entrypoint=controlled_job)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                         headers={"X-API-Key": "fixture-key"}) as client:
                job_id = (await post_mode(client, "detached-hang")).json()["id"]
                settings.backup_dir.mkdir(parents=True, exist_ok=True)
                (settings.backup_dir / "owner.job").write_text(job_id)
                await asyncio.Event().wait()
    asyncio.run(serve())


async def test_parent_crash_stops_detached_descendant_and_restart_cannot_overlap(execution_settings):
    import multiprocessing
    from backend.app.main import create_app
    settings = execution_settings
    owner = multiprocessing.get_context("spawn").Process(target=crashable_owner, args=(settings,))
    owner.start()
    try:
        await wait_for_file(settings.backup_dir / "owner.job")
        job_id = (settings.backup_dir / "owner.job").read_text()
        await wait_for_file(settings.backup_dir / (job_id + ".descendant"))
        child = int((settings.backup_dir / (job_id + ".started")).read_text())
        detached = int((settings.backup_dir / (job_id + ".descendant")).read_text())
        assert os.getpgid(child) != os.getpgid(detached)
        owner.kill()
        async with asyncio.timeout(5):
            while owner.is_alive():
                await asyncio.sleep(.02)
        owner.join(timeout=0)
        async with asyncio.timeout(12):
            while True:
                table = process_table()
                if all(pid not in table or table[pid][1].startswith("Z") for pid in [child, detached]):
                    break
                await asyncio.sleep(.02)
        replacement = create_app(settings, job_entrypoint=controlled_job)
        with pytest.raises(RuntimeError, match="Unresolved engine ownership"):
            async with replacement.router.lifespan_context(replacement):
                pass
        # Parent death does not certify cleanup or mutate/replay the running row.
        job = await replacement.state.store.get(job_id)
        assert job.status == "running"
        assert not (settings.backup_dir / "late").exists()
    finally:
        if owner.is_alive():
            owner.kill()
            owner.join(timeout=5)
        owner.close()


async def test_legacy_persisted_queue_excess_is_failed_with_input_retained(execution_settings):
    from backend.app.jobs import JobStore
    from backend.app.main import create_app
    settings = execution_settings
    settings.job_dir.mkdir()
    source = settings.job_dir / "legacy.html"
    source.write_text("<html>fast</html>")
    store = JobStore(settings.job_store_path)
    jobs = [await store.create(source, kind="convert_html_to_pdf") for _ in range(12)]
    app = create_app(settings, job_entrypoint=controlled_job)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            terminal = [await get_terminal(client, job.id) for job in jobs]
            assert sum(job["status"] == "done" for job in terminal) == 9
            rejected = [job for job in terminal if job["status"] == "failed"]
            assert len(rejected) == 3
            assert all(job["stage"] == "interrupted" for job in rejected)
            assert all("input retained" in job["error"] for job in rejected)
            assert source.is_file()
            assert (await client.get("/readyz")).status_code == 200


async def test_upload_store_failure_does_not_leak_staging_or_admission(execution_settings, monkeypatch):
    from backend.app.main import create_app
    settings = execution_settings
    app = create_app(settings, job_entrypoint=controlled_job)
    original = app.state.store.create
    async def unavailable(*args, **kwargs):
        raise OSError("fixture-secret private storage detail")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            monkeypatch.setattr(app.state.store, "create", unavailable)
            response = await post_mode(client, "fast")
            assert response.status_code == 500
            assert "fixture-secret" not in response.text
            assert not list(settings.job_dir.glob("_staging-*"))
            assert not await app.state.store.list_by_statuses({"queued", "running"})
            monkeypatch.setattr(app.state.store, "create", original)
            job_id = (await post_mode(client, "fast")).json()["id"]
            assert (await get_terminal(client, job_id))["status"] == "done"


async def test_authentication_precedes_saturated_direct_admission(execution_settings):
    from backend.app.main import create_app
    settings = execution_settings
    app = create_app(settings, direct_entrypoint=controlled_direct)
    entered, release = asyncio.Event(), asyncio.Event()
    async def blocked(job):
        entered.set()
        await release.wait()
    app.state.worker.runner = blocked
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            try:
                for _ in range(9):
                    assert (await post_mode(client, "fast")).status_code == 202
                await entered.wait()
                assert (await client.post("/v1/pdf/check", content=b"fixture")).status_code == 503
                client.headers.pop("X-API-Key")
                assert (await client.post("/v1/pdf/check", content=b"fixture")).status_code == 401
                assert not (settings.backup_dir / "direct.started").exists()
            finally:
                release.set()


async def test_direct_replay_preserves_parent_upload_rate_limit(execution_settings, monkeypatch):
    from backend.app.main import create_app
    settings = execution_settings
    settings.backup_dir.mkdir()
    monkeypatch.setenv("RATE_LIMIT_UPLOADS", "1/minute")
    app = create_app(settings, direct_entrypoint=controlled_direct)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            assert (await client.post("/v1/pdf/check", content=b"fixture")).status_code == 200
            first_pid = (settings.backup_dir / "direct.started").read_text()
            response = await client.post("/v1/pdf/check", content=b"fixture")
            assert response.status_code == 429
            assert (settings.backup_dir / "direct.started").read_text() == first_pid


async def controlled_direct_hang(settings, wire_scope, body, *, emit):
    settings.backup_dir.mkdir(parents=True, exist_ok=True)
    (settings.backup_dir / "direct.started").write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    await asyncio.sleep(30)
    return 200, [], b"unexpected late success"


async def test_actual_http_shutdown_waits_for_cancelled_direct_child(execution_settings):
    import socket
    import uvicorn
    from backend.app.main import create_app
    settings = execution_settings
    app = create_app(settings, direct_entrypoint=controlled_direct_hang)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on",
                                           timeout_graceful_shutdown=.2))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    checking = None
    try:
        async with asyncio.timeout(5):
            while not server.started:
                await asyncio.sleep(.01)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{listener.getsockname()[1]}", timeout=15,
                                     headers={"X-API-Key": "fixture-key"}) as client:
            checking = asyncio.create_task(client.post("/v1/pdf/check", content=b"fixture"))
            await wait_for_file(settings.backup_dir / "direct.started")
            child = int((settings.backup_dir / "direct.started").read_text())
            started = time.monotonic()
            server.should_exit = True
            await asyncio.wait_for(serving, 12)
            assert time.monotonic() - started < 12
            table = process_table()
            assert child not in table or table[child][1].startswith("Z")
            assert not list(settings.job_dir.glob("_request-*"))
            await asyncio.gather(checking, return_exceptions=True)
    finally:
        server.should_exit = True
        if not serving.done():
            await asyncio.wait_for(serving, 15)
        if checking is not None and not checking.done():
            checking.cancel()
            await asyncio.gather(checking, return_exceptions=True)
        listener.close()


@pytest.mark.parametrize("audit_path", ["/v1/quality/audit/pdf", "/v1/quality/audit/office"])
async def test_quality_audits_share_engine_overload_before_staging(execution_settings, audit_path):
    from backend.app.main import create_app
    app = create_app(execution_settings)
    entered, release = asyncio.Event(), asyncio.Event()
    async def blocked(job):
        entered.set()
        await release.wait()
    app.state.worker.runner = blocked
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            try:
                for _ in range(9):
                    assert (await post_mode(client, "fast")).status_code == 202
                await entered.wait()
                before = set(execution_settings.job_dir.rglob("*"))
                response = await client.post(audit_path, files={"file": ("invalid.bin", b"fixture")})
                assert response.status_code == 503
                assert response.headers["retry-after"] == "5"
                assert set(execution_settings.job_dir.rglob("*")) == before
            finally:
                release.set()


async def test_expired_before_ready_handling_stops_already_started_detached_child(execution_settings, monkeypatch):
    from dataclasses import replace
    from multiprocessing.context import SpawnProcess
    from backend.app.main import create_app
    settings = replace(execution_settings, job_total_timeout_seconds=.8)
    start = SpawnProcess.start
    delayed = False
    def delayed_start(process):
        nonlocal delayed
        start(process)
        if not delayed:
            delayed = True
            time.sleep(1.2)  # parent stalls while the real child starts work
    monkeypatch.setattr(SpawnProcess, "start", delayed_start)
    app = create_app(settings, job_entrypoint=controlled_job)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            job_id = (await post_mode(client, "detached-hang")).json()["id"]
            failed = await get_terminal(client, job_id)
            assert failed["stage"] == "timed_out"
            assert not (settings.backup_dir / (job_id + ".started")).exists()
            assert not (settings.backup_dir / (job_id + ".descendant")).exists()
            fast = (await post_mode(client, "fast")).json()["id"]
            assert (await get_terminal(client, fast))["status"] == "done"


async def quality_with_fixture_calibration(settings, wire_scope, body, *, emit):
    """Substitute calibration policy only; execute genuine quality audit engines."""
    from backend.app import quality_routes
    from backend.app.execution import execute_http
    def calibrated(*args, **kwargs):
        settings.backup_dir.mkdir(parents=True, exist_ok=True)
        (settings.backup_dir / "quality.started").write_text(str(os.getpid()))
        if (settings.backup_dir / "pause-calibration").exists():
            time.sleep(30)
    quality_routes.assert_quality_calibrated = calibrated
    return await execute_http(settings, wire_scope, body, emit=emit)


@pytest.mark.parametrize("kind", ["pdf", "office"])
async def test_quality_audit_deadline_keeps_health_responsive_then_real_audit_recovers(execution_settings, tmp_path, kind):
    from dataclasses import replace
    from reportlab.pdfgen.canvas import Canvas
    from tests.unit.office_fixtures import make_docx
    from backend.app.main import create_app
    settings = replace(execution_settings, job_total_timeout_seconds=3, worker_max_pending=1)
    settings.backup_dir.mkdir()
    paused = settings.backup_dir / "pause-calibration"
    paused.touch()
    if kind == "pdf":
        source = tmp_path / "fixture.pdf"
        canvas = Canvas(str(source))
        canvas.drawString(72, 720, "Retained sentinel")
        canvas.save()
    else:
        source = make_docx(tmp_path / "fixture.docx", body_paragraphs=["Retained sentinel"])
    app = create_app(settings, job_entrypoint=controlled_job, direct_entrypoint=quality_with_fixture_calibration)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture.invalid",
                                     headers={"X-API-Key": "fixture-key"}) as client:
            checking = asyncio.create_task(client.post("/v1/quality/audit/" + kind,
                files={"file": (source.name, source.read_bytes())}))
            await wait_for_file(settings.backup_dir / "quality.started")
            child = int((settings.backup_dir / "quality.started").read_text())
            assert child != os.getpid()
            assert (await asyncio.wait_for(client.get("/healthz"), .5)).status_code == 200
            queued = (await post_mode(client, "fast")).json()["id"]
            assert not (settings.backup_dir / (queued + ".started")).exists()
            excess = await client.post("/v1/quality/audit/" + kind, content=b"fixture")
            assert excess.status_code == 503 and excess.headers["retry-after"] == "5"
            assert (await checking).status_code == 504
            table = process_table()
            assert child not in table or table[child][1].startswith("Z")
            await get_terminal(client, queued)
            paused.unlink()
            response = await client.post("/v1/quality/audit/" + kind,
                files={"file": (source.name, source.read_bytes())})
            assert response.status_code == 200, response.text
            assert response.json()["format"] == ("pdf" if kind == "pdf" else "docx")
            assert response.json()["dimensions"]
            assert not list(settings.job_dir.glob("_request-*"))


def child_delays_shared_lock(connection, function, args, parent_pid, ownership_path, deadline):
    """OS lock adapter fixture: pause immediately before the actual shared flock."""
    import fcntl
    settings = args[1]
    original = fcntl.flock
    def delayed(lock, operation):
        if operation == (fcntl.LOCK_SH | fcntl.LOCK_NB):
            settings.backup_dir.mkdir(parents=True, exist_ok=True)
            (settings.backup_dir / "shared-lock.waiting").write_text(str(os.getpid()))
            while not (settings.backup_dir / "shared-lock.release").exists():
                time.sleep(.01)
        return original(lock, operation)
    fcntl.flock = delayed
    original_supervise(connection, function, args, parent_pid, ownership_path, deadline)


def owner_with_delayed_child_lock(settings):
    from backend.app import supervisor
    supervisor.supervise = child_delays_shared_lock
    crashable_owner(settings)


async def test_parent_death_during_shared_lock_handoff_never_starts_old_work(execution_settings):
    import multiprocessing
    from backend.app.main import create_app
    settings = execution_settings
    owner = multiprocessing.get_context("spawn").Process(target=owner_with_delayed_child_lock, args=(settings,))
    owner.start()
    child = None
    try:
        await wait_for_file(settings.backup_dir / "shared-lock.waiting")
        await wait_for_file(settings.backup_dir / "owner.job")
        child = int((settings.backup_dir / "shared-lock.waiting").read_text())
        job_id = (settings.backup_dir / "owner.job").read_text()
        owner.kill()
        async with asyncio.timeout(5):
            while owner.is_alive():
                await asyncio.sleep(.02)
        owner.join(timeout=0)
        replacement = create_app(settings, job_entrypoint=controlled_job)
        with pytest.raises(RuntimeError, match="Unresolved engine ownership"):
            async with replacement.router.lifespan_context(replacement):
                pass
        (settings.backup_dir / "shared-lock.release").touch()
        async with asyncio.timeout(5):
            while True:
                table = process_table()
                if child not in table or table[child][1].startswith("Z"):
                    break
                await asyncio.sleep(.02)
        assert not (settings.backup_dir / (job_id + ".started")).exists()
        with pytest.raises(RuntimeError, match="Unresolved engine ownership"):
            async with replacement.router.lifespan_context(replacement):
                pass
    finally:
        if owner.is_alive():
            owner.kill()
            owner.join(timeout=5)
        owner.close()
        if child is not None:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
