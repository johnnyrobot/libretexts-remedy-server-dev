"""A checker that crashes must not be recorded as a pass."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from project_remedy.models import ValidationResult
from project_remedy.validator import AccessibilityValidator


def _validator() -> AccessibilityValidator:
    config = SimpleNamespace(
        validation=SimpleNamespace(
            max_remediation_cycles=1,
            fail_on_serious=True,
            wave_api_key=None,
            wave_report_type=1,
        )
    )
    return AccessibilityValidator(config, None, db=None)


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
