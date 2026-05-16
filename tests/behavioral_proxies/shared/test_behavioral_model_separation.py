from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from project_remedy.behavioral_proxies.shared.base import (
    BehavioralResultCache,
    BehavioralTestResult,
    BehavioralModelSeparationError,
    BehavioralTestConfig,
    assert_behavioral_model_separation,
    artifact_sha256,
    behavioral_config_from_pipeline,
    behavioral_model_family,
    run_behavioral_tests,
)
from project_remedy.config import APIConfig, PipelineConfig


def test_behavioral_model_family_normalizes_cloud_suffixes() -> None:
    assert behavioral_model_family("ollama/qwen2.5:7b-cloud") == "qwen2.5"
    assert behavioral_model_family("gemma4:31b-cloud") == "gemma4"


def test_behavioral_test_result_rejects_invalid_score_ranges() -> None:
    with pytest.raises(ValueError, match="score must be between 0 and 1"):
        BehavioralTestResult(
            test_name="reading_order",
            dimension="reading_order",
            format="pdf",
            passed=False,
            score=1.1,
        )

    with pytest.raises(ValueError, match="threshold must be between 0 and 1"):
        BehavioralTestResult(
            test_name="reading_order",
            dimension="reading_order",
            format="pdf",
            passed=False,
            threshold=-0.1,
        )

    with pytest.raises(ValueError, match="score must be finite"):
        BehavioralTestResult(
            test_name="reading_order",
            dimension="reading_order",
            format="pdf",
            passed=False,
            score=float("nan"),
        )

    with pytest.raises(ValueError, match="passed must be a boolean"):
        BehavioralTestResult(
            test_name="reading_order",
            dimension="reading_order",
            format="pdf",
            passed="false",
        )


def test_behavioral_test_result_rejects_inapplicable_format_dimension() -> None:
    with pytest.raises(
        ValueError,
        match="behavioral result dimension 'reading_order' is not applicable to xlsx",
    ):
        BehavioralTestResult(
            test_name="reading_order",
            dimension="reading_order",
            format="xlsx",
            passed=False,
        )

    with pytest.raises(ValueError, match="unsupported behavioral result format: txt"):
        BehavioralTestResult(
            test_name="alt_text_substitution",
            dimension="alt_text",
            format="txt",
            passed=False,
        )


def test_behavioral_test_result_rejects_malformed_identity_and_payload_shapes() -> None:
    invalid_cases = [
        (
            {"test_name": ""},
            "test_name must be a non-empty string",
        ),
        (
            {"dimension": ""},
            "dimension must be a non-empty string",
        ),
        (
            {"format": ""},
            "format must be a non-empty string",
        ),
        (
            {"findings": "not-a-list"},
            "findings must be a list",
        ),
        (
            {"findings": ["not-an-object"]},
            "findings entries must be objects",
        ),
        (
            {"metadata": ["not", "an", "object"]},
            "metadata must be an object",
        ),
    ]

    for kwargs, message in invalid_cases:
        payload = {
            "test_name": "reading_order_comprehension",
            "dimension": "reading_order",
            "format": "pdf",
            "passed": True,
        }
        payload.update(kwargs)
        with pytest.raises(ValueError, match=message):
            BehavioralTestResult(**payload)


def test_behavioral_model_separation_rejects_production_family() -> None:
    with pytest.raises(BehavioralModelSeparationError):
        assert_behavioral_model_separation("gemma4:9b", ("gemma4:31b-cloud",))


def test_behavioral_model_separation_rejects_artifact_generator_family() -> None:
    with pytest.raises(
        BehavioralModelSeparationError,
        match="artifact generator model",
    ):
        assert_behavioral_model_separation(
            "qwen2.5:7b",
            (),
            artifact_generator_models=("qwen2.5:14b-cloud",),
        )


def test_behavioral_model_separation_accepts_independent_answerer() -> None:
    config = BehavioralTestConfig(
        backend="ollama",
        model="qwen2.5:7b",
        production_models=("gemma4:31b-cloud", "kimi-k2.6:cloud"),
    )

    config.validate_model_separation()


def test_behavioral_config_from_pipeline_uses_configured_model() -> None:
    config = PipelineConfig(
        api=APIConfig(
            text_model="gemma4:31b-cloud",
            vision_model="gemma4:31b-cloud",
            escalation_model="gemma4:31b-cloud",
            behavioral_test_model="qwen2.5:7b",
            behavioral_test_cache_path="/tmp/behavioral-cache.json",
        )
    )

    behavioral = behavioral_config_from_pipeline(config)

    assert behavioral.model == "qwen2.5:7b"
    assert behavioral.cache_path == "/tmp/behavioral-cache.json"
    assert behavioral.production_models == (
        "gemma4:31b-cloud",
        "gemma4:31b-cloud",
        "gemma4:31b-cloud",
    )


def test_behavioral_config_from_pipeline_rejects_production_model_family() -> None:
    config = PipelineConfig(
        api=APIConfig(
            text_model="gemma4:31b-cloud",
            vision_model="gemma4:31b-cloud",
            escalation_model="gemma4:31b-cloud",
            behavioral_test_model="gemma4:9b",
        )
    )

    with pytest.raises(BehavioralModelSeparationError):
        behavioral_config_from_pipeline(config)


def test_artifact_sha256_hashes_file_contents(tmp_path) -> None:
    artifact = tmp_path / "artifact.pdf"
    artifact.write_bytes(b"same bytes")

    assert artifact_sha256(artifact) == artifact_sha256(artifact)


def test_run_behavioral_tests_uses_document_hash_cache(tmp_path) -> None:
    artifact = tmp_path / "artifact.pdf"
    artifact.write_bytes(b"%PDF-1.4\n%%EOF")
    cache_path = tmp_path / "behavioral-cache.json"
    calls = {"count": 0}

    class CountingBehavioralTest:
        test_name = "counting_test"
        dimension = "reading_order"
        format = "pdf"

        def run(self, artifact_path: Path, **kwargs):  # noqa: ANN001, ARG002
            calls["count"] += 1
            return BehavioralTestResult(
                test_name=self.test_name,
                dimension=self.dimension,
                format=self.format,
                passed=True,
                score=0.91,
                threshold=0.90,
                confidence=0.8,
            )

    first = run_behavioral_tests(
        [CountingBehavioralTest()],
        artifact,
        cache_path=cache_path,
    )
    second = run_behavioral_tests(
        [CountingBehavioralTest()],
        artifact,
        cache_path=cache_path,
    )

    assert calls["count"] == 1
    assert first["counting_test"].score == 0.91
    assert second["counting_test"].score == 0.91


def test_run_behavioral_tests_cache_is_scoped_to_behavioral_model(tmp_path) -> None:
    artifact = tmp_path / "artifact.pdf"
    artifact.write_bytes(b"%PDF-1.4\n%%EOF")
    cache_path = tmp_path / "behavioral-cache.json"
    calls = {"count": 0}

    class CountingBehavioralTest:
        test_name = "counting_test"
        dimension = "reading_order"
        format = "pdf"

        def run(self, artifact_path: Path, **kwargs):  # noqa: ANN001, ARG002
            calls["count"] += 1
            return BehavioralTestResult(
                test_name=self.test_name,
                dimension=self.dimension,
                format=self.format,
                passed=True,
                score=0.9,
                threshold=0.8,
            )

    first = run_behavioral_tests(
        [CountingBehavioralTest()],
        artifact,
        cache_path=cache_path,
        behavioral_model="qwen2.5:7b",
    )
    second = run_behavioral_tests(
        [CountingBehavioralTest()],
        artifact,
        cache_path=cache_path,
        behavioral_model="llama3.1:8b",
    )
    third = run_behavioral_tests(
        [CountingBehavioralTest()],
        artifact,
        cache_path=cache_path,
        behavioral_model="qwen2.5:7b",
    )

    assert calls["count"] == 2
    assert first["counting_test"].metadata["behavioral_model"] == "qwen2.5:7b"
    assert second["counting_test"].metadata["behavioral_model"] == "llama3.1:8b"
    assert third["counting_test"].metadata["behavioral_model"] == "qwen2.5:7b"


def test_run_behavioral_tests_rejects_artifact_generator_overlap(tmp_path) -> None:
    class CountingBehavioralTest:
        test_name = "counting_test"
        dimension = "reading_order"
        format = "pdf"

        def run(self, artifact_path: Path, **kwargs):  # noqa: ANN001, ARG002
            raise AssertionError("overlapping artifact generator should fail first")

    with pytest.raises(BehavioralModelSeparationError, match="artifact generator model"):
        run_behavioral_tests(
            [CountingBehavioralTest()],
            tmp_path / "artifact.pdf",
            behavioral_model="qwen2.5:7b",
            artifact_generator_models=("qwen2.5:14b",),
        )


def test_behavioral_result_cache_rejects_non_boolean_passed(tmp_path) -> None:
    cache_path = tmp_path / "behavioral-cache.json"
    cache_path.write_text(
        '{"key":{"test_name":"cached","dimension":"reading_order","format":"pdf",'
        '"passed":"false","score":0.9,"threshold":0.8,"confidence":0.7}}\n',
        encoding="utf-8",
    )

    assert BehavioralResultCache(cache_path).get("key") is None


def test_behavioral_result_cache_rejects_coerced_numeric_fields(tmp_path) -> None:
    cache_path = tmp_path / "behavioral-cache.json"
    cache_path.write_text(
        '{"bool":{"test_name":"cached","dimension":"reading_order","format":"pdf",'
        '"passed":true,"score":true,"threshold":0.8,"confidence":0.7},'
        '"string":{"test_name":"cached","dimension":"reading_order","format":"pdf",'
        '"passed":true,"score":"0.9","threshold":0.8,"confidence":0.7},'
        '"nan":{"test_name":"cached","dimension":"reading_order","format":"pdf",'
        '"passed":true,"score":0.9,"threshold":NaN,"confidence":0.7}}\n',
        encoding="utf-8",
    )
    cache = BehavioralResultCache(cache_path)

    assert cache.get("bool") is None
    assert cache.get("string") is None
    assert cache.get("nan") is None


def test_behavioral_result_cache_rejects_malformed_metadata_shapes(tmp_path) -> None:
    cache_path = tmp_path / "behavioral-cache.json"
    cache_path.write_text(
        '{"findings":{"test_name":"cached","dimension":"reading_order","format":"pdf",'
        '"passed":true,"score":0.9,"threshold":0.8,"confidence":0.7,'
        '"findings":"not-a-list"},'
        '"metadata":{"test_name":"cached","dimension":"reading_order","format":"pdf",'
        '"passed":true,"score":0.9,"threshold":0.8,"confidence":0.7,'
        '"metadata":["not","an","object"]}}\n',
        encoding="utf-8",
    )
    cache = BehavioralResultCache(cache_path)

    assert cache.get("findings") is None
    assert cache.get("metadata") is None


def test_run_behavioral_tests_skips_cache_for_missing_artifacts(tmp_path) -> None:
    missing = tmp_path / "missing.pdf"
    calls = {"count": 0}

    class CountingBehavioralTest:
        test_name = "counting_test"
        dimension = "reading_order"
        format = "pdf"

        def run(self, artifact_path: Path, **kwargs):  # noqa: ANN001, ARG002
            calls["count"] += 1
            return BehavioralTestResult(
                test_name=self.test_name,
                dimension=self.dimension,
                format=self.format,
                passed=True,
            )

    run_behavioral_tests([CountingBehavioralTest()], missing, cache_path=tmp_path / "cache.json")
    run_behavioral_tests([CountingBehavioralTest()], missing, cache_path=tmp_path / "cache.json")

    assert calls["count"] == 2


def test_behavioral_prompt_artifacts_are_trackable() -> None:
    repo_root = Path(__file__).parents[3]
    prompt_dir = repo_root / "src/project_remedy/behavioral_proxies/shared/prompts"
    expected = {
        "question_generation_v1.md",
        "answer_retention_v1.md",
        "navigation_accuracy_v1.md",
        "table_lookup_v1.md",
        "decorative_equivalence_v1.md",
    }
    prompt_files = sorted(prompt_dir.glob("*.md"))

    assert {path.name for path in prompt_files} == expected
    assert all("JSON" in path.read_text(encoding="utf-8") for path in prompt_files)
    result = subprocess.run(
        [
            "git",
            "check-ignore",
            *[str(path.relative_to(repo_root)) for path in prompt_files],
        ],
        cwd=repo_root,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 1, result.stdout + result.stderr


def test_behavioral_source_files_are_not_hidden_by_test_file_ignore_rules() -> None:
    repo_root = Path(__file__).parents[3]
    source_files = [
        repo_root / "src/project_remedy/behavioral_proxies/pdf/decorative_skip_test.py"
    ]

    result = subprocess.run(
        [
            "git",
            "check-ignore",
            *[str(path.relative_to(repo_root)) for path in source_files],
        ],
        cwd=repo_root,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 1, result.stdout + result.stderr
