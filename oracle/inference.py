"""Pure-Python decision tree inference — no sklearn required at runtime.

Trees are stored as JSON files in `oracle/models_dir/` (gitignored
by convention). Each file is one trained "lobe". At load time the
JSON is parsed into a nested dict; at decision time a tiny recursive
walker compares feature values against node thresholds and returns
the leaf value.

File format:

  {
    "name": "rumination_template",
    "trained_at": "2026-04-12T00:00:00",
    "features": ["mood_is_restless", "tod_is_night", ...],
    "classes": ["concern", "subject", "observation"],
    "root": { ... tree node ... }
  }

Tree nodes are either internal (split):

  {
    "feature": 3,           # index into features list
    "threshold": 0.5,
    "left":  { ... },       # taken when feature value <= threshold
    "right": { ... }        # taken when feature value > threshold
  }

or leaves (predict):

  {
    "value": 1,             # index into classes list
    "samples": 47,          # training samples that reached this leaf
    "distribution": [3, 40, 4]  # counts per class at this leaf
  }

Inference is a while-loop walk; loading is json.load(). The
`samples` field on each leaf preserves confidence ("47 samples"
vs "2 samples") so the caller can weight the prediction.

Typical use:

    from oracle.inference import load_lobe, predict_class
    lobe = load_lobe('rumination_template')
    template_family = predict_class(lobe, features)
"""

import json
import os
from datetime import datetime

from django.conf import settings


# Lobes live in oracle/models_dir/ by default, or wherever the operator
# points ORACLE_MODELS_DIR in settings. Loaded lazily and cached in
# memory — once a lobe is loaded, subsequent predict() calls don't
# touch the disk.
_LOBE_CACHE = {}


def _models_dir():
    """Resolve the directory where trained lobe JSON files live.
    Falls back to `oracle/models_dir/` relative to the app. Creating
    the directory on first read so training runs don't fail on a
    missing path."""
    configured = getattr(settings, 'ORACLE_MODELS_DIR', None)
    if configured:
        path = configured
    else:
        # Walk up from this file: oracle/inference.py → oracle/ → models_dir
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, 'models_dir')
    os.makedirs(path, exist_ok=True)
    return path


def _lobe_path(name):
    return os.path.join(_models_dir(), f'{name}.tree.json')


def load_lobe(name, force_reload=False):
    """Load a trained lobe from disk. Cached in memory until force_reload
    is set. Returns None if the lobe file doesn't exist — callers must
    handle that (typically by falling back to heuristic behavior)."""
    if not force_reload and name in _LOBE_CACHE:
        return _LOBE_CACHE[name]
    path = _lobe_path(name)
    if not os.path.exists(path):
        _LOBE_CACHE[name] = None
        return None
    try:
        with open(path) as f:
            lobe = json.load(f)
    except (OSError, json.JSONDecodeError):
        _LOBE_CACHE[name] = None
        return None
    _LOBE_CACHE[name] = lobe
    return lobe


def save_lobe(name, lobe):
    """Write a lobe to disk. Invalidates the in-memory cache so the
    next load_lobe() call re-reads from file."""
    path = _lobe_path(name)
    with open(path, 'w') as f:
        json.dump(lobe, f, indent=2, sort_keys=True)
    _LOBE_CACHE.pop(name, None)
    return path


def _walk(tree, features):
    """Walk a tree node (internal or leaf) against a feature dict.
    Returns the leaf node when it bottoms out."""
    while 'feature' in tree:
        idx = tree['feature']
        threshold = tree['threshold']
        value = features[idx]
        tree = tree['left'] if value <= threshold else tree['right']
    return tree


def predict_leaf(lobe, features):
    """Return the leaf dict for a given feature vector. Raw — callers
    usually want predict_class or predict_distribution instead."""
    if lobe is None:
        return None
    leaf = _walk(lobe['root'], features)
    return leaf


def predict_class(lobe, features):
    """Return the predicted class label as a string. None if the lobe
    isn't loaded or the tree is malformed."""
    leaf = predict_leaf(lobe, features)
    if not leaf or 'value' not in leaf:
        return None
    classes = lobe.get('classes', [])
    idx = leaf['value']
    if 0 <= idx < len(classes):
        return classes[idx]
    return None


def predict_distribution(lobe, features):
    """Return the class distribution at the reached leaf as a dict of
    class_name → count. Useful for confidence-weighted decisions in
    downstream callers. None if the lobe isn't loaded."""
    leaf = predict_leaf(lobe, features)
    if not leaf or 'distribution' not in leaf:
        return None
    classes = lobe.get('classes', [])
    return {
        classes[i]: c for i, c in enumerate(leaf['distribution'])
        if 0 <= i < len(classes)
    }


def build_features_from_snapshot(snapshot, mood, open_concern_count):
    """Build the feature vector for the rumination_template lobe.

    The feature list here MUST match the one used by the trainer in
    oracle/training.py. Both lists are hardcoded so the operator can
    see exactly what the classifier considers. Adding a new feature
    requires updating both lists AND retraining.

    Returns a list of floats in feature-index order.
    """
    chronos = snapshot.get('chronos', {})
    nodes = snapshot.get('nodes', {})
    calendar = snapshot.get('calendar', {})

    mood_groups = {
        'contemplative': 0,
        'curious':       1,
        'alert':         2,
        'satisfied':     3,
        'concerned':     4,
        'excited':       5,
        'restless':      6,
        'protective':    7,
        'creative':      8,
        'weary':         9,
    }
    tod_groups = {'morning': 0, 'afternoon': 1, 'evening': 2, 'night': 3}
    moon_groups = {'new': 0, 'waxing': 1, 'full': 2, 'waning': 3}

    return [
        float(mood_groups.get(mood, 0)),
        float(tod_groups.get(chronos.get('tod'), 0)),
        float(moon_groups.get(chronos.get('moon'), 0)),
        float(open_concern_count),
        float(nodes.get('total', 0)),
        float(nodes.get('silent', 0)),
        float(len(calendar.get('upcoming', []) or [])),
        float(len(calendar.get('holidays', []) or [])),
    ]


FEATURE_NAMES = [
    'mood_group',
    'tod_group',
    'moon_group',
    'open_concern_count',
    'nodes_total',
    'nodes_silent',
    'upcoming_events',
    'upcoming_holidays',
]
