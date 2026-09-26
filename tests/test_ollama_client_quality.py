from __future__ import annotations

import pytest

from project_remedy.behavioral_proxies.shared.base import BehavioralModelSeparationError
from project_remedy.config import APIConfig, PipelineConfig
from project_remedy.ollama_client import OllamaClient


def test_quality_judge_client_uses_configured_model_and_base_url() -> None:
    config = PipelineConfig(
        api=APIConfig(
            base_url="https://ollama.example/v1",
            text_model="gemma4:31b-cloud",
            quality_judge_base_url="http://localhost:11434/v1",
            quality_judge_model="llama3.1:8b",
        )
    )

    client = OllamaClient.for_quality_judge(config)

    assert client.base_url == "http://localhost:11434/v1"
    assert client.text_model == "llama3.1:8b"


def test_quality_judge_client_falls_back_to_default_base_url() -> None:
    config = PipelineConfig(
        api=APIConfig(
            base_url="https://ollama.example/v1",
            text_model="gemma4:31b-cloud",
            quality_judge_base_url="",
            quality_judge_model="llama3.1:8b",
        )
    )

    client = OllamaClient.for_quality_judge(config)

    assert client.base_url == "https://ollama.example/v1"
    assert client.text_model == "llama3.1:8b"


def test_behavioral_test_client_uses_independent_answerer_model() -> None:
    config = PipelineConfig(
        api=APIConfig(
            text_model="gemma4:31b-cloud",
            behavioral_test_model="qwen2.5:7b",
        )
    )

    client = OllamaClient.for_behavioral_test(config)

    assert client.text_model == "qwen2.5:7b"


def test_behavioral_test_client_rejects_generator_model_family() -> None:
    config = PipelineConfig(
        api=APIConfig(
            text_model="gemma4:31b-cloud",
            behavioral_test_model="gemma4:9b",
        )
    )

    with pytest.raises(BehavioralModelSeparationError):
        OllamaClient.for_behavioral_test(config)
