"""hexnn — nearest-neighbour hex CA, K dialable from 4 to 256.

The user's "filtering rule" idea, built as a sibling to the existing
4 KB positional K=4 hex-CA family (s3lab / automaton / firmware /
helix.hexhunt). Nothing here imports those modules, and nothing
those modules import lives here — the two systems are deliberately
isolated so a change in one can't perturb the other.

Phase 1 (this app): the format spec, a Python + JavaScript engine,
and a single-page emulator. No hunt code, no DB persistence, no
cross-app interop. If the idea proves out we add hunting, models,
and integrations in later phases.
"""
