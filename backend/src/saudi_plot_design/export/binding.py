"""Export binding and safety gate (M5).

Export is blocked unless every validated artifact in the chain binds to the
EXACT plot and concept being exported - by content fingerprint, never by
descriptive id alone. Stale or substituted confirmation artifacts fail with
specific reasons.
"""

from __future__ import annotations

import math

from saudi_plot_design.character.models import (
    CharacterMatch,
    GateResult,
    StylePackReference,
    StyleSelection,
)
from saudi_plot_design.elevation.front import facade_generation_gate
from saudi_plot_design.elevation.models import FacadeConcept, PrimaryFacadeSelection
from saudi_plot_design.model import Concept, PlotModel
from saudi_plot_design.output import DISCLAIMER
from saudi_plot_design.styles.schema import StylePackData


def export_gate(
    plot: PlotModel,
    envelope,
    rules,
    concept: Concept,
    match: CharacterMatch,
    style_selection: StyleSelection,
    pack_ref: StylePackReference,
    pack_data: StylePackData,
    selection: PrimaryFacadeSelection,
    facade: FacadeConcept,
) -> GateResult:
    """All prerequisites for export, with specific blocking reasons."""
    from saudi_plot_design.elevation.validation import validate_facade
    from saudi_plot_design.rules.setbacks import compute_envelope

    reasons: list[str] = []

    # The full generation prerequisite chain (plot/concept validity, facade
    # confirmation + fingerprints, style gate + pack version binding).
    upstream = facade_generation_gate(
        plot, concept, selection, match, style_selection, pack_ref, pack_data
    )
    if not upstream.passed:
        reasons.extend(f"generation gate: {r}" for r in upstream.reasons)

    if not facade.is_valid:
        reasons.append(
            "facade concept is invalid or rejected: "
            + ("; ".join(facade.rejection_reasons) or "validation failed")
        )
    elif upstream.passed:  # re-validation is noise on top of upstream blocks
        # A stored validation report can be stale (persisted facade or copy
        # with modified geometry): re-validate the facade content against the
        # current inputs before trusting it.
        revalidated = validate_facade(
            facade, plot, concept, selection, pack_data, deterministic=True
        )
        if not revalidated.passed:
            failed = ", ".join(c.id for c in revalidated.failures())
            reasons.append(
                f"facade failed re-validation at export time (checks {failed}) - "
                f"its stored validation report is stale"
            )

    # The facade must have been generated under the very artifacts supplied
    # now - otherwise sheets and run.json would claim one dataset/style while
    # rendering geometry from another.
    if facade.character_match_zone_id != match.selected_zone_id:
        reasons.append(
            f"facade was generated for character zone "
            f"'{facade.character_match_zone_id}', but the supplied match selects "
            f"'{match.selected_zone_id}'"
        )
    if facade.style_selection_method != style_selection.selection_method.value:
        reasons.append(
            f"facade records style selection method '{facade.style_selection_method}', "
            f"but the supplied selection is '{style_selection.selection_method.value}'"
        )
    if facade.style_pack_id != pack_ref.style_pack_id or (
        facade.style_pack_version != pack_ref.version
    ):
        reasons.append(
            f"facade was generated with pack '{facade.style_pack_id}' "
            f"v{facade.style_pack_version}, but pack '{pack_ref.style_pack_id}' "
            f"v{pack_ref.version} is loaded - regenerate the facade"
        )
    # Same-id/version drift: the facade binds the COMPLETE consumed pack
    # content by fingerprint, and the display reference must be derivable
    # from that same data (a tampered reference - e.g. a reversed Arabic
    # name - would otherwise reach the PDF/DXF while run.json disagrees).
    if facade.style_pack_fingerprint != pack_data.fingerprint:
        reasons.append(
            "facade was generated from different style-pack content than the "
            "loaded pack (pack content fingerprint mismatch) - regenerate"
        )
    if (
        pack_ref.name_ar != pack_data.core.name_ar
        or pack_ref.name_en != pack_data.core.name_en
        or pack_ref.status != pack_data.core.status
        or pack_ref.applicable_zone_ids != pack_data.core.applicable_zone_ids
        or pack_ref.source_metadata != pack_data.source_metadata.model_dump(mode="json")
        or pack_ref.limitations != pack_data.source_metadata.limitations
    ):
        reasons.append(
            "style pack reference does not match the consumed pack data "
            "(names/status/zones/provenance drift) - reload the pack"
        )

    # The character match must belong to this plot's location: a stale match
    # from another coordinate in the same zone would report the wrong
    # confidence/provenance for this plot.
    if plot.location is None or ((match.point.latitude, match.point.longitude) != plot.location):
        reasons.append(
            f"character match was computed for point "
            f"({match.point.latitude:g}, {match.point.longitude:g}), which is not "
            f"the plot location {plot.location} - recompute the lookup"
        )

    # The supplied envelope must be exactly what the supplied plot + rules
    # produce (a stale envelope would be drawn while annotations claim the
    # supplied rules).
    recomputed = compute_envelope(plot, rules)
    if not all(
        math.isfinite(v) for v in (envelope.width_m, envelope.depth_m, envelope.area_m2)
    ) or not all(math.isfinite(v) for corner in envelope.corners for v in corner):
        reasons.append(
            "supplied buildable envelope contains non-finite values (NaN/inf) - "
            "recompute before exporting"
        )
    elif (
        # Ordered comparison: a reordered ring would draw a crossed polygon
        # even when the vertex SET matches. compute_envelope is deterministic,
        # so a genuine envelope matches exactly.
        tuple((round(x, 6), round(y, 6)) for x, y in recomputed.corners)
        != tuple((round(x, 6), round(y, 6)) for x, y in envelope.corners)
        or abs(recomputed.width_m - envelope.width_m) > 1e-6
        or abs(recomputed.depth_m - envelope.depth_m) > 1e-6
        or abs(recomputed.area_m2 - envelope.area_m2) > 1e-6
    ):
        reasons.append(
            "supplied buildable envelope does not match the envelope computed from "
            "the supplied plot and setback rules (ordered corners/width/depth/area) - "
            "recompute before exporting"
        )

    # The facade itself must bind to the exact plot/concept being exported.
    if facade.project_id != plot.plot_id:
        reasons.append(
            f"facade was generated for project '{facade.project_id}', not '{plot.plot_id}'"
        )
    elif facade.plot_fingerprint != plot.fingerprint:
        reasons.append(
            "facade was generated for a different plot with the same id "
            "(plot fingerprint mismatch) - regenerate the facade"
        )
    if facade.plan_concept_id != concept.concept_id:
        reasons.append(
            f"facade was generated for concept '{facade.plan_concept_id}', "
            f"not '{concept.concept_id}'"
        )
    elif facade.concept_fingerprint != concept.fingerprint:
        reasons.append(
            "facade was generated for a different concept with the same id "
            "(concept fingerprint mismatch) - regenerate the facade"
        )

    if facade.disclaimer != DISCLAIMER:
        reasons.append("the facade concept is missing the unconditional DEMO disclaimer")

    return GateResult(passed=not reasons, reasons=tuple(reasons))
