"""Aether — browser-based immersive worlds.

A World is a 3D scene authored and served entirely from Velour.
Worlds run in-browser via three.js — no plugins, no installs, no
headset required (though headsets work via WebXR).

Each World has a collection of Assets (3D models, textures, audio)
and Entities (placed instances of assets with position/rotation/scale
plus optional behaviors and scripts). The scene graph is flat:
entities exist in a single world-space.

A Portal links one world to another: step through a doorway in
World A and arrive in World B. Portals are bidirectional by default.

Scripts (EntityScript) attach to entities for intelligent NPC
behavior — state machines, pathfinding, interaction, movement.
Inspired by Meta Horizon Worlds' component pattern: each script
is a self-contained behavior that responds to events (start,
update, onPlayerNear, onInteract) with access to the entity's
transform, the world clock, and other entities.

The ObjectLibrary is a global catalog of importable 3D objects
from external repositories (Sketchfab, Poly Haven, etc.). Designed
to scale to 1M+ entries. Objects are downloaded on demand and
cached locally as GLTF/GLB files.
"""

from django.db import models
from django.utils.text import slugify


ASSET_TYPE_CHOICES = [
    ('model', 'GLTF/GLB 3D model'),
    ('texture', 'Image texture (JPG/PNG)'),
    ('audio', 'Audio clip (MP3/OGG)'),
    ('hdri', 'HDRI environment map'),
]

SKYBOX_CHOICES = [
    ('color', 'Solid color'),
    ('gradient', 'Gradient sky'),
    ('hdri', 'HDRI environment'),
    ('procedural', 'Procedural sky (sun + atmosphere)'),
]

BEHAVIOR_CHOICES = [
    ('static', 'Static (no interaction)'),
    ('rotate', 'Continuous rotation'),
    ('bob', 'Gentle bobbing'),
    ('clickable', 'Clickable (triggers event)'),
    ('portal', 'Portal to another world'),
    ('orbit', 'Orbit around a point'),
    ('billboard', 'Always face camera'),
    ('scripted', 'Scripted (custom JS behavior)'),
    ('npc_wander', 'NPC: wander randomly'),
    ('npc_patrol', 'NPC: patrol waypoints'),
    ('npc_follow', 'NPC: follow player'),
]

SCRIPT_EVENT_CHOICES = [
    ('start', 'On start (once, when world loads)'),
    ('update', 'On update (every frame, receives deltaTime)'),
    ('player_near', 'On player near (within interaction range)'),
    ('player_far', 'On player leaves range'),
    ('interact', 'On interact (player clicks/activates)'),
    ('collide', 'On collision with another entity'),
    ('timer', 'On timer (fires at configured interval)'),
    ('custom', 'Custom event (sent by other scripts)'),
]

LICENSE_CHOICES = [
    ('cc0', 'CC0 (Public Domain)'),
    ('cc-by', 'CC BY (Attribution)'),
    ('cc-by-sa', 'CC BY-SA (Attribution-ShareAlike)'),
    ('cc-by-nc', 'CC BY-NC (Attribution-NonCommercial)'),
    ('editorial', 'Editorial use only'),
    ('unknown', 'Unknown'),
]

OBJECT_SOURCE_CHOICES = [
    ('sketchfab', 'Sketchfab'),
    ('polyhaven', 'Poly Haven'),
    ('khronos', 'Khronos glTF samples'),
    ('local', 'Local upload'),
]


class World(models.Model):
    """A single immersive 3D scene."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)

    # Environment
    skybox = models.CharField(
        max_length=16, choices=SKYBOX_CHOICES, default='procedural',
    )
    sky_color = models.CharField(
        max_length=7, default='#87CEEB',
        help_text='Hex color for solid/gradient sky, or tint for procedural.',
    )
    ground_color = models.CharField(max_length=7, default='#3d5c3a')
    ground_size = models.FloatField(
        default=100.0, help_text='Ground plane radius in meters.',
    )
    ambient_light = models.FloatField(
        default=0.4, help_text='Ambient light intensity (0-1).',
    )
    fog_near = models.FloatField(
        default=50.0, help_text='Fog starts at this distance (meters).',
    )
    fog_far = models.FloatField(
        default=200.0, help_text='Fog fully opaque at this distance.',
    )
    fog_color = models.CharField(max_length=7, default='#c8d8e4')
    hdri_asset = models.CharField(
        max_length=120, blank=True, default='',
        help_text='Poly Haven HDRI name, e.g. "kloofendal_48d_partly_cloudy".',
    )

    # Ambient audio
    ambient_audio = models.FileField(
        upload_to='aether/audio/', blank=True, default='',
        help_text='Uploaded ambient loop (MP3/OGG). Loops automatically.',
    )
    ambient_audio_url = models.URLField(
        blank=True, default='',
        help_text='Stream URL (Icecast, internet radio, direct MP3 link).',
    )
    ambient_volume = models.FloatField(
        default=0.4, help_text='Ambient audio volume (0.0–1.0).',
    )
    soundscape = models.CharField(
        max_length=30, blank=True, default='',
        help_text='Procedural soundscape name (forest, cafe, city-street, '
                  'rainy, winter, beach, night, space-station). '
                  'Used when no audio file/URL is set.',
    )

    # Physics / interaction
    gravity = models.FloatField(default=-9.81)
    allow_flight = models.BooleanField(default=False)
    spawn_x = models.FloatField(default=0.0)
    spawn_y = models.FloatField(default=1.6)
    spawn_z = models.FloatField(default=0.0)

    # Publishing
    published = models.BooleanField(
        default=False,
        help_text='Unpublished worlds are only visible to staff.',
    )
    featured = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-featured', '-updated_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug and self.title:
            base = slugify(self.title)[:200] or 'world'
            candidate = base
            n = 2
            while World.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def audio_src(self):
        """Return the best audio source URL, or empty string."""
        if self.ambient_audio:
            return self.ambient_audio.url
        return self.ambient_audio_url or ''


class WorldPreset(models.Model):
    """Reusable environment template — one-click world types."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.CharField(max_length=300, blank=True)

    # Environment snapshot
    skybox = models.CharField(max_length=16, choices=SKYBOX_CHOICES, default='hdri')
    hdri_asset = models.CharField(max_length=120, blank=True, default='')
    sky_color = models.CharField(max_length=7, default='#87CEEB')
    ground_color = models.CharField(max_length=7, default='#3d5c3a')
    fog_color = models.CharField(max_length=7, default='#c8d8e4')
    fog_near = models.FloatField(default=50.0)
    fog_far = models.FloatField(default=200.0)
    ambient_light = models.FloatField(default=0.4)

    # Audio
    ambient_audio_url = models.URLField(
        blank=True, default='',
        help_text='Default ambient sound URL for this preset.',
    )
    ambient_volume = models.FloatField(default=0.4)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Asset(models.Model):
    """A reusable asset: 3D model, texture, audio clip, or HDRI."""

    world = models.ForeignKey(
        World, on_delete=models.CASCADE, related_name='assets',
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, blank=True)
    asset_type = models.CharField(
        max_length=16, choices=ASSET_TYPE_CHOICES, default='model',
    )
    file = models.FileField(upload_to='aether/assets/')
    thumbnail = models.ImageField(
        upload_to='aether/thumbnails/', blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['world', 'slug'],
                name='aether_unique_asset_slug_per_world',
            ),
        ]

    def __str__(self):
        return f'{self.world.title} / {self.name}'

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:200] or 'asset'
            candidate = base
            n = 2
            while Asset.objects.filter(
                world=self.world_id, slug=candidate,
            ).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)


class Entity(models.Model):
    """A placed instance of an asset (or a primitive) in a world."""

    world = models.ForeignKey(
        World, on_delete=models.CASCADE, related_name='entities',
    )
    name = models.CharField(max_length=200, blank=True)
    asset = models.ForeignKey(
        Asset, on_delete=models.SET_NULL, null=True, blank=True,
        help_text='Leave blank for primitive geometry (box, sphere, etc.).',
    )

    # Primitive geometry (used when asset is null)
    primitive = models.CharField(
        max_length=16, blank=True, default='',
        help_text='box, sphere, cylinder, cone, plane, torus, ring',
    )
    primitive_color = models.CharField(max_length=7, default='#808080')

    # Transform
    pos_x = models.FloatField(default=0.0)
    pos_y = models.FloatField(default=0.0)
    pos_z = models.FloatField(default=-5.0)
    rot_x = models.FloatField(default=0.0, help_text='Degrees')
    rot_y = models.FloatField(default=0.0)
    rot_z = models.FloatField(default=0.0)
    scale_x = models.FloatField(default=1.0)
    scale_y = models.FloatField(default=1.0)
    scale_z = models.FloatField(default=1.0)

    # Behavior
    behavior = models.CharField(
        max_length=16, choices=BEHAVIOR_CHOICES, default='static',
    )
    behavior_speed = models.FloatField(
        default=1.0, help_text='Speed multiplier for animations.',
    )

    # Rendering
    cast_shadow = models.BooleanField(default=True)
    receive_shadow = models.BooleanField(default=True)
    visible = models.BooleanField(default=True)

    # Avatar face — when set, the humanoid builder hides the procedural
    # 3D face features and shows this Face Forge genome on a billboard
    # plane attached to the head. Null = generate one deterministically
    # from the entity id at render time.
    face = models.ForeignKey(
        'SavedFace', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='entities',
        help_text='Face Forge avatar to display on this entity\'s head.',
    )

    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'pk']
        verbose_name_plural = 'entities'

    def __str__(self):
        label = self.name or self.primitive or 'entity'
        return f'{self.world.title} / {label}'


class Portal(models.Model):
    """A doorway between two worlds."""

    from_world = models.ForeignKey(
        World, on_delete=models.CASCADE, related_name='portals_out',
    )
    to_world = models.ForeignKey(
        World, on_delete=models.CASCADE, related_name='portals_in',
    )
    label = models.CharField(max_length=100, blank=True)

    # Position of the portal frame in the source world
    pos_x = models.FloatField(default=0.0)
    pos_y = models.FloatField(default=0.0)
    pos_z = models.FloatField(default=-10.0)
    width = models.FloatField(default=2.0)
    height = models.FloatField(default=3.0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['from_world', 'to_world']

    def __str__(self):
        return f'{self.from_world.title} -> {self.to_world.title}'


# -----------------------------------------------------------------------
# Entity scripting — Horizon Worlds-inspired component pattern
# -----------------------------------------------------------------------

class Script(models.Model):
    """A reusable JavaScript behavior script.

    Scripts are library items — write once, attach to many entities.
    The JS runs client-side in the three.js animation loop. It
    receives a context object with:

        ctx.entity      — the three.js Object3D
        ctx.deltaTime   — seconds since last frame
        ctx.elapsed     — total seconds since world load
        ctx.state       — persistent state object (survives frames)
        ctx.camera      — the player camera
        ctx.scene       — the three.js scene
        ctx.events      — { emit(name, data), on(name, callback) }
        ctx.nearby      — entities within interaction range
        ctx.props       — user-defined properties from EntityScript

    Example (NPC wander):

        if (!ctx.state.target) {
            ctx.state.target = {
                x: (Math.random() - 0.5) * 20,
                z: (Math.random() - 0.5) * 20,
            };
            ctx.state.speed = 1.5;
        }
        const dx = ctx.state.target.x - ctx.entity.position.x;
        const dz = ctx.state.target.z - ctx.entity.position.z;
        const dist = Math.sqrt(dx*dx + dz*dz);
        if (dist < 0.5) {
            ctx.state.target = {
                x: (Math.random() - 0.5) * 20,
                z: (Math.random() - 0.5) * 20,
            };
        } else {
            const step = ctx.state.speed * ctx.deltaTime;
            ctx.entity.position.x += (dx / dist) * step;
            ctx.entity.position.z += (dz / dist) * step;
            ctx.entity.rotation.y = Math.atan2(dx, dz);
        }
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)
    code = models.TextField(
        help_text='JavaScript executed in the animation loop. '
                  'Receives `ctx` object with entity, deltaTime, '
                  'elapsed, state, camera, scene, events, nearby, props.',
    )
    event = models.CharField(
        max_length=16, choices=SCRIPT_EVENT_CHOICES, default='update',
        help_text='When this script fires.',
    )
    is_builtin = models.BooleanField(
        default=False,
        help_text='Built-in scripts shipped with Aether.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:200] or 'script'
            candidate = base
            n = 2
            while Script.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)


class EntityScript(models.Model):
    """Attaches a Script to an Entity with per-instance properties.

    An entity can have multiple scripts (e.g. a wander script AND
    an interaction script). Each attachment can override properties
    (JSON dict) that the script reads via ctx.props.
    """

    entity = models.ForeignKey(
        Entity, on_delete=models.CASCADE, related_name='scripts',
    )
    script = models.ForeignKey(
        Script, on_delete=models.CASCADE, related_name='attachments',
    )
    props = models.JSONField(
        default=dict, blank=True,
        help_text='JSON properties passed to the script as ctx.props. '
                  'E.g. {"speed": 2, "range": 10, "greeting": "Hello!"}',
    )
    enabled = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'pk']

    def __str__(self):
        return f'{self.entity} <- {self.script.name}'


# -----------------------------------------------------------------------
# Object Library — global catalog for 1M+ importable 3D objects
# -----------------------------------------------------------------------

class ObjectCategory(models.Model):
    """Hierarchical category for library objects.

    E.g. Furniture > Seating > Chair, or Nature > Plants > Tree.
    """

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True)
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True,
        related_name='children',
    )

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'object categories'

    def __str__(self):
        if self.parent:
            return f'{self.parent.name} > {self.name}'
        return self.name


class LibraryObject(models.Model):
    """A cataloged 3D object from an external repository or local upload.

    This is the global object library — not tied to any specific world.
    When a user wants to place a "chair" in their world, they browse
    the library, pick one, and an Entity + Asset are created.

    Designed to scale to 1M+ entries via:
      - Indexed source_uid for dedup on import
      - Category FK for hierarchical browsing
      - Tags for search
      - Lazy download: file may be NULL until first use
    """

    name = models.CharField(max_length=300, db_index=True)
    slug = models.SlugField(max_length=320, unique=True, blank=True)
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        ObjectCategory, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='library_objects',
    )
    tags = models.CharField(
        max_length=500, blank=True, db_index=True,
        help_text='Comma-separated tags for search.',
    )

    # Source tracking
    source = models.CharField(
        max_length=16, choices=OBJECT_SOURCE_CHOICES, default='local',
    )
    source_uid = models.CharField(
        max_length=200, blank=True, db_index=True,
        help_text='UID from the source platform (e.g. Sketchfab model UID).',
    )
    source_url = models.URLField(max_length=500, blank=True)
    license = models.CharField(
        max_length=16, choices=LICENSE_CHOICES, default='unknown',
    )
    author = models.CharField(max_length=200, blank=True)

    # Files — may be NULL for not-yet-downloaded entries
    file = models.FileField(
        upload_to='aether/library/', blank=True,
        help_text='Local GLTF/GLB file. Downloaded on first use.',
    )
    thumbnail = models.URLField(
        max_length=500, blank=True,
        help_text='Thumbnail URL (remote or local).',
    )
    file_size = models.IntegerField(
        default=0, help_text='File size in bytes.',
    )
    poly_count = models.IntegerField(
        default=0, help_text='Approximate polygon count.',
    )

    # Metadata
    downloaded = models.BooleanField(default=False)
    featured = models.BooleanField(default=False)
    use_count = models.IntegerField(
        default=0, help_text='How many times placed in worlds.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-use_count', 'name']
        indexes = [
            models.Index(fields=['source', 'source_uid'],
                         name='aether_lib_source_uid_idx'),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:300] or 'object'
            candidate = base
            n = 2
            while LibraryObject.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    @property
    def tag_list(self):
        return [t.strip() for t in self.tags.split(',') if t.strip()]


# -----------------------------------------------------------------------
# Face Forge — procedurally bred kawaii faces for Aether avatars
# -----------------------------------------------------------------------

class SavedFace(models.Model):
    """A face genome saved from the Face Forge.

    The genome is the complete recipe for reconstructing the face:
    trait values (eye shape, nose width, lip fullness, scar position,
    tattoo, hat, jewelry, wrinkle count, etc.), palette (skin tone,
    hair color, iris color), and an L-system animation program
    (axiom + production rules + per-symbol param deltas).

    Rendering is purely client-side: the face viewer reads the genome
    and composes ~20 stacked 2D layers on a canvas, parallax-shifted
    by layer depth to fake 3D. At 60fps the animation pointer walks
    through the expanded L-system string and each symbol nudges the
    face parameters (blink, smile-curve, pupil-drift, brow-raise).

    Saved faces become candidate avatars for world entities. The
    binding lives outside this model (see Entity) — SavedFace is
    just the recipe.
    """

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    genome = models.JSONField(
        help_text='Trait dict + palette + L-system rules. Fully '
                  'reconstructs the face; no image stored.',
    )
    lineage = models.IntegerField(
        default=0,
        help_text='How many breeding generations deep this face is.',
    )
    use_count = models.IntegerField(
        default=0, help_text='How many entities use this face as an avatar.',
    )
    favorite = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-favorite', '-created_at']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            base = slugify(self.name)[:120] or 'face'
            candidate = base
            n = 2
            while SavedFace.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)
