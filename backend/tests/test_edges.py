"""Tests for manual edge classification and street width (M1)."""

import pytest

from saudi_plot_design.model import EdgeClass, EdgeRole, SpdInputError
from saudi_plot_design.plot.edges import (
    edge_roles,
    parse_edge_classes,
    require_single_street,
    validate_street_width,
)


class TestParseEdgeClasses:
    def test_all_classes_parse(self):
        assert parse_edge_classes("street, Neighbor,PATH,unknown", 4) == (
            EdgeClass.STREET,
            EdgeClass.NEIGHBOR,
            EdgeClass.PATH,
            EdgeClass.UNKNOWN,
        )

    def test_wrong_count(self):
        with pytest.raises(SpdInputError, match=r"expected 4 edge classes.*got 3"):
            parse_edge_classes("street,neighbor,neighbor", 4)

    def test_unknown_class_name(self):
        with pytest.raises(SpdInputError, match="edge 2: unknown class 'garden'"):
            parse_edge_classes("street,garden,neighbor,neighbor", 4)


class TestSingleStreetRule:
    def test_one_street_ok(self):
        edges = (EdgeClass.STREET, EdgeClass.NEIGHBOR, EdgeClass.PATH, EdgeClass.UNKNOWN)
        assert require_single_street(edges) == 0

    def test_no_street_rejected(self):
        edges = (EdgeClass.NEIGHBOR,) * 4
        with pytest.raises(SpdInputError, match="exactly one edge.*'street'.*got 0"):
            require_single_street(edges)

    def test_two_streets_rejected(self):
        edges = (EdgeClass.STREET, EdgeClass.STREET, EdgeClass.NEIGHBOR, EdgeClass.NEIGHBOR)
        with pytest.raises(SpdInputError, match="got 2"):
            require_single_street(edges)


class TestStreetWidth:
    def test_valid_width(self):
        assert validate_street_width(15.0) == 15.0

    @pytest.mark.parametrize("width", [0.0, -5.0, 2.9, 200.0])
    def test_invalid_width_rejected(self, width):
        with pytest.raises(SpdInputError, match="street width"):
            validate_street_width(width)

    def test_non_numeric_width_rejected(self):
        with pytest.raises(SpdInputError, match="must be a number"):
            validate_street_width("wide")


class TestEdgeRoles:
    def test_roles_front_rear_sides(self):
        edges = (EdgeClass.NEIGHBOR, EdgeClass.NEIGHBOR, EdgeClass.STREET, EdgeClass.NEIGHBOR)
        assert edge_roles(edges) == (
            EdgeRole.REAR,
            EdgeRole.SIDE,
            EdgeRole.FRONT,
            EdgeRole.SIDE,
        )

    def test_roles_require_four_edges(self):
        edges = (EdgeClass.STREET, EdgeClass.NEIGHBOR, EdgeClass.NEIGHBOR)
        with pytest.raises(SpdInputError, match="4-edge rectangular"):
            edge_roles(edges)
