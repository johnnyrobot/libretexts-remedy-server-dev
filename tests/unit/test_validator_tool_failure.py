"""A checker that crashes must not be recorded as a pass."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from project_remedy.database import DatabaseManager
from project_remedy.models import DocumentJob, JobStatus, RenderedPage, ValidationResult
from project_remedy.validator import AccessibilityValidator


def _validator(db=None) -> AccessibilityValidator:
    config = SimpleNamespace(
        validation=SimpleNamespace(
            max_remediation_cycles=1,
            fail_on_serious=True,
            wave_api_key=None,
            wave_report_type=1,
        )
    )
    return AccessibilityValidator(config, None, db=db)


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", ["axe", "pa11y", "lighthouse"])
async def test_crashed_checker_fails_closed(broken: str) -> None:
    validator = _validator()

    async def ok(tool: str):
        return ValidationResult(tool=tool, score=100, violations=[], passed=True)

    async def boom(_path: Path):
        raise RuntimeError("checker crashed")

    validator.validate_with_axe = boom if broken == "axe" else (lambda _p: ok("axe"))
    validator.validate_with_pa11y = boom if broken == "pa11y" else (lambda _p: ok("pa11y"))
    validator.validate_with_lighthouse = (
        boom if broken == "lighthouse" else (lambda _p: ok("lighthouse"))
    )

    report = await validator.validate(Path("unused.html"))

    assert report.passed is False
    assert "Checker did not run" in report.summary
    result = {
        "axe": report.axe_result,
        "pa11y": report.pa11y_result,
        "lighthouse": report.lighthouse_result,
    }[broken]
    assert result.passed is False


@pytest.mark.asyncio
async def test_clean_run_still_passes() -> None:
    validator = _validator()

    async def ok(tool: str):
        return ValidationResult(tool=tool, score=100, violations=[], passed=True)

    validator.validate_with_axe = lambda _p: ok("axe")
    validator.validate_with_pa11y = lambda _p: ok("pa11y")
    validator.validate_with_lighthouse = lambda _p: ok("lighthouse")

    report = await validator.validate(Path("unused.html"))

    assert report.passed is True
    assert "Checker did not run" not in report.summary


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["pa11y", "lighthouse"])
@pytest.mark.parametrize("cleanup", ["normal", "pipe-stuck", "exit-race"])
async def test_checker_timeout_does_not_report_success(monkeypatch, tool, cleanup) -> None:
    class Process:
        returncode = None

        async def communicate(self):
            if self.returncode is None or cleanup == "pipe-stuck":
                raise asyncio.TimeoutError
            return b"", b""

        def kill(self):
            self.returncode = -9
            if cleanup == "exit-race":
                raise ProcessLookupError

    process = Process()

    async def spawn(*args, **kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(RuntimeError, match=f"{tool}.*timed out"):
        await getattr(_validator(), f"validate_with_{tool}")(Path("unused.html"))
    assert process.returncode == -9


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["pa11y", "lighthouse"])
@pytest.mark.parametrize("failure", ["malformed", "missing", "wrong-shape", "exit"])
async def test_invalid_checker_output_does_not_report_success(monkeypatch, tool, failure):
    output = b"not JSON" if failure == "malformed" else (
        b"" if failure == "missing" else json.dumps({}).encode()
    )

    class Process:
        returncode = 1 if failure == "exit" else 0

        async def communicate(self):
            return output, b"checker failed"

    async def spawn(*args, **kwargs):
        if tool == "lighthouse":
            path = Path(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--output-path=")))
            if failure == "missing":
                path.unlink()
            else:
                path.write_bytes(output)
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(RuntimeError, match=tool):
        await getattr(_validator(), f"validate_with_{tool}")(Path("unused.html"))


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,issues", [("pa11y", False), ("pa11y", True), ("lighthouse", False)])
async def test_completed_checker_output_retains_its_verdict(monkeypatch, tool, issues):
    output = [{"type": "error", "message": "Image is missing alt text", "code": "WCAG2AA.1_1_1"}] if issues else []

    class Process:
        returncode = 2 if issues else 0

        async def communicate(self):
            return json.dumps(output).encode(), b""

    async def spawn(*args, **kwargs):
        if tool == "lighthouse":
            path = Path(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--output-path=")))
            path.write_text(json.dumps({"categories": {"accessibility": {"score": 1}}, "audits": {}}))
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    result = await getattr(_validator(), f"validate_with_{tool}")(Path("unused.html"))
    assert result.passed is not issues
    assert len(result.violations) == (1 if issues else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["standalone", "rendered", "job"])
async def test_checker_only_failure_never_attempts_llm_remediation(monkeypatch, tmp_path, entrypoint):
    # Replace only the external browser and CLI boundaries; validation and all
    # remediation orchestration run through their real public interfaces.
    import playwright.async_api

    page = SimpleNamespace(goto=AsyncMock(), add_script_tag=AsyncMock(),
                           wait_for_function=AsyncMock(),
                           evaluate=AsyncMock(return_value={"violations": []}))
    browser = SimpleNamespace(new_page=AsyncMock(return_value=page), close=AsyncMock())

    class Playwright:
        async def __aenter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)))

        async def __aexit__(self, *args):
            return None

    async def spawn(*args, **kwargs):
        raise RuntimeError("checker unavailable")

    monkeypatch.setattr(playwright.async_api, "async_playwright", Playwright)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    validator = _validator(db=DatabaseManager())
    html = "<!doctype html><html lang='en'><title>Clean</title><body><p>Clean page</p></body></html>"
    path = tmp_path / "index.html"
    path.write_text(html)
    job = DocumentJob(generated_html=html)

    if entrypoint == "standalone":
        result = await validator.remediate_html_path(path)
        assert result.passed is False
        assert result.used_llm is False
        assert "Checker did not run" in result.final_report.summary
    elif entrypoint == "rendered":
        rendered = RenderedPage("canonical", "canonical", "Clean", "index.html", html)
        result = await validator.validate_rendered_page(job, rendered, path)
        assert result.passed is False
        assert "Checker did not run" in result.error_message
    else:
        report = await validator.validate(path)
        result = await validator.auto_remediate(job, report)
        assert result.status is JobStatus.FLAGGED
        assert "Checker did not run" in result.error_message

    assert result.remediation_count == 0
    assert (result.generated_html if entrypoint == "job" else result.html) == html
    assert path.read_text() == html
