"""Ouroboros — the class-4 fixed-point quine.

A small Velour app that pulls together everything we know about
quine #122 and its lineage: a 16,384-byte K=4 hex CA rule whose
chain converges to a class-4 fixed point at level 130, producing
effective infinite class-4 chain depth.

The app reads from existing ``caformer.ComponentChampion`` rows;
no new models.  Views render lineage trees, chain walks, rulesets
as 128×128 images, and per-level statistics for any saved quine.
"""
default_app_config = 'ouroboros.apps.OuroborosConfig'
