"""Structured JSON report for a validated plot and its buildable envelope.

The DEMO disclaimer is unconditional on every output of every run
(GEOSPATIAL_DATA_PROVENANCE.md par.1 rule 3, ARCHITECTURE.md D4).
"""

from __future__ import annotations

import json
from pathlib import Path

from saudi_plot_design.model import BuildableEnvelope, PlotMetrics, PlotModel, SetbackRuleSet

# Verbatim mandated text (GEOSPATIAL_DATA_PROVENANCE.md par.1 rule 3) - em dash included.
DISCLAIMER = (
    "DEMO DATA — geographic zones, setback rules, and style rules are demonstration "
    "data, not official Saudi regulations or official Saudi Architecture guidelines."
)


def plot_report(
    plot: PlotModel,
    metrics: PlotMetrics,
    rules: SetbackRuleSet,
    envelope: BuildableEnvelope,
) -> dict:
    """Build the structured report for a validated plot + envelope (M1 output)."""
    return {
        "schema_version": 1,
        "disclaimer": DISCLAIMER,
        "plot": {
            "corners_m": [list(c) for c in plot.corners],
            "edges": [e.value for e in plot.edges],
            "street_edge_index": plot.street_edge_index,
            "street_width_m": plot.street_width_m,
            "location_wgs84": list(plot.location) if plot.location else None,
        },
        "metrics": {
            "area_m2": round(metrics.area_m2, 3),
            "perimeter_m": round(metrics.perimeter_m, 3),
            "centroid_m": [round(v, 3) for v in metrics.centroid],
            "edge_lengths_m": [round(v, 3) for v in metrics.edge_lengths_m],
        },
        "setback_rules": {
            "id": rules.id,
            "provenance": rules.provenance,
            "display_name": rules.display_name,
            "statement": rules.statement,
            "front_m": rules.front_m,
            "side_m": rules.side_m,
            "rear_m": rules.rear_m,
        },
        "buildable_envelope": {
            "corners_m": [list(c) for c in envelope.corners],
            "area_m2": round(envelope.area_m2, 3),
            "width_m": round(envelope.width_m, 3),
            "depth_m": round(envelope.depth_m, 3),
        },
    }


def write_plot_report(path: str | Path, report: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def character_match_report(match, plot_id: str) -> dict:
    """Character-classification artifact linked to the project by plot_id."""
    return {
        "schema_version": 1,
        "disclaimer": DISCLAIMER,
        "plot_id": plot_id,
        "character_match": match.model_dump(mode="json"),
    }


def style_selection_report(selection, gate_result, plot_id: str) -> dict:
    return {
        "schema_version": 1,
        "disclaimer": DISCLAIMER,
        "plot_id": plot_id,
        "style_selection": selection.model_dump(mode="json"),
        "confirmation_gate": gate_result.model_dump(mode="json"),
    }


def style_pack_snapshot(reference, data) -> dict:
    return {
        "schema_version": 1,
        "disclaimer": DISCLAIMER,
        "style_pack_reference": reference.model_dump(mode="json"),
        "style_pack_data": data.model_dump(mode="json"),
    }


def facade_concept_report(facade) -> dict:
    """Canonical JSON artifact for a FacadeConcept (disclaimer embedded twice:
    at artifact level and inside the concept itself)."""
    return {
        "schema_version": 1,
        "disclaimer": DISCLAIMER,
        "facade_concept": facade.model_dump(mode="json"),
        "is_valid": facade.is_valid,
    }


def facade_validation_report(facade) -> dict:
    return {
        "schema_version": 1,
        "disclaimer": DISCLAIMER,
        "facade_concept_id": facade.facade_concept_id,
        "rejection_reasons": list(facade.rejection_reasons),
        "validation": facade.validation.model_dump(mode="json") if facade.validation else None,
        "passed": facade.is_valid,
    }


def concept_report(concept) -> dict:
    """Canonical JSON form of a Concept, with the unconditional disclaimer."""
    return {
        "schema_version": 1,
        "disclaimer": DISCLAIMER,
        "concept": concept.model_dump(mode="json"),
        "is_valid": concept.is_valid,
    }


def write_concept_report(path: str | Path, concept) -> Path:
    return write_plot_report(path, concept_report(concept))
