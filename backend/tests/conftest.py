"""Shared fixtures and paths for the M1 test suite."""

import os
from pathlib import Path

import pytest
from saudi_plot_design.model import EdgeClass

# ── Secret-isolation fixture ─────────────────────────────────────────────────
# Strip known API-key env vars for the entire test session so that a real
# GEMINI_API_KEY present in the host environment cannot silently change the
# behaviour of tests that expect "service not configured" responses.
# Tests that genuinely need a key receive one via make_settings(gemini_api_key=…)
# or monkeypatch — never via the ambient environment.

_SENSITIVE_KEYS = ("GEMINI_API_KEY", "SPD_GEMINI_API_KEY")


@pytest.fixture(scope="session", autouse=True)
def _strip_sensitive_env_vars():
    """Remove known secret env vars for the full test session."""
    saved = {k: os.environ.pop(k) for k in _SENSITIVE_KEYS if k in os.environ}
    yield
    os.environ.update(saved)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CSV = ROOT / "samples" / "plot_20x30.csv"
DEMO_RULES = ROOT / "src" / "saudi_plot_design" / "data" / "demo" / "demo_setback_rules.json"

REFERENCE_CORNERS = ((0.0, 0.0), (20.0, 0.0), (20.0, 30.0), (0.0, 30.0))


def standard_edges() -> tuple[EdgeClass, ...]:
    """Street on edge 1 (the 20 m frontage), neighbors elsewhere."""
    return (EdgeClass.STREET, EdgeClass.NEIGHBOR, EdgeClass.NEIGHBOR, EdgeClass.NEIGHBOR)


def reference_pipeline(edges=None, location=(24.65, 46.71)):
    """Full M1-M3 reference pipeline state for facade tests (M4)."""
    from saudi_plot_design.character.engine import load_zone_dataset, recommend_character
    from saudi_plot_design.character.models import LocationPoint
    from saudi_plot_design.character.selection import confirm_selection, recommend_style
    from saudi_plot_design.planner.compact_3br import plan_compact_3br
    from saudi_plot_design.plot.geometry import build_plot_model
    from saudi_plot_design.rules.setbacks import compute_envelope, load_default_setback_rules
    from saudi_plot_design.styles.loader import load_pilot_style_pack

    plot, _ = build_plot_model(
        REFERENCE_CORNERS, edges or standard_edges(), 15.0, location=location
    )
    envelope = compute_envelope(plot, load_default_setback_rules())
    concept = plan_compact_3br(plot, envelope)
    dataset = load_zone_dataset()
    pack_ref, pack_data = load_pilot_style_pack(
        known_zone_ids=tuple(z.zone_id for z in dataset.zones)
    )
    match = recommend_character(dataset, LocationPoint(latitude=location[0], longitude=location[1]))
    from saudi_plot_design.character.selection import override_selection

    zone_pack = (
        dataset.zone_by_id(match.selected_zone_id).style_pack_id if match.selected_zone_id else None
    )
    base_selection = recommend_style(match, zone_pack)
    if zone_pack == pack_ref.style_pack_id:
        style_selection = confirm_selection(base_selection, pack_ref)
    else:
        style_selection = override_selection(
            base_selection, pack_ref, "test fixture: pilot pack applied outside its demo zone"
        )
    return {
        "plot": plot,
        "concept": concept,
        "dataset": dataset,
        "pack_ref": pack_ref,
        "pack_data": pack_data,
        "match": match,
        "style_selection": style_selection,
    }
