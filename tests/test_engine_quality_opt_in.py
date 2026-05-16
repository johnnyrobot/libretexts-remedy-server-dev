from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.jobs import JOB_KIND_REMEDIATE_OFFICE, JOB_KIND_REMEDIATE_PDF, Job
from project_remedy.models import FileType
from project_remedy.quality_judges.shared.base import (
    QualityDimensionScore,
    QualityResult,
)


class _FakeStore:
    def __init__(self) -> None:
        self.updates: list[dict] = []

    async def update(self, job_id: str, **kwargs):  # noqa: ANN001
        self.updates.append({"job_id": job_id, **kwargs})
        return None


def _job(tmp_path: Path, *, kind: str, suffix: str, metadata: dict) -> Job:
    input_path = tmp_path / f"input{suffix}"
    input_path.write_bytes(b"%PDF-1.4\n%%EOF" if suffix == ".pdf" else b"PK\x03\x04fake")
    return Job(
        id="job-1",
        kind=kind,
        status="running",
        stage="starting",
        progress=0.0,
        input_path=str(input_path),
        output_path="",
        report_path="",
        error="",
        created_at="2026-05-08T00:00:00+00:00",
        updated_at="2026-05-08T00:00:00+00:00",
        metadata_json=json.dumps(metadata),
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        api_key="",
        ollama_api_key="test",
        job_store_path=tmp_path / "jobs.db",
        job_dir=tmp_path / "jobs",
        backup_dir=tmp_path / "backups",
        quality_experiment_store_path=tmp_path / "quality_experiments.db",
    )


async def test_pdf_quality_opt_in_attaches_result_to_report(monkeypatch, tmp_path) -> None:
    from backend.app import engine_service

    quality = QualityResult(
        format="pdf",
        dimensions={
            "alt_text": QualityDimensionScore("alt_text", "pdf", 0.9)
        },
        overall_pass=True,
    )
    seen = {}

    def fake_fix(input_path, output_path, **kwargs):  # noqa: ANN001, ARG001
        Path(output_path).write_bytes(b"%PDF-1.4\n%%EOF")

    class FakeVera:
        checked = False
        passed = True

    class FakeAcceptance:
        passed = True
        verapdf_result = FakeVera()
        quality_result = None

    def fake_acceptance(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        return FakeAcceptance()

    def fake_audit(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        return quality

    def fake_report(*, output_dir, acceptance, **kwargs):  # noqa: ANN001, ARG001
        seen["quality_result"] = acceptance.quality_result
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "report.html").write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(engine_service, "fix_and_verify", fake_fix)
    monkeypatch.setattr(engine_service, "evaluate_pdf_acceptance", fake_acceptance)
    monkeypatch.setattr(
        "project_remedy.quality_judges.pdf.audit.audit_pdf_quality",
        fake_audit,
    )
    monkeypatch.setattr(engine_service, "generate_document_report", fake_report)

    store = _FakeStore()
    await engine_service._remediate_pdf(
        _job(tmp_path, kind=JOB_KIND_REMEDIATE_PDF, suffix=".pdf", metadata={"quality": True}),
        store,
        _settings(tmp_path),
    )

    assert seen["quality_result"] is quality
    assert store.updates[-1]["status"] == "done"


async def test_pdf_quality_opt_in_obeys_calibration_gate(monkeypatch, tmp_path) -> None:
    from backend.app import engine_service
    from backend.app.quality_calibration import QualityCalibrationError

    def fake_fix(input_path, output_path, **kwargs):  # noqa: ANN001, ARG001
        Path(output_path).write_bytes(b"%PDF-1.4\n%%EOF")

    class FakeVera:
        checked = False
        passed = True

    class FakeAcceptance:
        passed = True
        verapdf_result = FakeVera()
        quality_result = None

    def fake_acceptance(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        return FakeAcceptance()

    def fail_audit(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        raise AssertionError("quality audit should not run before calibration")

    monkeypatch.setattr(engine_service, "fix_and_verify", fake_fix)
    monkeypatch.setattr(engine_service, "evaluate_pdf_acceptance", fake_acceptance)
    monkeypatch.setattr(
        "project_remedy.quality_judges.pdf.audit.audit_pdf_quality",
        fail_audit,
    )

    settings = replace(_settings(tmp_path), quality_require_calibration=True)

    with pytest.raises(QualityCalibrationError):
        await engine_service._remediate_pdf(
            _job(tmp_path, kind=JOB_KIND_REMEDIATE_PDF, suffix=".pdf", metadata={"quality": True}),
            _FakeStore(),
            settings,
        )


async def test_pdf_default_flow_does_not_run_quality_audit(monkeypatch, tmp_path) -> None:
    from backend.app import engine_service

    seen = {}

    def fake_fix(input_path, output_path, **kwargs):  # noqa: ANN001, ARG001
        Path(output_path).write_bytes(b"%PDF-1.4\n%%EOF")

    class FakeVera:
        checked = False
        passed = True

    class FakeAcceptance:
        passed = True
        verapdf_result = FakeVera()
        quality_result = None

    def fake_acceptance(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        return FakeAcceptance()

    def fail_audit(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        raise AssertionError("quality audit should not run by default")

    def fake_report(*, output_dir, acceptance, **kwargs):  # noqa: ANN001, ARG001
        seen["quality_result"] = acceptance.quality_result
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "report.html").write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(engine_service, "fix_and_verify", fake_fix)
    monkeypatch.setattr(engine_service, "evaluate_pdf_acceptance", fake_acceptance)
    monkeypatch.setattr(
        "project_remedy.quality_judges.pdf.audit.audit_pdf_quality",
        fail_audit,
    )
    monkeypatch.setattr(engine_service, "generate_document_report", fake_report)

    store = _FakeStore()
    await engine_service._remediate_pdf(
        _job(tmp_path, kind=JOB_KIND_REMEDIATE_PDF, suffix=".pdf", metadata={}),
        store,
        _settings(tmp_path),
    )

    assert seen["quality_result"] is None
    assert store.updates[-1]["status"] == "done"


async def test_office_quality_opt_in_persists_quality_result_metadata(monkeypatch, tmp_path) -> None:
    from backend.app import engine_service

    quality = QualityResult(
        format="docx",
        dimensions={
            "heading_semantics": QualityDimensionScore("heading_semantics", "docx", 1.0)
        },
        overall_pass=True,
    )

    class FakeOfficeRemediator:
        async def remediate(self, file_path, output_path, **kwargs):  # noqa: ANN001, ARG002
            Path(output_path).write_bytes(b"PK\x03\x04fake")

    def fake_audit(file_path, *, file_type, config=None):  # noqa: ANN001, ARG001
        assert file_type == FileType.DOCX
        return quality

    monkeypatch.setattr(
        "project_remedy.office_remediator.OfficeRemediator",
        lambda: FakeOfficeRemediator(),
    )
    monkeypatch.setattr(
        "project_remedy.quality_judges.office.audit.audit_office_quality",
        fake_audit,
    )

    store = _FakeStore()
    await engine_service._remediate_office(
        _job(tmp_path, kind=JOB_KIND_REMEDIATE_OFFICE, suffix=".docx", metadata={"quality": True}),
        store,
        _settings(tmp_path),
    )

    metadata_updates = [
        update for update in store.updates if "metadata_json" in update
    ]
    assert metadata_updates
    metadata = json.loads(metadata_updates[-1]["metadata_json"])
    assert metadata["quality_result"]["format"] == "docx"
    assert metadata["quality_result"]["dimensions"]["heading_semantics"]["score"] == 1.0


async def test_office_quality_opt_in_obeys_calibration_gate(monkeypatch, tmp_path) -> None:
    from backend.app import engine_service
    from backend.app.quality_calibration import QualityCalibrationError

    class FakeOfficeRemediator:
        async def remediate(self, file_path, output_path, **kwargs):  # noqa: ANN001, ARG002
            Path(output_path).write_bytes(b"PK\x03\x04fake")

    def fail_audit(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        raise AssertionError("office quality audit should not run before calibration")

    monkeypatch.setattr(
        "project_remedy.office_remediator.OfficeRemediator",
        lambda: FakeOfficeRemediator(),
    )
    monkeypatch.setattr(
        "project_remedy.quality_judges.office.audit.audit_office_quality",
        fail_audit,
    )

    settings = replace(_settings(tmp_path), quality_require_calibration=True)

    with pytest.raises(QualityCalibrationError):
        await engine_service._remediate_office(
            _job(tmp_path, kind=JOB_KIND_REMEDIATE_OFFICE, suffix=".docx", metadata={"quality": True}),
            _FakeStore(),
            settings,
        )


async def test_office_default_flow_does_not_run_quality_audit(monkeypatch, tmp_path) -> None:
    from backend.app import engine_service

    class FakeOfficeRemediator:
        async def remediate(self, file_path, output_path, **kwargs):  # noqa: ANN001, ARG002
            Path(output_path).write_bytes(b"PK\x03\x04fake")

    def fail_audit(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        raise AssertionError("quality audit should not run by default")

    monkeypatch.setattr(
        "project_remedy.office_remediator.OfficeRemediator",
        lambda: FakeOfficeRemediator(),
    )
    monkeypatch.setattr(
        "project_remedy.quality_judges.office.audit.audit_office_quality",
        fail_audit,
    )

    store = _FakeStore()
    await engine_service._remediate_office(
        _job(tmp_path, kind=JOB_KIND_REMEDIATE_OFFICE, suffix=".docx", metadata={}),
        store,
        _settings(tmp_path),
    )

    assert not any("metadata_json" in update for update in store.updates)
    assert store.updates[-1]["status"] == "done"
