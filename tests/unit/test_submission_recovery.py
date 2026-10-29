"""Actual hard-exit submission regressions using only synthetic SQLite/files."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import hashlib

import pytest

from backend.app.config import Settings
from backend.app.jobs import JobStore

SOURCE = b"<!doctype html><html><body>Retained submission sentinel</body></html>"
OPTIONS = '{"quality":true,"synthetic_option":"retained"}'


def crash_after_rename(directory, point="rename"):
    from backend.app.routes import _finalize_upload_and_enqueue
    settings = Settings(job_store_path=directory / "jobs.db", job_dir=directory / "jobs")
    settings.job_dir.mkdir()
    staging = settings.job_dir / "_staging-synthetic.html"
    staging.write_bytes(SOURCE)
    store = JobStore(settings.job_store_path)
    fsync, rename = os.fsync, Path.rename
    sync_count = 0
    def crash_sync(descriptor):
        nonlocal sync_count
        fsync(descriptor)
        sync_count += 1
        if point == f"fsync-{sync_count}":
            os._exit(73)
    os.fsync = crash_sync
    def crash(path, destination):
        result = rename(path, destination)
        if path == staging and point == "rename":
            os._exit(73)
        return result
    Path.rename = crash
    if point in {"db-before-commit", "db-after-commit"}:
        from tests.unit.submission_faults import exit_at_intent_commit
        exit_at_intent_commit(store, point)
    if point == "ready":
        advance = store._advance_upload
        async def crash_ready(*args):
            result = await advance(*args)
            os._exit(73)
        store._advance_upload = crash_ready
    published = False
    if point == "receipt":
        get = store.get
        async def crash_receipt(*args):
            result = await get(*args)
            assert published
            os._exit(73)
        store.get = crash_receipt
    class Worker:
        async def enqueue(self, *args):
            nonlocal published
            if point == "enqueue-before":
                os._exit(73)
            published = True
            if point == "enqueue-after":
                os._exit(73)
            if point != "receipt":
                raise AssertionError("No dispatch before crash")
    asyncio.run(_finalize_upload_and_enqueue(store, Worker(), settings,
        staging, ".html", kind="convert_html_to_pdf", result_media_type="application/pdf", metadata_json=OPTIONS))


async def cold_recover(directory, crash_dispatch=False):
    store = JobStore(directory / "jobs.db")
    await store.fail_running_jobs("Interrupted dispatch; input retained.")
    for job in await store.recover_uploads(directory / "jobs", 9):
        claimed = await store.claim_upload(job.id, directory / "jobs")
        assert claimed is not None
        if crash_dispatch:
            os._exit(73)
        with (directory / "effects.jsonl").open("a") as effects:
            effects.write(json.dumps({"id": job.id, "options": json.loads(claimed.metadata_json),
                "sha256": hashlib.sha256(Path(claimed.input_path).read_bytes()).hexdigest()}) + "\n")
            effects.flush()
            os.fsync(effects.fileno())
        await store.update(job.id, status="done", stage="complete")


def child_run(directory, point):
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(directory), point],
        capture_output=True, timeout=15, env=os.environ | {"PYTHON_DOTENV_DISABLED": "1"})
    return result


async def test_hard_exit_after_rename_keeps_full_input_and_options_before_queue_eligibility(tmp_path):
    result = child_run(tmp_path, "rename")
    assert result.returncode == 73, result.stderr.decode()
    store = JobStore(tmp_path / "jobs.db")
    jobs = await store.list_by_statuses({"queued"})
    assert len(jobs) == 1
    job = jobs[0]
    assert json.loads(job.metadata_json) == json.loads(OPTIONS)
    assert Path(job.input_path).read_bytes() == SOURCE
    assert job.stage == "finalizing"  # persisted intent is not yet queue eligible


@pytest.mark.parametrize("point", ["db-before-commit", "db-after-commit",
    "rename", "ready", "enqueue-before", "enqueue-after", "receipt"])
async def test_hard_exit_boundaries_cold_recover_once_with_exact_bytes_and_options(tmp_path, point):
    await assert_cold_boundary(tmp_path, point)


async def test_every_file_and_directory_fsync_boundary_cold_recovers_once(tmp_path):
    # Includes every ancestor when a route just created a new configured tree;
    # count follows path depth across macOS and the actual Linux shipping image.
    count = 6 + len((tmp_path / "cut-1" / "jobs").resolve().parents)
    for index in range(1, count + 1):
        directory = tmp_path / f"cut-{index}"
        directory.mkdir()
        await assert_cold_boundary(directory, f"fsync-{index}")


async def assert_cold_boundary(tmp_path, point):
    crash = child_run(tmp_path, point)
    assert crash.returncode == 73, crash.stderr.decode()
    store = JobStore(tmp_path / "jobs.db")
    queued = await store.list_by_statuses({"queued"})
    for _ in range(2):
        recovered = child_run(tmp_path, "recover")
        assert recovered.returncode == 0, recovered.stderr.decode()
    effects = tmp_path / "effects.jsonl"
    if not queued:  # no intent committed: retained unsubmitted staging is never guessed/replayed
        assert not effects.exists()
        assert (tmp_path / "jobs" / "_staging-synthetic.html").read_bytes() == SOURCE
    else:
        assert len(queued) == 1
        records = [json.loads(line) for line in effects.read_text().splitlines()]
        assert records == [{"id": queued[0].id, "options": json.loads(OPTIONS),
                            "sha256": hashlib.sha256(SOURCE).hexdigest()}]
        job = await JobStore(tmp_path / "jobs.db").get(queued[0].id)
        assert job.status == "done" and Path(job.input_path).read_bytes() == SOURCE


async def test_hard_exit_after_dispatch_claim_never_automatically_replays(tmp_path):
    assert child_run(tmp_path, "rename").returncode == 73
    store = JobStore(tmp_path / "jobs.db")
    job = (await store.list_by_statuses({"queued"}))[0]
    assert child_run(tmp_path, "dispatch").returncode == 73
    for _ in range(2):
        result = child_run(tmp_path, "recover")
        assert result.returncode == 0, result.stderr.decode()
    assert not (tmp_path / "effects.jsonl").exists()
    retained = await JobStore(tmp_path / "jobs.db").get(job.id)
    assert retained.status == "failed" and Path(retained.input_path).read_bytes() == SOURCE
    assert json.loads(retained.metadata_json) == json.loads(OPTIONS)


async def prepared_upload(tmp_path, ready=True):
    root = tmp_path / "jobs"
    root.mkdir()
    staging = root / "_staging-synthetic.html"
    staging.write_bytes(SOURCE)
    store = JobStore(tmp_path / "jobs.db")
    job = await store.prepare_upload(staging, root, ".html", kind="convert_html_to_pdf",
        result_media_type="application/pdf", metadata_json=OPTIONS, deadline_at="")
    if ready:
        assert await store.finish_upload(job.id, root) is not None
    return store, root, staging, job


async def test_public_finalization_preserves_case_insensitive_office_admission(tmp_path):
    from backend.app.routes import _finalize_upload_and_enqueue
    settings = Settings(job_store_path=tmp_path / "jobs.db", job_dir=tmp_path / "jobs")
    settings.job_dir.mkdir()
    staging = settings.job_dir / "_staging-synthetic.docx"
    from tests.unit.office_fixtures import make_docx
    make_docx(staging, body_paragraphs=["Synthetic mixed-case admission"])
    source = staging.read_bytes()
    store = JobStore(settings.job_store_path)
    published = []
    class Worker:
        async def enqueue(self, job_id, reservation):
            published.append(job_id)
    response = await _finalize_upload_and_enqueue(store, Worker(), settings, staging, ".DOCX",
        kind="remediate_office", result_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        metadata_json=OPTIONS)
    assert published == [response["id"]]
    job = await store.get(response["id"])
    assert Path(job.input_path).suffix == ".docx"
    assert Path(job.input_path).read_bytes() == source and json.loads(job.metadata_json) == json.loads(OPTIONS)


@pytest.mark.parametrize("producer", ["office", "vision"])
async def test_async_upload_producers_are_compatible_with_journal_ownership(tmp_path, producer):
    from io import BytesIO
    from fastapi import UploadFile
    from backend.app.routes import _finalize_upload_and_enqueue
    settings = Settings(job_store_path=tmp_path / "jobs.db", job_dir=tmp_path / "jobs")
    if producer == "office":
        from backend.app.office_routes import _stage_office
        from tests.unit.office_fixtures import make_docx
        path = make_docx(tmp_path / "fixture.docx", body_paragraphs=["Owned Office upload"])
        source, suffix, kind = path.read_bytes(), ".docx", "remediate_office"
        staging, _ = await _stage_office(UploadFile(filename="fixture.docx", file=BytesIO(source)), settings, modern_only=True)
    else:
        from backend.app.vision_plan_routes import _stage_pdf
        import pikepdf
        stream = BytesIO()
        with pikepdf.new() as pdf:
            pdf.add_blank_page()
            pdf.save(stream)
        source, suffix, kind = stream.getvalue(), ".pdf", "vision_plan_run"
        staging = await _stage_pdf(UploadFile(filename="fixture.pdf", file=BytesIO(source)), settings)
    store = JobStore(settings.job_store_path)
    published = []
    class Queue:
        async def enqueue(self, job_id, reservation):
            published.append(job_id)
    result = await _finalize_upload_and_enqueue(store, Queue(), settings, staging, suffix,
        kind=kind, result_media_type="application/pdf")
    assert published == [result["id"]]
    assert Path((await store.get(result["id"])).input_path).read_bytes() == source


async def test_prepared_intent_is_not_dispatch_eligible(tmp_path):
    store, root, staging, job = await prepared_upload(tmp_path, ready=False)
    assert await store.claim_upload(job.id, root) is None
    assert (await store.get(job.id)).stage == "submission_quarantined"
    assert staging.read_bytes() == SOURCE
    assert await store.recover_uploads(root, 9) == []


async def test_dequeue_waiting_for_capacity_does_not_claim_durable_dispatch(tmp_path):
    from types import SimpleNamespace
    import time
    from backend.app.jobs import JobWorker
    store, root, staging, job = await prepared_upload(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    async def waiting_runner(_job):
        entered.set()
        await release.wait()
    worker = JobWorker(store, waiting_runner, execution=SimpleNamespace(accepting=True), job_dir=root)
    ticket = SimpleNamespace(deadline=time.monotonic()+30, transferred=False, retained=False, release=lambda: None)
    worker.start()
    try:
        await worker.enqueue(job.id, ticket)
        await asyncio.wait_for(entered.wait(), 2)
        intent, persisted = await store._submission(job.id)
        assert intent["phase"] == "ready" and persisted.status == "queued"
    finally:
        await worker.stop()
    assert [entry.id for entry in await JobStore(tmp_path / "jobs.db").recover_uploads(root, 9)] == [job.id]


@pytest.mark.parametrize("fault", ["bytes", "options", "missing", "symlink", "owned-path"])
async def test_dispatch_validates_final_bytes_options_and_path_ownership(tmp_path, fault):
    store, root, staging, job = await prepared_upload(tmp_path)
    final = Path(job.input_path)
    retained = tmp_path / "retained-input.html"
    if fault == "bytes":
        final.write_bytes(b"Synthetic changed bytes")
    elif fault == "options":
        await store.update(job.id, metadata_json='{"quality":false}')
    elif fault in {"missing", "symlink"}:
        final.rename(retained)
        if fault == "symlink":
            final.symlink_to(retained)
    else:
        await store.update(job.id, input_path=str(tmp_path / "outside-owned-directory.html"))
    assert await store.claim_upload(job.id, root) is None
    assert (await store.get(job.id)).stage == "submission_quarantined"
    assert await store.recover_uploads(root, 9) == []
    assert final.exists() or retained.read_bytes() == SOURCE


async def test_ambiguous_move_preserves_both_paths_and_quarantines(tmp_path):
    store, root, staging, job = await prepared_upload(tmp_path, ready=False)
    final = Path(job.input_path)
    final.parent.mkdir()
    final.write_bytes(SOURCE)
    assert await store.finish_upload(job.id, root) is None
    assert (await store.get(job.id)).stage == "submission_quarantined"
    assert staging.read_bytes() == final.read_bytes() == SOURCE


async def test_legacy_unknown_intent_is_never_requeued_or_automatically_pruned(tmp_path):
    from backend.app.jobs import prune_expired_jobs
    import sqlite3
    root = tmp_path / "jobs"
    root.mkdir()
    source = root / "legacy.html"
    source.write_bytes(SOURCE)
    store = JobStore(tmp_path / "jobs.db")
    job = await store.create(source, kind="convert_html_to_pdf")
    assert await store.recover_uploads(root, 9) == []
    assert (await store.get(job.id)).stage == "submission_quarantined"
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("UPDATE jobs SET created_at='2000-01-01T00:00:00+00:00' WHERE id=?", (job.id,))
    assert await prune_expired_jobs(store, root, 1) == 0
    assert await store.get(job.id) is not None and source.read_bytes() == SOURCE


async def test_expired_unknown_intent_is_quarantined_before_retention(tmp_path):
    import sqlite3
    from backend.app.jobs import prune_expired_jobs
    root = tmp_path / "jobs"
    root.mkdir()
    store = JobStore(tmp_path / "jobs.db")
    source = root / "legacy.html"
    source.write_bytes(SOURCE)
    job = await store.create(source, kind="convert_html_to_pdf", deadline_at="2000-01-01T00:00:00+00:00")
    owned = root / job.id / "input.html"
    owned.parent.mkdir()
    source.rename(owned)
    source = owned
    await store.update(job.id, input_path=str(source))
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("UPDATE jobs SET created_at='2000-01-01T00:00:00+00:00' WHERE id=?", (job.id,))
    assert await store.recover_uploads(root, 9) == []
    assert (await store.get(job.id)).stage == "submission_quarantined"
    assert await prune_expired_jobs(store, root, 1) == 0
    assert source.read_bytes() == SOURCE


async def test_cold_reconciliation_is_bounded_and_retains_excess_intent_and_inputs(tmp_path):
    root = tmp_path / "jobs"
    root.mkdir()
    store = JobStore(tmp_path / "jobs.db")
    jobs = []
    for index in range(4):
        staging = root / f"_staging-synthetic-{index}.html"
        staging.write_bytes(SOURCE)
        job = await store.prepare_upload(staging, root, ".html", kind="convert_html_to_pdf",
            result_media_type="application/pdf", metadata_json=OPTIONS, deadline_at="")
        assert await store.finish_upload(job.id, root) is not None
        jobs.append(job)
    recovered = await JobStore(tmp_path / "jobs.db").recover_uploads(root, 2)
    assert [job.id for job in recovered] == [job.id for job in jobs[:2]]
    for job in jobs:
        saved = await store.get(job.id)
        assert saved.stage == ("queued" if job in jobs[:2] else "submission_quarantined")
        assert Path(saved.input_path).read_bytes() == SOURCE and json.loads(saved.metadata_json) == json.loads(OPTIONS)


async def test_actual_sqlite_submission_configuration_receipt(tmp_path):
    import sqlite3
    store = JobStore(tmp_path / "jobs.db")
    with store._connect() as connection:
        receipt = {"version": sqlite3.sqlite_version,
                   "source_id": connection.execute("SELECT sqlite_source_id()").fetchone()[0],
                   "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
                   "synchronous": connection.execute("PRAGMA synchronous").fetchone()[0],
                   "foreign_keys": connection.execute("PRAGMA foreign_keys").fetchone()[0]}
    assert receipt["journal_mode"] == "wal" and receipt["synchronous"] == 2 and receipt["foreign_keys"] == 1
    if os.environ.get("REMEDY_SANDBOX_AUDIT_DIR"):
        package = subprocess.run(["dpkg-query", "-W", "libsqlite3-0"], capture_output=True, text=True, timeout=5)
        assert package.returncode == 0
        receipt["distribution_package"] = package.stdout.strip()
        (Path(os.environ["REMEDY_SANDBOX_AUDIT_DIR"]) / "submission-sqlite.json").write_text(json.dumps(receipt, indent=2))


@pytest.mark.parametrize("after_enqueue", [False, True])
async def test_publication_or_acknowledgement_failure_retains_owned_input_and_options(tmp_path, after_enqueue):
    from backend.app.routes import _finalize_upload_and_enqueue
    from types import SimpleNamespace
    import time
    settings = Settings(job_store_path=tmp_path / "jobs.db", job_dir=tmp_path / "jobs")
    settings.job_dir.mkdir()
    staging = settings.job_dir / "_staging-synthetic.html"
    staging.write_bytes(SOURCE)
    store = JobStore(settings.job_store_path)
    reservation = SimpleNamespace(deadline=time.monotonic() + 30, transferred=False)
    get = store.get
    class Worker:
        async def enqueue(self, job_id, ticket):
            if not after_enqueue:
                raise OSError("Synthetic publication failure")
            ticket.transferred = True
            async def acknowledgement_lost(*args):
                raise OSError("Synthetic acknowledgement loss")
            store.get = acknowledgement_lost
    with pytest.raises(OSError):
        await _finalize_upload_and_enqueue(store, Worker(), settings, staging, ".html",
            kind="convert_html_to_pdf", result_media_type="application/pdf", metadata_json=OPTIONS,
            reservation=reservation)
    store.get = get
    rows = await store.list_by_statuses({"queued", "failed"})
    assert len(rows) == 1 and Path(rows[0].input_path).read_bytes() == SOURCE
    assert json.loads(rows[0].metadata_json) == json.loads(OPTIONS)
    assert rows[0].stage == ("queued" if after_enqueue else "submission_quarantined")


if __name__ == "__main__":
    directory, point = Path(sys.argv[1]), sys.argv[2]
    if point in {"recover", "dispatch"}:
        asyncio.run(cold_recover(directory, point == "dispatch"))
    else:
        crash_after_rename(directory, point)
