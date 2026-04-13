import json
import random

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import PlantSpecies


# ---------------------------------------------------------------------------
# List + CRUD
# ---------------------------------------------------------------------------

@login_required
def species_list(request):
    species = PlantSpecies.objects.all()
    category = request.GET.get('category')
    if category:
        species = species.filter(category=category)
    return render(request, 'lsystem/list.html', {
        'species': species,
        'categories': PlantSpecies.CATEGORY_CHOICES,
        'active_category': category,
    })


@login_required
def species_add(request):
    if request.method == 'POST':
        sp = _save_from_post(request, PlantSpecies())
        messages.success(request, f'Created "{sp.name}".')
        return redirect('lsystem:species_detail', slug=sp.slug)
    return render(request, 'lsystem/form.html', {
        'species': None,
        'categories': PlantSpecies.CATEGORY_CHOICES,
        'leaf_shapes': PlantSpecies.LEAF_SHAPE_CHOICES,
        'roof_styles': PlantSpecies.ROOF_STYLE_CHOICES,
        'arch_styles': PlantSpecies.ARCH_STYLE_CHOICES,
    })


@login_required
def species_detail(request, slug):
    sp = get_object_or_404(PlantSpecies, slug=slug)
    return render(request, 'lsystem/detail.html', {
        'species': sp,
        'props_json': json.dumps(sp.to_aether_props()),
    })


@login_required
def species_edit(request, slug):
    sp = get_object_or_404(PlantSpecies, slug=slug)
    if request.method == 'POST':
        sp = _save_from_post(request, sp)
        messages.success(request, f'Updated "{sp.name}".')
        return redirect('lsystem:species_detail', slug=sp.slug)
    return render(request, 'lsystem/form.html', {
        'species': sp,
        'categories': PlantSpecies.CATEGORY_CHOICES,
        'leaf_shapes': PlantSpecies.LEAF_SHAPE_CHOICES,
        'roof_styles': PlantSpecies.ROOF_STYLE_CHOICES,
        'arch_styles': PlantSpecies.ARCH_STYLE_CHOICES,
    })


@login_required
@require_POST
def species_delete(request, slug):
    sp = get_object_or_404(PlantSpecies, slug=slug)
    name = sp.name
    sp.delete()
    messages.success(request, f'Deleted "{name}".')
    return redirect('lsystem:species_list')


@login_required
def species_preview_json(request, slug):
    """Return props JSON for the three.js preview renderer."""
    sp = get_object_or_404(PlantSpecies, slug=slug)
    seed = int(request.GET.get('seed', 42))
    scale = float(request.GET.get('scale', 1.0))
    return JsonResponse(sp.to_aether_props(scale=scale, seed=seed))


# ---------------------------------------------------------------------------
# Duplicate / randomize
# ---------------------------------------------------------------------------

@login_required
@require_POST
def species_duplicate(request, slug):
    sp = get_object_or_404(PlantSpecies, slug=slug)
    sp.pk = None
    sp.slug = ''
    sp.name = f'{sp.name} (copy)'
    sp.save()
    messages.success(request, f'Duplicated as "{sp.name}".')
    return redirect('lsystem:species_edit', slug=sp.slug)


@login_required
@require_POST
def species_randomize(request):
    """Generate a random plant or building with plausible parameters."""
    rng = random.Random()
    mode = request.POST.get('mode', 'any')

    plant_templates = [
        ('Random Oak Variant', 'tree', 'F', [{'F': 'FF+[+F-F-F]-[-F+F+F]'}],
         (18, 30), (0.55, 0.75), (0.6, 1.0), (0.6, 0.8)),
        ('Random Pine Variant', 'tree', 'F', [{'F': 'F[+F][-F]F[+F][-F]'}],
         (20, 30), (0.45, 0.65), (0.4, 0.7), (0.55, 0.7)),
        ('Random Bush', 'bush', 'F', [{'F': 'F[+F]F[-F][F]'}],
         (25, 45), (0.5, 0.7), (0.2, 0.4), (0.5, 0.7)),
        ('Random Willow', 'tree', 'F', [{'F': 'FF[-F+F+F][+F-F]'}],
         (12, 25), (0.6, 0.8), (0.6, 0.9), (0.65, 0.8)),
        ('Random Fern', 'grass', 'X', [{'X': 'F+[[X]-X]-F[-FX]+X', 'F': 'FF'}],
         (20, 30), (0.45, 0.65), (0.1, 0.2), (0.4, 0.6)),
        ('Random Flowering', 'flower', 'F', [{'F': 'FF[-F+F][+F-F]F'}],
         (22, 35), (0.5, 0.7), (0.4, 0.6), (0.6, 0.75)),
    ]

    building_templates = [
        # (name, category, axiom, rules, angle, iterations, arch_style, roof_style)
        ('Random Cottage', 'building', 'F', [{'F': 'F[+F][-F]'}],
         90, (2, 3), 'cottage', 'gable'),
        ('Random Tower', 'tower', 'F', [{'F': 'FF[+F][-F]'}],
         90, (3, 5), 'tower', 'spire'),
        ('Random Modern', 'building', 'F', [{'F': 'F[+F]F[-F]'}],
         90, (2, 3), 'modern', 'flat'),
        ('Random Medieval', 'building', 'F', [{'F': 'FF[+F][-F][+F]'}],
         90, (2, 4), 'medieval', 'gable'),
        ('Random Gothic', 'building', 'F', [{'F': 'FFF[+F][-F]'}],
         90, (3, 5), 'gothic', 'spire'),
        ('Random Industrial', 'building', 'F', [{'F': 'FF[+F][-F]F'}],
         90, (2, 3), 'industrial', 'flat'),
        ('Random Classical', 'building', 'F', [{'F': 'F[+F][-F]F[+F][-F]'}],
         90, (2, 3), 'classical', 'hip'),
        ('Random Wall', 'wall', 'F', [{'F': 'FF[+F]'}],
         90, (2, 3), '', 'none'),
    ]

    use_building = mode == 'building' or (mode == 'any' and rng.random() > 0.6)

    if use_building:
        tmpl = rng.choice(building_templates)
        name, cat, axiom, rules, angle, iter_r, astyle, rstyle = tmpl
        wall_colors = ['#a08870', '#c8b898', '#e0d0b8', '#8a7860',
                       '#706050', '#b0a090', '#d0c0a0', '#908070']
        roof_colors = ['#6a3020', '#4a2818', '#8a5040', '#504038',
                       '#384048', '#3a4830', '#605848']
        sp = PlantSpecies(
            name=name, category=cat, axiom=axiom, rules=rules,
            angle=angle,
            iterations=rng.randint(*iter_r),
            length_factor=round(rng.uniform(0.6, 0.9), 2),
            start_length=round(rng.uniform(0.8, 1.5), 2),
            trunk_taper=1.0,
            trunk_radius=0.5,
            arch_style=astyle,
            roof_style=rstyle,
            wall_color=rng.choice(wall_colors),
            wall_color2=rng.choice(wall_colors),
            roof_color=rng.choice(roof_colors),
            window_color=rng.choice(['#ffe880', '#e0d0a0', '#80c0ff', '#ffffff']),
            door_color=rng.choice(['#5a3818', '#4a2810', '#6a4828', '#3a2010']),
            wall_width=round(rng.uniform(0.6, 1.4), 2),
            floor_height=round(rng.uniform(0.8, 1.5), 2),
            has_windows=True,
            window_density=round(rng.uniform(0.3, 0.8), 2),
            has_chimney=rng.random() > 0.6 and rstyle in ('gable', 'hip'),
            has_balcony=rng.random() > 0.7,
            has_columns=astyle == 'classical' or rng.random() > 0.85,
        )
    else:
        tmpl = rng.choice(plant_templates)
        name, cat, axiom, rules, angle_r, lf_r, sl_r, tt_r = tmpl
        trunk_colors = ['#5a4020', '#4a3018', '#6a5838', '#3a2810', '#5a3818',
                        '#8a7868', '#4a3828', '#6a4828']
        leaf_colors = ['#2a6818', '#1a4810', '#4a8830', '#3a7020', '#2a7818',
                       '#308830', '#506838']
        sp = PlantSpecies(
            name=name, category=cat, axiom=axiom, rules=rules,
            iterations=rng.randint(3, 5),
            angle=round(rng.uniform(*angle_r), 1),
            length_factor=round(rng.uniform(*lf_r), 2),
            start_length=round(rng.uniform(*sl_r), 2),
            trunk_taper=round(rng.uniform(*tt_r), 2),
            trunk_radius=round(rng.uniform(0.04, 0.10), 3),
            trunk_color=rng.choice(trunk_colors),
            leaf_color=rng.choice(leaf_colors),
            leaf_color2='#%02x%02x%02x' % tuple(rng.randint(40, 160) for _ in range(3)),
            leaf_size=round(rng.uniform(0.1, 0.5), 2),
            leaf_density=round(rng.uniform(0.3, 0.9), 2),
            leaf_shape=rng.choice(['sphere', 'cone', 'star']),
            droop=round(rng.uniform(0, 0.2), 2) if rng.random() > 0.6 else 0,
            has_flowers=cat == 'flower' or rng.random() > 0.7,
            flower_color='#%02x%02x%02x' % (
                rng.randint(180, 255), rng.randint(60, 180), rng.randint(60, 200)),
            flower_density=round(rng.uniform(0.1, 0.4), 2),
        )

    sp.save()
    messages.success(request, f'Generated "{sp.name}".')
    return redirect('lsystem:species_detail', slug=sp.slug)


# ---------------------------------------------------------------------------
# Export to Aether
# ---------------------------------------------------------------------------

@login_required
@require_POST
def export_to_aether(request, slug):
    """Register this plant species as a reusable Aether Script so it can
    be placed in any world via the random generator or manually."""
    try:
        from aether.models import Script
    except ImportError:
        messages.error(request, 'Aether app not available.')
        return redirect('lsystem:species_detail', slug=slug)

    sp = get_object_or_404(PlantSpecies, slug=slug)

    # The plant script in Aether already supports custom props that override
    # presets. We create a "preset script" that wraps the l-system-plant
    # script with baked-in props for this species.
    plant_script = Script.objects.filter(slug='l-system-plant').first()
    if not plant_script:
        messages.error(request, 'Aether l-system-plant script not found. '
                       'Run seed_metropolis first.')
        return redirect('lsystem:species_detail', slug=slug)

    # Store the species definition in a companion preset script
    script_slug = f'lsystem-preset-{sp.slug}'
    code = _build_preset_code(sp)

    obj, created = Script.objects.update_or_create(
        slug=script_slug,
        defaults={
            'name': f'L-System: {sp.name}',
            'event': 'start',
            'code': code,
            'description': f'Custom L-system plant: {sp.name}. '
                           f'Exported from L-System app.',
        },
    )

    verb = 'Exported' if created else 'Updated export of'
    messages.success(request,
        f'{verb} "{sp.name}" to Aether as script "{obj.slug}".')
    return redirect('lsystem:species_detail', slug=slug)


def _build_preset_code(sp):
    """Generate JavaScript that sets up custom preset props and then
    delegates to the standard l-system-plant script logic.

    The Aether plant script checks for a '_custom' species and reads
    all parameters from props. We just need to set the right props."""
    props = sp.to_aether_props()
    # The script simply overrides ctx.props with baked values,
    # then the standard plant script reads them.
    lines = [
        '// Auto-generated L-System preset: ' + sp.name,
        '// Exported from the L-System Dashboard app.',
        'const P = ctx.props;',
    ]
    for key, val in props.items():
        if key in ('scale', 'seed'):
            continue  # These come from entity placement
        if isinstance(val, bool):
            lines.append(f'if (P.{key} === undefined) P.{key} = {str(val).lower()};')
        elif isinstance(val, (int, float)):
            lines.append(f'if (P.{key} === undefined) P.{key} = {val};')
        elif isinstance(val, str):
            lines.append(f'if (P.{key} === undefined) P.{key} = {json.dumps(val)};')
        elif isinstance(val, list):
            lines.append(f'if (P.{key} === undefined) P.{key} = {json.dumps(val)};')
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Import from Aether
# ---------------------------------------------------------------------------

@login_required
def import_from_aether(request):
    """List Aether worlds + their plant entities for import."""
    try:
        from aether.models import EntityScript, World
    except ImportError:
        messages.error(request, 'Aether app not available.')
        return redirect('lsystem:species_list')

    worlds = World.objects.all().order_by('title')

    if request.method == 'POST':
        entity_ids = request.POST.getlist('entities')
        if not entity_ids:
            messages.warning(request, 'No plants selected.')
            return redirect('lsystem:import_from_aether')

        imported = 0
        for es in EntityScript.objects.filter(
            entity_id__in=entity_ids,
            script__slug='l-system-plant',
        ).select_related('entity'):
            props = es.props or {}
            name = es.entity.name or f'Imported Plant'
            # Check if species preset is used
            sp_name = props.get('species', 'oak')
            if sp_name != '_custom':
                name = f'{name} ({sp_name})'

            sp = PlantSpecies.from_aether_props(name, props)
            sp.save()
            imported += 1

        messages.success(request, f'Imported {imported} plant(s) from Aether.')
        return redirect('lsystem:species_list')

    # Build list of worlds with their plant entities
    plant_worlds = []
    for w in worlds:
        plant_es = EntityScript.objects.filter(
            entity__world=w,
            script__slug='l-system-plant',
        ).select_related('entity')
        if plant_es.exists():
            plant_worlds.append({
                'world': w,
                'plants': [{'entity': es.entity, 'props': es.props}
                           for es in plant_es],
            })

    return render(request, 'lsystem/import.html', {
        'plant_worlds': plant_worlds,
    })


# ---------------------------------------------------------------------------
# Seed defaults
# ---------------------------------------------------------------------------

@login_required
@require_POST
def seed_defaults(request):
    """Populate the library with the 15 built-in species from Aether."""
    DEFAULTS = [
        ('Oak', 'tree', 'F', [{'F': 'FF+[+F-F-F]-[-F+F+F]'}], 22.5, 0.65, 0.8, 0.7,
         '#5a4020', '#2a6818', '#3a7828', 0.35, 0.6, 'sphere'),
        ('Pine', 'tree', 'F', [{'F': 'F[+F][-F]F[+F][-F]'}], 25, 0.55, 0.6, 0.65,
         '#4a3018', '#1a4810', '#2a5818', 0.25, 0.8, 'cone'),
        ('Birch', 'tree', 'F', [{'F': 'F[-F][+F]F'}], 30, 0.7, 0.7, 0.75,
         '#d0c8b8', '#4a8830', '#5a9838', 0.2, 0.5, 'sphere'),
        ('Palm', 'tree', 'FFFFF', [{'F': 'F'}], 0, 1.0, 0.9, 0.92,
         '#6a5838', '#2a7818', '#3a8828', 0.5, 0, 'sphere'),
        ('Bush', 'bush', 'F', [{'F': 'F[+F]F[-F][F]'}], 35, 0.6, 0.3, 0.6,
         '#4a3818', '#2a6020', '#3a7028', 0.18, 0.9, 'sphere'),
        ('Willow', 'tree', 'F', [{'F': 'FF[-F+F+F][+F-F]'}], 18, 0.68, 0.75, 0.72,
         '#5a4828', '#6aa840', '#7ab848', 0.15, 0.7, 'sphere'),
        ('Cactus', 'succulent', 'F', [{'F': 'F[+F][-F]'}], 90, 0.5, 0.6, 0.85,
         '#2a6030', '#2a6030', '#2a6030', 0, 0, 'sphere'),
        ('Maple', 'tree', 'F', [{'F': 'FF+[+F-F]-[-F+F]'}, {'F': 'F[+F][-F]FF[-F+F]'}],
         25, 0.62, 0.75, 0.68, '#5a3818', '#c83020', '#e86030', 0.3, 0.65, 'star'),
        ('Cherry Blossom', 'flower', 'F', [{'F': 'FF[-F+F][+F-F]F'}], 28, 0.6, 0.55, 0.7,
         '#6a3028', '#ffa0b0', '#ff80a0', 0.22, 0.55, 'sphere'),
        ('Bamboo', 'grass', 'FFFFF', [{'F': 'F'}], 5, 1.0, 0.6, 0.98,
         '#4a8830', '#3a7020', '#4a8030', 0.2, 0, 'sphere'),
        ('Fern', 'grass', 'X', [{'X': 'F+[[X]-X]-F[-FX]+X', 'F': 'FF'}], 25, 0.55, 0.15, 0.5,
         '#2a4818', '#2a7818', '#3a8828', 0.08, 0.85, 'sphere'),
        ('Succulent', 'succulent', 'F', [{'F': 'F[+F][-F]'}], 137.5, 0.75, 0.1, 0.9,
         '#508848', '#70a860', '#80b870', 0.12, 0.95, 'sphere'),
        ('Cypress', 'tree', 'F', [{'F': 'F[+F]F[-F]F'}], 12, 0.6, 0.7, 0.7,
         '#4a3018', '#1a3810', '#2a4818', 0.3, 0.75, 'cone'),
        ('Baobab', 'tree', 'F', [{'F': 'FFF[+F][-F][+F-F]'}], 40, 0.45, 0.5, 0.55,
         '#8a7868', '#4a7828', '#5a8838', 0.25, 0.35, 'sphere'),
        ('Vine', 'vine', 'F', [{'F': 'F[-F][+F]F[-F]'}], 35, 0.72, 0.4, 0.5,
         '#3a5020', '#4a8030', '#5a9040', 0.12, 0.6, 'sphere'),
    ]

    created = 0
    for row in DEFAULTS:
        (name, cat, axiom, rules, angle, lf, sl, tt,
         trunk, leaf, leaf2, ls, ld, lshape) = row
        if not PlantSpecies.objects.filter(name=name).exists():
            sp = PlantSpecies(
                name=name, category=cat, axiom=axiom, rules=rules,
                angle=angle, length_factor=lf, start_length=sl, trunk_taper=tt,
                trunk_color=trunk, leaf_color=leaf, leaf_color2=leaf2,
                leaf_size=ls, leaf_density=ld, leaf_shape=lshape,
            )
            # Set special flags per species
            if name == 'Palm':
                sp.has_fronds = True
                sp.has_coconuts = True
            elif name == 'Willow':
                sp.droop = 0.15
            elif name == 'Cactus':
                sp.trunk_is_green = True
                sp.has_flowers = True
                sp.flower_color = '#e84080'
            elif name == 'Cherry Blossom':
                sp.has_flowers = True
                sp.flower_color = '#ffc0d0'
                sp.flower_density = 0.4
            elif name == 'Birch':
                sp.bark_stripes = True
            elif name == 'Bamboo':
                sp.trunk_is_green = True
                sp.has_culms = True
            elif name == 'Fern':
                sp.is_ground_cover = True
            elif name == 'Succulent':
                sp.trunk_is_green = True
                sp.is_ground_cover = True
                sp.has_rosette = True
            elif name == 'Cypress':
                sp.narrow = True
            elif name == 'Baobab':
                sp.fat_trunk = True
            elif name == 'Vine':
                sp.droop = 0.2
                sp.is_ground_cover = True
            elif name == 'Maple':
                pass
            sp.save()
            created += 1

    # ── Architecture defaults ─────────────────────────────
    ARCH_DEFAULTS = [
        # (name, cat, axiom, rules, angle, iters, lf, sl, style, roof,
        #  wall, wall2, roofC, winC, doorC, ww, fh, chimney, balcony, columns)
        ('Cottage', 'building', 'F', [{'F': 'F[+F][-F]'}],
         90, 3, 0.7, 1.0, 'cottage', 'gable',
         '#c8b898', '#b0a080', '#6a3020', '#ffe880', '#5a3818',
         1.0, 1.2, True, False, False),
        ('Tower Keep', 'tower', 'F', [{'F': 'FF[+F][-F]'}],
         90, 4, 0.8, 1.2, 'tower', 'spire',
         '#8a7860', '#706050', '#504038', '#ffe880', '#4a2810',
         0.8, 1.0, False, False, False),
        ('Modern Office', 'building', 'F', [{'F': 'F[+F]F[-F]'}],
         90, 3, 0.85, 1.4, 'modern', 'flat',
         '#b0b8c0', '#a0a8b0', '#606870', '#80c0ff', '#384048',
         1.2, 1.5, False, True, False),
        ('Gothic Cathedral', 'building', 'F', [{'F': 'FFF[+F][-F]'}],
         90, 4, 0.75, 1.5, 'gothic', 'spire',
         '#908070', '#807060', '#384838', '#ffe880', '#3a2010',
         0.9, 1.8, False, False, True),
        ('Classical Villa', 'building', 'F', [{'F': 'F[+F][-F]F[+F][-F]'}],
         90, 2, 0.65, 1.2, 'classical', 'hip',
         '#e0d0b8', '#d0c0a0', '#6a3020', '#ffe880', '#5a3818',
         1.1, 1.3, True, True, True),
        ('Medieval House', 'building', 'F', [{'F': 'FF[+F][-F][+F]'}],
         90, 3, 0.7, 1.0, 'medieval', 'gable',
         '#a08870', '#8a7860', '#504038', '#e0d0a0', '#4a2810',
         0.9, 1.1, True, False, False),
        ('Industrial Block', 'building', 'F', [{'F': 'FF[+F][-F]F'}],
         90, 2, 0.8, 1.3, 'industrial', 'flat',
         '#706860', '#605850', '#484048', '#c0d0e0', '#384048',
         1.4, 1.6, True, False, False),
        ('Castle Wall', 'wall', 'F', [{'F': 'FF[+F]'}],
         90, 3, 0.85, 1.0, '', 'none',
         '#807060', '#706050', '#504038', '#ffe880', '#4a2810',
         1.2, 0.8, False, False, False),
    ]

    for row in ARCH_DEFAULTS:
        (name, cat, axiom, rules, angle, iters, lf, sl, style, roof,
         wall, wall2, roofC, winC, doorC, ww, fh, chimney, balcony, columns) = row
        if not PlantSpecies.objects.filter(name=name).exists():
            sp = PlantSpecies(
                name=name, category=cat, axiom=axiom, rules=rules,
                angle=angle, iterations=iters, length_factor=lf,
                start_length=sl, trunk_taper=1.0, trunk_radius=0.5,
                arch_style=style, roof_style=roof,
                wall_color=wall, wall_color2=wall2, roof_color=roofC,
                window_color=winC, door_color=doorC,
                wall_width=ww, floor_height=fh,
                has_windows=True, window_density=0.6,
                has_chimney=chimney, has_balcony=balcony,
                has_columns=columns,
            )
            sp.save()
            created += 1

    messages.success(request, f'Seeded {created} default species.')
    return redirect('lsystem:species_list')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_from_post(request, sp):
    sp.name = request.POST.get('name', sp.name or 'Unnamed')
    sp.description = request.POST.get('description', '')
    sp.category = request.POST.get('category', 'tree')
    sp.axiom = request.POST.get('axiom', 'F')
    sp.iterations = int(request.POST.get('iterations', 4))
    sp.angle = float(request.POST.get('angle', 22.5))
    sp.length_factor = float(request.POST.get('length_factor', 0.65))
    sp.start_length = float(request.POST.get('start_length', 0.8))
    sp.trunk_taper = float(request.POST.get('trunk_taper', 0.7))
    sp.trunk_radius = float(request.POST.get('trunk_radius', 0.06))
    sp.tags = request.POST.get('tags', '')

    # Plant-specific
    sp.trunk_color = request.POST.get('trunk_color', '#5a4020')
    sp.trunk_is_green = 'trunk_is_green' in request.POST
    sp.bark_stripes = 'bark_stripes' in request.POST
    sp.leaf_color = request.POST.get('leaf_color', '#2a6818')
    sp.leaf_color2 = request.POST.get('leaf_color2', '#3a7828')
    sp.leaf_size = float(request.POST.get('leaf_size', 0.35))
    sp.leaf_density = float(request.POST.get('leaf_density', 0.6))
    sp.leaf_shape = request.POST.get('leaf_shape', 'sphere')
    sp.droop = float(request.POST.get('droop', 0))
    sp.narrow = 'narrow' in request.POST
    sp.fat_trunk = 'fat_trunk' in request.POST
    sp.has_flowers = 'has_flowers' in request.POST
    sp.flower_color = request.POST.get('flower_color', '#ff80a0')
    sp.flower_density = float(request.POST.get('flower_density', 0.15))
    sp.has_fronds = 'has_fronds' in request.POST
    sp.has_coconuts = 'has_coconuts' in request.POST
    sp.has_culms = 'has_culms' in request.POST
    sp.has_rosette = 'has_rosette' in request.POST
    sp.is_ground_cover = 'is_ground_cover' in request.POST

    # Architecture-specific
    sp.wall_color = request.POST.get('wall_color', '#a08870')
    sp.wall_color2 = request.POST.get('wall_color2', '#8a7860')
    sp.roof_color = request.POST.get('roof_color', '#6a3020')
    sp.window_color = request.POST.get('window_color', '#ffe880')
    sp.door_color = request.POST.get('door_color', '#5a3818')
    sp.wall_width = float(request.POST.get('wall_width', 1.0))
    sp.floor_height = float(request.POST.get('floor_height', 1.2))
    sp.has_windows = 'has_windows' in request.POST
    sp.window_density = float(request.POST.get('window_density', 0.6))
    sp.roof_style = request.POST.get('roof_style', 'gable')
    sp.has_chimney = 'has_chimney' in request.POST
    sp.has_balcony = 'has_balcony' in request.POST
    sp.has_columns = 'has_columns' in request.POST
    sp.arch_style = request.POST.get('arch_style', '')

    # Parse rules JSON
    rules_raw = request.POST.get('rules', '')
    try:
        sp.rules = json.loads(rules_raw)
    except (json.JSONDecodeError, TypeError):
        sp.rules = [{'F': rules_raw or 'FF+[+F-F-F]-[-F+F+F]'}]

    sp.save()
    return sp
