import jsonschema
import pytest
from pydantic import ValidationError

from hexworld.agents.fake import FakeClient
from hexworld.agents.llm import LLMRequest, strict_schema
from hexworld.agents.super import ANCHOR_SCHEMA, PLAN_SCHEMA, REVIEW_SCHEMA
from hexworld.agents.tile import normalize_design, tile_design_schema
from hexworld.domain import (
    AttributeDef,
    EdgeSpec,
    StyleGuide,
    TileDesign,
    World,
    WorldPlan,
    compile_attribute_schema,
)


def _walk(node, path="$"):
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


@pytest.mark.parametrize("schema", [PLAN_SCHEMA, REVIEW_SCHEMA, ANCHOR_SCHEMA])
def test_strict_schemas_are_closed(schema):
    jsonschema.Draft202012Validator.check_schema(schema)
    for path, node in _walk(schema):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, path
            assert set(node["required"]) == set(node["properties"]), path
        assert "default" not in node or path.endswith(".properties"), path


def test_strict_schema_keeps_property_named_title():
    assert "title" in PLAN_SCHEMA["$defs"]["WorldSpec"]["properties"]


def test_attribute_meta_schema():
    with pytest.raises(ValidationError):
        AttributeDef(name="kind", type="enum", description="", enum_values=[], minimum=None, maximum=None)
    attrs = [
        AttributeDef(name="Elevation", type="integer", description="h", enum_values=[], minimum=0, maximum=5),
        AttributeDef(
            name="loot", type="enum_list", description="l", enum_values=["a", "b"], minimum=None, maximum=None
        ),
    ]
    assert attrs[0].name == "elevation"
    s = compile_attribute_schema(attrs)
    jsonschema.validate({"elevation": 3, "loot": ["a"]}, s)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"elevation": 9, "loot": []}, s)


def test_style_guide_coercion():
    sg = StyleGuide(
        palette=["#AABBCC", "#aabbcc", "#000000", "#ffffff", "#123456"],
        tile_px=44,
        view="v",
        light_direction="l",
        outline="o",
        style_keywords="k",
    )
    assert sg.palette == ["#aabbcc", "#000000", "#ffffff", "#123456"]
    assert sg.tile_px == 48


async def _fake_plan() -> WorldPlan:
    req = LLMRequest(
        role="super",
        task="world_plan",
        system="",
        schema=PLAN_SCHEMA,
        payload={
            "existing_world": None,
            "user_prompt": "a pirate island",
            "origin": {"q": 0, "r": 0},
            "candidate_coords": [{"q": 0, "r": 0, "ring": 0}, {"q": 1, "r": 0, "ring": 1}],
            "existing_tiles_nearby": [],
        },
    )
    res = await FakeClient(latency_s=0).complete(req)
    jsonschema.validate(res.data, PLAN_SCHEMA)
    return WorldPlan.model_validate(res.data)


async def test_fake_plan_is_schema_valid_and_tile_schema_compiles():
    plan = await _fake_plan()
    world = World(
        id="w",
        name="t",
        radius=5,
        created_at=0,
        spec=plan.world,
        style=plan.style,
        tile_attributes=plan.tile_attributes,
    )
    schema = tile_design_schema(world)
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["properties"]["biome"]["enum"] == plan.world.terrain_vocabulary


async def test_normalize_design_repairs_edges_and_clamps():
    plan = await _fake_plan()
    world = World(
        id="w",
        name="t",
        radius=5,
        created_at=0,
        spec=plan.world,
        style=plan.style,
        tile_attributes=plan.tile_attributes,
    )
    vocab = plan.world.terrain_vocabulary
    design = TileDesign(
        biome="not_a_terrain",
        summary="s",
        art_prompt="a",
        negative_prompt="",
        attributes={"danger": 99, "loot": "none"},
        edges=[EdgeSpec(terrain=vocab[0], connectors=["bogus"]) for _ in range(6)],
    )
    want = EdgeSpec(terrain=vocab[1], connectors=[])
    fixed, report = normalize_design(design, world, {2: want})
    assert fixed.biome in vocab
    assert fixed.edges[2] == want and report["repaired_edges"] == [2]
    assert all(e.connectors == [] for e in fixed.edges)
    assert fixed.attributes["danger"] == 5 and "danger" in report["clamped"]
    assert "encounter" in report["defaulted"]


def test_strict_schema_roundtrip_simple():
    from pydantic import BaseModel

    class M(BaseModel):
        a: int
        b: str | None = None

    s = strict_schema(M)
    assert s["required"] == ["a", "b"] and s["additionalProperties"] is False
