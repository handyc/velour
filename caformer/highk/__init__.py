"""High-K cellular automata experiments.

User insight 2026-05-22: at K=2^32, a single CA cell can directly
encode a token ID (one per word, ~4.3B addressable).  The rule
table for K=2^32 with 7 inputs is (2^32)^7 ≈ 2^224 entries —
unenumerable — but we don't enumerate.  We define a SPARSE subset
of rules and pick a default for everything else.

Phase 1: derive ~1M rules from a 1024x1024 Mandelbrot rendering at
32-bit color depth (one rule per pixel), run a small CA grid, look
at qualitative dynamics."""
