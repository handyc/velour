"""
Lego-world generator.

A *world* is a 32x32-stud colored baseplate populated with 0-8 buildings,
0-8 trees, 0-8 flowers, and 0-8 people — each of which is grown from an
L-System rule (see lsystem.py).

Worlds serialize to JSON files with a searchable filename convention:

    world_<name>_b<buildings>_t<trees>_f<flowers>_p<people>_<biome>_s<seed>.json

Which makes glob queries natural:

    worlds/world_*_b0_*.json            # worlds with zero buildings
    worlds/world_*_*_plains_*.json      # plains biome
    worlds/world_forest_*_s0042.json    # specific seed

The JSON payload holds enough information to deterministically re-render the
world and also lists the placed objects so downstream tools (search,
filtering, analytics) don't need to re-run the L-System to know what is in
the scene.
"""
from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field, asdict
from typing import Any

from .brick_render import (
    Brick, BRICK_H, PLATE_H,
    BRICK_RED, BRICK_BLUE, BRICK_YELLOW, BRICK_GREEN, BRICK_ORANGE,
    BRICK_WHITE, BRICK_BLACK, BRICK_GREY, BRICK_TAN, BRICK_PURPLE,
)
from . import lsystem as L


BASEPLATE_STUDS = 32


# Biome -> baseplate color mapping. The biome also biases some object choices
# via the placement helper, but the L-System rules themselves are color-agnostic
# (they pick from their own palette).
BIOMES: dict[str, str] = {
    "plains":  L.MEADOW,
    "forest":  L.DARK_GREEN,
    "desert":  L.SAND,
    "snow":    L.SNOW,
    "harbor":  L.SEA,
    "autumn":  "#b8733a",
    "town":    L.STONE_GREY,
    "dusk":    "#4d6b8c",
    "meadow":  L.MEADOW,
    "island":  L.SEA,
}


@dataclass
class PlacedObject:
    kind: str                  # "building", "tree", "flower", "person", "hill"
    x: int                     # bottom-left stud coordinate on baseplate
    y: int
    seed: int                  # per-object seed used by the L-System
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class World:
    name: str
    biome: str
    seed: int
    baseplate_color: str
    n_buildings: int
    n_trees: int
    n_flowers: int
    n_people: int
    n_hills: int = 0
    n_lamps: int = 0
    n_rocks: int = 0
    objects: list[PlacedObject] = field(default_factory=list)

    @property
    def n_decor(self) -> int:
        return self.n_hills + self.n_lamps + self.n_rocks

    # -------- filename convention --------
    # Filename packs the four primary counts into short flags (b/t/f/p) and
    # rolls terrain decor into a single d<n>. Full per-kind breakdown is in
    # the JSON body. Shape:
    #   world_<name>_b<n>_t<n>_f<n>_p<n>_d<n>_<biome>_s<seed>.json
    def filename(self) -> str:
        return (
            f"world_{self.name}"
            f"_b{self.n_buildings}"
            f"_t{self.n_trees}"
            f"_f{self.n_flowers}"
            f"_p{self.n_people}"
            f"_d{self.n_decor}"
            f"_{self.biome}"
            f"_s{self.seed:04d}.json"
        )

    # -------- JSON round-trip --------
    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, indent=2)

    @classmethod
    def from_json(cls, blob: str) -> "World":
        d = json.loads(blob)
        objs = [PlacedObject(**o) for o in d.pop("objects")]
        w = cls(**d)
        w.objects = objs
        return w

    def save(self, directory: str = "worlds") -> str:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, self.filename())
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
        return path


# ---------------------------------------------------------------------------
# Placement: naive grid occupancy
# ---------------------------------------------------------------------------
def _reserve(occupancy: list[list[bool]], x: int, y: int,
             w: int, d: int) -> bool:
    """Try to mark a WxD rectangle starting at (x, y) as occupied.
    Returns False if any cell is already taken or out of bounds."""
    if x < 0 or y < 0 or x + w > BASEPLATE_STUDS or y + d > BASEPLATE_STUDS:
        return False
    for i in range(x, x + w):
        for j in range(y, y + d):
            if occupancy[i][j]:
                return False
    for i in range(x, x + w):
        for j in range(y, y + d):
            occupancy[i][j] = True
    return True


def _try_place(rng: random.Random, occupancy, w: int, d: int,
               margin: int = 0, tries: int = 40) -> tuple[int, int] | None:
    for _ in range(tries):
        x = rng.randint(margin, BASEPLATE_STUDS - w - margin)
        y = rng.randint(margin, BASEPLATE_STUDS - d - margin)
        if _reserve(occupancy, x, y, w, d):
            return x, y
    return None


# ---------------------------------------------------------------------------
# World construction
# ---------------------------------------------------------------------------
def build_world(name: str, biome: str, seed: int,
                n_buildings: int, n_trees: int,
                n_flowers: int, n_people: int,
                n_hills: int = 0, n_lamps: int = 0,
                n_rocks: int = 0,
                library_placements: list[tuple[str, int]] | None = None) -> World:
    """Deterministic world assembly. All randomness threads through `seed`."""
    rng = random.Random(seed)
    baseplate_color = BIOMES.get(biome, L.MEADOW)
    world = World(name=name, biome=biome, seed=seed,
                  baseplate_color=baseplate_color,
                  n_buildings=n_buildings, n_trees=n_trees,
                  n_flowers=n_flowers, n_people=n_people,
                  n_hills=n_hills, n_lamps=n_lamps, n_rocks=n_rocks)

    occupancy = [[False] * BASEPLATE_STUDS for _ in range(BASEPLATE_STUDS)]

    # Place buildings first (largest footprint), then trees (which can be
    # near buildings but not on them), then people, then flowers (smallest).
    # Each object keeps its own sub-seed so re-generation is deterministic.
    sub = 0
    for _ in range(n_buildings):
        sub_rng = random.Random(seed * 1000 + sub)
        w, d, floors, _ = L.footprint_building(sub_rng)
        pos = _try_place(rng, occupancy, w + 1, d + 1, margin=1)
        if pos is None:
            sub += 1
            continue
        world.objects.append(PlacedObject(
            kind="building", x=pos[0], y=pos[1],
            seed=seed * 1000 + sub,
            meta={"w": w, "d": d, "floors": floors}))
        sub += 1

    for _ in range(n_trees):
        fw, fd = L.footprint_tree()
        pos = _try_place(rng, occupancy, fw, fd)
        if pos is None:
            sub += 1
            continue
        world.objects.append(PlacedObject(
            kind="tree", x=pos[0], y=pos[1],
            seed=seed * 1000 + sub))
        sub += 1

    for _ in range(n_people):
        fw, fd = L.footprint_person()
        pos = _try_place(rng, occupancy, fw, fd)
        if pos is None:
            sub += 1
            continue
        world.objects.append(PlacedObject(
            kind="person", x=pos[0], y=pos[1],
            seed=seed * 1000 + sub))
        sub += 1

    for _ in range(n_hills):
        fw, fd = L.footprint_hill()
        pos = _try_place(rng, occupancy, fw, fd)
        if pos is None:
            sub += 1
            continue
        world.objects.append(PlacedObject(
            kind="hill", x=pos[0], y=pos[1],
            seed=seed * 1000 + sub))
        sub += 1

    for _ in range(n_rocks):
        fw, fd = L.footprint_rock()
        pos = _try_place(rng, occupancy, fw, fd)
        if pos is None:
            sub += 1
            continue
        world.objects.append(PlacedObject(
            kind="rock", x=pos[0], y=pos[1],
            seed=seed * 1000 + sub))
        sub += 1

    for _ in range(n_lamps):
        fw, fd = L.footprint_lamp()
        pos = _try_place(rng, occupancy, fw, fd)
        if pos is None:
            sub += 1
            continue
        world.objects.append(PlacedObject(
            kind="lamp", x=pos[0], y=pos[1],
            seed=seed * 1000 + sub))
        sub += 1

    for _ in range(n_flowers):
        fw, fd = L.footprint_flower()
        pos = _try_place(rng, occupancy, fw, fd)
        if pos is None:
            sub += 1
            continue
        world.objects.append(PlacedObject(
            kind="flower", x=pos[0], y=pos[1],
            seed=seed * 1000 + sub))
        sub += 1

    if library_placements:
        # Pull footprints in a single query so we don't hit the DB per object.
        from .models import LegoModel
        slugs = [s for s, _ in library_placements if _ > 0]
        models_by_slug = {
            m.slug: m for m in LegoModel.objects.filter(slug__in=slugs)
        }
        for slug, count in library_placements:
            if count <= 0:
                continue
            m = models_by_slug.get(slug)
            if m is None:
                continue
            fw, fd = m.footprint_w, m.footprint_d
            for _ in range(count):
                pos = _try_place(rng, occupancy, fw, fd)
                if pos is None:
                    sub += 1
                    continue
                world.objects.append(PlacedObject(
                    kind="library", x=pos[0], y=pos[1],
                    seed=seed * 1000 + sub,
                    meta={"slug": slug}))
                sub += 1

    return world


# ---------------------------------------------------------------------------
# Rendering: flatten a World into (Brick, pos) placements
# ---------------------------------------------------------------------------
def world_to_bricks(world: World) -> list[L.Placement]:
    """Produce the full (Brick, (x, y, z)) list for a world.

    Includes the baseplate itself so callers can draw the whole scene with a
    single draw_group().
    """
    placements: list[L.Placement] = []
    # baseplate: one giant 32x32 plate at z = -PLATE_H so objects at z=0 sit
    # on top of it
    placements.append((
        Brick(BASEPLATE_STUDS, BASEPLATE_STUDS, 1, world.baseplate_color),
        (0, 0, -PLATE_H)))

    for obj in world.objects:
        origin = (obj.x, obj.y, 0.0)
        rng = random.Random(obj.seed)
        if obj.kind == "building":
            dims = (obj.meta["w"], obj.meta["d"], obj.meta["floors"])
            placements.extend(L.make_building(rng, origin=origin, dims=dims))
        elif obj.kind == "tree":
            placements.extend(L.make_tree(rng, origin=origin))
        elif obj.kind == "flower":
            placements.extend(L.make_flower(rng, origin=origin))
        elif obj.kind == "person":
            placements.extend(L.make_person(rng, origin=origin))
        elif obj.kind == "hill":
            placements.extend(L.make_hill(rng, origin=origin))
        elif obj.kind == "lamp":
            placements.extend(L.make_lamp(rng, origin=origin))
        elif obj.kind == "rock":
            placements.extend(L.make_rock(rng, origin=origin))
        elif obj.kind == "library":
            from .models import LegoModel
            slug = (obj.meta or {}).get("slug")
            if not slug:
                continue
            model = LegoModel.objects.filter(slug=slug).first()
            if model is None:
                continue
            placements.extend(L.make_from_spec(model.as_spec(), origin=origin))
    return placements
