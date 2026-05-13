from django.db.models import Count
from django.shortcuts import get_object_or_404, render

from .models import Creature, Origin, Tradition, Trait, Weakness


def index(request):
    traditions = (Tradition.objects
                  .annotate(n_creatures=Count('creatures'))
                  .order_by('name'))
    n_creatures = Creature.objects.count()
    n_traits    = Trait.objects.count()
    n_origins   = Origin.objects.count()
    n_weak      = Weakness.objects.count()
    return render(request, 'vampyrik/index.html', {
        'traditions':  traditions,
        'n_creatures': n_creatures,
        'n_traits':    n_traits,
        'n_origins':   n_origins,
        'n_weaknesses': n_weak,
    })


def tradition_detail(request, slug):
    tradition = get_object_or_404(Tradition, slug=slug)
    creatures = (tradition.creatures
                          .prefetch_related('traits', 'origins', 'weaknesses')
                          .order_by('name'))
    return render(request, 'vampyrik/tradition.html', {
        'tradition': tradition,
        'creatures': creatures,
    })


def creature_detail(request, slug):
    creature = get_object_or_404(
        Creature.objects.select_related('tradition')
                        .prefetch_related('traits', 'origins',
                                          'weaknesses', 'sources'),
        slug=slug)
    # Other creatures sharing at least one trait — a "kindred" list.
    kindred = (Creature.objects
               .exclude(pk=creature.pk)
               .filter(traits__in=creature.traits.all())
               .annotate(shared=Count('traits'))
               .order_by('-shared', 'tradition__name')[:8])
    return render(request, 'vampyrik/creature.html', {
        'creature': creature,
        'kindred':  kindred,
    })


def _tag_detail(request, model_cls, slug, template, ctx_key):
    obj = get_object_or_404(model_cls, slug=slug)
    creatures = (obj.creatures
                    .select_related('tradition')
                    .order_by('tradition__name', 'name'))
    return render(request, template, {
        ctx_key:     obj,
        'creatures': creatures,
    })


def trait_detail(request, slug):
    return _tag_detail(request, Trait, slug,
                       'vampyrik/tag.html', 'tag')


def origin_detail(request, slug):
    return _tag_detail(request, Origin, slug,
                       'vampyrik/tag.html', 'tag')


def weakness_detail(request, slug):
    return _tag_detail(request, Weakness, slug,
                       'vampyrik/tag.html', 'tag')


def taxonomy(request):
    """A single big-picture page listing every trait/origin/weakness
    with its creature count, so the user can browse the tag space."""
    traits = (Trait.objects.annotate(n=Count('creatures'))
              .order_by('-n', 'kind', 'name'))
    origins = (Origin.objects.annotate(n=Count('creatures'))
               .order_by('-n', 'name'))
    weaknesses = (Weakness.objects.annotate(n=Count('creatures'))
                  .order_by('-destroys', '-n', 'name'))
    return render(request, 'vampyrik/taxonomy.html', {
        'traits':     traits,
        'origins':    origins,
        'weaknesses': weaknesses,
    })
