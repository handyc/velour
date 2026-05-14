"""loupe — Mandelbrot zoom + agent-walk library.

A ``Walk`` is one trajectory through the complex plane: a starting
viewport, a sequence of pan/zoom steps, and the rendered final
state.  Walks come from three sources distinguished by ``method``:

* ``manual`` — user dragged the viewport in the interactive
  zoomer and clicked "Save view".  A single-step gene.
* ``agent``  — a browser-side agent ran an epsilon-greedy walk
  trying to maximise the Shannon entropy of escape-time
  histograms in its window.
* ``replay`` — a re-played walk; gene reproduced from an
  ancestor.

Genes are JSON arrays of step dicts.  The first entry is the start
state; subsequent entries are the state *after* each move:

    [ {"cx": -0.5,    "cy": 0.0,   "span": 3.0,  "fitness": 1.8},
      {"cx": -0.47,   "cy": 0.04,  "span": 2.4,  "fitness": 2.1},
      ... ]

This makes replay a simple iteration through the list; diffs can
be derived as differences of consecutive entries if needed.
"""

from __future__ import annotations

from django.db import models


METHOD_CHOICES = [
    ('manual',  'Manual save'),
    ('agent',   'Agent walk'),
    ('replay',  'Replayed walk'),
]


class Walk(models.Model):
    slug = models.SlugField(unique=True, max_length=80)
    name = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)

    # The walk's deterministic gene.  Each entry must contain at least
    # cx, cy, span; optional keys: fitness, iter, dx, dy, dz.
    gene_json = models.JSONField(default=list)

    # Denormalised summary used by the list page so we don't decode
    # the gene for every card.
    n_steps        = models.PositiveIntegerField(default=0)
    fitness_final  = models.FloatField(default=0.0)
    fitness_max    = models.FloatField(default=0.0)
    fitness_mean   = models.FloatField(default=0.0)

    # Final viewport (also denormalised — gene[-1] should agree).
    end_cx    = models.FloatField(default=-0.5)
    end_cy    = models.FloatField(default=0.0)
    end_span  = models.FloatField(default=3.0)
    end_iter  = models.PositiveIntegerField(default=192)

    # Final-frame PNG, base64-encoded.  Kept small (typ. 128×128).
    thumbnail_b64    = models.TextField(blank=True)
    thumbnail_w      = models.PositiveSmallIntegerField(default=128)
    thumbnail_h      = models.PositiveSmallIntegerField(default=128)

    # Lineage / population tagging.
    method        = models.CharField(max_length=12, choices=METHOD_CHOICES,
                                      default='manual')
    population_id = models.CharField(max_length=24, blank=True,
                                      db_index=True)
    parent_slug   = models.CharField(max_length=80, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        bits = [self.slug]
        if self.name:
            bits.append(f'"{self.name}"')
        bits.append(self.method)
        return ' · '.join(bits)
