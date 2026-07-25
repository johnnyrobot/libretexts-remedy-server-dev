"""Shared behavioral proxy protocol and result types."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol


class BehavioralModelSeparationError(ValueError):
    """Raised when a behavioral test model overlaps with artifact generators."""


@dataclass(frozen=True)
class BehavioralTestConfig:
    """Runtime configuration for LLM-backed behavioral proxy tests."""

    backend: str
    model: str
    production_models: tuple[str, ...] = ()
    artifact_generator_models: tuple[str, ...] = ()
    cache_path: str = ""

    def validate_model_separation(self) -> None:
        """Raise if the behavioral answerer overlaps with artifact generators."""
        assert_behavioral_model_separation(
            self.model,
            self.production_models,
            artifact_generator_models=self.artifact_generator_models,
        )


@dataclass
class BehavioralTestResult:
    """Result from one functional quality proxy test."""

    test_name: str
    dimension: str
    format: str
    passed: bool
    score: float = 0.0
    threshold: float = 0.0
    confidence: float = 0.0
    findings: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.test_name, str) or not self.test_name.strip():
            raise ValueError("test_name must be a non-empty string")
        if not isinstance(self.dimension, str) or not self.dimension.strip():
            raise ValueError("dimension must be a non-empty string")
        if not isinstance(self.format, str) or not self.format.strip():
            raise ValueError("format must be a non-empty string")
        if not isinstance(self.passed, bool):
            raise ValueError("passed must be a boolean")
        if not isinstance(self.findings, list):
            raise ValueError("findings must be a list")
        if any(not isinstance(finding, dict) for finding in self.findings):
            raise ValueError("findings entries must be objects")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be an object")
        require_unit_interval("score", self.score)
        require_unit_interval("threshold", self.threshold)
        require_unit_interval("confidence", self.confidence)
        dimensions_by_format = _dimensions_by_format()
        if self.format not in dimensions_by_format:
            raise ValueError(f"unsupported behavioral result format: {self.format}")
        if self.dimension not in dimensions_by_format[self.format]:
            raise ValueError(
                f"behavioral result dimension {self.dimension!r} "
                f"is not applicable to {self.format}"
            )


class BehavioralTest(Protocol):
    """Protocol implemented by format-specific behavioral proxy tests."""

    test_name: str
    dimension: str
    format: str

    def run(self, artifact_path: Path, **kwargs: Any) -> BehavioralTestResult:
        """Run the proxy test on one artifact."""


class BehavioralResultCache:
    """Small JSON-backed cache keyed by document hash and proxy identity."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._items: dict[str, dict[str, Any]] | None = None

    def get(self, key: str) -> BehavioralTestResult | None:
        """Return a cached result if present and structurally valid."""
        payload = self._load().get(key)
        if not isinstance(payload, dict):
            return None
        try:
            findings = payload.get("findings") or []
            metadata = payload.get("metadata") or {}
            if not isinstance(payload["test_name"], str):
                return None
            if not isinstance(payload["dimension"], str):
                return None
            if not isinstance(payload["format"], str):
                return None
            if not isinstance(findings, list):
                return None
            if not isinstance(metadata, dict):
                return None
            return BehavioralTestResult(
                test_name=payload["test_name"],
                dimension=payload["dimension"],
                format=payload["format"],
                passed=payload["passed"],
                score=payload.get("score", 0.0),
                threshold=payload.get("threshold", 0.0),
                confidence=payload.get("confidence", 0.0),
                findings=findings,
                metadata=metadata,
            )
        except (KeyError, TypeError, ValueError):
            return None

    def set(self, key: str, result: BehavioralTestResult) -> None:
        """Persist one behavioral proxy result."""
        items = self._load()
        items[key] = asdict(result)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(items, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._items is not None:
            return self._items
        if not self.path.exists():
            self._items = {}
            return self._items
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        self._items = loaded if isinstance(loaded, dict) else {}
        return self._items


def artifact_sha256(path: Path) -> str:
    """Hash an artifact for behavioral proxy cache keys."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def behavioral_cache_key(
    test: BehavioralTest,
    artifact_path: Path,
    *,
    behavioral_model: str = "",
) -> str:
    """Build the document-hash cache key for a behavioral proxy."""
    return ":".join(
        [
            artifact_sha256(artifact_path),
            test.format,
            test.test_name,
            test.__class__.__module__,
            test.__class__.__name__,
            behavioral_model.strip().lower(),
        ]
    )


def run_behavioral_tests(
    tests: Iterable[BehavioralTest],
    artifact_path: Path,
    *,
    cache_path: str | Path = "",
    behavioral_model: str = "",
    artifact_generator_models: tuple[str, ...] = (),
    **kwargs: Any,
) -> dict[str, BehavioralTestResult]:
    """Run behavioral tests, optionally using a document-hash result cache."""
    if artifact_generator_models:
        assert_behavioral_model_separation(
            behavioral_model,
            (),
            artifact_generator_models=artifact_generator_models,
        )
    cache = BehavioralResultCache(cache_path) if cache_path else None
    results: dict[str, BehavioralTestResult] = {}
    for test in tests:
        if cache is not None and artifact_path.exists():
            key = behavioral_cache_key(
                test,
                artifact_path,
                behavioral_model=behavioral_model,
            )
            cached = cache.get(key)
            if cached is not None and _behavioral_metadata_matches(
                cached,
                behavioral_model=behavioral_model,
                artifact_generator_models=artifact_generator_models,
            ):
                results[test.test_name] = cached
                continue
            result = test.run(artifact_path, **kwargs)
            _attach_behavioral_metadata(
                result,
                behavioral_model=behavioral_model,
                artifact_generator_models=artifact_generator_models,
            )
            cache.set(key, result)
        else:
            result = test.run(artifact_path, **kwargs)
            _attach_behavioral_metadata(
                result,
                behavioral_model=behavioral_model,
                artifact_generator_models=artifact_generator_models,
            )
        results[test.test_name] = result
    return results


def behavioral_model_family(model: str) -> str:
    """Return a coarse model family identifier for separation checks."""
    normalized = model.strip().lower()
    if not normalized:
        return ""
    normalized = normalized.rsplit("/", 1)[-1]
    normalized = normalized.split(":", 1)[0]
    for suffix in ("-cloud", "_cloud"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
    return normalized


def assert_behavioral_model_separation(
    behavioral_model: str,
    production_models: tuple[str, ...],
    *,
    artifact_generator_models: tuple[str, ...] = (),
) -> None:
    """Enforce behavioral answerer separation from artifact generator models."""
    model = behavioral_model.strip()
    family = behavioral_model_family(model)
    if not model or not family:
        raise BehavioralModelSeparationError("BEHAVIORAL_TEST_MODEL must be configured")

    generator_models = [
        ("production remediation model", generator_model)
        for generator_model in production_models
    ] + [
        ("artifact generator model", generator_model)
        for generator_model in artifact_generator_models
    ]
    for label, generator_model in generator_models:
        generator = generator_model.strip()
        if not generator:
            continue
        if model.lower() == generator.lower():
            raise BehavioralModelSeparationError(
                f"BEHAVIORAL_TEST_MODEL must differ from {label}s"
            )
        if family == behavioral_model_family(generator):
            raise BehavioralModelSeparationError(
                "BEHAVIORAL_TEST_MODEL must come from a different model family "
                f"than {label} {generator!r}"
            )


def behavioral_config_from_pipeline(config: Any) -> BehavioralTestConfig:
    """Build behavioral-test config from ``PipelineConfig`` without coupling."""
    api = config.api
    production_models = tuple(
        model
        for model in (
            getattr(api, "text_model", ""),
            getattr(api, "vision_model", ""),
            getattr(api, "escalation_model", ""),
        )
        if model
    )
    behavioral = BehavioralTestConfig(
        backend=getattr(api, "behavioral_test_backend", "ollama"),
        model=getattr(api, "behavioral_test_model", ""),
        production_models=production_models,
        cache_path=getattr(api, "behavioral_test_cache_path", ""),
    )
    behavioral.validate_model_separation()
    return behavioral


def require_unit_interval(field_name: str, value: float) -> float:
    """Return a validated finite numeric value between 0.0 and 1.0."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"{field_name} must be finite")
    if numeric < 0.0 or numeric > 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return numeric


def _attach_behavioral_metadata(
    result: BehavioralTestResult,
    *,
    behavioral_model: str,
    artifact_generator_models: tuple[str, ...],
) -> None:
    if behavioral_model:
        result.metadata["behavioral_model"] = behavioral_model
    if artifact_generator_models:
        result.metadata["artifact_generator_models"] = list(artifact_generator_models)


def _behavioral_metadata_matches(
    result: BehavioralTestResult,
    *,
    behavioral_model: str,
    artifact_generator_models: tuple[str, ...],
) -> bool:
    if behavioral_model and result.metadata.get("behavioral_model") != behavioral_model:
        return False
    if artifact_generator_models and result.metadata.get("artifact_generator_models") != list(
        artifact_generator_models
    ):
        return False
    return True


def _dimensions_by_format() -> dict[str, tuple[str, ...]]:
    from project_remedy.quality_judges.shared.dimensions import DIMENSIONS_BY_FORMAT

    return DIMENSIONS_BY_FORMAT
