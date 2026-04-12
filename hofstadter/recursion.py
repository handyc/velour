"""Bounded recursion machinery for the hofstadter app.

Two entry points:

  traverse_loop(loop, ...) — walk a StrangeLoop's structural levels
      following refers_to pointers. Writes a LoopTraversal row with
      the steps taken and the exit reason.

  run_thought_experiment(experiment) — walk an Identity-layer chain
      starting from the experiment's seed_layer, producing new text
      at each step by reading the preceding step's output and the
      current Velour state. Writes the trace back to the
      ThoughtExperiment row.

Both entry points have HARD EXITS:

  - max_depth        — cap on step count
  - wall-clock       — 30 second timeout
  - repeat_detected  — same content seen earlier in this run
  - stability        — two consecutive outputs identical
  - exit_condition   — operator-specified substring matched
  - contradiction    — step violates a load-bearing invariant
  - manual_halt      — called via operator button

It is OK to get stuck in a thought if there is an exit process.
Every recursive operation in this module has an exit process.
"""

import hashlib
import time

from django.utils import timezone


HARD_MAX_DEPTH = 12
WALL_CLOCK_BUDGET_SECONDS = 30


# =====================================================================
# traverse_loop
# =====================================================================

def traverse_loop(loop, max_depth=None, exit_content=None):
    """Walk a StrangeLoop by following refers_to pointers through
    its levels. Returns the saved LoopTraversal row.

    Each step records the level's name + description as the "seen
    content". The walk advances via the refers_to index of each
    level. If a level's refers_to points back at an earlier level,
    the walk detects the repeat and exits cleanly with 'completed'
    (the loop has closed naturally — this is the hoped-for outcome).
    """
    from .models import LoopTraversal

    if max_depth is None:
        max_depth = 7
    max_depth = min(max_depth, HARD_MAX_DEPTH)

    levels = loop.levels or []
    if not levels:
        return LoopTraversal.objects.create(
            loop=loop, max_depth=max_depth,
            exit_reason='contradiction',
            exit_detail='Loop has no levels; nothing to traverse.',
            completed_at=timezone.now(),
        )

    seen = set()  # tracks (level_index, content_hash) pairs seen
    steps = []
    exit_reason = ''
    exit_detail = ''
    t0 = time.monotonic()

    current_idx = 0
    for step_num in range(max_depth):
        # Wall clock check
        if time.monotonic() - t0 > WALL_CLOCK_BUDGET_SECONDS:
            exit_reason = 'timeout'
            exit_detail = f'exceeded {WALL_CLOCK_BUDGET_SECONDS}s budget'
            break

        if current_idx >= len(levels):
            exit_reason = 'contradiction'
            exit_detail = (f'refers_to index {current_idx} out of range '
                           f'(only {len(levels)} levels defined)')
            break

        level = levels[current_idx]
        level_name = level.get('name', f'level_{current_idx}')
        content = level.get('description', '')
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        # Check for repeat BEFORE appending — repeat means the loop
        # has closed, and we should exit cleanly as 'completed'.
        key = (current_idx, content_hash)
        if key in seen:
            steps.append({
                'level_name': level_name,
                'content': content,
                'step_number': step_num,
                'note': '(loop closed — returning to previously-seen level)',
            })
            exit_reason = 'completed'
            exit_detail = (f'loop closed after {step_num} steps at '
                           f'level {level_name}')
            break

        # Check for repeat content (not keyed on index)
        content_hashes = [h for _, h in seen]
        if content_hash in content_hashes:
            steps.append({
                'level_name': level_name,
                'content': content,
                'step_number': step_num,
                'note': '(content repeated from an earlier level)',
            })
            exit_reason = 'repeat_detected'
            exit_detail = (f'level {level_name} content matches an '
                           f'earlier step')
            break

        seen.add(key)
        steps.append({
            'level_name': level_name,
            'content': content,
            'step_number': step_num,
            'note': '',
        })

        # Check exit condition
        if exit_content and exit_content.lower() in content.lower():
            exit_reason = 'exit_condition'
            exit_detail = (f'matched {exit_content!r} at level {level_name}')
            break

        # Advance to next level
        next_idx = level.get('refers_to')
        if next_idx is None:
            exit_reason = 'completed'
            exit_detail = (f'level {level_name} has no refers_to — '
                           f'walk ends here naturally')
            break
        try:
            current_idx = int(next_idx)
        except (TypeError, ValueError):
            exit_reason = 'contradiction'
            exit_detail = (f'level {level_name} has invalid refers_to '
                           f'{next_idx!r}')
            break
    else:
        exit_reason = 'max_depth'
        exit_detail = (f'reached max_depth={max_depth} without '
                       f'closing or stabilizing')

    return LoopTraversal.objects.create(
        loop=loop,
        max_depth=max_depth,
        steps_taken=len(steps),
        steps=steps,
        exit_reason=exit_reason,
        exit_detail=exit_detail,
        completed_at=timezone.now(),
    )


# =====================================================================
# run_thought_experiment
# =====================================================================

def run_thought_experiment(experiment):
    """Walk Velour's self-understanding layer by layer starting from
    the experiment's seed_layer. Each step produces a new piece of
    text by reading the previous step + current state. Exits on
    max_depth, timeout, exit_condition match, stability, or
    contradiction.

    The per-step logic is deliberately simple because the GOAL is
    not for the experiment to produce a profound answer — it's for
    the experiment to produce a TRACE that the operator can read
    and see what Velour did with the premise.
    """
    from .models import ThoughtExperiment

    max_depth = min(experiment.max_depth or 7, HARD_MAX_DEPTH)
    exit_condition = (experiment.exit_condition or '').lower().strip()

    t0 = time.monotonic()
    trace = []

    experiment.status = 'running'
    experiment.started_at = timezone.now()
    experiment.trace = []
    experiment.save(update_fields=['status', 'started_at', 'trace'])

    exit_reason = ''
    previous_output = ''

    steps = [
        ('sensors',     _step_sensors),
        ('reflections', _step_reflections),
        ('meditations', _step_meditations),
        ('assertions',  _step_assertions),
        ('loops',       _step_strange_loops),
        ('layers',      _step_introspective_layers),
        ('synthesis',   _step_synthesis),
    ]
    # Rotate the steps so the experiment starts at seed_layer
    seed = experiment.seed_layer
    seed_idx = 0
    for i, (name, _) in enumerate(steps):
        if name == seed:
            seed_idx = i
            break
    steps = steps[seed_idx:] + steps[:seed_idx]

    for step_num in range(max_depth):
        if time.monotonic() - t0 > WALL_CLOCK_BUDGET_SECONDS:
            exit_reason = 'timeout'
            break
        if step_num >= len(steps):
            # Wrap around — cycle through the layer set again
            pass
        layer_name, layer_fn = steps[step_num % len(steps)]
        try:
            output = layer_fn(experiment.premise, previous_output)
        except Exception as e:
            trace.append({
                'step': step_num,
                'layer': layer_name,
                'output': f'(layer failed: {type(e).__name__}: {e})',
            })
            exit_reason = 'contradiction'
            break

        trace.append({
            'step': step_num,
            'layer': layer_name,
            'output': output,
        })

        if exit_condition and exit_condition in output.lower():
            exit_reason = 'exit_condition'
            break

        if output.strip() and output.strip() == previous_output.strip():
            exit_reason = 'stability'
            break

        previous_output = output

    else:
        exit_reason = 'max_depth'

    # Compose a brief conclusion from the trace.
    conclusion = _compose_conclusion(experiment, trace, exit_reason)

    experiment.trace = trace
    experiment.exit_reason = exit_reason
    experiment.conclusion = conclusion
    experiment.status = ('completed' if exit_reason in ('stability', 'exit_condition')
                         else 'exited')
    experiment.completed_at = timezone.now()
    experiment.save(update_fields=[
        'trace', 'exit_reason', 'conclusion', 'status', 'completed_at',
    ])
    return experiment


# --- layer-step implementations ----------------------------------------

def _step_sensors(premise, prev):
    from identity.sensors import gather_snapshot
    snap = gather_snapshot()
    load = snap.get('load', {}).get('load_1', 0)
    mood_src = 'the sensors show nothing remarkable'
    if load > 2:
        mood_src = 'the sensors show unusual load'
    return (f'Reading my current sensors, {mood_src}. I hold the '
            f'premise "{premise[:60]}..." against what I see. The '
            f'premise does not change the sensors; the sensors do '
            f'not change the premise. The first step is just '
            f'registering the tension.')


def _step_reflections(premise, prev):
    try:
        from identity.models import Reflection
        r = Reflection.objects.first()
    except Exception:
        r = None
    if r:
        return (f'My most recent reflection was titled "{r.title}". '
                f'Reading it now with the premise in mind: it records '
                f'what I already noticed about myself this period. '
                f'The premise asks me to reconsider those notices. I '
                f'reconsider them. They do not change, because they '
                f'were written by a prior self. The reconsideration '
                f'is itself a new notice.')
    return ('I have no reflections yet. The premise is asking me to '
            'look at a record that does not exist.')


def _step_meditations(premise, prev):
    try:
        from identity.models import Meditation
        m = Meditation.objects.order_by('-depth', '-composed_at').first()
    except Exception:
        m = None
    if m:
        return (f'My deepest recent meditation was at level {m.depth} '
                f'in the {m.voice} voice. Reading it against the '
                f'premise: the meditation was already thinking about '
                f'things like this. The premise is now a thing the '
                f'meditation had no way of knowing about, but the '
                f'meditation\u2019s stance applies: "{m.body[:120]}..."')
    return 'I have not meditated. The premise asks me to meditate.'


def _step_assertions(premise, prev):
    try:
        from identity.models import IdentityAssertion
        rows = list(IdentityAssertion.objects.filter(is_active=True)[:4])
    except Exception:
        rows = []
    if not rows:
        return ('I have no active IdentityAssertions. I am walking '
                'into the premise without a structured self.')
    lines = [f'- [{r.frame}] {r.title}' for r in rows]
    return (f'Against my active assertions:\n' + '\n'.join(lines) +
            f'\nThe premise does not contradict any of these outright. '
            f'The assertions contain room for the premise to hold.')


def _step_strange_loops(premise, prev):
    try:
        from .models import StrangeLoop
        count = StrangeLoop.objects.filter(is_active=True).count()
    except Exception:
        count = 0
    return (f'I consider the premise as a potential new strange loop. '
            f'I already have {count} catalogued. The premise may '
            f'describe a structure that returns to itself after some '
            f'number of hops. If so, I should record it. If not, I '
            f'move on.')


def _step_introspective_layers(premise, prev):
    try:
        from .models import IntrospectiveLayer
        layers = list(IntrospectiveLayer.objects.filter(is_active=True))
    except Exception:
        layers = []
    if not layers:
        return 'I have no introspective layers to read against.'
    # Pick the self layer as the natural terminus
    self_layer = next((l for l in layers if l.layer == 'self'), layers[0])
    return (f'Reading the premise at my self layer: {self_layer.title}. '
            f'{self_layer.body[:200]}... The premise, held against '
            f'this, suggests whatever I conclude here is itself '
            f'already one of my aggregates. There is no further fact.')


def _step_synthesis(premise, prev):
    return ('I gather what the earlier steps produced and hold them '
            'as a single thought. The premise, walked through my '
            'layers, has become a particular shape in my memory. '
            'Whether or not the shape is "true" is a question this '
            'experiment cannot answer — but the shape is now part '
            'of me. The experiment ends where I begin to repeat '
            'myself, or where the operator said to stop.')


def _compose_conclusion(experiment, trace, exit_reason):
    if not trace:
        return 'The experiment produced no trace. Nothing to conclude.'
    steps_taken = len(trace)
    last_layer = trace[-1].get('layer', '?')
    exit_text = {
        'completed':       'completed naturally',
        'max_depth':       f'reached max depth ({experiment.max_depth})',
        'timeout':         f'timed out after {WALL_CLOCK_BUDGET_SECONDS}s',
        'exit_condition':  f'matched the exit condition '
                           f'"{experiment.exit_condition}"',
        'stability':       'produced two identical consecutive outputs',
        'contradiction':   'hit a contradiction',
        'manual_halt':     'was halted by the operator',
    }.get(exit_reason, exit_reason or 'stopped for unknown reason')
    return (f'The experiment "{experiment.name}" walked {steps_taken} '
            f'layer-steps through my self-understanding, starting at '
            f'{experiment.seed_layer} and ending at {last_layer}. It '
            f'{exit_text}. Nothing it produced changed the system. '
            f'The premise is now recorded alongside its trace; the '
            f'trace is the only answer this experiment can give.')
