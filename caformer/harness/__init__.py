"""caformer.harness — the interface layer around the deterministic
caformer core.

The deterministic core (CA chain, cell8 rules, board128 rules, the
QRPair dispatcher) produces bytes from bytes.  The harness wraps that
core with everything that makes a "chat" feel like talking to a
collaborator: persona, system prompt, context injection, query
prefiltering, register matching, post-processing.

This subpackage is intentionally a *thin* shell.  Each module owns
one concern (composer, prefilter, verbs, context) so a deployment
on low-resource equipment can pick which to compile in.

Public entry point: ``run_turn(profile, prompt) -> HarnessReply`` —
takes a HarnessProfile + user prompt, returns the assembled reply
plus the harness metadata (category, verb chosen, context block, …).
"""
from __future__ import annotations

from .composer import HarnessReply, run_turn

__all__ = ['HarnessReply', 'run_turn']
