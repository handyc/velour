"""Aether scene IR — intermediate representation for 3D worlds.

Unlike the CRUD-app IR in ir.py, this captures a spatial scene graph:
environment, entities with transforms, scripts, and portals. Used by
gen_stereokit.py (and future generators) to produce native VR projects
from any Aether world.
"""

from dataclasses import dataclass, field


@dataclass
class ScriptIR:
    event: str          # start, update, player_near, interact, timer, etc.
    code: str           # original JS source
    props: dict = field(default_factory=dict)


@dataclass
class EntityIR:
    id: int
    name: str
    primitive: str = ''          # box, sphere, cylinder, cone, plane, torus, ring
    primitive_color: str = '#808080'
    asset_url: str = ''          # GLTF/GLB path (relative to media root)
    position: list = field(default_factory=lambda: [0, 0, 0])
    rotation: list = field(default_factory=lambda: [0, 0, 0])  # degrees
    scale: list = field(default_factory=lambda: [1, 1, 1])
    behavior: str = 'static'
    behavior_speed: float = 1.0
    cast_shadow: bool = True
    receive_shadow: bool = True
    scripts: list = field(default_factory=list)  # list of ScriptIR


@dataclass
class PortalIR:
    label: str
    target_slug: str
    target_title: str
    position: list = field(default_factory=lambda: [0, 0, -10])
    width: float = 2.0
    height: float = 3.0


@dataclass
class EnvironmentIR:
    skybox: str = 'color'         # color, hdri, procedural
    sky_color: str = '#87CEEB'
    ground_color: str = '#3d5c3a'
    ground_size: float = 100.0
    ambient_light: float = 0.4
    fog_near: float = 50.0
    fog_far: float = 200.0
    fog_color: str = '#c8d8e4'
    hdri_asset: str = ''
    ambient_audio_url: str = ''
    ambient_volume: float = 0.4
    soundscape: str = ''
    gravity: float = -9.81


@dataclass
class SceneIR:
    title: str
    slug: str
    environment: EnvironmentIR
    spawn: list = field(default_factory=lambda: [0, 1.6, 0])
    entities: list = field(default_factory=list)   # list of EntityIR
    portals: list = field(default_factory=list)     # list of PortalIR
