"""Preserve the source-pinned v1 HTML response at its agreed public seam.

The real validator orchestration and serializer run; external checker adapters
are synthetic. These tests do not claim browser, CLI, HTTP or live execution.
Fixture version/provenance fields belong to the manifest, not the response.
"""

import hashlib
import json
import math
from pathlib import Path

import pytest

from backend.app.html_utils import serialize_validation_report
from project_remedy.config import PipelineConfig
from project_remedy.database import DatabaseManager
from project_remedy.models import ValidationResult
from project_remedy.validator import AccessibilityValidator


FIXTURES = Path(__file__).parent / "contracts_v1"
MANIFEST = json.loads((FIXTURES / "remedy-html-validation.json").read_text())


def assert_findings_preserved(actual, expected):
    assert isinstance(actual, list)
    assert len(actual) == len(expected)
    for received, known in zip(actual, expected, strict=True):
        assert isinstance(received, dict)
        assert known.keys() <= received.keys()
        assert {key: received[key] for key in known} == known


def validator_with_adapters(monkeypatch, case):
    """Fixed synthetic tool observations, independent of golden output data."""
    validator = AccessibilityValidator(PipelineConfig(), None, DatabaseManager())
    impacts = {"warning": "moderate", "accessibility_failure": "serious", "null_impact": None}

    async def axe(_path):
        violations = []
        if case in impacts:
            violations.append({
                "tool": "axe", "id": "synthetic-rule", "impact": impacts[case],
                "description": "Synthetic contract example", "help": "Synthetic explanation",
                "help_url": "https://example.invalid/rule", "wcag": "wcag111",
                "nodes_count": 1, "html_snippets": ['<img src="synthetic.png">'],
            })
        return ValidationResult(tool="axe", passed=case != "accessibility_failure", violations=violations)

    async def pa11y(_path):
        if case == "partial_checker_failure":
            raise RuntimeError("Synthetic external checker unavailable")
        return ValidationResult(tool="pa11y", passed=True, violations=[])

    async def lighthouse(_path):
        return ValidationResult(tool="lighthouse", score=100, passed=True, violations=[])

    monkeypatch.setattr(validator, "validate_with_axe", axe)
    monkeypatch.setattr(validator, "validate_with_pa11y", pa11y)
    monkeypatch.setattr(validator, "validate_with_lighthouse", lighthouse)
    return validator


@pytest.mark.parametrize("example", MANIFEST["examples"], ids=lambda example: example["name"])
async def test_current_orchestration_and_serializer_preserve_v1(monkeypatch, example):
    validator = validator_with_adapters(monkeypatch, example["name"])
    report = await validator.validate(Path("synthetic-external-adapter-input.html"))
    payload = serialize_validation_report(report)
    expected = example["body"]

    # Human-readable summary wording is deliberately not a machine contract.
    assert isinstance(payload["summary"], str)
    assert type(payload["overall_passed"]) is bool
    assert isinstance(payload["all_violations"], list)
    assert expected.keys() <= payload.keys()  # additive evolution is allowed
    for name, value in expected.items():
        if name == "summary":
            continue
        if name in {"axe", "pa11y", "lighthouse", "wave"}:
            assert value.keys() <= payload[name].keys()
            assert type(payload[name]["passed"]) is bool
            assert isinstance(payload[name]["violations"], list)
            score = payload[name]["score"]
            assert score is None or (type(score) in {int, float} and math.isfinite(score))
            for field, field_value in value.items():
                if field == "violations":
                    assert_findings_preserved(payload[name][field], field_value)
                else:
                    assert payload[name][field] == field_value
        elif name == "all_violations":
            assert_findings_preserved(payload[name], value)
        else:
            assert payload[name] == value


async def test_optional_lighthouse_fields_and_empty_strings_are_preserved(monkeypatch):
    validator = validator_with_adapters(monkeypatch, "pass")
    finding = {"tool": "lighthouse", "id": "", "description": "", "impact": "moderate", "score": 0.5}

    async def lighthouse(_path):
        # Unknown synthetic data exercises additive fields without inventing a required wire field.
        observation = {**finding, "synthetic_extension": {"enabled": True}}
        return ValidationResult(tool="lighthouse", score=90, passed=True, violations=[observation])

    monkeypatch.setattr(validator, "validate_with_lighthouse", lighthouse)
    payload = serialize_validation_report(await validator.validate(Path("synthetic.html")))
    assert_findings_preserved(payload["all_violations"], [finding])
    assert_findings_preserved(payload["lighthouse"]["violations"], [finding])
    assert payload["overall_passed"] is True
    # No wcag/selector fields were fabricated or required for this tool.


def test_integration_fixtures_pin_agreed_sources_and_authoritative_adapt_array():
    pins = json.loads((FIXTURES / "integration-targets.json").read_text())
    adapt = json.loads((FIXTURES / "adapt-assignment-enumeration.json").read_text())
    assert pins["server"]["html_fixture_sha256"] == hashlib.sha256(
        (FIXTURES / "remedy-html-validation.json").read_bytes()
    ).hexdigest()
    assert MANIFEST["contract_id_is_payload_field"] is False
    assert MANIFEST["source_commit"] == "78710dc0af53d3e63a662fb392b5190f2e2d0dab"
    assert adapt["source_commit"] == pins["adapt"]["commit"] == "ee9478b0b418d222c17a15a004a36cec43858dfd"
    assert adapt["request"] == {"method": "GET", "path": "/api/assignments/{assignment}/questions/ids"}
    cases = {example["name"]: example for example in adapt["examples"]}
    assert cases["enumerated"]["body"] == {
        "type": "success", "question_ids": "[101,202]", "question_ids_array": [101, 202],
    }
    assert cases["empty_success"]["body"]["question_ids_array"] == []
    assert pins["conductor"]["staging_commit"] == "67301b35c3784ed73ba1a65011ef5a1d689abca1"
    assert pins["conductor"]["released_floor_commit"] == "352a657ec6de7b317a70ad3f8f744bc6d5054d9d"
    assert pins["conductor"]["released_floor_tag"] == "v2.156.2"
