"""Tests for the strict single-pack style loader (M3)."""

import json
import shutil
from pathlib import Path

import pytest

from saudi_plot_design.model import SpdInputError
from saudi_plot_design.styles.loader import default_styles_root, load_pilot_style_pack

KNOWN_ZONES = ("DEMO-ZONE-NAJDI-01", "DEMO-ZONE-HEJAZI-01", "DEMO-ZONE-ASIRI-01")
SHIPPED_PACK = default_styles_root() / "najdi_demo_v1"


def copy_pack(tmp_path, pack_name="najdi_demo_v1") -> Path:
    root = tmp_path / "styles"
    root.mkdir(exist_ok=True)
    shutil.copytree(SHIPPED_PACK, root / pack_name)
    return root


def edit_json(pack_dir: Path, filename: str, mutate) -> None:
    path = pack_dir / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")


class TestShippedPack:
    def test_exactly_one_pilot_pack_loads(self):
        reference, data = load_pilot_style_pack(known_zone_ids=KNOWN_ZONES)
        assert reference.style_pack_id == "najdi_demo_v1"
        assert reference.name_ar == "الطابع النجدي التجريبي"
        assert reference.name_en == "Demo Najdi Character"
        assert reference.version == "0.1.0"
        assert reference.status == "demo_requires_architect_review"
        assert reference.applicable_zone_ids == ("DEMO-ZONE-NAJDI-01",)
        assert reference.reviewer is None
        assert data.facade_rules.provenance == "demo"
        assert data.core.allowed_building_type == "detached_single_storey_villa"
        assert data.materials.material_palette

    def test_pack_values_labeled_demo(self):
        _, data = load_pilot_style_pack(known_zone_ids=KNOWN_ZONES)
        for group in (
            data.facade_rules.entrance_composition_options,
            data.facade_rules.window_group_ids,
            data.facade_rules.parapet_family_ids,
            data.facade_rules.wall_treatment_ids,
            data.facade_rules.shading_element_ids,
        ):
            assert all(v.startswith("demo_") for v in group)
        assert all(m.id.startswith("demo_") for m in data.materials.material_palette)


class TestLoaderRejections:
    def test_second_active_pack_rejected(self, tmp_path):
        root = copy_pack(tmp_path)
        shutil.copytree(SHIPPED_PACK, root / "another_demo_v1")
        with pytest.raises(SpdInputError, match="exactly one pilot style pack"):
            load_pilot_style_pack(root)

    def test_zero_packs_rejected(self, tmp_path):
        root = tmp_path / "styles"
        root.mkdir()
        with pytest.raises(SpdInputError, match="found 0"):
            load_pilot_style_pack(root)

    def test_missing_required_file_rejected(self, tmp_path):
        root = copy_pack(tmp_path)
        (root / "najdi_demo_v1" / "materials.json").unlink()
        with pytest.raises(SpdInputError, match="missing required file 'materials.json'"):
            load_pilot_style_pack(root)

    def test_invalid_schema_rejected(self, tmp_path):
        root = copy_pack(tmp_path)
        edit_json(root / "najdi_demo_v1", "style.json", lambda d: d.update(surprise=True))
        with pytest.raises(SpdInputError, match="style.json rejected"):
            load_pilot_style_pack(root)

    def test_official_status_claim_rejected(self, tmp_path):
        root = copy_pack(tmp_path)
        edit_json(
            root / "najdi_demo_v1",
            "style.json",
            lambda d: d.update(status="official_approved"),
        )
        with pytest.raises(SpdInputError, match="style.json rejected at 'status'"):
            load_pilot_style_pack(root)

    def test_verified_provenance_claim_rejected(self, tmp_path):
        root = copy_pack(tmp_path)
        edit_json(
            root / "najdi_demo_v1",
            "source_metadata.json",
            lambda d: d.update(provenance_level="verified"),
        )
        with pytest.raises(SpdInputError, match="source_metadata.json rejected"):
            load_pilot_style_pack(root)

    def test_unknown_zone_reference_rejected(self, tmp_path):
        root = copy_pack(tmp_path)
        edit_json(
            root / "najdi_demo_v1",
            "style.json",
            lambda d: d.update(applicable_zone_ids=["NO-SUCH-ZONE"]),
        )
        with pytest.raises(SpdInputError, match="unknown zone ids: NO-SUCH-ZONE"):
            load_pilot_style_pack(root, known_zone_ids=KNOWN_ZONES)

    def test_id_directory_mismatch_rejected(self, tmp_path):
        # The directory must be the pilot id AND style.json must agree.
        root = copy_pack(tmp_path)
        edit_json(
            root / "najdi_demo_v1",
            "style.json",
            lambda d: d.update(style_pack_id="other_demo_v1"),
        )
        with pytest.raises(SpdInputError, match="must match its directory name"):
            load_pilot_style_pack(root)

    def test_non_pilot_pack_id_rejected(self, tmp_path):
        # Regression (Codex M3 P1): a single well-formed pack with a different
        # id (e.g. hejazi_demo_v1) must not activate - only the locked pilot.
        root = tmp_path / "styles"
        root.mkdir()
        shutil.copytree(SHIPPED_PACK, root / "hejazi_demo_v1")
        edit_json(
            root / "hejazi_demo_v1",
            "style.json",
            lambda d: d.update(style_pack_id="hejazi_demo_v1"),
        )
        with pytest.raises(SpdInputError, match="only the locked pilot pack 'najdi_demo_v1'"):
            load_pilot_style_pack(root)

    def test_bad_semver_rejected(self, tmp_path):
        root = copy_pack(tmp_path)
        edit_json(root / "najdi_demo_v1", "style.json", lambda d: d.update(version="v1"))
        with pytest.raises(SpdInputError, match="version"):
            load_pilot_style_pack(root)

    def test_inverted_proportion_range_rejected(self, tmp_path):
        root = copy_pack(tmp_path)
        edit_json(
            root / "najdi_demo_v1",
            "facade_rules.json",
            lambda d: d.update(window_proportion_range_w_to_h={"min": 0.9, "max": 0.4}),
        )
        with pytest.raises(SpdInputError, match="min > max"):
            load_pilot_style_pack(root)

    @pytest.mark.parametrize("color", ["beige", "#GGGGGG", "#12345", "#1234567"])
    def test_invalid_hex_color_rejected(self, tmp_path, color):
        # "#GGGGGG" is the Codex M3 P2 regression: right shape, not hex.
        root = copy_pack(tmp_path)
        edit_json(
            root / "najdi_demo_v1",
            "materials.json",
            lambda d: d.update(color_palette_hex=[color]),
        )
        with pytest.raises(SpdInputError, match="invalid hex color"):
            load_pilot_style_pack(root)

    def test_infinite_range_value_rejected(self, tmp_path):
        # Regression (Codex M3 P2): JSON 1e400 decodes to +inf and must not
        # reach M4 geometry.
        root = copy_pack(tmp_path)
        path = root / "najdi_demo_v1" / "facade_rules.json"
        content = path.read_text(encoding="utf-8").replace('"min": 0.3', '"min": 1e400')
        path.write_text(content, encoding="utf-8")
        with pytest.raises(SpdInputError, match="facade_rules.json rejected"):
            load_pilot_style_pack(root)

    def test_sill_above_head_rejected(self, tmp_path):
        root = copy_pack(tmp_path)
        edit_json(
            root / "najdi_demo_v1",
            "facade_rules.json",
            lambda d: d["facade_dimensions"].update(window_sill_height_m=2.6),
        )
        with pytest.raises(SpdInputError, match="sill < head"):
            load_pilot_style_pack(root)

    def test_facade_dimensions_present_for_m4(self):
        # Regression (Codex M3 P1): the pack must carry the dimensional data
        # FR-6 needs so M4 never hard-codes facade geometry.
        _, data = load_pilot_style_pack(known_zone_ids=KNOWN_ZONES)
        dims = data.facade_rules.facade_dimensions
        assert dims.wall_height_m == 3.6
        assert 0 < dims.window_sill_height_m < dims.window_head_height_m <= dims.wall_height_m
        assert dims.window_max_width_m == 1.2
        assert dims.parapet_height_m > 0 and dims.ornament_band_elevation_m < dims.wall_height_m

    def test_pack_window_contract_is_self_consistent(self):
        # Regression (Codex M3 verification P1): the widest allowed window at
        # the pack's fixed heights must satisfy the pack's own proportion max,
        # otherwise M4 would reject the default concept.
        _, data = load_pilot_style_pack(known_zone_ids=KNOWN_ZONES)
        dims = data.facade_rules.facade_dimensions
        height = dims.window_head_height_m - dims.window_sill_height_m
        assert dims.window_max_width_m / height <= (
            data.facade_rules.window_proportion_range_w_to_h.max
        )

    def test_inconsistent_window_contract_rejected(self, tmp_path):
        root = copy_pack(tmp_path)
        edit_json(
            root / "najdi_demo_v1",
            "facade_rules.json",
            lambda d: d["facade_dimensions"].update(window_max_width_m=1.5),
        )
        with pytest.raises(SpdInputError, match="internally inconsistent"):
            load_pilot_style_pack(root)

    def test_exact_boundary_ratio_accepted(self, tmp_path):
        # Regression (Codex M3 verification round 3, P2): 0.68 / 1.7 rounds to
        # 0.39999999999999997 in binary floats; a pack landing mathematically
        # on the declared minimum must still load.
        root = copy_pack(tmp_path)
        edit_json(
            root / "najdi_demo_v1",
            "facade_rules.json",
            lambda d: d["facade_dimensions"].update(window_max_width_m=0.68),
        )
        reference, _ = load_pilot_style_pack(root)
        assert reference.style_pack_id == "najdi_demo_v1"

    def test_unsatisfiable_minimum_proportion_rejected(self, tmp_path):
        # Regression (Codex M3 verification round 2, P2): a width cap so small
        # that no window can reach the minimum proportion must also reject
        # (0.5 m / 1.7 m = 0.294 < declared minimum 0.4).
        root = copy_pack(tmp_path)
        edit_json(
            root / "najdi_demo_v1",
            "facade_rules.json",
            lambda d: d["facade_dimensions"].update(window_max_width_m=0.5),
        )
        with pytest.raises(SpdInputError, match="below the pack's declared minimum"):
            load_pilot_style_pack(root)
