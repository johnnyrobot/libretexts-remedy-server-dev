"""Office L0-L4 gates (PRD §3.1) + the AC3 never-L5 invariant."""

from __future__ import annotations

import random
from pathlib import Path

from project_remedy.levels import LevelResult
from project_remedy.models import FileType
from project_remedy.office_acceptance import (
    OfficeAcceptanceResult,
    OfficeCheckReport,
    OfficeCheckResult,
    OfficePackageResult,
    OfficeScreenReaderResult,
    evaluate_office_acceptance,
)
from project_remedy.office_levels import (
    OFFICE_PROFILE_NAME,
    OfficeStructureProbe,
    classify_level,
    probe_office_structure,
)
from project_remedy.quality_judges.shared.base import QualityResult
from tests.unit.office_fixtures import make_docx


def _acceptance(*, openable=True, statuses=(), quality=None) -> OfficeAcceptanceResult:
    path = Path("synthetic.docx")
    results = [
        OfficeCheckResult(rule_id=f"r{i}", description="d", status=s)
        for i, s in enumerate(statuses)
    ]
    return OfficeAcceptanceResult(
        file_path=path,
        file_type=FileType.DOCX,
        checker_report=OfficeCheckReport(file_path=path, file_type=FileType.DOCX, results=results),
        screen_reader_result=OfficeScreenReaderResult(file_path=path, file_type=FileType.DOCX, issues=[]),
        package_result=OfficePackageResult(checked=True, passed=openable),
        quality_result=quality,
    )


def _probe(**overrides) -> OfficeStructureProbe:
    base = dict(has_text=True, has_heading_structure=True, has_table_header_marks=False,
                has_alt_text_signal=False, paragraph_count=3, table_count=0, image_count=0)
    base.update(overrides)
    return OfficeStructureProbe(**base)


def test_gate_ladder():
    assert classify_level(None, _probe()).level == "L0"
    assert classify_level(_acceptance(openable=False), _probe()).level == "L0"
    assert classify_level(_acceptance(), _probe(has_text=False)).level == "L0"
    r = classify_level(_acceptance(), _probe(has_heading_structure=False))
    assert r.level == "L1" and r.blocking_conditions == ["no_structural_signal"]
    assert classify_level(_acceptance(statuses=["Failed"]), _probe()).level == "L2"
    r = classify_level(_acceptance(statuses=["Passed"]), _probe())
    assert r.level == "L3" and "quality_layer_not_run" in r.blocking_conditions
    bad_q = QualityResult(format="docx", overall_pass=False)
    assert classify_level(_acceptance(statuses=["Passed"], quality=bad_q), _probe()).level == "L3"
    good_q = QualityResult(format="docx", overall_pass=True)
    r = classify_level(_acceptance(statuses=["Passed"], quality=good_q), _probe())
    assert r.level == "L4" and r.profile == OFFICE_PROFILE_NAME
    assert isinstance(r, LevelResult)  # FR3: shared dataclass, not a fork


def test_manual_check_routes_to_needs_human_not_blocking():
    r = classify_level(_acceptance(statuses=["Passed", "Manual Check Needed"]), _probe())
    assert r.level == "L3"
    assert "r1" in r.needs_human


def test_never_l5_fuzz():
    """AC3: randomized inputs can never produce L5 (seeded — deterministic)."""
    rng = random.Random(20260701)
    statuses = ["Passed", "Failed", "Manual Check Needed"]
    for _ in range(500):
        acceptance = None
        if rng.random() > 0.1:
            quality = None
            if rng.random() > 0.5:
                quality = QualityResult(format="docx", overall_pass=rng.random() > 0.5)
            acceptance = _acceptance(
                openable=rng.random() > 0.2,
                statuses=[rng.choice(statuses) for _ in range(rng.randrange(0, 6))],
                quality=quality,
            )
        probe = _probe(
            has_text=rng.random() > 0.3,
            has_heading_structure=rng.random() > 0.5,
            has_table_header_marks=rng.random() > 0.5,
            has_alt_text_signal=rng.random() > 0.5,
        )
        result = classify_level(acceptance, probe)
        assert result.level in {"L0", "L1", "L2", "L3", "L4"}


def test_probe_reads_real_docx(tmp_path):
    rich = make_docx(tmp_path / "rich.docx", headings=[("T", 0)], tables=1,
                     inline_images=1, image_alt="chart",
                     body_paragraphs=["Some body text."])
    probe = probe_office_structure(rich, FileType.DOCX)
    assert probe.has_text and probe.has_heading_structure
    assert probe.has_table_header_marks and probe.has_alt_text_signal
    assert probe.table_count == 1 and probe.image_count == 1

    empty = make_docx(tmp_path / "empty.docx")
    probe = probe_office_structure(empty, FileType.DOCX)
    assert not probe.has_text and not probe.has_heading_structure

    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"not a zip at all")
    probe = probe_office_structure(broken, FileType.DOCX)  # must never raise
    assert probe == OfficeStructureProbe(False, False, False, False, 0, 0, 0)


def test_end_to_end_classification(tmp_path):
    path = make_docx(tmp_path / "l2.docx", title="T", headings=[("T", 0)],
                     inline_images=1, image_alt=None)  # structure present, alt fails
    acceptance = evaluate_office_acceptance(path)
    result = classify_level(acceptance, probe_office_structure(path, FileType.DOCX))
    assert result.level == "L2"
    assert "docx-alt-text" in result.blocking_conditions
