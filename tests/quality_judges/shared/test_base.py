from __future__ import annotations

from dataclasses import fields

import pytest

from project_remedy.config import APIConfig, PipelineConfig
from project_remedy.quality_judges.shared.base import (
    ModelSeparationError,
    QualityJudgeConfig,
    assert_model_separation,
    model_family,
    quality_config_from_pipeline,
)


def test_model_family_normalizes_provider_and_cloud_suffixes() -> None:
    assert model_family("gemma4:31b-cloud") == "gemma4"
    assert model_family("ollama/gemma4:9b") == "gemma4"
    assert model_family("kimi-k2.6:cloud") == "kimi-k2.6"


def test_model_separation_rejects_exact_and_family_matches() -> None:
    with pytest.raises(ModelSeparationError):
        assert_model_separation("gemma4:31b-cloud", ("gemma4:31b-cloud",))

    with pytest.raises(ModelSeparationError):
        assert_model_separation("gemma4:9b", ("gemma4:31b-cloud",))


def test_model_separation_accepts_distinct_family() -> None:
    config = QualityJudgeConfig(
        backend="ollama",
        model="llama3.1:8b",
        production_models=("gemma4:31b-cloud", "kimi-k2.6:cloud"),
    )

    config.validate_model_separation()


def test_quality_config_from_pipeline_uses_configured_judge_model() -> None:
    config = PipelineConfig(
        api=APIConfig(
            text_model="gemma4:31b-cloud",
            vision_model="gemma4:31b-cloud",
            escalation_model="gemma4:31b-cloud",
            quality_judge_model="llama3.1:8b",
        )
    )

    quality = quality_config_from_pipeline(config)

    assert quality.model == "llama3.1:8b"
    assert quality.production_models == (
        "gemma4:31b-cloud",
        "gemma4:31b-cloud",
        "gemma4:31b-cloud",
    )


def test_quality_config_from_pipeline_rejects_production_family() -> None:
    config = PipelineConfig(
        api=APIConfig(
            text_model="gemma4:31b-cloud",
            vision_model="gemma4:31b-cloud",
            escalation_model="gemma4:31b-cloud",
            quality_judge_model="gemma4:9b",
        )
    )

    with pytest.raises(ModelSeparationError):
        quality_config_from_pipeline(config)


def test_acceptance_results_have_optional_quality_result_field() -> None:
    from project_remedy.office_acceptance import OfficeAcceptanceResult
    from project_remedy.pdf_acceptance import PDFAcceptanceResult

    pdf_fields = {field.name: field.default for field in fields(PDFAcceptanceResult)}
    office_fields = {field.name: field.default for field in fields(OfficeAcceptanceResult)}

    assert pdf_fields["quality_result"] is None
    assert office_fields["quality_result"] is None
