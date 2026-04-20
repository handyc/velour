"""Tournaments — shared-seed head-to-head scoring for Det Candidates.

A SearchRun scores each candidate against one random initial grid. That
makes the raw score sensitive to seed luck. A Tournament re-scores a
roster of candidates against N shared initial grids and aggregates.
A candidate that wins across seeds is robustly Class-4-like; one that
only won its native SearchRun was lucky with its starting condition.

The scorer is identical to det.search._score — same signals, same
weights — so aggregate scores are directly comparable to native scores
when the grid dimensions, horizon, and n_colors match. Tournaments lock
those three to keep comparisons honest.
"""

from django.utils import timezone

from automaton.detector import step_exact

from . import engine
from .search import _classify, _score


def _round_seeds(master_seed, n_seeds):
    return [f'{master_seed}-round-{i}' for i in range(n_seeds)]


def _score_on_seed(rules, seed, W, H, n_colors, horizon):
    """Run `rules` forward from a seeded grid and return the same shape
    SearchRun would have recorded. Mirrors search._step_and_measure
    without importing it (private) — re-implementing is cheaper than
    widening the module's surface and keeps the two scorers obviously
    in sync line-by-line."""
    grid = engine.seeded_random_grid(W, H, n_colors, seed)
    history = [grid]
    activity_samples = []
    period, entered_at = None, None
    for t in range(1, horizon + 1):
        nxt = step_exact(grid, W, H, rules)
        activity_samples.append(engine.activity_rate(grid, nxt))
        history.append(nxt)
        grid = nxt
        if t >= 4 and t % 2 == 0:
            p, ea = engine.detect_cycle(history, max_period=16)
            if p is not None:
                period, entered_at = p, ea
                break

    uniform = engine.is_uniform(grid)
    block_ent = engine.block_entropy_grid(grid, k=2)
    dens = engine.density_profile(grid, n_colors)
    color_diversity = sum(1 for d in dens if d > 0.01)
    tail_slice = activity_samples[-max(1, len(activity_samples) // 3):]
    activity_tail = (sum(tail_slice) / len(tail_slice)
                     if tail_slice else 0.0)

    analysis = {
        'uniform':         uniform,
        'period':          period,
        'entered_at':      entered_at,
        'ended_at_tick':   len(history) - 1,
        'activity_tail':   round(activity_tail, 4),
        'block_entropy':   round(block_ent, 4),
        'density_profile': [round(d, 4) for d in dens],
        'color_diversity': color_diversity,
    }
    score, breakdown = _score(analysis, n_colors)
    analysis['score_breakdown'] = breakdown
    est = _classify(analysis, score, n_colors)
    return {
        'seed':      seed,
        'score':     score,
        'est_class': est,
        'analysis':  analysis,
    }


def add_candidate(tournament, candidate):
    """Register a Candidate for the tournament. Idempotent: adding the
    same candidate twice returns the existing entry. Raises ValueError
    if the candidate's n_colors doesn't match (the substrate mismatch
    would make scores meaningless)."""
    from .models import TournamentEntry
    if candidate.run.n_colors != tournament.n_colors:
        raise ValueError(
            f'Candidate #{candidate.pk} has n_colors='
            f'{candidate.run.n_colors} but tournament is n_colors='
            f'{tournament.n_colors}.')
    entry, _ = TournamentEntry.objects.get_or_create(
        tournament=tournament, candidate=candidate,
    )
    return entry


def execute(tournament, progress_cb=None):
    """Score every entry against every round seed, then rank.

    Raises on internal error after marking the tournament failed. Sets
    `rank` 1-based on completion; disqualified entries get rank=None
    and sit at the bottom of the template sort.
    """
    if not tournament.master_seed:
        tournament.master_seed = timezone.now().strftime('%Y%m%d-%H%M%S')
    tournament.status = 'running'
    tournament.started_at = timezone.now()
    tournament.error = ''
    tournament.save()

    seeds = _round_seeds(tournament.master_seed, tournament.n_seeds)
    W = tournament.screen_width
    H = tournament.screen_height
    n_colors = tournament.n_colors
    horizon = tournament.horizon

    try:
        entries = list(
            tournament.entries.select_related('candidate', 'candidate__run')
        )
        for i, entry in enumerate(entries, 1):
            if entry.candidate.run.n_colors != n_colors:
                entry.disqualified = True
                entry.note = (f'n_colors mismatch '
                              f'({entry.candidate.run.n_colors} vs '
                              f'{n_colors})')
                entry.rank = None
                entry.save(update_fields=['disqualified', 'note', 'rank'])
                continue
            per_seed = [
                _score_on_seed(entry.candidate.rules_json, s,
                               W, H, n_colors, horizon)
                for s in seeds
            ]
            entry.per_seed = per_seed
            entry.aggregate_score = round(
                sum(r['score'] for r in per_seed) / len(per_seed), 3)
            entry.save(update_fields=['per_seed', 'aggregate_score'])
            if progress_cb:
                progress_cb(i, len(entries))

        alive = [e for e in entries if not e.disqualified]
        alive.sort(key=lambda e: (-e.aggregate_score, e.id))
        for i, e in enumerate(alive, start=1):
            e.rank = i
            e.save(update_fields=['rank'])

        tournament.status = 'finished'
    except Exception as exc:
        tournament.status = 'failed'
        tournament.error = str(exc)
        raise
    finally:
        tournament.finished_at = timezone.now()
        tournament.save()
