"""Parse an Aether world into a SceneIR for code generation.

Reads directly from the database (no HTTP round-trip) using the same
query logic as aether.views.world_scene_json.
"""

from .aether_ir import (
    EntityIR, EnvironmentIR, PortalIR, SceneIR, ScriptIR,
)


def parse_world(slug):
    """Parse an Aether World by slug into a SceneIR.

    Returns a SceneIR dataclass, or None if the world doesn't exist.
    """
    from aether.models import World

    try:
        world = World.objects.get(slug=slug)
    except World.DoesNotExist:
        return None

    env = EnvironmentIR(
        skybox=world.skybox,
        sky_color=world.sky_color,
        ground_color=world.ground_color,
        ground_size=world.ground_size,
        ambient_light=world.ambient_light,
        fog_near=world.fog_near,
        fog_far=world.fog_far,
        fog_color=world.fog_color,
        hdri_asset=world.hdri_asset,
        ambient_audio_url=world.audio_src(),
        ambient_volume=world.ambient_volume,
        soundscape=world.soundscape,
        gravity=world.gravity,
    )

    entities = []
    for ent in world.entities.filter(visible=True).select_related('asset'):
        scripts = []
        for es in ent.scripts.filter(enabled=True).select_related('script'):
            scripts.append(ScriptIR(
                event=es.script.event,
                code=es.script.code,
                props=es.props or {},
            ))

        asset_url = ''
        if ent.asset and ent.asset.file:
            asset_url = ent.asset.file.url

        entities.append(EntityIR(
            id=ent.pk,
            name=ent.name,
            primitive=ent.primitive,
            primitive_color=ent.primitive_color,
            asset_url=asset_url,
            position=[ent.pos_x, ent.pos_y, ent.pos_z],
            rotation=[ent.rot_x, ent.rot_y, ent.rot_z],
            scale=[ent.scale_x, ent.scale_y, ent.scale_z],
            behavior=ent.behavior,
            behavior_speed=ent.behavior_speed,
            cast_shadow=ent.cast_shadow,
            receive_shadow=ent.receive_shadow,
            scripts=scripts,
        ))

    portals = []
    for p in world.portals_out.select_related('to_world'):
        portals.append(PortalIR(
            label=p.label or p.to_world.title,
            target_slug=p.to_world.slug,
            target_title=p.to_world.title,
            position=[p.pos_x, p.pos_y, p.pos_z],
            width=p.width,
            height=p.height,
        ))

    return SceneIR(
        title=world.title,
        slug=world.slug,
        environment=env,
        spawn=[world.spawn_x, world.spawn_y, world.spawn_z],
        entities=entities,
        portals=portals,
    )
