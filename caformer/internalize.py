"""caformer/internalize — CA-native corpus internalisation, no training.

Two non-iterative methods for getting a text corpus *into* a CAformer
without GA, without SGD, without backprop:

A. ``ngram_bake_output_rule(corpus)`` — one-pass byte counting →
   output_rule. For every position i in the corpus, encode the previous
   7 bytes as a 14-bit LUT key (each byte's bottom 2 bits = its colour)
   and bin corpus[i] into one of 4 colour buckets. Argmax over the
   buckets per key becomes the rule entry. The output_rule then biases
   the model toward the corpus's actual byte-transition statistics.

B. ``corpus_to_metapact_seed(corpus)`` — hash the corpus deterministic-
   ally into a 16,384-byte seed_state, then run
   ``spoeqi.metachain.metachain_expand`` to derive all 10 CAformer rule
   tables. The corpus IS the recipe; same bytes always produce the
   same model.

Both methods output a complete TrainedModel via the same save helper
``save_as_trained_model``, so the chat endpoint immediately sees the
new model in its dropdown.

Why "non-normal training": the corpus isn't being used to *update* the
rules through a loss-and-gradient cycle. In (A) the corpus is read once
and tallied; in (B) it's used as a deterministic key. Both produce
byte-identical results across runs given the same corpus, and both
finish in seconds even on very large inputs.
"""
from __future__ import annotations

import hashlib
from typing import Iterable, Optional, Tuple

import numpy as np


LUT_SIZE = 16384         # 4^7 — the K=4 hex CA rule-table size
RULE_SIZE = LUT_SIZE     # alias, matches spoeqi.metachain.RULE_SIZE
N_BUCKETS = 4            # K=4: each output colour is one bucket of 64 byte values
CONTEXT_BYTES = 7        # 7 bytes × 2 bits = 14 bits = LUT key


# ─── Approach A: n-gram → output_rule ────────────────────────────────

def ngram_bake_output_rule(corpus: bytes,
                              *, context_bytes: int = CONTEXT_BYTES,
                              n_buckets: int = N_BUCKETS,
                              ) -> Tuple[bytes, dict]:
    """Walk ``corpus`` byte-by-byte, accumulating a ``(LUT_SIZE,
    n_buckets)`` counter where key = last ``context_bytes`` bytes
    (each contributing its bottom 2 bits, packed little-endian) and
    bucket = corpus[i] // (256 // n_buckets).

    Returns ``(rule_bytes, stats)``. ``rule_bytes`` is exactly
    ``LUT_SIZE`` bytes (uint8 in 0..3) that drops into ``rule_output``.
    ``stats`` reports coverage so the caller can tell how much of the
    LUT was actually informed by the corpus (untouched entries fall
    back to bucket 0 — uniform on the lowest 64 bytes — which is the
    same as the random baseline for those neighbourhoods).
    """
    if context_bytes < 1 or context_bytes > 7:
        raise ValueError(
            f'context_bytes must be in [1, 7]; got {context_bytes}')
    if 256 % n_buckets != 0:
        raise ValueError(
            f'n_buckets must divide 256 evenly; got {n_buckets}')
    bucket_width = 256 // n_buckets
    key_mask = (1 << (2 * context_bytes)) - 1     # only the live bits

    counts = np.zeros((LUT_SIZE, n_buckets), dtype=np.uint32)
    arr = np.frombuffer(corpus, dtype=np.uint8)
    if arr.size <= context_bytes:
        # Too short — return an all-zero rule and a 0-coverage report.
        return bytes(LUT_SIZE), {
            'n_positions': 0, 'lut_coverage': 0.0,
            'corpus_bytes': int(arr.size),
        }

    # Pack the rolling 7-byte context into a 14-bit key. We slide the
    # 14-bit window left by 2 bits per step and OR in the new byte's
    # bottom 2 bits. This matches the K=4 colour quantisation the CA
    # pipeline uses everywhere else.
    key = 0
    for i in range(context_bytes):
        key = ((key << 2) | int(arr[i] & 3)) & key_mask

    for i in range(context_bytes, arr.size):
        next_byte = int(arr[i])
        bucket = next_byte // bucket_width
        counts[key, bucket] += 1
        key = ((key << 2) | (next_byte & 3)) & key_mask

    # Argmax → rule. Untouched entries default to bucket 0.
    rule = counts.argmax(axis=1).astype(np.uint8)
    touched = int((counts.sum(axis=1) > 0).sum())
    stats = {
        'n_positions':   int(arr.size - context_bytes),
        'lut_coverage':  touched / LUT_SIZE,
        'corpus_bytes':  int(arr.size),
        'context_bytes': context_bytes,
        'n_buckets':     n_buckets,
    }
    return bytes(rule), stats


# ─── Approach B: corpus → metachain seed → 10 rules ──────────────────

def corpus_to_metapact_seed(corpus: bytes,
                              *, salt: bytes = b'caformer.internalize',
                              ) -> bytes:
    """Deterministic hash of ``corpus`` to a 16,384-byte CA seed_state.

    Uses SHA-512 over (salt || corpus) and stretches the digest by
    repeated rehashing with a counter so the resulting bytes pass a
    cheap whiteness check (each colour ~25%, no obvious periodicity).
    The output is suitable as the ``seed_state`` argument to
    ``spoeqi.metachain.metachain_expand``.
    """
    out = bytearray()
    counter = 0
    while len(out) < RULE_SIZE:
        h = hashlib.sha512(
            salt + counter.to_bytes(8, 'big') + corpus).digest()
        out.extend(h)
        counter += 1
    # Quantise to K=4 colours by taking each byte's bottom 2 bits.
    rule = bytes(b & 3 for b in out[:RULE_SIZE])
    return rule


def corpus_to_caformer_genome(corpus: bytes,
                                *, depth: int = 10,
                                chain_ticks: int = 20,
                                ) -> dict:
    """End-to-end: corpus bytes → metapact seed → metachain → 10 rules.

    Returns a dict matching ``caformer.ga.FULL_STACK_NAMES`` keys, each
    value a (16384,) uint8 numpy array — ready to drop into
    ``ca_forward_qkv(**kwargs)`` or into a ``TrainedModel`` row.
    """
    from spoeqi.metachain import (
        metachain_expand, metachain_to_caformer_genome,
    )
    seed = corpus_to_metapact_seed(corpus)
    chain = metachain_expand(seed, depth=depth, chain_ticks=chain_ticks)
    return metachain_to_caformer_genome(chain.states)


# ─── Save helpers — both methods land in TrainedModel ────────────────

def _bytes_for_excerpt(corpus: bytes, n: int = 500) -> str:
    """ASCII-safe corpus excerpt for the TrainedModel detail page."""
    snippet = corpus[:n]
    return snippet.decode('utf-8', errors='replace')


def save_ngram_baked_model(corpus: bytes, *,
                              name: str, slug: str,
                              base_seed: int = 0xCAFE5EED,
                              notes: str = '',
                              context_bytes: int = CONTEXT_BYTES,
                              ):
    """Bake an n-gram output_rule from ``corpus`` and save a complete
    TrainedModel. Other 9 rules are deterministic random defaults
    keyed by ``base_seed`` (you can re-roll them by changing the seed).
    """
    from .models import TrainedModel
    from .ga import FULL_STACK_NAMES
    from .primitives import default_norm_rule, random_rule_table

    output_rule, stats = ngram_bake_output_rule(
        corpus, context_bytes=context_bytes)
    rules = {
        n: random_rule_table(base_seed ^ (0x100 * (i + 1)))
        for i, n in enumerate(FULL_STACK_NAMES)
    }
    rules['output'] = np.frombuffer(output_rule, dtype=np.uint8).copy()
    rules['norm']   = default_norm_rule(base_seed ^ 0x8000)

    auto_notes = (
        f'n-gram bake (caformer.internalize): {stats["n_positions"]:,} '
        f'corpus positions, {context_bytes}-byte context, '
        f'{stats["lut_coverage"]:.1%} LUT coverage.'
    )
    obj, _ = TrainedModel.objects.update_or_create(
        slug=slug,
        defaults={
            'name':        name,
            'notes':       notes or auto_notes,
            'rule_q':      bytes(rules['q']),
            'rule_k':      bytes(rules['k']),
            'rule_v':      bytes(rules['v']),
            'rule_score':  bytes(rules['score']),
            'rule_mix':    bytes(rules['mix']),
            'rule_merge':  bytes(rules['merge']),
            'rule_mlp':    bytes(rules['mlp']),
            'rule_norm':   bytes(rules['norm']),
            'rule_output': bytes(rules['output']),
            'rule_embed':  bytes(rules['embed']),
            'corpus_excerpt': _bytes_for_excerpt(corpus),
            'vocab_size':   256,
            'n_blocks':     2,
            'pop_size':     0,
            'generations':  0,
            'final_fitness': 0.0,
            'history_json': [{'method': 'ngram_bake', **stats}],
        },
    )
    return obj, stats


def save_metachain_seeded_model(corpus: bytes, *,
                                   name: str, slug: str,
                                   depth: int = 10,
                                   chain_ticks: int = 20,
                                   notes: str = '',
                                   ):
    """Hash ``corpus`` → metapact seed → 10 rule tables. All 10 rules
    come from the corpus (vs n-gram bake which only sets output_rule).
    """
    from .models import TrainedModel
    from spoeqi.metachain import (
        metachain_expand, metachain_to_caformer_genome,
    )

    seed = corpus_to_metapact_seed(corpus)
    chain = metachain_expand(seed, depth=depth, chain_ticks=chain_ticks)
    genome = metachain_to_caformer_genome(chain.states)

    auto_notes = (
        f'metachain seeded from corpus (caformer.internalize): '
        f'sha-stretched {len(corpus):,} bytes → 16,384-byte seed → '
        f'metachain depth={depth}, ticks={chain_ticks}, '
        f'chain_quality={chain.chain_quality:.3f}, '
        f'class4_depth={chain.depth_class4}/{len(chain.classes)}.'
    )
    obj, _ = TrainedModel.objects.update_or_create(
        slug=slug,
        defaults={
            'name':        name,
            'notes':       notes or auto_notes,
            'rule_q':      bytes(genome['q']),
            'rule_k':      bytes(genome['k']),
            'rule_v':      bytes(genome['v']),
            'rule_score':  bytes(genome['score']),
            'rule_mix':    bytes(genome['mix']),
            'rule_merge':  bytes(genome['merge']),
            'rule_mlp':    bytes(genome['mlp']),
            'rule_norm':   bytes(genome['norm']),
            'rule_output': bytes(genome['output']),
            'rule_embed':  bytes(genome['embed']),
            'corpus_excerpt': _bytes_for_excerpt(corpus),
            'vocab_size':   256,
            'n_blocks':     2,
            'pop_size':     0,
            'generations':  0,
            'final_fitness': 0.0,
            'history_json': [{
                'method':        'metachain_seed',
                'corpus_bytes':  int(len(corpus)),
                'depth':         int(depth),
                'chain_ticks':   int(chain_ticks),
                'chain_quality': float(chain.chain_quality),
                'class4_depth':  int(chain.depth_class4),
                'chain_classes': list(chain.classes),
            }],
        },
    )
    return obj, {
        'chain_quality': float(chain.chain_quality),
        'class4_depth':  int(chain.depth_class4),
        'chain_classes': list(chain.classes),
        'corpus_bytes':  int(len(corpus)),
    }


# ─── Default corpora baked in for one-click experiments ──────────────

# Six Shakespeare sonnets (public domain, ~3.2 KB). Enough to give the
# n-gram baker something to learn and small enough to ship in the repo.
SHAKESPEARE_SONNETS = b"""\
Sonnet 18

Shall I compare thee to a summer's day?
Thou art more lovely and more temperate:
Rough winds do shake the darling buds of May,
And summer's lease hath all too short a date:
Sometime too hot the eye of heaven shines,
And often is his gold complexion dimmed,
And every fair from fair sometime declines,
By chance, or nature's changing course untrimmed:
But thy eternal summer shall not fade,
Nor lose possession of that fair thou ow'st,
Nor shall death brag thou wander'st in his shade,
When in eternal lines to time thou grow'st,
  So long as men can breathe, or eyes can see,
  So long lives this, and this gives life to thee.

Sonnet 29

When in disgrace with fortune and men's eyes,
I all alone beweep my outcast state,
And trouble deaf heaven with my bootless cries,
And look upon myself and curse my fate,
Wishing me like to one more rich in hope,
Featured like him, like him with friends possessed,
Desiring this man's art and that man's scope,
With what I most enjoy contented least;
Yet in these thoughts myself almost despising,
Haply I think on thee, and then my state,
Like to the lark at break of day arising
From sullen earth, sings hymns at heaven's gate;
  For thy sweet love remembered such wealth brings
  That then I scorn to change my state with kings.

Sonnet 30

When to the sessions of sweet silent thought
I summon up remembrance of things past,
I sigh the lack of many a thing I sought,
And with old woes new wail my dear time's waste:
Then can I drown an eye, unused to flow,
For precious friends hid in death's dateless night,
And weep afresh love's long since cancelled woe,
And moan th'expense of many a vanished sight.
Then can I grieve at grievances foregone,
And heavily from woe to woe tell o'er
The sad account of fore-bemoaned moan,
Which I new pay as if not paid before.
  But if the while I think on thee, dear friend,
  All losses are restored, and sorrows end.

Sonnet 116

Let me not to the marriage of true minds
Admit impediments. Love is not love
Which alters when it alteration finds,
Or bends with the remover to remove.
O no! it is an ever-fixed mark
That looks on tempests and is never shaken;
It is the star to every wand'ring bark,
Whose worth's unknown, although his height be taken.
Love's not Time's fool, though rosy lips and cheeks
Within his bending sickle's compass come;
Love alters not with his brief hours and weeks,
But bears it out even to the edge of doom.
  If this be error and upon me proved,
  I never writ, nor no man ever loved.

Sonnet 130

My mistress' eyes are nothing like the sun;
Coral is far more red than her lips' red;
If snow be white, why then her breasts are dun;
If hairs be wires, black wires grow on her head.
I have seen roses damasked, red and white,
But no such roses see I in her cheeks;
And in some perfumes is there more delight
Than in the breath that from my mistress reeks.
I love to hear her speak, yet well I know
That music hath a far more pleasing sound:
I grant I never saw a goddess go;
My mistress, when she walks, treads on the ground.
  And yet, by heaven, I think my love as rare
  As any she belied with false compare.

Sonnet 73

That time of year thou mayst in me behold
When yellow leaves, or none, or few, do hang
Upon those boughs which shake against the cold,
Bare ruined choirs, where late the sweet birds sang.
In me thou see'st the twilight of such day
As after sunset fadeth in the west,
Which by and by black night doth take away,
Death's second self, that seals up all in rest.
In me thou see'st the glowing of such fire
That on the ashes of his youth doth lie,
As the death-bed whereon it must expire,
Consumed with that which it was nourished by.
  This thou perceiv'st, which makes thy love more strong,
  To love that well which thou must leave ere long.
"""
