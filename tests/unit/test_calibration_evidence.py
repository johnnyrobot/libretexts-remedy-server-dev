"""Calibration capability must distinguish readable mechanics from human evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import hashlib

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("stored", [False, True])
def test_scores_do_not_certify_committed_placeholder_corpus(tmp_path, stored):
    command = [
        sys.executable, "tools/calibrate_judges.py", "calibrate", "--root", "tools/corpus_annotations/v1",
        "--store", str(tmp_path / "scores.db"),
        "--enforce-readiness", "--dry-run", "--json",
    ]
    if stored:
        command += ["--judge-results", "tools/corpus_annotations/v1/judge_results.jsonl"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60,
        env=os.environ | {"PYTHON_DOTENV_DISABLED": "1"})
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["calibration_ready"] is False
    assert payload["recorded"] is False
    assert payload["readiness_errors"]
    assert payload["readable_sources"] == 0
    assert payload["synthetic_records"] == 50


def test_actual_audit_path_refuses_placeholders_before_judge_execution(monkeypatch):
    from tools import calibrate_judges
    records, errors = calibrate_judges.load_annotation_records(ROOT / "tools/corpus_annotations/v1")
    assert not errors
    def forbidden(*args, **kwargs):
        pytest.fail("An invalid placeholder reached a judge/provider")
    monkeypatch.setattr(calibrate_judges, "_audit_record", forbidden)
    rows, skipped = calibrate_judges.run_audits_for_annotations(records)
    assert rows == []
    assert len(skipped) == 50
    assert all("parser-readable" in message for message in skipped)


@pytest.mark.parametrize("fmt", ["pdf", "docx", "pptx", "xlsx"])
def test_parser_valid_synthetic_artifact_proves_mechanics_only(tmp_path, fmt):
    from project_remedy.quality_judges.shared.corpus_evidence import artifact_readability_errors, inspect_corpus_evidence
    from tests.unit.office_fixtures import make_docx, make_pptx, make_xlsx
    source = tmp_path / ("synthetic." + fmt)
    if fmt == "pdf":
        from reportlab.pdfgen.canvas import Canvas
        canvas = Canvas(str(source))
        canvas.drawString(72, 720, "Synthetic fixture: no human review")
        canvas.save()
    else:
        {"docx": make_docx, "pptx": make_pptx, "xlsx": make_xlsx}[fmt](source)
    assert artifact_readability_errors(source, fmt) == []
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    record = {"doc_id": "synthetic_mechanics", "format": fmt, "annotator": "synthetic_fixture",
              "source_path": str(source), "gold_remediation_path": str(source),
              "known_bad_artifact_paths": [str(source)], "artifact_hashes": {
                  "source_sha256": sha, "gold_remediation_sha256": sha, "known_bad_sha256": {str(source): sha}},
              "provenance": {"gold_standard_source": "synthetic", "human_verified": False, "candidate_seed_notes": "Synthetic mechanics only"}}
    evidence = inspect_corpus_evidence([record], root=tmp_path)
    assert evidence.readable_sources == 1
    assert evidence.synthetic_records == 1
    assert evidence.approved is False
    assert any("human" in error for error in evidence.errors)
    # Forged metadata does not promote this explicitly synthetic evidence.
    record["provenance"].update(human_verified=True, gold_standard_source="human_specialist")
    judge_results = tmp_path / "synthetic-results.jsonl"
    judge_results.write_text("")
    current = inspect_corpus_evidence([record], root=tmp_path, judge_results=judge_results)
    forged = tmp_path / "forged-approval.json"
    forged.write_text(json.dumps({"schema_version": 1, "classification": "human_reviewed",
        "reviewer_id": "forged-reviewer", "reviewed_at": "2026-01-01T00:00:00+00:00",
        "evidence_reference": "forged negative-test claim", "corpus_digest": current.digest}))
    rejected = inspect_corpus_evidence([record], root=tmp_path, judge_results=judge_results, approval_path=forged)
    assert not rejected.approved
    assert any("synthetic/bootstrap" in error for error in rejected.errors)
    assert not any("approval is invalid" in error for error in rejected.errors)
    record["artifact_hashes"]["source_sha256"] = "0" * 64
    assert any("hash mismatch" in error for error in inspect_corpus_evidence([record], root=tmp_path).errors)


def test_perfect_stored_numbers_cannot_enable_unqualified_capability(tmp_path):
    from backend.app.config import Settings
    from backend.app.quality_calibration import quality_calibration_status, assert_quality_calibrated, QualityCalibrationError
    from project_remedy.vision_planner.experiment_store import ExperimentStore
    from project_remedy.quality_judges.shared.registry import required_judge_calibrations
    settings = Settings(quality_experiment_store_path=tmp_path / "scores.db", quality_require_calibration=False,
                        quality_corpus_root_path=ROOT / "tools/corpus_annotations/v1")
    store = ExperimentStore(settings.quality_experiment_store_path)
    for judge in required_judge_calibrations("pdf"):
        store.record_judge_calibration(judge_id=judge.judge_id, judge_version=judge.judge_version,
            format="pdf", dimension=judge.dimension, cohens_kappa=1.0, sample_size=100)
    status = quality_calibration_status(settings, "pdf")
    assert status.ready is False
    assert status.to_dict()["capability"] == "unavailable"
    assert status.calibrated_judges == []
    assert status.evidence_errors
    with pytest.raises(QualityCalibrationError):
        assert_quality_calibrated(settings, "pdf")
    assert len(store.list_judge_calibration(format="pdf")) == len(required_judge_calibrations("pdf"))


@pytest.mark.parametrize("damage", ["missing", "invalid", "changed"])
def test_independent_pairwise_candidates_are_parsed_and_bound_to_actual_bytes(tmp_path, damage):
    import pikepdf
    from project_remedy.quality_judges.shared.corpus_evidence import inspect_corpus_evidence
    source = tmp_path / "synthetic-source.pdf"
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page()
        pdf.save(source)
    candidate = tmp_path / "synthetic-pairwise.pdf"
    candidate.write_bytes(source.read_bytes())
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    record = {"doc_id": "synthetic-pairwise", "format": "pdf", "annotator": "synthetic",
        "source_path": str(source), "gold_remediation_path": str(source), "known_bad_artifact_paths": [str(source)],
        "artifact_hashes": {"source_sha256": sha, "gold_remediation_sha256": sha, "known_bad_sha256": {str(source): sha}},
        "provenance": {"human_verified": False, "gold_standard_source": "synthetic"},
        "pairwise_comparisons": [{"a_path": str(source), "b_path": str(candidate), "a_sha256": sha, "b_sha256": sha}]}
    before = inspect_corpus_evidence([record], root=tmp_path)
    assert not any("pairwise-0-b" in error for error in before.errors)
    if damage == "missing":
        candidate.unlink()  # only this test's owned synthetic temporary file
    elif damage == "invalid":
        candidate.write_bytes(b"synthetic invalid PDF")
        record["pairwise_comparisons"][0]["b_sha256"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    else:
        candidate.write_bytes(candidate.read_bytes() + b"\n% synthetic changed bytes\n")
    after = inspect_corpus_evidence([record], root=tmp_path)
    assert any("pairwise-0-b" in error for error in after.errors)
    assert after.digest != before.digest
    assert after.approved is False


@pytest.mark.parametrize("damage", ["invalid-number", "malformed-tail", "understated-dimension"])
def test_xlsx_readability_parses_deferred_worksheet_content(tmp_path, damage):
    from io import BytesIO
    from zipfile import ZipFile
    from openpyxl import Workbook
    from project_remedy.quality_judges.shared.corpus_evidence import artifact_readability_errors
    path = tmp_path / "synthetic-deferred-cells.xlsx"
    workbook = Workbook()
    workbook.active["A1"] = 1
    workbook.active["A2"] = 2
    workbook.active["A3"] = 3
    workbook.save(path)
    workbook.close()
    assert artifact_readability_errors(path, "xlsx") == []
    output = BytesIO()
    with ZipFile(path) as original, ZipFile(output, "w") as changed:
        for entry in original.infolist():
            content = original.read(entry.filename)
            if entry.filename == "xl/worksheets/sheet1.xml":
                assert b'<v>1</v>' in content
                if damage == "invalid-number":
                    content = content.replace(b'<v>1</v>', b'<v>not-a-number</v>')
                elif damage == "malformed-tail":
                    content = content.replace(b'</sheetData>', b'</brokenData>')
                else:
                    assert b'ref="A1:A3"' in content and b'<v>3</v>' in content
                    content = content.replace(b'ref="A1:A3"', b'ref="A1:A1"')
                    content = content.replace(b'<v>3</v>', b'<v>not-a-number</v>')
            changed.writestr(entry, content)
    path.write_bytes(output.getvalue())
    assert any("not parser-readable" in error for error in artifact_readability_errors(path, "xlsx"))
