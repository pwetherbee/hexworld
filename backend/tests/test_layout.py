from hexworld.art.layout import PropRequest, _fits, _overlap, layout_props


def test_layout_keeps_props_inside_the_hex_and_apart():
    reqs = [
        PropRequest("keep", 0.0, 0.1, 1.0, 30, 36, "landmark"),
        PropRequest("cart", 0.05, 0.15, 1.0, 14, 10, "prop"),  # asks for the keep's spot
        PropRequest("banner", -0.5, -0.5, 1.0, 8, 20, "prop"),  # asks for a spot off the tile
        PropRequest("barrel", 0.3, 0.3, 1.0, 8, 9, "prop"),
    ]
    slots, dropped = layout_props(reqs, 64)
    assert not dropped and len(slots) == 4
    for a in slots:
        assert _fits(a.x, a.y, a.w, a.h)
        for b in slots:
            if a is not b:
                assert _overlap(a, b.x, b.y, b.w, b.h) <= 0.18 + 1e-6
    keep = next(s for s in slots if s.kind == "keep")
    assert keep.w <= 0.95 and abs(keep.x) < 0.3


def test_layout_drops_what_cannot_fit():
    reqs = [PropRequest(f"tower{i}", 0, 0.1, 1.6, 30, 36, "prop") for i in range(12)]
    slots, dropped = layout_props(reqs, 64)
    assert slots and dropped and len(slots) + len(dropped) == 12
