from __future__ import annotations

import pytest

from project_remedy.vision_planner.experiment_store import (
    ExperimentRecord,
    ExperimentStore,
)
from project_remedy.vision_planner.proposer import (
    HarnessProposer,
    analyze_failures,
    load_dimension_strategy_map,
    strategy_map_entry,
    validate_dimension_strategy_map,
)


def _store_with_variant() -> ExperimentStore:
    store = ExperimentStore(":memory:")
    store.register_variant("h1")
    return store


def test_analyze_failures_recommends_dimension_strategy_for_quality_fail() -> None:
    store = _store_with_variant()
    store.record_experiment(
        ExperimentRecord(
            experiment_id="e1",
            harness_id="h1",
            document_hash="doc-1",
            document_type="scientific_paper",
            passed=True,
            quality_dimensions={"alt_text": 0.45, "reading_order": 0.91},
            behavioral_results={"alt_text_substitution": False},
        )
    )

    analysis = analyze_failures(store, "h1")
    strategy_names = [strategy.name for strategy in analysis["recommended_strategies"]]

    assert analysis["weak_dimensions_by_doc_type"] == {
        "scientific_paper": {"alt_text": 0.45}
    }
    assert analysis["compliance_passes_quality_fails"] == [
        {"doc_hash": "doc-1", "weak_dims": ["alt_text"]}
    ]
    assert "improve_alt_text_scientific_paper" in strategy_names


def test_behavioral_failures_are_normalized_to_quality_dimensions() -> None:
    store = _store_with_variant()
    store.record_experiment(
        ExperimentRecord(
            experiment_id="e1",
            harness_id="h1",
            document_hash="doc-1",
            document_format="pptx",
            document_type="slide_deck",
            passed=True,
            behavioral_results={
                "slide_reading_order_comprehension": False,
                "slide_title_navigation": False,
                "screen_reader_transcript_analysis": False,
            },
        )
    )
    store.record_experiment(
        ExperimentRecord(
            experiment_id="e2",
            harness_id="h1",
            document_hash="doc-2",
            document_format="xlsx",
            document_type="spreadsheet_workbook",
            passed=True,
            behavioral_results={
                "sheet_navigation": False,
            },
        )
    )

    analysis = analyze_failures(store, "h1")

    assert analysis["behavioral_proxy_failures_by_dim"] == {
        "reading_order": 2,
        "sheet_organization": 1,
        "slide_title": 1,
    }


def test_office_quality_signals_do_not_generate_pdf_evolution_strategies() -> None:
    store = _store_with_variant()
    store.record_experiment(
        ExperimentRecord(
            experiment_id="pptx-1",
            harness_id="h1",
            document_hash="deck-1",
            document_format="pptx",
            document_type="slide_deck",
            passed=True,
            quality_dimensions={"reading_order": 0.4, "slide_title": 0.5},
            behavioral_results={"slide_reading_order_comprehension": False},
        )
    )
    store.record_experiment(
        ExperimentRecord(
            experiment_id="xlsx-1",
            harness_id="h1",
            document_hash="workbook-1",
            document_format="xlsx",
            document_type="spreadsheet_workbook",
            passed=True,
            quality_dimensions={"sheet_organization": 0.4},
            behavioral_results={"sheet_navigation": False},
        )
    )

    analysis = analyze_failures(store, "h1")

    assert analysis["weak_dimensions_by_doc_type"] == {
        "slide_deck": {"reading_order": 0.4, "slide_title": 0.5},
        "spreadsheet_workbook": {"sheet_organization": 0.4},
    }
    assert analysis["weak_dimensions_by_format"] == {
        "pptx": {"reading_order": 0.4, "slide_title": 0.5},
        "xlsx": {"sheet_organization": 0.4},
    }
    assert analysis["weak_dimensions_by_format_and_doc_type"] == {
        "pptx": {"slide_deck": {"reading_order": 0.4, "slide_title": 0.5}},
        "xlsx": {"spreadsheet_workbook": {"sheet_organization": 0.4}},
    }
    assert analysis["behavioral_proxy_failures_by_dim"] == {
        "reading_order": 1,
        "sheet_organization": 1,
    }
    assert analysis["behavioral_proxy_failures_by_format"] == {
        "pptx": {"reading_order": 1},
        "xlsx": {"sheet_organization": 1},
    }
    assert analysis["recommended_strategies"] == []


def test_dimension_strategies_coexist_with_verapdf_strategies() -> None:
    store = _store_with_variant()
    store.record_experiment(
        ExperimentRecord(
            experiment_id="e1",
            harness_id="h1",
            document_hash="doc-1",
            document_type="mixed_structure",
            violation_types=["7.2-11"],
            passed=False,
            quality_dimensions={"alt_text": 0.55},
        )
    )

    analysis = analyze_failures(store, "h1")
    strategy_names = [strategy.name for strategy in analysis["recommended_strategies"]]

    assert "table_structure_focus" in strategy_names
    assert "improve_alt_text_mixed_structure" in strategy_names


def test_dimension_strategy_map_declares_generated_strategy() -> None:
    mapping = load_dimension_strategy_map()
    entry = strategy_map_entry("improve_alt_text_scientific_paper", mapping)

    assert entry is not None
    assert entry["dimension"] == "alt_text"
    assert entry["target"] == "planner_prompt"
    assert entry["hook"] == "alt_text_action_examples"
    assert {
        (target["file"], target.get("method"), target["hook"])
        for target in entry["targets"]
    } == {
        (
            "vision_planner/harness.py",
            "VisionPlannerHarness.build_planner_prompt",
            "alt_text_action_examples",
        ),
        (
            "vision.py",
            "VisionProcessor.generate_alt_text",
            "alt_text_generation_prompt",
        ),
    }


def test_dimension_strategy_map_declares_vision_targets_from_prd() -> None:
    mapping = load_dimension_strategy_map()

    assert {
        (target["file"], target.get("method"), target["hook"])
        for target in mapping["improve_alt_text"]["targets"]
    } >= {
        (
            "vision.py",
            "VisionProcessor.generate_alt_text",
            "alt_text_generation_prompt",
        )
    }
    assert {
        (target["file"], target.get("method"), target["hook"])
        for target in mapping["improve_complex_content_description"]["targets"]
    } >= {
        (
            "vision.py",
            "VisionProcessor.recreate_chart_as_svg",
            "chart_data_description_prompt",
        ),
        (
            "vision.py",
            "VisionProcessor.describe_diagram",
            "diagram_structure_description_prompt",
        ),
    }


def test_dimension_strategy_map_declares_reading_order_targets_from_prd() -> None:
    mapping = load_dimension_strategy_map()

    assert {
        (target["file"], target.get("method"), target["hook"])
        for target in mapping["tighten_reading_order"]["targets"]
    } >= {
        (
            "vision_planner/harness.py",
            "VisionPlannerHarness.build_grounder_prompt",
            "reading_order_region_detection",
        ),
        (
            "vision_planner/harness.py",
            "VisionPlannerHarness.build_planner_prompt",
            "fix_reading_order_action_guidance",
        ),
    }


def test_dimension_strategy_map_declares_concrete_targets_for_every_entry() -> None:
    mapping = load_dimension_strategy_map()

    for entry in mapping.values():
        assert entry["targets"]
        for target in entry["targets"]:
            assert target["file"]
            assert target["hook"]
            assert ("method" in target) ^ ("function" in target)


def _valid_strategy_map_entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "name_pattern": "^improve_alt_text_.+$",
        "dimension": "alt_text",
        "target": "planner_prompt",
        "hook": "alt_text_action_examples",
        "targets": [
            {
                "file": "vision_planner/harness.py",
                "method": "VisionPlannerHarness.build_planner_prompt",
                "hook": "alt_text_action_examples",
            }
        ],
    }
    entry.update(overrides)
    return entry


def test_dimension_strategy_map_validation_requires_concrete_targets() -> None:
    mapping = {"improve_alt_text": _valid_strategy_map_entry(targets=[])}

    with pytest.raises(ValueError, match="targets must declare"):
        validate_dimension_strategy_map(mapping)


def test_dimension_strategy_map_validation_rejects_non_pdf_dimensions() -> None:
    mapping = {
        "organize_sheets": _valid_strategy_map_entry(
            name_pattern="^organize_sheets$",
            dimension="sheet_organization",
        )
    }

    with pytest.raises(ValueError, match="not applicable to PDF evolution"):
        validate_dimension_strategy_map(mapping)


def test_dimension_strategy_map_validation_rejects_missing_source_methods() -> None:
    mapping = {
        "improve_alt_text": _valid_strategy_map_entry(
            targets=[
                {
                    "file": "vision_planner/harness.py",
                    "method": "VisionPlannerHarness.missing_method",
                    "hook": "alt_text_action_examples",
                }
            ]
        )
    }

    with pytest.raises(ValueError, match="target symbol"):
        validate_dimension_strategy_map(mapping)


def test_dimension_strategy_map_validation_rejects_duplicate_hooks() -> None:
    mapping = {
        "improve_alt_text": _valid_strategy_map_entry(),
        "improve_other_alt_text": _valid_strategy_map_entry(
            name_pattern="^improve_other_alt_text$",
        ),
    }

    with pytest.raises(ValueError, match="already claimed"):
        validate_dimension_strategy_map(mapping)


def test_dimension_strategy_map_validation_rejects_duplicate_target_hooks() -> None:
    mapping = {
        "improve_alt_text": _valid_strategy_map_entry(
            targets=[
                {
                    "file": "vision_planner/harness.py",
                    "method": "VisionPlannerHarness.build_planner_prompt",
                    "hook": "alt_text_action_examples",
                },
                {
                    "file": "vision.py",
                    "method": "VisionProcessor.generate_alt_text",
                    "hook": "shared_generation_hook",
                },
            ]
        ),
        "improve_complex_content": _valid_strategy_map_entry(
            name_pattern="^improve_complex_content$",
            dimension="complex_content",
            hook="complex_content_description",
            targets=[
                {
                    "file": "vision_planner/harness.py",
                    "method": "VisionPlannerHarness.build_planner_prompt",
                    "hook": "complex_content_description",
                },
                {
                    "file": "vision.py",
                    "method": "VisionProcessor.describe_diagram",
                    "hook": "shared_generation_hook",
                },
            ],
        ),
    }

    with pytest.raises(ValueError, match="target hook 'shared_generation_hook'"):
        validate_dimension_strategy_map(mapping)


def test_proposer_applies_dimension_strategy_to_declared_hook_only() -> None:
    store = _store_with_variant()
    store.record_experiment(
        ExperimentRecord(
            experiment_id="e1",
            harness_id="h1",
            document_hash="doc-1",
            document_type="scientific_paper",
            passed=True,
            quality_dimensions={"alt_text": 0.45},
        )
    )

    proposals = HarnessProposer(store, max_proposals_per_iteration=1).propose_variants(
        "h1",
        base_config={},
    )

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["strategy"].name == "improve_alt_text_scientific_paper"
    config = proposal["config"]
    assert config["quality_dimension_focus"] == ["alt_text"]
    assert config["dimension_strategy_hooks"] == {
        "alt_text": "alt_text_action_examples"
    }
    assert config["dimension_strategy_targets"] == {
        "alt_text": strategy_map_entry("improve_alt_text_scientific_paper")[
            "targets"
        ]
    }
    assert "planner_additions" in config
    assert "grounder_additions" not in config


@pytest.mark.parametrize(
    ("dimension", "expected_strategy"),
    [
        ("alt_text", "improve_alt_text_scientific_paper"),
        ("reading_order", "tighten_reading_order_scientific_paper"),
        ("heading_semantics", "improve_heading_semantics_scientific_paper"),
        ("decorative", "tighten_decorative_classification"),
        ("complex_content", "improve_complex_content_description"),
        ("table_structure", "improve_table_structure_scientific_paper"),
        ("link_text", "improve_link_text"),
    ],
)
def test_each_dimension_strategy_modifies_declared_hook_only(
    dimension: str,
    expected_strategy: str,
) -> None:
    store = _store_with_variant()
    store.record_experiment(
        ExperimentRecord(
            experiment_id=f"e-{dimension}",
            harness_id="h1",
            document_hash=f"doc-{dimension}",
            document_type="scientific_paper",
            passed=True,
            quality_dimensions={dimension: 0.45},
        )
    )

    proposals = HarnessProposer(store, max_proposals_per_iteration=1).propose_variants(
        "h1",
        base_config={},
    )

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["strategy"].name == expected_strategy
    entry = strategy_map_entry(expected_strategy)
    assert entry is not None
    config = proposal["config"]
    assert config["quality_dimension_focus"] == [dimension]
    assert config["dimension_strategy_hooks"] == {dimension: entry["hook"]}
    assert config["dimension_strategy_targets"] == {dimension: entry["targets"]}
    if entry["target"] == "planner_prompt":
        assert "planner_additions" in config
        assert "grounder_additions" not in config
    elif entry["target"] == "grounder_prompt":
        assert "grounder_additions" in config
        assert "planner_additions" not in config
    else:
        raise AssertionError(f"unexpected target: {entry['target']}")
