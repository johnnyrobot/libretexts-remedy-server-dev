"""Proposer: generate prompt variants when success rate drops below threshold.

Analyzes failure patterns from the experiment store and produces targeted
modifications to the VisionPlannerHarness configuration. Operates on the
harness.py interface (prompt templates, context assembly, output parsing).
"""

from __future__ import annotations

import copy
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from project_remedy.quality_judges.shared.dimensions import (
    DIMENSIONS_BY_FORMAT,
    dimension_from_behavioral_test,
)
from project_remedy.vision_planner.experiment_store import (
    ExperimentRecord,
    ExperimentStore,
    HarnessVariant,
    _weak_dimensions_by_doc_type,
    _weak_dimensions_overall,
)

logger = logging.getLogger(__name__)

DIMENSION_STRATEGY_MAP_PATH = Path(__file__).resolve().with_name(
    "dimension_strategy_map.yaml"
)
PROJECT_REMEDY_ROOT = Path(__file__).resolve().parents[1]

_DIMENSION_STRATEGY_TARGETS = {"planner_prompt", "grounder_prompt"}


# ---------------------------------------------------------------------------
# Proposal strategies
# ---------------------------------------------------------------------------


@dataclass
class ProposalStrategy:
    """A specific modification to try on a harness variant."""

    name: str
    description: str
    target: str  # "grounder_prompt", "planner_prompt", "violation_filter", etc.
    modifications: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Failure analysis
# ---------------------------------------------------------------------------


def analyze_failures(
    store: ExperimentStore, harness_id: str
) -> dict[str, Any]:
    """Analyze why a harness is failing and recommend strategies.

    Returns dict with:
    - success_rate: float
    - failure_count: int
    - top_failing_doc_types: list of (type, count)
    - top_failing_violation_types: list of (type, count)
    - recommended_strategies: list of ProposalStrategy
    """
    patterns = store.get_failure_patterns(harness_id)
    experiments = store.get_experiments_for_harness(harness_id)
    success_rate = store.compute_success_rate(harness_id)

    total = len(experiments)
    failures = total - sum(1 for e in experiments if e.passed)

    # Sort failure causes by frequency
    doc_types = sorted(
        patterns["failing_doc_types"].items(), key=lambda x: x[1], reverse=True
    )
    violation_types = sorted(
        patterns["failing_violation_types"].items(), key=lambda x: x[1], reverse=True
    )
    dimension_strategy_inputs = _pdf_dimension_strategy_inputs(experiments)

    strategies = _recommend_strategies(
        doc_types=doc_types,
        violation_types=violation_types,
        destructive_docs=patterns["destructive_docs"],
        common_errors=patterns["common_errors"],
        success_rate=success_rate,
        experiments=experiments,
        weak_dimensions_overall=dimension_strategy_inputs["weak_dimensions_overall"],
        weak_dimensions_by_doc_type=dimension_strategy_inputs["weak_dimensions_by_doc_type"],
        compliance_passes_quality_fails=dimension_strategy_inputs["compliance_passes_quality_fails"],
        behavioral_proxy_failures_by_dim=dimension_strategy_inputs["behavioral_proxy_failures_by_dim"],
    )

    return {
        "success_rate": success_rate,
        "failure_count": failures,
        "total_count": total,
        "top_failing_doc_types": doc_types[:5],
        "top_failing_violation_types": violation_types[:10],
        "destructive_count": len(patterns["destructive_docs"]),
        "weak_dimensions_overall": patterns.get("weak_dimensions_overall", {}),
        "weak_dimensions_by_doc_type": patterns.get("weak_dimensions_by_doc_type", {}),
        "weak_dimensions_by_format": patterns.get("weak_dimensions_by_format", {}),
        "weak_dimensions_by_format_and_doc_type": patterns.get(
            "weak_dimensions_by_format_and_doc_type",
            {},
        ),
        "compliance_passes_quality_fails": patterns.get("compliance_passes_quality_fails", []),
        "behavioral_proxy_failures_by_dim": patterns.get("behavioral_proxy_failures_by_dim", {}),
        "behavioral_proxy_failures_by_format": patterns.get(
            "behavioral_proxy_failures_by_format",
            {},
        ),
        "recommended_strategies": strategies,
    }


def _pdf_dimension_strategy_inputs(
    experiments: list[ExperimentRecord],
) -> dict[str, Any]:
    """Return only PDF quality evidence for the PDF vision-planner proposer.

    Reuses the shared aggregators in ``experiment_store`` so the PDF-only
    feed stays in lockstep with the multi-format failure-pattern aggregation.
    """
    pdf_experiments = [
        experiment
        for experiment in experiments
        if experiment.document_format == "pdf"
    ]
    return {
        "weak_dimensions_overall": _weak_dimensions_overall(pdf_experiments),
        "weak_dimensions_by_doc_type": _weak_dimensions_by_doc_type(pdf_experiments),
        "compliance_passes_quality_fails": _compliance_passes_quality_fails(pdf_experiments),
        "behavioral_proxy_failures_by_dim": _behavioral_failures_by_dimension(pdf_experiments),
    }


def _compliance_passes_quality_fails(
    experiments: list[ExperimentRecord],
) -> list[dict[str, Any]]:
    """List passing experiments whose quality dimensions still fall below 0.8."""
    results: list[dict[str, Any]] = []
    for experiment in experiments:
        if not experiment.passed:
            continue
        weak_dims = [
            dimension
            for dimension, score in experiment.quality_dimensions.items()
            if score < 0.8
        ]
        if weak_dims:
            results.append({"doc_hash": experiment.document_hash, "weak_dims": weak_dims})
    return results


def _behavioral_failures_by_dimension(
    experiments: list[ExperimentRecord],
) -> dict[str, int]:
    """Count failing behavioral proxy tests, grouped by the dimension they map to."""
    counts: dict[str, int] = {}
    for experiment in experiments:
        for test_name, passed in experiment.behavioral_results.items():
            if passed:
                continue
            dimension = dimension_from_behavioral_test(test_name)
            counts[dimension] = counts.get(dimension, 0) + 1
    return counts


def _recommend_strategies(
    doc_types: list[tuple[str, int]],
    violation_types: list[tuple[str, int]],
    destructive_docs: list[str],
    common_errors: dict[str, int],
    success_rate: float,
    experiments: list,
    weak_dimensions_overall: dict[str, float] | None = None,
    weak_dimensions_by_doc_type: dict[str, dict[str, float]] | None = None,
    compliance_passes_quality_fails: list[dict] | None = None,
    behavioral_proxy_failures_by_dim: dict[str, int] | None = None,
) -> list[ProposalStrategy]:
    """Generate recommended modification strategies based on failure analysis."""
    strategies: list[ProposalStrategy] = []

    # Strategy 1: Table structure improvements (if table violations dominate)
    table_violations = [
        (vt, c) for vt, c in violation_types
        if vt.startswith("7.2") or vt.startswith("7.5")
    ]
    if table_violations:
        table_count = sum(c for _, c in table_violations)
        total_violations = sum(c for _, c in violation_types)
        if total_violations > 0 and table_count / total_violations > 0.2:
            strategies.append(ProposalStrategy(
                name="table_structure_focus",
                description=(
                    f"Table violations account for {table_count}/{total_violations} "
                    f"({table_count/total_violations:.0%}) of failures. "
                    "Add explicit table reconstruction guidance to planner prompt."
                ),
                target="planner_prompt",
                modifications={
                    "add_table_examples": True,
                    "emphasize_table_structure": True,
                    "table_violation_count": table_count,
                },
            ))

    # Strategy 2: Untagged content handling
    untagged = [
        (vt, c) for vt, c in violation_types if vt.startswith("7.1")
    ]
    if untagged:
        untagged_count = sum(c for _, c in untagged)
        strategies.append(ProposalStrategy(
            name="untagged_content_tagging",
            description=(
                f"{untagged_count} untagged content violations. "
                "Improve grounder region detection and planner tag assignment."
            ),
            target="grounder_prompt",
            modifications={
                "emphasize_comprehensive_detection": True,
                "untagged_violation_count": untagged_count,
            },
        ))

    # Strategy 3: Reduce destructive edits
    if destructive_docs:
        strategies.append(ProposalStrategy(
            name="reduce_destructive_edits",
            description=(
                f"{len(destructive_docs)} documents had more violations after "
                "remediation than before. Raise confidence threshold and add "
                "conservative operation guards."
            ),
            target="confidence_threshold",
            modifications={
                "raise_threshold": True,
                "destructive_doc_count": len(destructive_docs),
                "add_safety_guards": True,
            },
        ))

    # Strategy 4: Parse error recovery
    parse_errors = {
        k: v for k, v in common_errors.items()
        if "parse" in k.lower() or "json" in k.lower()
    }
    if parse_errors:
        strategies.append(ProposalStrategy(
            name="output_parsing_robustness",
            description=(
                "Model output parsing failures detected. "
                "Add fallback parsing or switch to tool-calling mode."
            ),
            target="output_parsing",
            modifications={
                "use_tool_calling": True,
                "add_fallback_parsers": True,
                "parse_error_count": sum(parse_errors.values()),
            },
        ))

    # Strategy 5: Anchor graph compression (if documents are complex)
    complex_docs = [
        (dt, c) for dt, c in doc_types
        if "complex" in dt.lower() or "mixed" in dt.lower()
    ]
    if complex_docs:
        strategies.append(ProposalStrategy(
            name="anchor_graph_compression",
            description=(
                "Complex/mixed documents are failing. "
                "Compress anchor graph to reduce noise and focus on relevant regions."
            ),
            target="anchor_graph_format",
            modifications={
                "compress_graph": True,
                "filter_by_page": True,
                "limit_text_excerpts": True,
            },
        ))

    # Strategy 6: Violation grouping (always worth trying if success < 50%)
    if success_rate < 0.5:
        strategies.append(ProposalStrategy(
            name="violation_grouping",
            description=(
                f"Success rate is {success_rate:.0%}. "
                "Group violations by page and type so planner sees related "
                "violations together."
            ),
            target="planner_prompt",
            modifications={
                "group_by_page": True,
                "group_by_type": True,
                "prioritize_impactful": True,
            },
        ))

    # Strategy 7: Few-shot examples (only if there are actual failures and
    # no other strong strategy -- do not fire if success_rate is already high)
    if success_rate < 0.3 and (not strategies or len(strategies) < 2):
        strategies.append(ProposalStrategy(
            name="few_shot_examples",
            description=(
                "Add few-shot examples of successful remediation plans "
                "from prior experiments to guide the planner."
            ),
            target="planner_prompt",
            modifications={
                "add_examples": True,
                "example_source": "successful_experiments",
            },
        ))

    strategies.extend(
        _recommend_dimension_strategies(
            weak_dimensions_overall=weak_dimensions_overall or {},
            weak_dimensions_by_doc_type=weak_dimensions_by_doc_type or {},
            compliance_passes_quality_fails=compliance_passes_quality_fails or [],
            behavioral_proxy_failures_by_dim=behavioral_proxy_failures_by_dim or {},
            violation_types=violation_types,
        )
    )

    return strategies


def load_dimension_strategy_map(
    path: Path = DIMENSION_STRATEGY_MAP_PATH,
    *,
    validate: bool = True,
) -> dict[str, Any]:
    """Load the version-controlled dimension strategy map."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")

    strategies = data.get("strategies", {})
    if validate:
        validate_dimension_strategy_map(strategies, path=path)
    return strategies


def validate_dimension_strategy_map(
    strategy_map: dict[str, Any],
    *,
    path: Path = DIMENSION_STRATEGY_MAP_PATH,
    project_root: Path = PROJECT_REMEDY_ROOT,
) -> None:
    """Validate Phase G strategy declarations against the PRD map contract."""
    if not isinstance(strategy_map, dict) or not strategy_map:
        raise ValueError(f"{path} must define at least one strategy")

    pdf_dimensions = set(DIMENSIONS_BY_FORMAT["pdf"])
    claimed_hooks: dict[str, str] = {}
    claimed_target_hooks: dict[str, str] = {}

    for key, entry in strategy_map.items():
        if not isinstance(entry, dict):
            raise ValueError(f"{key}: strategy entry must be a mapping")

        dimension = entry.get("dimension")
        if dimension not in pdf_dimensions:
            raise ValueError(
                f"{key}: dimension {dimension!r} is not applicable to PDF evolution"
            )

        target = entry.get("target")
        if target not in _DIMENSION_STRATEGY_TARGETS:
            raise ValueError(
                f"{key}: target must be one of {sorted(_DIMENSION_STRATEGY_TARGETS)}"
            )

        hook = entry.get("hook")
        if not isinstance(hook, str) or not hook.strip():
            raise ValueError(f"{key}: hook is required")
        if hook in claimed_hooks:
            raise ValueError(
                f"{key}: hook {hook!r} is already claimed by {claimed_hooks[hook]}"
            )
        claimed_hooks[hook] = key

        pattern = entry.get("name_pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError(f"{key}: name_pattern is required")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"{key}: invalid name_pattern: {exc}") from exc

        concrete_targets = entry.get("targets")
        if not isinstance(concrete_targets, list) or not concrete_targets:
            raise ValueError(
                f"{key}: targets must declare at least one file/method/hook entry"
            )
        target_hooks = []
        for target_entry in concrete_targets:
            target_hook = _validate_dimension_strategy_target(
                key,
                target_entry,
                project_root,
            )
            target_owner = claimed_target_hooks.get(target_hook)
            if target_owner is not None:
                raise ValueError(
                    f"{key}: target hook {target_hook!r} is already claimed by "
                    f"{target_owner}"
                )
            claimed_target_hooks[target_hook] = key
            target_hooks.append(target_hook)
        if hook not in target_hooks:
            raise ValueError(f"{key}: primary hook {hook!r} is not in targets")


def _validate_dimension_strategy_target(
    strategy_key: str,
    target_entry: Any,
    project_root: Path,
) -> str:
    """Validate one concrete file/method/function target declaration."""
    if not isinstance(target_entry, dict):
        raise ValueError(f"{strategy_key}: target entry must be a mapping")

    file_name = target_entry.get("file")
    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError(f"{strategy_key}: target file is required")
    file_path = Path(file_name)
    if file_path.is_absolute():
        raise ValueError(f"{strategy_key}: target file must be repo-relative")

    resolved_root = project_root.resolve()
    resolved_file = (resolved_root / file_path).resolve()
    if resolved_file != resolved_root and resolved_root not in resolved_file.parents:
        raise ValueError(f"{strategy_key}: target file escapes project root")
    if not resolved_file.is_file():
        raise ValueError(f"{strategy_key}: target file does not exist: {file_name}")

    method = target_entry.get("method")
    function = target_entry.get("function")
    if bool(method) == bool(function):
        raise ValueError(
            f"{strategy_key}: target must declare exactly one method or function"
        )
    symbol = method if method else function
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError(f"{strategy_key}: target symbol is required")

    source = resolved_file.read_text(encoding="utf-8")
    symbol_name = symbol.rsplit(".", 1)[-1]
    if f"def {symbol_name}(" not in source and f"async def {symbol_name}(" not in source:
        raise ValueError(
            f"{strategy_key}: target symbol {symbol_name!r} not found in {file_name}"
        )
    if method and "." in method:
        class_name = method.split(".", 1)[0]
        if f"class {class_name}" not in source:
            raise ValueError(
                f"{strategy_key}: target class {class_name!r} not found in {file_name}"
            )

    hook = target_entry.get("hook")
    if not isinstance(hook, str) or not hook.strip():
        raise ValueError(f"{strategy_key}: target hook is required")
    return hook


def strategy_map_entry(
    strategy_name: str,
    strategy_map: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Find the map entry declaring a strategy name or name pattern."""
    mapping = strategy_map if strategy_map is not None else load_dimension_strategy_map()
    for key, entry in mapping.items():
        pattern = entry.get("name_pattern")
        if strategy_name == key or (pattern and re.match(pattern, strategy_name)):
            return {"key": key, **entry}
    return None


def _recommend_dimension_strategies(
    *,
    weak_dimensions_overall: dict[str, float],
    weak_dimensions_by_doc_type: dict[str, dict[str, float]],
    compliance_passes_quality_fails: list[dict],
    behavioral_proxy_failures_by_dim: dict[str, int],
    violation_types: list[tuple[str, int]],
) -> list[ProposalStrategy]:
    """Recommend strategies from quality dimensions without replacing compliance ones."""
    strategies: list[ProposalStrategy] = []
    seen: set[str] = set()
    table_verapdf_already_firing = any(
        vt.startswith("7.2") or vt.startswith("7.5")
        for vt, _count in violation_types
    )

    for doc_type, dimensions in weak_dimensions_by_doc_type.items():
        for dimension, score in dimensions.items():
            if score < 0.7:
                strategy = _dimension_strategy_for(
                    dimension,
                    doc_class=doc_type,
                    score=score,
                    table_verapdf_already_firing=table_verapdf_already_firing,
                )
                if strategy and strategy.name not in seen:
                    strategies.append(strategy)
                    seen.add(strategy.name)

    for dimension, score in weak_dimensions_overall.items():
        if score >= 0.7:
            continue
        strategy = _dimension_strategy_for(
            dimension,
            doc_class="global",
            score=score,
            table_verapdf_already_firing=table_verapdf_already_firing,
        )
        if strategy and strategy.name not in seen:
            strategies.append(strategy)
            seen.add(strategy.name)

    for dimension, count in behavioral_proxy_failures_by_dim.items():
        if count <= 0 or any(s.modifications.get("quality_dimension") == dimension for s in strategies):
            continue
        strategy = _dimension_strategy_for(
            dimension,
            doc_class="behavioral_proxy",
            score=0.0,
            table_verapdf_already_firing=table_verapdf_already_firing,
            behavioral_failure_count=count,
        )
        if strategy and strategy.name not in seen:
            strategies.append(strategy)
            seen.add(strategy.name)

    if compliance_passes_quality_fails:
        for item in compliance_passes_quality_fails[:3]:
            for dimension in item.get("weak_dims", []):
                if any(s.modifications.get("quality_dimension") == dimension for s in strategies):
                    continue
                strategy = _dimension_strategy_for(
                    dimension,
                    doc_class="compliance_pass_quality_fail",
                    score=0.0,
                    table_verapdf_already_firing=table_verapdf_already_firing,
                )
                if strategy and strategy.name not in seen:
                    strategies.append(strategy)
                    seen.add(strategy.name)

    return strategies


def _dimension_strategy_for(
    dimension: str,
    *,
    doc_class: str,
    score: float,
    table_verapdf_already_firing: bool,
    behavioral_failure_count: int = 0,
) -> ProposalStrategy | None:
    slug = re.sub(r"[^a-z0-9]+", "_", doc_class.lower()).strip("_") or "global"
    strategy_by_dimension = {
        "alt_text": ("improve_alt_text", f"improve_alt_text_{slug}", "planner_prompt"),
        "reading_order": ("tighten_reading_order", f"tighten_reading_order_{slug}", "grounder_prompt"),
        "heading_semantics": ("improve_heading_semantics", f"improve_heading_semantics_{slug}", "planner_prompt"),
        "decorative": ("tighten_decorative_classification", "tighten_decorative_classification", "grounder_prompt"),
        "complex_content": ("improve_complex_content_description", "improve_complex_content_description", "planner_prompt"),
        "table_structure": ("improve_table_structure", f"improve_table_structure_{slug}", "planner_prompt"),
        "link_text": ("improve_link_text", "improve_link_text", "planner_prompt"),
    }
    if dimension == "table_structure" and table_verapdf_already_firing:
        return None
    item = strategy_by_dimension.get(dimension)
    if item is None:
        return None
    map_key, name, _target = item
    map_entry = strategy_map_entry(name)
    if map_entry is None:
        raise ValueError(
            f"Dimension strategy {name!r} is not declared in "
            "dimension_strategy_map.yaml"
        )
    description = (
        f"{dimension} quality score is {score:.2f} for {doc_class}. "
        f"Apply {map_key} guidance from dimension_strategy_map.yaml."
    )
    if behavioral_failure_count:
        description += f" Behavioral proxy failures: {behavioral_failure_count}."
    return ProposalStrategy(
        name=name,
        description=description,
        target=map_entry["target"],
        modifications={
            "quality_dimension": dimension,
            "doc_class": doc_class,
            "quality_score": score,
            "strategy_map_key": map_key,
            "strategy_map_hook": map_entry["hook"],
            "strategy_map_targets": map_entry["targets"],
            "behavioral_failure_count": behavioral_failure_count,
            "dimension_guidance": _dimension_guidance(dimension, doc_class),
        },
    )


def _dimension_guidance(dimension: str, doc_class: str) -> str:
    guidance = {
        "alt_text": "Add alt text that conveys the image's purpose and data in this document class.",
        "reading_order": "Detect columns, sidebars, captions, and headers before assigning reading order.",
        "heading_semantics": "Choose heading levels from the semantic outline instead of visual font size alone.",
        "decorative": "Classify content as decorative only when skipping it loses no information.",
        "complex_content": "Describe charts, diagrams, and equations with data-level meaning, not just object type.",
        "table_structure": "Reconstruct data tables with explicit headers before layout tables.",
        "link_text": "Rewrite vague link text using local context and destination purpose.",
    }
    base = guidance.get(dimension, f"Improve {dimension} quality.")
    return f"{base} Document class: {doc_class}."


# ---------------------------------------------------------------------------
# Proposer
# ---------------------------------------------------------------------------


class HarnessProposer:
    """Generate harness variant proposals based on experiment data.

    Analyzes failure patterns and applies targeted modifications to
    create new harness configurations for evaluation.
    """

    def __init__(
        self,
        store: ExperimentStore,
        success_threshold: float = 0.5,
        max_proposals_per_iteration: int = 3,
    ):
        self._store = store
        self._success_threshold = success_threshold
        self._max_proposals = max_proposals_per_iteration

    @property
    def success_threshold(self) -> float:
        return self._success_threshold

    def should_propose(self, harness_id: str) -> bool:
        """Check if the current harness needs improvement.

        Returns True if success rate is below threshold.
        """
        rate = self._store.compute_success_rate(harness_id)
        return rate < self._success_threshold

    def propose_variants(
        self,
        base_harness_id: str,
        base_config: dict,
    ) -> list[dict]:
        """Generate new harness variant proposals.

        Args:
            base_harness_id: The harness to improve on.
            base_config: The current harness configuration dict.

        Returns:
            List of proposal dicts, each with:
            - harness_id: new unique ID
            - parent_id: base_harness_id
            - description: what changed
            - config: modified harness config dict
            - strategy: the ProposalStrategy that generated it
        """
        analysis = analyze_failures(self._store, base_harness_id)
        strategies = analysis["recommended_strategies"]

        if not strategies:
            logger.info(
                "No improvement strategies found for %s (rate=%.1f%%)",
                base_harness_id,
                analysis["success_rate"] * 100,
            )
            return []

        proposals = []
        for strategy in strategies[: self._max_proposals]:
            new_config = self._apply_strategy(base_config, strategy)
            new_id = _generate_harness_id(strategy.name)

            proposals.append({
                "harness_id": new_id,
                "parent_id": base_harness_id,
                "description": strategy.description,
                "config": new_config,
                "strategy": strategy,
            })

            logger.info(
                "Proposed variant %s from %s: %s",
                new_id, base_harness_id, strategy.name,
            )

        return proposals

    def _apply_strategy(
        self, base_config: dict, strategy: ProposalStrategy
    ) -> dict:
        """Apply a strategy's modifications to a base config.

        Returns a new config dict with the strategy's changes applied.
        """
        config = copy.deepcopy(base_config)

        if strategy.target == "planner_prompt":
            config = self._modify_planner_prompt(config, strategy)
        elif strategy.target == "grounder_prompt":
            config = self._modify_grounder_prompt(config, strategy)
        elif strategy.target == "confidence_threshold":
            config = self._modify_confidence(config, strategy)
        elif strategy.target == "output_parsing":
            config = self._modify_parsing(config, strategy)
        elif strategy.target == "anchor_graph_format":
            config = self._modify_anchor_format(config, strategy)

        # Always record what strategy was applied
        config.setdefault("_meta", {})
        config["_meta"]["strategy"] = strategy.name
        config["_meta"]["strategy_description"] = strategy.description

        return config

    def _modify_planner_prompt(self, config: dict, strategy: ProposalStrategy) -> dict:
        """Apply planner prompt modifications."""
        mods = strategy.modifications

        if mods.get("add_table_examples"):
            config.setdefault("planner_additions", [])
            config["planner_additions"].append(
                "\nTABLE RECONSTRUCTION GUIDANCE:\n"
                "When you see table structure violations (7.2-x, 7.5-x), "
                "use reconstruct_table with explicit rows, cols, header_rows, "
                "and cells specification. Always identify header rows first.\n"
            )

        if mods.get("group_by_page"):
            config["violation_grouping"] = "page_then_type"

        if mods.get("group_by_type"):
            config.setdefault("violation_grouping", "type_then_page")

        if mods.get("prioritize_impactful"):
            config["violation_priority_order"] = [
                "7.1",  # Structure (most common failures)
                "7.2",  # Table
                "7.5",  # Table headers
                "1.",   # Alt text
                "7.3",  # Reading order
            ]

        if mods.get("add_examples"):
            config["include_few_shot"] = True
            config["few_shot_source"] = mods.get("example_source", "curated")

        _apply_dimension_guidance(config, mods, additions_key="planner_additions")

        return config

    def _modify_grounder_prompt(self, config: dict, strategy: ProposalStrategy) -> dict:
        """Apply grounder prompt modifications."""
        mods = strategy.modifications

        if mods.get("emphasize_comprehensive_detection"):
            config.setdefault("grounder_additions", [])
            config["grounder_additions"].append(
                "\nIMPORTANT: Identify ALL content on the page. "
                "Do not miss headers, footers, page numbers, or decorative elements. "
                "Untagged content is the most common violation type.\n"
            )

        _apply_dimension_guidance(config, mods, additions_key="grounder_additions")

        return config

    def _modify_confidence(self, config: dict, strategy: ProposalStrategy) -> dict:
        """Adjust confidence threshold and safety guards."""
        mods = strategy.modifications

        if mods.get("raise_threshold"):
            current = config.get("confidence_threshold", 0.7)
            config["confidence_threshold"] = min(current + 0.1, 0.95)

        if mods.get("add_safety_guards"):
            config["pre_check_violations"] = True
            config["abort_on_increase"] = True

        return config

    def _modify_parsing(self, config: dict, strategy: ProposalStrategy) -> dict:
        """Improve output parsing robustness."""
        mods = strategy.modifications

        if mods.get("use_tool_calling"):
            config["use_tool_calling"] = True

        if mods.get("add_fallback_parsers"):
            config["fallback_parsers"] = ["json_extract", "regex_extract", "partial_json"]

        return config

    def _modify_anchor_format(self, config: dict, strategy: ProposalStrategy) -> dict:
        """Modify anchor graph formatting."""
        mods = strategy.modifications

        if mods.get("compress_graph"):
            config["anchor_graph_max_anchors_per_page"] = 50

        if mods.get("filter_by_page"):
            config["anchor_graph_filter_by_violation_pages"] = True

        if mods.get("limit_text_excerpts"):
            config["anchor_graph_text_excerpt_max_chars"] = 40

        return config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_dimension_guidance(
    config: dict,
    mods: dict,
    *,
    additions_key: str,
) -> None:
    """Apply dimension-aware guidance to a prompt config in place.

    ``additions_key`` is the config field that carries free-text additions for
    the active prompt (``planner_additions`` or ``grounder_additions``). When
    no ``dimension_guidance`` is present in ``mods`` this is a no-op so callers
    can invoke it unconditionally.
    """
    guidance = mods.get("dimension_guidance")
    if not guidance:
        return

    dimension = mods.get("quality_dimension")
    config.setdefault(additions_key, [])
    config[additions_key].append(
        "\nQUALITY DIMENSION GUIDANCE:\n"
        f"{guidance}\n"
    )
    config.setdefault("quality_dimension_focus", [])
    config["quality_dimension_focus"].append(dimension)
    config.setdefault("dimension_strategy_hooks", {})
    config["dimension_strategy_hooks"][dimension] = mods.get("strategy_map_hook", "")
    config.setdefault("dimension_strategy_targets", {})
    config["dimension_strategy_targets"][dimension] = mods.get("strategy_map_targets", [])


def _generate_harness_id(strategy_name: str) -> str:
    """Generate a unique harness ID based on the strategy name."""
    short_uuid = uuid.uuid4().hex[:8]
    slug = re.sub(r"[^a-z0-9]+", "_", strategy_name.lower()).strip("_")
    return f"auto_{slug}_{short_uuid}"


def get_successful_examples(
    store: ExperimentStore,
    harness_id: str,
    limit: int = 3,
) -> list[dict]:
    """Get successful experiment examples for few-shot prompting.

    Returns simplified dicts with violation_types and fix_sequence
    from experiments that passed.
    """
    experiments = store.get_experiments_for_harness(harness_id)
    passed = [e for e in experiments if e.passed]

    # Prefer diverse examples (different document types)
    seen_types: set[str] = set()
    examples: list[dict] = []

    for exp in passed:
        if exp.document_type not in seen_types and len(examples) < limit:
            examples.append({
                "document_type": exp.document_type,
                "violation_types": exp.violation_types,
                "fix_sequence": exp.fix_sequence,
                "violations_before": exp.violations_before,
                "violations_after": exp.violations_after,
            })
            seen_types.add(exp.document_type)

    # Fill remaining slots with any passed examples
    for exp in passed:
        if len(examples) >= limit:
            break
        already = any(
            e["document_type"] == exp.document_type
            and e["violation_types"] == exp.violation_types
            for e in examples
        )
        if not already:
            examples.append({
                "document_type": exp.document_type,
                "violation_types": exp.violation_types,
                "fix_sequence": exp.fix_sequence,
                "violations_before": exp.violations_before,
                "violations_after": exp.violations_after,
            })

    return examples
