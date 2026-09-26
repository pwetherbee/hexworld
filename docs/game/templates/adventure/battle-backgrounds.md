# Adventure: battle backgrounds

Every battle happens *somewhere specific*: the backdrop is a layered, animated pixel-art scene of the
tile where the fight started, generated for that tile, consistent with the world's art.

---

## 1. Look

A side-view scene (the battle camera looks across the tile, not down on it), in 4–5 parallax layers:

```
L0  sky        gradient + clouds / stars / smog, time of day and weather
L1  far        distant silhouettes: the region's skyline, mountain range, sea horizon
L2  mid        this tile's landmark and big shapes (the lighthouse, towers, trees), from its sprites
L3  ground     the battle floor: the tile's ground material seen at a shallow angle, two platforms
L4  near       foreground frame elements (grass tufts, a railing, rocks), slightly blurred/darkened
FX             weather particles, water shimmer, drifting leaves, smoke, fireflies
```

- Resolution matches the world's pixel density (a 64 px world renders backgrounds at ~320×180 logical
  pixels, scaled with nearest filtering).
- Idle motion: slow parallax drift, cloud motion, water shimmer, sway in L4, a subtle light flicker for
  fires and windows. All in shaders, like world-life.md.

## 2. How a background is made (hybrid: engine + image model)

Using the world's own assets wherever possible keeps backgrounds consistent with the map:

| layer | source |
|---|---|
| L0 sky | engine: gradient from the world palette + time of day; cloud and star sprites from a small pack |
| L1 far | **engine**: a horizon silhouette built from the region's relief (the heightmap sampled along a line through the tile, far-to-near), coloured from the region's dominant materials; plus distant landmark sprites from neighbouring tiles |
| L2 mid | **engine**: the tile's own landmark and mid props (their painted sprites, enlarged) arranged on the horizon line; buildings rendered as flat facades from the tile's facade layer |
| L3 ground | **engine**: the tile's ground material rendered in perspective by the material DSL (same ops, stretched), with two oval platforms tinted from the material ramp |
| L4 near | engine: 2–4 of the tile's L1/L2 scatter sprites, scaled up, darkened |
| accent | optional **image model** layer per region: a painted "far scenery" panel (a 16:4 strip) in the house style for the region's signature view, cached per region |

> **Decision:** engine-first. The map's own sprites, materials and relief produce most of the scene, so
> it always matches the tile and costs nothing. The image model adds one painted panorama per region
> for richness. This avoids a slow image call per battle and keeps style consistent.

- **BackdropDirector** (a skill) writes a short brief per region (what's on the horizon, the mood, what
  the painted panel should show) and picks which tile sprites to feature; the engine composes.
- Backgrounds are cached per (tile, time-of-day bucket, weather); a battle starts instantly.

## 3. Special arenas

- Warden arenas use their tile's scene plus the mechanic made visible (a flooded floor for a tide
  mechanic, pylons for a shield mechanic, a storm for weather).
- The confrontation gets a unique painted panorama.

## 4. Open questions

- Side view vs. a 3/4 view that matches the map's camera? Side view is classic and readable (Pokémon,
  Cassette Beasts); a 3/4 view could reuse the actual 3D tile. Proposal: side view, with an option to
  test the 3D-tile variant later (render the tile's relief mesh from a low angle as L2/L3).
