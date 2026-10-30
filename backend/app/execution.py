"""Bounded admission; a persistent Linux supervisor owns each compute lifetime."""
from __future__ import annotations

import asyncio
import json
import re
import queue
import threading
import fcntl
import multiprocessing
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import anyio
from fastapi import HTTPException

_OWNED_CHILD = False


def in_owned_child() -> bool:
    return _OWNED_CHILD


def strict_execution_supported() -> bool:
    from backend.app.supervisor import supported
    return supported()


class ExecutionDeadline(RuntimeError):
    pass


class ExecutionStopped(RuntimeError):
    pass


class CleanupUnresolved(RuntimeError):
    pass


@dataclass(eq=False)
class Reservation:
    owner: "OwnedExecution"
    deadline: float
    transferred: bool = False
    released: bool = False
    retained: bool = False

    def release(self) -> None:
        if not self.released and not self.retained:
            self.released = True
            self.owner._admitted.discard(self)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class OwnedExecution:
    """Admission, durable quarantine, and publication after kernel-proven cleanup."""

    def __init__(self, concurrency: int = 1, pending: int = 8, total_seconds: float = 900) -> None:
        self.capacity = concurrency + pending
        self.total_seconds = total_seconds
        self._slots = asyncio.Semaphore(concurrency)
        self._admitted: set[Reservation] = set()
        self._executions: set[asyncio.Task] = set()
        self._profile_supported = strict_execution_supported()
        self.accepting = False
        self._context = multiprocessing.get_context("spawn")
        self._ownership_path = None
        self._ownership_lock = None
        self._owner_lock = None
        self._unresolved = None

    def start_ownership(self, path) -> None:
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        owner_lock = path.with_name(path.name + ".owner").open("a")
        lock = path.open("a")
        try:
            fcntl.flock(owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            unresolved = path.with_name(path.name + ".unresolved")
            unresolved.mkdir(exist_ok=True)
            if any(unresolved.iterdir()):
                raise RuntimeError("Unresolved engine ownership; offline recovery required.")
            fcntl.flock(lock, fcntl.LOCK_SH)
        except BaseException as exc:
            lock.close()
            owner_lock.close()
            if isinstance(exc, OSError):
                raise RuntimeError("Engine store already has an owner or unfinished execution.") from None
            raise
        self._ownership_path, self._ownership_lock, self._owner_lock = str(path), lock, owner_lock
        self._unresolved = unresolved
        from backend.app.supervisor import probe_adoption
        self.accepting = self._profile_supported and probe_adoption()

    def reserve(self, *, remaining: float | None = None) -> Reservation:
        if not self.accepting or len(self._admitted) >= self.capacity:
            raise HTTPException(503, "Engine capacity unavailable.", headers={"Retry-After": "5"})
        reservation = Reservation(self, time.monotonic() + (self.total_seconds if remaining is None else remaining))
        self._admitted.add(reservation)
        return reservation

    async def run(self, function: Callable, args: tuple, reservation: Reservation,
                  *, on_update: Callable | None = None, operation_timeouts: dict | None = None,
                  on_acquired: Callable | None = None) -> Any:
        if not self.accepting:
            raise ExecutionStopped("Engine admission has stopped.")
        task = asyncio.current_task()
        self._executions.add(task)
        try:
            remaining = reservation.deadline - time.monotonic()
            if remaining <= 0:
                raise ExecutionDeadline("Engine total deadline exceeded while queued.")
            try:
                await asyncio.wait_for(self._slots.acquire(), remaining)
            except TimeoutError:
                raise ExecutionDeadline("Engine total deadline exceeded while queued.") from None
            try:
                if reservation.deadline <= time.monotonic():
                    raise ExecutionDeadline("Engine total deadline exceeded while queued.")
                if not self.accepting:
                    raise ExecutionStopped("Engine admission has stopped.")
                if on_acquired is not None:
                    await on_acquired()
                if not self.accepting:
                    raise ExecutionStopped("Engine admission has stopped.")
                return await self._run_process(function, args, reservation, on_update, operation_timeouts or {})
            finally:
                if not reservation.retained:
                    self._slots.release()
        finally:
            self._executions.discard(task)

    def _mark_unresolved(self) -> Path:
        if self._unresolved is None:
            raise RuntimeError("Engine ownership has not been established.")
        marker = self._unresolved / uuid.uuid4().hex
        with marker.open("x") as stream:
            json.dump({"parent_pid": os.getpid(), "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                       "state": "unresolved"}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        _sync_directory(self._unresolved)
        return marker

    async def _run_process(self, function, args, reservation, on_update, operation_timeouts):
        from backend.app.supervisor import supervise, receive_messages
        control, child_control = self._context.Pipe()
        process = self._context.Process(target=supervise, args=(child_control, function, args,
            os.getpid(), self._ownership_path, reservation.deadline), daemon=True)
        marker = self._mark_unresolved()  # durable BEFORE spawn, including interrupted startup
        reader = queue.Queue(maxsize=64)
        closed = threading.Event()
        clean = False
        outcome, result = "error", None
        phase_deadline = reservation.deadline
        previous_stage = None
        failure = None
        try:
            process.start()
            child_control.close()
            threading.Thread(target=receive_messages, args=(control, reader, closed), daemon=True).start()
            while True:
                if time.monotonic() >= min(reservation.deadline, phase_deadline):
                    raise ExecutionDeadline("Engine execution deadline exceeded.")
                if not reader.empty():
                    kind, data = reader.get_nowait()  # drain buffered messages even after supervisor exit
                    if kind == "ready":
                        control.send(("dispatch", None))
                    elif kind == "update":
                        stage = data.get("stage")
                        if stage and stage != previous_stage:
                            previous_stage = stage
                            phase_deadline = min(reservation.deadline, time.monotonic() + operation_timeouts.get(stage, self.total_seconds))
                        if on_update is not None:
                            await on_update(data)
                    elif kind == "clean":
                        clean = True
                        outcome, result = data
                        break
                    elif kind == "unresolved":
                        raise CleanupUnresolved("Supervisor could not prove engine cleanup.")
                    if kind == "eof":
                        raise CleanupUnresolved("Supervisor IPC closed without cleanup proof.")
                await asyncio.sleep(.01)
        except BaseException as exc:
            failure = exc
        finally:
            # Request cancellation, but only a positive cleanup certificate can
            # clear durable ownership. EOF, supervisor exit and SIGKILL cannot.
            with anyio.CancelScope(shield=True):
                if not clean:
                    try:
                        control.send(("stop", None))
                    except (BrokenPipeError, EOFError, OSError):
                        pass
                    until = time.monotonic() + 11
                    while process.pid is not None and time.monotonic() < until:
                        if not reader.empty():
                            try:
                                kind, data = reader.get_nowait()
                            except (EOFError, OSError):
                                break
                            if kind == "clean":
                                clean = True
                                outcome, result = data
                                break
                            if kind == "unresolved":
                                break
                            if kind == "eof":
                                break
                        await asyncio.sleep(.01)
                if process.pid is not None:
                    until = time.monotonic() + 1
                    while process.is_alive() and time.monotonic() < until:
                        await asyncio.sleep(.01)
                    if process.is_alive() or process.exitcode != 0:
                        clean = False
                    else:
                        process.join(timeout=0)
                        process.close()
                # Closing our send end lets a lingering supervisor detect EOF.
                control.close()
                child_control.close()
                closed.set()
                if clean:
                    try:
                        marker.unlink()
                        _sync_directory(marker.parent)
                    except OSError:
                        clean = False
                if not clean:
                    reservation.retained = True
                    self.stop_admission()
                    raise CleanupUnresolved("Engine cleanup unresolved; offline recovery required.") from None
        if failure is not None:
            raise failure
        if outcome == "timed_out" or time.monotonic() >= min(reservation.deadline, phase_deadline):
            raise ExecutionDeadline("Engine execution deadline exceeded.")
        if outcome != "ok":
            raise ExecutionStopped("Engine operation failed.")
        return result

    def stop_admission(self) -> None:
        self.accepting = False

    async def shutdown(self) -> None:
        self.stop_admission()
        tasks = [task for task in self._executions if task is not asyncio.current_task()]
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        unresolved = any(reservation.retained for reservation in self._admitted)
        if not unresolved:
            for name in ("_ownership_lock", "_owner_lock"):
                lock = getattr(self, name)
                if lock is not None:
                    lock.close()
                    setattr(self, name, None)
        else:
            raise CleanupUnresolved("Shutdown incomplete: engine ownership remains unresolved.")


async def execute_job(job, settings, *, emit):
    """Child has no SQLite handle; only the parent can publish job state."""
    from backend.app.engine_service import run_job

    class ResultStore:
        def __init__(self):
            self.updates = {}
        async def update(self, job_id, **updates):
            self.updates.update(updates)
            emit(("update", updates))

    store = ResultStore()
    await run_job(job, store, settings)
    return store.updates


_JOB_UPLOAD_PATHS = frozenset({
    "/v1/remediate", "/v1/office/remediate", "/v1/vision-plan/run",
    "/v1/convert/pdf-to-html", "/v1/convert/office-to-html", "/v1/convert/html-to-pdf",
})


def _direct_operation(path: str) -> bool:
    return (path.startswith(("/v1/pdf/", "/v1/validate/", "/v1/html/"))
            or path in {"/v1/office/check", "/v1/convert/extract-markdown",
                        "/v1/quality/audit/pdf", "/v1/quality/audit/office"})


class EngineAdmissionMiddleware:
    """Reserve before route staging; direct operations use the same process slots."""
    def __init__(self, app, execution: OwnedExecution, settings, direct_entrypoint=None) -> None:
        self.app, self.execution, self.settings = app, execution, settings
        self.direct_entrypoint = direct_entrypoint or execute_http

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if (scope["type"] != "http" or scope.get("method") != "POST"
                or scope.get("remedy_owned_child")
                or (path not in _JOB_UPLOAD_PATHS and not _direct_operation(path))):
            return await self.app(scope, receive, send)
        from fastapi.responses import JSONResponse, Response
        from starlette.requests import Request
        from slowapi import _rate_limit_exceeded_handler
        from slowapi.errors import RateLimitExceeded
        from slowapi.middleware import _find_route_handler
        from dataclasses import replace
        from backend.app.request_envelope import declared_too_large, refusal
        import shutil
        import uuid

        if declared_too_large(scope,self.settings.request_byte_limit):
            return await refusal()(scope,receive,send)
        reservation = None
        request_dir = None
        request = Request(scope, receive=receive)
        limiter = request.app.state.limiter
        # Direct routes are replayed in fresh child apps. Account rate limits
        # once in the retained parent storage, using the real caller address.
        if path not in _JOB_UPLOAD_PATHS and limiter.enabled:
            handler = _find_route_handler(request.app.routes, scope)
            if handler is not None:
                try:
                    limiter._check_request_limit(request, handler, False)
                    request.state._rate_limiting_complete = True
                except RateLimitExceeded as exc:
                    return await _rate_limit_exceeded_handler(request, exc)(scope, receive, send)
        async def bounded_receive():
            remaining = reservation.deadline - time.monotonic()
            if remaining <= 0:
                raise ExecutionDeadline("Request admission deadline exceeded.")
            try:
                return await asyncio.wait_for(receive(), remaining)
            except TimeoutError:
                raise ExecutionDeadline("Request admission deadline exceeded.") from None
        try:
            reservation = self.execution.reserve()
            if path in _JOB_UPLOAD_PATHS:
                scope.setdefault("state", {})["engine_reservation"] = reservation
                return await self.app(scope, bounded_receive, send)
            contents = bytearray()
            while True:
                message = await bounded_receive()
                if message["type"] == "http.disconnect":
                    return
                contents.extend(message.get("body", b""))
                if len(contents) > self.settings.request_byte_limit:
                    raise HTTPException(413, "Request exceeds upload size limit.")
                if not message.get("more_body", False):
                    break
            request_dir = self.settings.job_dir / ("_request-" + uuid.uuid4().hex)
            child_settings = replace(self.settings, job_dir=request_dir,
                                     job_store_path=request_dir / "request.db")
            wire_scope = {key: scope[key] for key in ("method", "path", "query_string", "headers", "scheme")}
            code, headers, content = await self.execution.run(
                self.direct_entrypoint, (child_settings, wire_scope, bytes(contents)), reservation)
            if code == 200 and path in {"/v1/pdf/fix", "/v1/pdf/rebuild"}:
                # Token downloads are a second parent HTTP request. Publish the
                # completed child artifact only after all owned processes stop.
                token = json.loads(content).get("download_token")
                if token:
                    pattern = (r"_pdf-[0-9a-f]{32}\.fixed\.pdf" if path.endswith("/fix")
                               else r"_pdf-[0-9a-f]{32}\.rebuilt\.preserving\.pdf")
                    artifact = request_dir / token if isinstance(token, str) and re.fullmatch(pattern, token) else None
                    if artifact is None or artifact.is_symlink() or not artifact.is_file() or artifact.stat().st_size == 0:
                        raise ExecutionStopped("Direct operation produced no downloadable artifact.")
                    self.settings.job_dir.mkdir(parents=True, exist_ok=True)
                    destination = self.settings.job_dir / token
                    if destination.exists():
                        raise ExecutionStopped("Direct artifact publication conflict.")
                    artifact.replace(destination)
            response = Response(content=content, status_code=code)
            response.raw_headers = headers
            if limiter.enabled and hasattr(request.state, "view_rate_limit"):
                response = limiter._inject_headers(response, request.state.view_rate_limit)
            await response(scope, receive, send)
        except ExecutionDeadline:
            await JSONResponse({"detail": "Engine execution deadline exceeded."}, status_code=504)(scope, receive, send)
        except ExecutionStopped:
            await JSONResponse({"detail": "Engine operation failed."}, status_code=500)(scope, receive, send)
        except HTTPException as exc:
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                               headers=exc.headers)(scope, receive, send)
        finally:
            if request_dir is not None and (reservation is None or not reservation.retained):
                shutil.rmtree(request_dir, ignore_errors=True)
            if reservation is not None and not reservation.transferred:
                reservation.release()


async def execute_http(settings, wire_scope, body, *, emit):
    """Replay a direct engine request inside its owned process, with no worker lifespan."""
    import httpx
    from backend.app.main import create_app
    app = create_app(settings)
    async def owned_app(scope, receive, send):
        scope["remedy_owned_child"] = True
        scope.setdefault("state", {})["_rate_limiting_complete"] = True
        scope["state"]["view_rate_limit"] = None  # parent injects its authoritative rate headers
        await app(scope, receive, send)
    query = wire_scope["query_string"].decode("ascii")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=owned_app),
                                base_url=f"{wire_scope['scheme']}://owned.invalid", follow_redirects=False) as client:
        response = await client.request(wire_scope["method"], wire_scope["path"] + ("?" + query if query else ""),
                                        headers=wire_scope["headers"], content=body)
    return response.status_code, list(response.headers.raw), response.content
