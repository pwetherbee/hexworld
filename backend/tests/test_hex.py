import math

import pytest

from hexworld.hex import DIRECTIONS, ORIGIN, Hex, corner, edge_endpoints, opposite, ring, spiral, within


def test_neighbors_and_direction_to():
    h = Hex(2, -1)
    for i in range(6):
        n = h.neighbor(i)
        assert h.distance(n) == 1
        assert h.direction_to(n) == i
        assert n.direction_to(h) == opposite(i)
    assert h.direction_to(Hex(5, 5)) is None


@pytest.mark.parametrize("k", [0, 1, 2, 3, 5])
def test_ring_and_spiral_sizes(k):
    r = ring(ORIGIN, k)
    assert len(r) == (1 if k == 0 else 6 * k)
    assert len(set(r)) == len(r)
    assert all(ORIGIN.distance(h) == k for h in r)
    assert len(spiral(ORIGIN, k)) == 1 + 3 * k * (k + 1)
    assert set(spiral(ORIGIN, k)) == set(within(ORIGIN, k))


def test_three_coloring_is_proper():
    for h in within(ORIGIN, 8):
        for n in h.neighbors():
            assert h.color3() != n.color3()


def test_shared_edge_endpoints_coincide():
    """Edge i of a hex and edge i+3 of its neighbor are the same segment, reversed."""
    size = 10.0
    for i, _ in enumerate(DIRECTIONS):
        n = ORIGIN.neighbor(i)
        nx, ny = n.to_pixel(size)
        (a0, a1), (b0, b1) = edge_endpoints(size, i), edge_endpoints(size, opposite(i))
        b0 = (b0[0] + nx, b0[1] + ny)
        b1 = (b1[0] + nx, b1[1] + ny)
        assert math.dist(a0, b1) < 1e-9
        assert math.dist(a1, b0) < 1e-9


def test_pointy_top_corners():
    s = 1.0
    # corners at -30, 30, 90 (bottom, y down), ... => a corner straight below the center
    assert corner(s, 2) == pytest.approx((0.0, 1.0), abs=1e-9)
    assert corner(s, 5) == pytest.approx((0.0, -1.0), abs=1e-9)


def test_key_roundtrip():
    h = Hex(-3, 7)
    assert Hex.parse(h.key) == h
