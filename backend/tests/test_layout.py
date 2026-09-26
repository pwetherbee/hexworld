from hexworld.art.layout import PropRequest, PropSlot, _fits, _overlap, layout_props, relocate


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


def _street(x: float, y: float, w: float, surface: str = "land") -> bool:
    """A city tile where the only open ground is an east-west street along y = 0.3."""
    return abs(y - 0.3) < 0.04


def test_props_stand_in_the_street_not_on_roofs():
    reqs = [
        PropRequest("parked car", 0.3, -0.3, 1.0, 20, 10, "prop"),  # asks for a rooftop
        PropRequest("street vendor", -0.2, 0.0, 1.0, 8, 12, "prop"),
    ]
    slots, dropped = layout_props(reqs, 64, size=0.5, ground_ok=_street)
    assert not dropped and len(slots) == 2
    assert all(abs(s.y - 0.3) < 0.04 for s in slots)
    full, _ = layout_props(reqs, 64)
    car = next(s for s in slots if s.kind == "parked car")
    assert abs(car.w - next(s for s in full if s.kind == "parked car").w * 0.5) < 1e-6  # world prop scale


def test_relocate_moves_props_off_new_buildings():
    slots = [
        PropSlot("car", 0.2, -0.3, 1.0, 0.3, 0.15, "prop"),
        PropSlot("lamp", -0.2, -0.3, 1.0, 0.1, 0.3, "prop"),
    ]
    kept, dropped = relocate(slots, _street)
    assert not dropped and all(abs(s.y - 0.3) < 0.04 for s in kept)
    assert relocate(slots, lambda *_: False) == ([], ["car", "lamp"])


def test_boats_float_and_people_stay_ashore():
    def coast(x: float, y: float, w: float, surface: str) -> bool:
        return (y > 0.2) == (surface == "water")  # the south of the tile is the sea

    reqs = [
        PropRequest("fishing boat", 0.0, -0.3, 1.0, 16, 12, "prop", "water"),
        PropRequest("fisherman", 0.1, 0.5, 1.0, 8, 12, "prop", "land"),
    ]
    slots, dropped = layout_props(reqs, 64, ground_ok=coast)
    assert not dropped
    boat = next(s for s in slots if s.kind == "fishing boat")
    man = next(s for s in slots if s.kind == "fisherman")
    assert boat.y > 0.2 and man.y <= 0.2 and boat.surface == "water"
