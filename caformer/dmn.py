"""caformer/dmn.py — Default-Mode-Network analogue.

What the system thinks about when there's no external prompt:

    ┌──────────────────────────────────────────────────────────────┐
    │ ca_state ── step ──▶ ca_state                                │
    │      │                  │                                    │
    │      └──── gene_chain ──┴──▶ thought                         │
    │                                  │                            │
    │                          tinyLLM.complete(thought)            │
    │                                  │                            │
    │                              refined ──▶ thoughts buffer     │
    │                                  │                            │
    │                          sha256(refined) ──▶ perturb ca_state │
    │                                                                │
    └──────────────────────────────────────────────────────────────┘

The loop has no external input — only the CA's tick and the LLM's
interpretation of the CA's projection.  Topics should drift, return,
mutate, and surface fragments of the rumination buffer in unexpected
combinations.

Use as a generator:

    for thought in dmn_loop(pact):
        print(thought)
        if user_interrupts():
            break

The implementation here is intentionally small.  Scale-up paths:
- swap the single backbone for a chat_gpt3_shape parallel ensemble
- run multiple parallel DMNs that occasionally exchange thoughts
- record the rumination buffer as the system's *episodic memory* and
  let the gene chain attend to it
"""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Iterator, Optional


@dataclass
class DMNStep:
    tick:        int
    ca_seed_in:  int        # the seed used for this tick
    thought:     str        # raw text from the gene chain
    refined:     str        # text after the tinyLLM completes/polishes it
    ca_seed_out: int        # the seed for the next tick (sha256 of `refined`)


def _seed_from_text(text: str) -> int:
    """Stable 32-bit seed derived from the LLM's output — feeds the
    next CA tick so each refinement perturbs the substrate."""
    h = hashlib.sha256(text.encode('utf-8', errors='replace')).digest()
    return int.from_bytes(h[:4], 'big')


def dmn_loop(pact, *,
              gene_chain_fn: Optional[Callable] = None,
              llm_fn:        Optional[Callable] = None,
              max_steps:     int = 64,
              k_ticks_per_step: int = 1,
              starting_seed: int = 0xC011AB0,
              prompt_seed_text: str = 'I find myself thinking about',
              buffer_size:   int = 16,
              ) -> Iterator[DMNStep]:
    """Yield successive `DMNStep`s from a self-feeding CA + LLM loop.

    Arguments:
      pact            — a spoeqi.Pact (its rule + seed_matrix drive the
                        substrate; the loop perturbs *which generation*
                        the chain reads from)
      gene_chain_fn   — callable(pact, generation, n_components) → list
                        of (mode, mapping) tasks.  Default: derive the
                        pact-native chain via spoeqi.textmask.
      llm_fn          — callable(prompt) → completion text.  Default:
                        identity (echo the thought) so the loop runs
                        without an LLM in the loop for testing; swap in
                        a karpathy/minGPT-gpt2 client in production.
      max_steps       — stop after this many iterations (Iterator
                        protocol; the caller can break earlier).
      k_ticks_per_step — how many CA generations advance per loop turn.
      starting_seed   — the initial seed perturbing the CA generation.
      prompt_seed_text — initial prompt fragment so the LLM has somewhere
                        to begin on tick 0.
      buffer_size     — rolling window of recent thoughts (the
                        rumination buffer).
    """
    from spoeqi import textmask as tm

    if gene_chain_fn is None:
        def gene_chain_fn(p, gen, n):
            return tm.derive_chain_gene(p, generation=gen)

    if llm_fn is None:
        def llm_fn(prompt: str) -> str:
            # Test stub: echo the prompt so the loop is exercisable
            # without loading a real backbone.
            return prompt

    buffer: Deque[str] = deque(maxlen=buffer_size)
    seed = starting_seed
    cur_text = prompt_seed_text

    for tick in range(max_steps):
        # 1. CA generation index = (seed mod 256) so the chain reads
        # from a different state each tick.  We deliberately keep this
        # window small (≤ keystream's per-call ADVANCE_CAP of 2000) so
        # the loop doesn't blow past the spoeqi state cache.
        gen = (tick * k_ticks_per_step + (seed & 0xFF)) & 0xFF

        # 2. Build a gene-chain at this generation, run it on the
        # current text → next thought.
        stages = gene_chain_fn(pact, gen, 64)
        results = tm.apply_chain(pact, stages, cur_text)
        thought = results[-1].output_text if results else cur_text

        # 3. Combine the new thought with a fragment of the rumination
        # buffer — this is what makes the loop "wander" instead of
        # collapsing to a fixed point.
        if buffer:
            tail = ' / '.join(list(buffer)[-3:])
            prompt = f'{thought} ({tail})'
        else:
            prompt = thought

        # 4. LLM polishes / completes the prompt.
        refined = llm_fn(prompt)
        buffer.append(refined)

        # 5. Hash the refined text → next CA seed.
        next_seed = _seed_from_text(refined)

        yield DMNStep(
            tick=tick,
            ca_seed_in=seed,
            thought=thought,
            refined=refined,
            ca_seed_out=next_seed,
        )

        seed = next_seed
        cur_text = refined


@dataclass
class CADMNStep:
    """One iteration of the fully-CA DMN — no external LLM, no spoeqi
    dependency.  Every field is a pure CA observable.

    The substrate is a single CA grid that ticks forward each step.
    Every N ticks the grid is fed through caformer.nano_gpt as a token
    sequence, the output's argmax is sampled, and the sampled token is
    XOR-folded back into the grid — that fold is the loop closure that
    Hofstadter / Gödel argue is where self-reference lives.
    """
    tick:        int
    grid_hash:   str        # short hash of the substrate at this tick
    sampled:     int        # token sampled from nano_gpt's output head
    novelty:     float      # 1.0 if grid_hash never seen before, else 0.0
    cycle_at:    Optional[int]   # earlier tick this hash matched, if any


def dmn_loop_caformer(*,
                       max_steps: int = 32,
                       grid_side: int = 16,
                       starting_seed: int = 0xDEFA001,
                       window_tokens: int = 4,
                       n_blocks: int = 2,
                       vocab_size: int = 64,
                       ) -> Iterator[CADMNStep]:
    """The DMN with no external LLM and no Pact dependency.

    Loop body, per tick:
      1. Tick the substrate CA forward one generation.
      2. Read `window_tokens` tokens from the substrate by hashing
         distinct row groups.
      3. Run those tokens through ``nano_gpt`` (caformer's L2
         composition) → vocab logits → argmax token.
      4. XOR-fold the sampled token's binary representation back into
         the substrate at deterministically-chosen cells.

    The only thing that distinguishes one tick's behaviour from the
    next is the *fold-back from sampled token* — without it, the loop
    would just be the substrate's own attractor cycle.  With it, the
    nano_gpt is reading its own past output and steering the substrate
    toward whatever its rules find probable.  That is the Default Mode
    Network in caformer-pure form.
    """
    import hashlib
    import numpy as np
    from .primitives import (
        hex_ca_step, lcg_bytes, random_rule_table)
    from .transformer import nano_gpt

    rule = random_rule_table(starting_seed ^ 0xD3F)
    grid = (lcg_bytes(starting_seed, grid_side * grid_side) & 3
             ).reshape(grid_side, grid_side)

    seen: dict = {}     # grid_hash → first tick we saw it (cycle detection)

    for tick in range(max_steps):
        # 1. Tick the substrate.
        grid = hex_ca_step(grid, rule)
        gh = hashlib.sha256(grid.tobytes()).hexdigest()[:16]

        cycle_at = seen.get(gh)
        novelty = 0.0 if cycle_at is not None else 1.0
        if cycle_at is None:
            seen[gh] = tick

        # 2. Read `window_tokens` tokens by hashing row-groups of the
        # substrate.  Each token is one byte (0..vocab_size-1).
        rows_per_token = max(1, grid_side // window_tokens)
        toks = []
        for t in range(window_tokens):
            chunk = grid[t * rows_per_token:(t + 1) * rows_per_token].tobytes()
            toks.append(int.from_bytes(
                hashlib.sha256(chunk).digest()[:2], 'big') % vocab_size)

        # 3. nano_gpt (the L2 recursive composition) → vocab logits → argmax.
        logits = nano_gpt(toks, vocab_size=vocab_size,
                            base_seed=starting_seed)
        sampled = int(logits.argmax())

        # 4. Fold the sampled token back into the substrate.  Two cells
        # per fold: position derived from the token, value taken from
        # the lower 2 bits of the sampled token + a derived 2-bit slice.
        # Two cells (not one) so a single sampled token actually
        # perturbs the substrate enough for the next tick to diverge.
        flat = grid.flatten()
        n = flat.size
        flat[sampled % n]               ^= sampled        & 3
        flat[(sampled * 31 + 7) % n]    ^= (sampled >> 2) & 3
        grid = (flat & 3).reshape(grid_side, grid_side)

        yield CADMNStep(
            tick=tick, grid_hash=gh, sampled=sampled,
            novelty=novelty, cycle_at=cycle_at,
        )


def dmn_observables(steps: list) -> dict:
    """Summarise a DMN run into measurable scalars.  Every value is in
    [0, 1] except `unique_hashes` (a count).  Use these for GA fitness
    or for visualising "is the loop wandering or stuck?"

    Returned keys:
      novelty_rate    — fraction of steps that produced a never-seen grid
      cycle_length    — distance to the most recent prior match (0 if none)
      unique_tokens   — fraction of distinct sampled tokens
      buffer_overlap  — Jaccard of (sampled tokens, hashes mod 256)
                        — high overlap = the LLM keeps regurgitating its
                        own outputs as substrate state
      unique_hashes   — int, count of distinct grid states seen
    """
    if not steps:
        return {'novelty_rate': 0.0, 'cycle_length': 0,
                'unique_tokens': 0.0, 'buffer_overlap': 0.0,
                'unique_hashes': 0}
    n = len(steps)
    novelties  = [s.novelty for s in steps]
    cycle_dists = [(s.tick - s.cycle_at) for s in steps if s.cycle_at is not None]
    sampled    = {s.sampled for s in steps}
    hash_ints  = {int(s.grid_hash[:2], 16) for s in steps}
    overlap = (len(sampled & hash_ints) / max(1, len(sampled | hash_ints)))
    unique_hashes = len({s.grid_hash for s in steps})
    return {
        'novelty_rate':  sum(novelties) / n,
        'cycle_length':  cycle_dists[-1] if cycle_dists else 0,
        'unique_tokens': len(sampled) / n,
        'buffer_overlap': overlap,
        'unique_hashes': unique_hashes,
    }


def make_minigpt_llm(model_name: str = 'karpathy/minGPT-gpt2',
                      max_new_tokens: int = 24,
                      ) -> Callable[[str], str]:
    """Build an `llm_fn` callable backed by a real backbone via
    spoeqi.llm_lora.load_backbone.  Heavy: first call may download
    GPT-2 weights from HuggingFace.  Greedy decoding for determinism."""
    from spoeqi.llm_lora import load_backbone
    tok, model = load_backbone(model_name)

    def _complete(prompt: str) -> str:
        import torch
        ids = tok(prompt, return_tensors='pt').input_ids
        with torch.no_grad():
            out = model.generate(
                input_ids=ids, max_new_tokens=max_new_tokens,
                do_sample=False, pad_token_id=tok.eos_token_id,
            )
        # Return ONLY the new tokens, not the prompt.
        gen = out[0, ids.shape[1]:]
        return tok.decode(gen, skip_special_tokens=True)

    return _complete
