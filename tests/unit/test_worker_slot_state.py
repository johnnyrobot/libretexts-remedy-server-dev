"""Durable queue behavior while an execution adapter awaits shared capacity."""
import asyncio
import json
import time
from types import SimpleNamespace

from backend.app.jobs import JobStore, JobWorker


async def test_shutdown_preserves_undispatched_queue_and_exact_input_options(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    source = tmp_path / "input.html"
    source.write_bytes(b"<html>retained synthetic input</html>")
    job = await store.create(source, kind="convert_html_to_pdf")
    options = json.dumps({"quality": True, "rebuild_backend": "typst"})
    await store.update(job.id, metadata_json=options)
    slot, waiting = asyncio.Semaphore(1), asyncio.Event()
    await slot.acquire()
    entered = []
    async def runner(_job):
        waiting.set()
        await slot.acquire()
        entered.append(_job.id)
    released = []
    ticket = SimpleNamespace(deadline=time.monotonic() + 60, transferred=False,
                             retained=False, release=lambda: released.append(True))
    worker = JobWorker(store, runner, execution=SimpleNamespace(accepting=True))
    worker.start()
    try:
        await worker.enqueue(job.id, ticket)
        await asyncio.wait_for(waiting.wait(), 2)
        assert (await store.get(job.id)).status == "queued"
    finally:
        await worker.stop()
    retained = await JobStore(tmp_path / "jobs.db").get(job.id)
    assert retained.status == "queued" and retained.metadata_json == options
    assert source.read_bytes() == b"<html>retained synthetic input</html>"
    assert len(await store.list_by_statuses({"queued"})) == 1
    assert entered == [] and len(released) == 1
