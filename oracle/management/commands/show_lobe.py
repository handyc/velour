"""Print a trained Oracle lobe as nested if/else rules.

    python manage.py show_lobe water_plant
    python manage.py show_lobe rumination_template --leaves-only

The goal is auditability: a decision tree isn't mysterious — it's just
a dense set of thresholds the operator should be able to read by hand
and judge. This command renders the JSON tree that inference.py loads
into the same structure a human would write if they'd hand-coded the
lobe.
"""

from django.core.management.base import BaseCommand, CommandError

from oracle.inference import load_lobe


class Command(BaseCommand):
    help = 'Pretty-print a trained lobe as readable if/else rules.'

    def add_arguments(self, parser):
        parser.add_argument('name')
        parser.add_argument('--leaves-only', action='store_true',
                            help='Only print the distinct leaf outcomes, '
                                 'not the branching structure.')

    def handle(self, *args, **opts):
        name = opts['name']
        lobe = load_lobe(name, force_reload=True)
        if lobe is None:
            raise CommandError(f'lobe not found: {name}')

        features = lobe.get('features', [])
        classes  = lobe.get('classes', [])
        self.stdout.write(self.style.NOTICE(f'lobe: {name}'))
        self.stdout.write(f'trained_at: {lobe.get("trained_at", "?")}')
        self.stdout.write(f'features:   {features}')
        self.stdout.write(f'classes:    {classes}')
        self.stdout.write('')

        if opts['leaves_only']:
            self._list_leaves(lobe['root'], classes)
            return
        self._walk(lobe['root'], features, classes, depth=0)

    def _walk(self, node, features, classes, depth):
        pad = '  ' * depth
        if 'feature' in node:
            fname = features[node['feature']] if node['feature'] < len(features) else f'f{node["feature"]}'
            thresh = node['threshold']
            self.stdout.write(f'{pad}if {fname} <= {thresh:g}:')
            self._walk(node['left'],  features, classes, depth + 1)
            self.stdout.write(f'{pad}else:')
            self._walk(node['right'], features, classes, depth + 1)
        else:
            cls_idx = node.get('value', 0)
            cls = classes[cls_idx] if cls_idx < len(classes) else f'?{cls_idx}'
            dist = node.get('distribution', [])
            samples = node.get('samples', '?')
            self.stdout.write(
                f'{pad}→ {cls}  (n={samples}, dist={dist})')

    def _list_leaves(self, node, classes, path=None):
        path = path or []
        if 'feature' in node:
            self._list_leaves(node['left'],  classes, path + ['L'])
            self._list_leaves(node['right'], classes, path + ['R'])
        else:
            cls_idx = node.get('value', 0)
            cls = classes[cls_idx] if cls_idx < len(classes) else f'?{cls_idx}'
            samples = node.get('samples', '?')
            self.stdout.write(f"  {''.join(path) or 'root'}: {cls} (n={samples})")
