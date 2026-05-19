"""caformer/qr_trainer — long-running Q→R trainer.

Reaches multi-byte exact-match on a (prompt, expected) pair by
combining strategies that the short in-page autotrain doesn't have
budget for:

  * **Multi-seed restarts.**  When a lineage plateaus for too many
    generations, start a fresh random seed and let it compete.  Keep
    whichever lineage has the highest fitness *across all restarts*.

  * **GA → polish alternation.**  The GA explores; polish (strictly
    monotone coordinate descent on individual LUT entries) exploits
    every local improvement the GA missed.  Each phase is short so
    we can interleave.

  * **Argmax bonus + autoregressive fitness.**  Bytes get a discrete
    bonus when their argmax matches, and contexts use the model's
    own outputs (matches what inference does).  The combination is
    what makes multi-byte exact match learnable in the first place.

  * **Frequent checkpoints.**  Every improvement updates the
    QRPair row in place so the user can chat with the best-so-far
    weights at any time, without waiting for the trainer to finish.

The loop runs for a wall-clock budget (default 1 hour) or until the
model produces ``expected`` byte-for-byte under temperature-0
argmax sampling — whichever comes first.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Dict, Optional

import numpy as np

from .ga import (FULL_STACK_NAMES, GAConfig, _evolve, make_qr_fitness,
                  polish_genome)
from .primitives import random_rule_table, compute_fire_mask
from .transformer import ca_forward_qkv


def _embed_context_for_fire_mask(ctx_bytes, side: int = 8) -> np.ndarray:
    """Reproduce the embedding shape ca_forward_qkv uses for its
    output head: pack ctx bytes into a side×side K=4 board, 4 base-4
    digits per byte, top-left layout.  This board is then used to
    compute which LUT entries the output rule queries — i.e. the
    fire mask for GA mutation."""
    n_cells = side * side
    cap_bytes = n_cells // 4
    raw = bytes(ctx_bytes)[:cap_bytes]
    out = np.zeros(n_cells, dtype=np.uint8)
    for i, b in enumerate(raw):
        out[i * 4 + 0] = (b >> 6) & 3
        out[i * 4 + 1] = (b >> 4) & 3
        out[i * 4 + 2] = (b >> 2) & 3
        out[i * 4 + 3] =  b       & 3
    return out.reshape(side, side)


# ── Defaults tuned for the "hi → hello" class of target ──────────────
DEFAULT_POP                = 24
DEFAULT_GENS_PER_BURST     = 24
DEFAULT_MUTATION_RATE      = 0.012
DEFAULT_POLISH_TRIALS      = 150
DEFAULT_ARGMAX_BONUS       = 4.0
DEFAULT_STALL_PATIENCE     = 3      # consecutive non-improving bursts → restart


@dataclass
class TrainConfig:
    pop_size:            int   = DEFAULT_POP
    gens_per_burst:      int   = DEFAULT_GENS_PER_BURST
    mutation_rate:       float = DEFAULT_MUTATION_RATE
    polish_trials:       int   = DEFAULT_POLISH_TRIALS
    argmax_bonus:        float = DEFAULT_ARGMAX_BONUS
    stall_patience:      int   = DEFAULT_STALL_PATIENCE
    max_seconds:         float = 3600.0
    base_seed:           int   = 0xCAFE_BABE
    autoregressive:      bool  = True


def genome_to_blob(genome: Dict[str, np.ndarray]) -> bytes:
    parts = []
    for n in FULL_STACK_NAMES:
        arr = genome[n].astype(np.uint8) & 3
        if arr.size != 16_384:
            raise ValueError(f'rule {n!r}: expected 16,384 bytes, got {arr.size}')
        parts.append(arr.tobytes())
    return b''.join(parts)


def sample_argmax(genome: Dict[str, np.ndarray],
                    prompt: str, n_new: int, *,
                    n_blocks: int = 1) -> bytes:
    """Generate `n_new` bytes by temperature-0 argmax — the inference
    mode the trainer optimises for."""
    seq = list(prompt.encode('utf-8'))
    block_rules = [{k: genome[k] for k in
                    ('q', 'k', 'v', 'score', 'mix', 'merge', 'mlp')}] * n_blocks
    out = []
    for _ in range(n_new):
        logits = ca_forward_qkv(
            seq, n_blocks=n_blocks,
            embed_rule=genome['embed'], block_rules=block_rules,
            norm_rule=genome['norm'], output_rule=genome['output'],
            vocab_size=256)
        nxt = int(np.argmax(logits))
        out.append(nxt)
        seq.append(nxt)
    return bytes(out)


def random_genome(seed: int) -> Dict[str, np.ndarray]:
    return {n: random_rule_table(seed ^ (0x100 * (i + 1)))
            for i, n in enumerate(FULL_STACK_NAMES)}


# ── Per-position output rules trainer ────────────────────────────────
#
# Architecture: random fixed base rules (embed/q/k/v/score/mix/merge/
# mlp/norm) + N evolved output rules, one per output byte position.
# Phase i: teacher-force prefix expected[:i], evolve out_rule[i] in
# isolation so argmax(forward(prompt + expected[:i])) == expected[i].
#
# Per-phase search: 16,384 bytes (one rule) against a single-byte
# target — the regime where the GA reliably reaches EXACT match in
# seconds.  Autoregressive sampling at inference uses out_rule[i] at
# position i; because each rule's training prefix == its inference
# prefix (assuming prior positions hit their argmax), the sampled
# sequence equals ``expected`` byte-for-byte.


@dataclass
class PositionalTrainConfig:
    pop_size:       int   = 24
    gens_per_phase: int   = 40
    polish_trials:  int   = 200
    mutation_rate:  float = 0.012
    argmax_bonus:   float = 5.0
    max_seconds:    float = 3600.0
    base_seed:      int   = 0xBA5E_C0DE
    out_seed:       int   = 0xCAFE_F00D


def train_pair_positional(pair_id: int, *,
                            cfg: Optional[PositionalTrainConfig] = None,
                            on_event: Optional[Callable] = None) -> dict:
    """Phased per-position trainer.  Splits the multi-byte target into
    N single-byte problems, each solved by evolving one 16,384-byte
    output rule with the base 9 rules frozen."""
    import time
    from .models import QRPair
    cfg = cfg or PositionalTrainConfig()
    fire = on_event or (lambda *_a, **_kw: None)
    t_start = time.time()

    pair = QRPair.objects.get(pk=pair_id)
    prompt_bytes = list(pair.prompt.encode('utf-8'))
    target_bytes = list(pair.expected.encode('utf-8'))
    n_pos = len(target_bytes)
    n_blocks = pair.n_blocks

    # Fixed base genome — random but reproducible.  These never change.
    base = {n: random_rule_table(cfg.base_seed ^ (0x100 * (i + 1)))
            for i, n in enumerate(FULL_STACK_NAMES)}
    block_rules_template = [{k: base[k] for k in
                                ('q', 'k', 'v', 'score', 'mix', 'merge', 'mlp')}
                              ] * n_blocks

    fire('positional_start', {
        'pair_id': pair_id, 'prompt': pair.prompt,
        'expected': pair.expected, 'n_positions': n_pos,
        'n_blocks': n_blocks, 'budget_s': cfg.max_seconds,
    })

    out_rules: list = []
    locked = []                # accumulated bytes the model produced at argmax
    for pos in range(n_pos):
        if time.time() - t_start >= cfg.max_seconds:
            fire('positional_done', {
                'reason': 'budget',
                'completed_positions': pos, 'n_positions': n_pos,
            })
            break

        tb = target_bytes[pos]
        # Teacher-force the prefix: every byte 0..pos-1 is expected[i],
        # not the model's earlier argmax.  Because each prior output
        # rule has reached argmax == expected[i], inference will
        # produce the same context.
        ctx = list(prompt_bytes) + target_bytes[:pos]

        def _f(g: Genome) -> float:
            logits = ca_forward_qkv(
                ctx, n_blocks=n_blocks,
                embed_rule=base['embed'],
                block_rules=block_rules_template,
                norm_rule=base['norm'],
                output_rule=g['output'], vocab_size=256)
            shifted = logits - float(logits.max())
            exp = np.exp(shifted)
            denom = float(exp.sum())
            p_true = float(exp[tb] / denom) if denom > 0 else 1e-30
            lp = float(np.log(max(p_true, 1e-30)))
            bonus = cfg.argmax_bonus if int(np.argmax(logits)) == tb else 0.0
            return lp + bonus

        template = {'output': random_rule_table(
            cfg.out_seed ^ (pos * 7919))}
        # Fire-mask: which 16,384 LUT entries actually fire when this
        # template runs on this position's context.  The base genome
        # is frozen during per-position training, so the mask is
        # stable across the GA — compute once before the phase, reuse
        # for every mutation + polish step.
        # We embed the context into an 8×8 K=4 board (matches the
        # embed used inside ca_forward_qkv) so the mask covers the
        # entries the output rule will actually query.
        sample_board = _embed_context_for_fire_mask(ctx)
        fmask = compute_fire_mask(template['output'], sample_board,
                                     n_ticks=1)
        ga_cfg = GAConfig(
            pop_size=cfg.pop_size, generations=cfg.gens_per_phase,
            tournament_k=3, elite_n=2,
            mutation_rate=cfg.mutation_rate,
            seed=cfg.out_seed + pos * 4099,
            parallel_workers=1,
            fire_mask=fmask)
        phase_t = time.time()
        fire('phase_begin', {
            'pair_id': pair_id, 'pos': pos, 'target_byte': tb,
            'target_char': chr(tb) if 32 <= tb < 127 else f'\\x{tb:02x}',
            'elapsed_s': time.time() - t_start,
        })
        r = _evolve(template, _f, ga_cfg)
        # Polish: strictly monotone coordinate descent on the single
        # rule.  Often flips the argmax that GA almost reached.
        polished, fit2, n_imp = polish_genome(
            r.best_genome, _f, trials=cfg.polish_trials,
            seed=cfg.out_seed ^ 0xCAFE ^ (pos * 31),
            fire_mask=fmask)
        out_rule = polished['output']
        out_rules.append(out_rule)

        # Verify this position now hits argmax:
        logits = ca_forward_qkv(
            ctx, n_blocks=n_blocks, embed_rule=base['embed'],
            block_rules=block_rules_template, norm_rule=base['norm'],
            output_rule=out_rule, vocab_size=256)
        argmax = int(np.argmax(logits))
        match = (argmax == tb)
        locked.append(argmax)

        # Persist progress to the DB after every phase so the UI can
        # show partial results live + the deploy button works mid-run.
        _persist_positional(pair, base, out_rules, prompt_bytes,
                              target_bytes, t_start, phase='phase',
                              extra={'positions_done': len(out_rules)})

        fire('phase_end', {
            'pair_id': pair_id, 'pos': pos,
            'target_byte': tb,
            'argmax': argmax,
            'argmax_char': chr(argmax) if 32 <= argmax < 127 else f'\\x{argmax:02x}',
            'match': match, 'fitness': float(fit2),
            'phase_s': time.time() - phase_t,
            'elapsed_s': time.time() - t_start,
        })

        if not match:
            fire('phase_failed', {
                'pair_id': pair_id, 'pos': pos,
                'target_byte': tb, 'argmax': argmax,
                'fitness': float(fit2),
                'note': 'phase did not converge on target byte; '
                        'subsequent phases may still proceed but the '
                        'autoregressive sample will diverge from here.',
            })

    # Final autoregressive verification.
    sampled = sample_positional(base, out_rules, prompt_bytes,
                                  n_blocks=n_blocks)
    exact = (sampled == bytes(target_bytes))
    _persist_positional(pair, base, out_rules, prompt_bytes,
                          target_bytes, t_start, phase='done',
                          extra={'final': True})
    fire('positional_done', {
        'pair_id': pair_id, 'reason': 'completed',
        'exact': exact,
        'sampled': sampled.decode('utf-8', errors='replace'),
        'target':  pair.expected,
        'elapsed_s': time.time() - t_start,
    })
    return {
        'reason': 'completed', 'exact': exact,
        'completed_positions': len(out_rules), 'n_positions': n_pos,
        'sampled': sampled.decode('utf-8', errors='replace'),
        'elapsed_s': time.time() - t_start,
    }


def sample_positional(base: Dict[str, np.ndarray],
                        out_rules: list,
                        prompt_bytes: list, *,
                        n_blocks: int = 1) -> bytes:
    """Generate len(out_rules) bytes via temperature-0 argmax using
    per-position output rules."""
    seq = list(prompt_bytes)
    block_rules = [{k: base[k] for k in
                    ('q', 'k', 'v', 'score', 'mix', 'merge', 'mlp')}] * n_blocks
    out = []
    for i in range(len(out_rules)):
        logits = ca_forward_qkv(
            seq, n_blocks=n_blocks, embed_rule=base['embed'],
            block_rules=block_rules, norm_rule=base['norm'],
            output_rule=out_rules[i], vocab_size=256)
        nxt = int(np.argmax(logits))
        out.append(nxt); seq.append(nxt)
    return bytes(out)


def _persist_positional(pair, base, out_rules, prompt_bytes,
                          target_bytes, t_start, *, phase, extra=None):
    """Save the base genome + per-position output rules + autoregressive
    sample to the QRPair row.  Called after each phase so the UI can
    show partial progress."""
    import time
    # Pad out_rules to full length with random fillers so the blob
    # always has n_target_bytes slots — keeps inference robust if a
    # mid-training crash leaves only some rules trained.
    blob_parts = []
    n_target = len(target_bytes)
    for i in range(n_target):
        if i < len(out_rules):
            arr = out_rules[i].astype(np.uint8) & 3
        else:
            arr = random_rule_table(0xDEAD_BEEF ^ i)
        blob_parts.append(arr.tobytes())
    pair.positional_output_blob = b''.join(blob_parts)
    pair.best_genome_blob = genome_to_blob(base)

    # Sample what we've got so far for the user-visible status.
    n_partial = min(len(out_rules), n_target)
    sample_n = n_partial if n_partial > 0 else 0
    if sample_n > 0:
        sampled = sample_positional(base, out_rules, prompt_bytes,
                                       n_blocks=pair.n_blocks)
    else:
        sampled = b''
    try:
        pair.best_output = sampled.decode('utf-8')
    except UnicodeDecodeError:
        pair.best_output = sampled.decode('latin-1', errors='replace')
    pair.best_exact = (sampled == bytes(target_bytes))
    # Synthetic fitness: fraction of target bytes that now argmax-match.
    matches = sum(1 for i in range(n_partial)
                    if i < len(sampled) and sampled[i] == target_bytes[i])
    pair.best_fitness = float(matches)        # 0..N integer
    pair.last_phase = phase
    pair.total_seconds = float(time.time() - t_start)
    pair.save(update_fields=['positional_output_blob', 'best_genome_blob',
                                'best_output', 'best_exact', 'best_fitness',
                                'last_phase', 'total_seconds', 'updated_at'])
    # Auto-deploy as soon as the pair hits exact match — that way the
    # per-prompt chat dispatcher can find it without manual UI clicks.
    if pair.best_exact and not pair.deployed_slug:
        try:
            from .views import _deploy_qr_pair
            _deploy_qr_pair(pair.pk)
        except Exception:
            pass


def train_pair(pair_id: int, *, cfg: Optional[TrainConfig] = None,
                 on_event: Optional[Callable[[str, dict], None]] = None
                 ) -> dict:
    """Long-running trainer for one QRPair.  Updates the row in place
    after every improvement.  Returns a summary dict at exit."""
    import time
    from .models import QRPair
    cfg = cfg or TrainConfig()
    fire = on_event or (lambda *_a, **_kw: None)
    t_start = time.time()

    pair = QRPair.objects.get(pk=pair_id)
    prompt   = pair.prompt
    expected = pair.expected
    n_blocks = pair.n_blocks
    expected_bytes = expected.encode('utf-8')
    n_target_bytes = len(expected_bytes)

    fitness = make_qr_fitness(prompt, expected, n_blocks=n_blocks,
                                argmax_bonus=cfg.argmax_bonus,
                                autoregressive=cfg.autoregressive)

    # Seed from existing best genome if present, else random.
    overall_best_g = pair.best_genome()
    if overall_best_g is None:
        overall_best_g = random_genome(cfg.base_seed)
    overall_best_f = float(fitness(overall_best_g))

    fire('start', {
        'pair_id': pair_id, 'prompt': prompt, 'expected': expected,
        'n_blocks': n_blocks, 'max_seconds': cfg.max_seconds,
        'initial_fitness': overall_best_f,
        'argmax_bonus': cfg.argmax_bonus,
    })

    def _persist(genome, fit, phase, restarts):
        out = sample_argmax(genome, prompt, n_target_bytes,
                              n_blocks=n_blocks)
        exact = (out == expected_bytes)
        pair.best_fitness = fit
        pair.best_genome_blob = genome_to_blob(genome)
        # Use latin-1 to losslessly stuff arbitrary bytes into the
        # CharField — it's a debug surface, not for re-parsing.
        try:
            pair.best_output = out.decode('utf-8')
        except UnicodeDecodeError:
            pair.best_output = out.decode('latin-1', errors='replace')
        pair.best_exact = exact
        pair.last_phase = phase
        pair.restarts = restarts
        pair.total_seconds = float(time.time() - t_start
                                       + (pair.total_seconds or 0.0))
        # Track only the time since this call started; revisits reset.
        # Actually — careful: pair.total_seconds may already include
        # past calls.  Don't double-count: hold the original baseline.
        pair.save(update_fields=['best_fitness', 'best_genome_blob',
                                    'best_output', 'best_exact',
                                    'last_phase', 'restarts',
                                    'total_seconds', 'updated_at'])
        return out, exact

    # Capture starting baseline so total_seconds isn't double-counted.
    baseline_total = float(pair.total_seconds or 0.0)

    def _commit(genome, fit, phase, restarts, evals_added):
        nonlocal overall_best_g, overall_best_f
        if fit > overall_best_f:
            overall_best_g = genome
            overall_best_f = float(fit)
            pair.n_evals = (pair.n_evals or 0) + evals_added
            out, exact = _persist(genome, fit, phase, restarts)
            # Reset total_seconds bookkeeping each commit so we don't
            # drift; baseline + elapsed since start.
            pair.total_seconds = baseline_total + (time.time() - t_start)
            pair.save(update_fields=['n_evals', 'total_seconds'])
            fire('improved', {
                'pair_id': pair_id, 'phase': phase, 'restarts': restarts,
                'fitness': float(fit),
                'output': out.decode('utf-8', errors='replace'),
                'exact': exact,
                'elapsed_s': time.time() - t_start,
            })
            return exact
        return False

    restarts = pair.restarts or 0
    stall = 0
    template = overall_best_g
    burst_idx = 0
    finished_reason = 'budget'

    while True:
        # Budget exhausted?
        if time.time() - t_start >= cfg.max_seconds:
            break

        # ── GA burst ──
        ga_cfg = GAConfig(
            pop_size=cfg.pop_size, generations=cfg.gens_per_burst,
            tournament_k=3, elite_n=2,
            mutation_rate=cfg.mutation_rate,
            seed=cfg.base_seed ^ (burst_idx * 1009)
                  ^ (restarts * 65537),
            parallel_workers=1,
        )
        fire('burst_begin', {
            'pair_id': pair_id, 'burst': burst_idx, 'restarts': restarts,
            'template_fitness': float(fitness(template)),
            'elapsed_s': time.time() - t_start,
        })
        result = _evolve(template, fitness, ga_cfg)
        evals = cfg.pop_size * (cfg.gens_per_burst + 1)
        improved_ga = _commit(result.best_genome, float(result.best_fitness),
                                phase='ga', restarts=restarts,
                                evals_added=evals)
        if pair.best_exact:
            finished_reason = 'exact_match'
            break
        # ── Polish phase ──
        if time.time() - t_start >= cfg.max_seconds:
            break
        fire('polish_begin', {
            'pair_id': pair_id, 'burst': burst_idx, 'restarts': restarts,
            'trials': cfg.polish_trials,
        })
        polished, polished_fit, n_imp = polish_genome(
            result.best_genome, fitness,
            trials=cfg.polish_trials,
            seed=cfg.base_seed ^ 0xCAFE ^ (burst_idx * 4099))
        improved_polish = _commit(polished, float(polished_fit),
                                       phase='polish', restarts=restarts,
                                       evals_added=cfg.polish_trials * 3)
        fire('polish_end', {
            'pair_id': pair_id, 'burst': burst_idx, 'n_improvements': n_imp,
            'fitness': float(polished_fit),
        })
        if pair.best_exact:
            finished_reason = 'exact_match'
            break

        # ── Stall detection + restart ──
        any_improved = improved_ga or improved_polish
        if not any_improved:
            stall += 1
        else:
            stall = 0
        if stall >= cfg.stall_patience:
            restarts += 1
            stall = 0
            # Fresh random seed — but stash overall_best_g so we don't
            # lose it; if the restart doesn't beat it, we revert.
            template = random_genome(cfg.base_seed ^ (restarts * 0xC0_FF_EE))
            fire('restart', {
                'pair_id': pair_id, 'restart_idx': restarts,
                'reason': 'stall',
                'overall_best_fitness': overall_best_f,
                'elapsed_s': time.time() - t_start,
            })
        else:
            # Continue from the best so far (either polished or the
            # previous best — overall_best_g is updated by _commit
            # when fitness improves).
            template = overall_best_g
        burst_idx += 1

    fire('done', {
        'pair_id': pair_id, 'reason': finished_reason,
        'overall_best_fitness': overall_best_f,
        'exact': pair.best_exact,
        'restarts': restarts, 'bursts': burst_idx,
        'elapsed_s': time.time() - t_start,
        'final_output': pair.best_output,
    })
    return {
        'reason': finished_reason,
        'fitness': overall_best_f,
        'exact': pair.best_exact,
        'restarts': restarts,
        'bursts': burst_idx,
        'elapsed_s': time.time() - t_start,
    }
