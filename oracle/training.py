"""sklearn-based trainer for Oracle lobes.

Only used when (re)training. The trained lobe gets serialized to the
JSON format oracle/inference.py loads, and the sklearn dependency is
unneeded at inference time — the pure-Python walker in inference.py
handles all the hot-path work.

The trainer is deliberately thin: sklearn's DecisionTreeClassifier
does the heavy lifting, and _serialize_sklearn_tree() walks its
internal tree_ attribute to produce the JSON format. Operators who
prefer a different classifier (random forest, gradient boost) can
extend this module without touching inference — as long as the
output JSON format stays the same.
"""

from datetime import datetime


def _serialize_sklearn_tree(clf, feature_names, class_names):
    """Convert a sklearn DecisionTreeClassifier into the JSON format
    expected by oracle/inference.py."""
    tree = clf.tree_

    def node_to_dict(node_id):
        # Leaf node: left == right == -1
        if tree.children_left[node_id] == -1 and tree.children_right[node_id] == -1:
            # sklearn >=1.3 returns normalized fractions in tree_.value.
            # Earlier versions returned raw weighted counts. Detect which
            # and scale to integer counts either way.
            raw     = list(tree.value[node_id][0])
            total   = int(tree.n_node_samples[node_id])
            raw_sum = sum(raw)
            if raw_sum > 0 and raw_sum <= 1.01:
                distribution = [int(round(v * total)) for v in raw]
            else:
                distribution = [int(v) for v in raw]
            predicted_class = max(range(len(raw)), key=raw.__getitem__)
            return {
                'value':    predicted_class,
                'samples':  total,
                'distribution': distribution,
            }
        # Internal node: split
        return {
            'feature':   int(tree.feature[node_id]),
            'threshold': float(tree.threshold[node_id]),
            'left':      node_to_dict(int(tree.children_left[node_id])),
            'right':     node_to_dict(int(tree.children_right[node_id])),
        }

    return {
        'trained_at': datetime.now().isoformat(),
        'features':   list(feature_names),
        'classes':    list(class_names),
        'root':       node_to_dict(0),
    }


def train_lobe(name, X, y, feature_names, class_names, max_depth=8):
    """Train a DecisionTreeClassifier on (X, y) and return the JSON
    serialized tree. Raises ImportError if sklearn isn't installed
    — the expectation is that sklearn only needs to be present when
    re-training, not at runtime."""
    from sklearn.tree import DecisionTreeClassifier

    clf = DecisionTreeClassifier(max_depth=max_depth, random_state=42)
    clf.fit(X, y)
    lobe = _serialize_sklearn_tree(clf, feature_names, class_names)
    lobe['name'] = name
    return lobe
