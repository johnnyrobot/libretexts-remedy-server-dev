"""FastAPI entry point.

Run with ``uvicorn backend.app.main:app --reload``.
"""

from __future__ import annotations

import os
import asyncio
import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from backend.app.backup import backup_jobstore
from backend.app.auth import require_api_key_dependency
from backend.app.config import Settings, load_settings, operation_timeout
from backend.app.execution import EngineAdmissionMiddleware, OwnedExecution, execute_job, execute_http, in_owned_child
from backend.app.jobs import JobStore, JobWorker, prune_expired_jobs
from backend.app.logging_setup import configure_logging, request_id_var
from backend.app.routes import build_router
from backend.app.scheduler import PeriodicTask


def create_app(settings: Settings | None = None, *, job_entrypoint=execute_job,
               direct_entrypoint=execute_http) -> FastAPI:
    """Application factory. Accepts an injected ``Settings`` for tests."""
    configure_logging()
    log = structlog.get_logger("project_remedy.backend")

    settings = settings or load_settings()
    config_errors = settings.validation_errors()
    if config_errors:
        raise RuntimeError("Invalid Remedy Server settings: " + "; ".join(config_errors))

    store = JobStore(settings.job_store_path)

    execution = OwnedExecution(settings.worker_concurrency, settings.worker_max_pending,
                               settings.job_total_timeout_seconds)

    async def _runner(job):
        async def acquired():
            await store.update(job.id, status="running", stage="starting", progress=0.05)
        async def progress(updates):
            # Output paths/terminal state are private until every owned process exits.
            visible = {key: value for key, value in updates.items() if key in {"stage", "progress"}}
            if updates.get("status") in {"done", "failed"}:
                visible = {}
            if visible:
                await store.update(job.id, **visible)
        timeouts = {}
        if job.kind == "remediate_pdf":
            for stage, variable, default in [
                ("remediating", "PDF_REMEDIATION_TIMEOUT_SECONDS", 900),
                ("evaluating_acceptance", "PDF_ACCEPTANCE_TIMEOUT_SECONDS", 300),
                ("evaluating_quality", "PDF_ACCEPTANCE_TIMEOUT_SECONDS", 300),
            ]:
                timeouts[stage] = operation_timeout(variable, default)
        result = await execution.run(job_entrypoint, (job, settings), worker.reservation_for(job.id),
                                     on_update=progress, operation_timeouts=timeouts, on_acquired=acquired)
        if result.get("status") not in {"done", "failed"}:
            raise RuntimeError("Engine returned without a terminal outcome.")
        if result["status"] == "failed":
            result["error"] = "Engine operation failed."
        await store.update(job.id, **result)

    worker = JobWorker(store, _runner, concurrency=settings.worker_concurrency, execution=execution)

    pruner = PeriodicTask(
        lambda: prune_expired_jobs(
            store, settings.job_dir, settings.job_retention_hours
        ),
        interval_seconds=settings.prune_interval_hours * 3600,
        name="job-pruner",
    )
    backup_task = PeriodicTask(
        lambda: backup_jobstore(
            settings.job_store_path,
            settings.backup_dir,
            settings.backup_keep_n,
        ),
        interval_seconds=settings.backup_interval_hours * 3600,
        name="jobstore-backup",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ARG001
        log.info(
            "app.startup",
            app_env=settings.app_env,
            job_dir=str(settings.job_dir),
            auth_enabled=bool(settings.api_key),
            worker_concurrency=settings.worker_concurrency,
        )
        execution.start_ownership(settings.job_store_path.resolve().with_name(settings.job_store_path.resolve().name + ".execution.lock"))
        interrupted, queued = 0, []
        if execution.accepting:
            interrupted = await store.fail_running_jobs(
                "Server restarted while this job was running; submit it again if needed."
            )
            queued = await store.list_by_statuses({"queued"})
            for job in queued:
                try:
                    await worker.enqueue(job.id)
                except HTTPException:
                    await store.update(job.id, status="failed", stage="interrupted",
                                       error="Restart queue capacity exceeded; input retained.")
        if interrupted or queued:
            log.info(
                "jobs.recovered",
                interrupted_failed=interrupted,
                queued_reenqueued=len(queued),
            )
        worker.start()
        await pruner.start()
        await backup_task.start()
        try:
            yield
        finally:
            log.info("app.shutdown")
            execution.stop_admission()
            await backup_task.stop()
            await pruner.stop()
            await asyncio.gather(worker.stop(), execution.shutdown())

    # ----- Rate limiter --------------------------------------------------

    # slowapi reads the default limit from env or configured Limiter args.
    default_limit = os.environ.get("RATE_LIMIT_DEFAULT", "60/minute")
    upload_limit = os.environ.get("RATE_LIMIT_UPLOADS", "10/minute")

    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[default_limit],
        headers_enabled=True,
        storage_uri=os.environ.get("RATE_LIMIT_STORAGE", "memory://"),
        strategy="fixed-window",
    )

    app = FastAPI(
        title="Remedy Server — PDF Accessibility Remediation API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    # Make the limiter available to route builders that want per-route limits.
    app.state.limiter = limiter
    app.state.upload_rate_limit = upload_limit
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(EngineAdmissionMiddleware, execution=execution, settings=settings,
                       direct_entrypoint=direct_entrypoint)


    # ----- Request-ID + structured access log middleware -----------------

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            log.error(
                "request.error",
                method=request.method,
                path=request.url.path,
                elapsed_ms=round(elapsed_ms, 2),
                error=type(exc).__name__,
            )
            request_id_var.reset(token)
            return JSONResponse(
                status_code=500,
                content={"detail": "internal server error", "request_id": rid},
                headers={"x-request-id": rid},
            )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        response.headers["x-request-id"] = rid
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("x-frame-options", "DENY")
        response.headers.setdefault("referrer-policy", "no-referrer")
        response.headers.setdefault("cache-control", "no-store")
        # Skip noisy healthz logging.
        if request.url.path not in ("/healthz", "/readyz"):
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                elapsed_ms=round(elapsed_ms, 2),
                client=request.client.host if request.client else "",
            )
        request_id_var.reset(token)
        return response

    require_app_key = require_api_key_dependency(settings)

    @app.middleware("http")
    async def authenticate_api(request: Request, call_next):
        # Authenticate before body parsing and routing, including unknown aliases.
        if request.url.path.startswith("/v1/"):
            try:
                await require_app_key(request)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    app.state.settings = settings
    app.state.store = store
    app.state.worker = worker
    app.state.execution = execution

    app.include_router(build_router(settings, store, worker, limiter, upload_limit))

    from backend.app.pdf_routes import build_router as build_pdf_router
    from backend.app.pdf_fix_routes import build_router as build_pdf_fix_router
    from backend.app.office_routes import build_router as build_office_router
    from backend.app.html_routes import build_router as build_html_router
    from backend.app.validate_routes import build_router as build_validate_router
    from backend.app.vision_plan_routes import build_router as build_vp_router
    from backend.app.quality_routes import build_router as build_quality_router
    from backend.app.cxone_routes import build_router as build_cxone_router
    app.include_router(build_pdf_router(settings, limiter, upload_limit))
    app.include_router(build_pdf_fix_router(settings, limiter, upload_limit))
    app.include_router(build_office_router(settings, store, worker, limiter, upload_limit))
    app.include_router(build_html_router(settings, limiter, upload_limit))
    app.include_router(build_validate_router(settings, limiter, upload_limit))
    app.include_router(build_vp_router(settings, store, worker, limiter, upload_limit))
    app.include_router(build_quality_router(settings, limiter, upload_limit))
    app.include_router(build_cxone_router(settings))

    return app


# Module-level app for uvicorn convenience
app = None if in_owned_child() else create_app()
