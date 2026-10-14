"""Style selection and the explicit code-level confirmation gate (M3).

The plan-to-facade pipeline (M4+) must call ``confirmation_gate`` and may
proceed only when it passes. Gate rules (SAUDI_CHARACTER_ENGINE.md par.6):

- character lookup completed,
- a style pack was selected,
- selection_method is user_confirmed or manual_override,
- user_confirmed is true,
- the pack is applicable to the selected zone, or an override reason exists.
"""

from __future__ import annotations

from saudi_plot_design.character.models import (
    CharacterMatch,
    GateResult,
    SelectionMethod,
    StylePackReference,
    StyleSelection,
)
from saudi_plot_design.model import SpdInputError


def recommend_style(match: CharacterMatch, zone_style_pack_id: str | None) -> StyleSelection:
    """Initial (unconfirmed) selection derived from a character match."""
    warnings: list[str] = []
    if match.selected_zone_id is None:
        return StyleSelection(
            recommended_style_pack_id=None,
            selected_style_pack_id=None,
            selection_method=SelectionMethod.UNRESOLVED,
            warnings=(
                "no zone recommendation available; manual style selection and "
                "confirmation required",
            ),
        )
    if zone_style_pack_id is None:
        warnings.append(
            f"zone '{match.selected_zone_id}' declares no installed style pack; "
            f"manual selection required"
        )
        return StyleSelection(
            recommended_style_pack_id=None,
            selected_style_pack_id=None,
            selection_method=SelectionMethod.UNRESOLVED,
            warnings=tuple(warnings),
        )
    return StyleSelection(
        recommended_style_pack_id=zone_style_pack_id,
        selected_style_pack_id=zone_style_pack_id,
        selection_method=SelectionMethod.AUTOMATIC_RECOMMENDATION,
        user_confirmed=False,
        warnings=tuple(warnings),
    )


def confirm_selection(selection: StyleSelection, pack: StylePackReference) -> StyleSelection:
    """Explicit user confirmation of the recommended pack."""
    if selection.recommended_style_pack_id != pack.style_pack_id:
        raise SpdInputError(
            f"cannot confirm '{pack.style_pack_id}': the recommendation is "
            f"'{selection.recommended_style_pack_id}' - use override_selection instead"
        )
    return selection.model_copy(
        update={
            "selected_style_pack_id": pack.style_pack_id,
            "selection_method": SelectionMethod.USER_CONFIRMED,
            "user_confirmed": True,
            "style_pack_version": pack.version,
        }
    )


def override_selection(
    selection: StyleSelection, pack: StylePackReference, override_reason: str
) -> StyleSelection:
    """Explicit manual override; a non-empty reason is mandatory."""
    if not override_reason or not override_reason.strip():
        raise SpdInputError("manual override requires a non-empty override reason")
    return selection.model_copy(
        update={
            "selected_style_pack_id": pack.style_pack_id,
            "selection_method": SelectionMethod.MANUAL_OVERRIDE,
            "user_confirmed": True,
            "override_reason": override_reason.strip(),
            "style_pack_version": pack.version,
        }
    )


def confirmation_gate(
    match: CharacterMatch | None,
    selection: StyleSelection | None,
    pack: StylePackReference | None,
) -> GateResult:
    """The hard gate the facade pipeline must pass before generating anything."""
    reasons: list[str] = []
    if match is None:
        reasons.append("character lookup has not completed")
    if selection is None or selection.selected_style_pack_id is None:
        reasons.append("no style pack selected")
    if pack is None:
        reasons.append("no style pack loaded")
    if selection is not None:
        if selection.selection_method not in (
            SelectionMethod.USER_CONFIRMED,
            SelectionMethod.MANUAL_OVERRIDE,
        ):
            reasons.append(
                f"selection_method is '{selection.selection_method.value}'; explicit "
                f"user confirmation or manual override required"
            )
        if not selection.user_confirmed:
            reasons.append("user_confirmed is false")
    if selection is not None and pack is not None:
        if (
            selection.selected_style_pack_id is not None
            and selection.selected_style_pack_id != pack.style_pack_id
        ):
            reasons.append(
                f"selected pack '{selection.selected_style_pack_id}' does not match the "
                f"loaded pack '{pack.style_pack_id}'"
            )
        zone_id = match.selected_zone_id if match is not None else None
        zone_compatible = zone_id is not None and zone_id in pack.applicable_zone_ids
        if not zone_compatible and not selection.override_reason:
            reasons.append(
                "style pack is not declared applicable to the selected zone and no "
                "override reason is recorded"
            )
    return GateResult(passed=not reasons, reasons=tuple(reasons))
