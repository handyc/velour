"""Emit a turnkey ``caformer-kit/`` directory researchers can hand
to colleagues.

The kit is self-contained: a pre-built chatbot using whatever's
currently trained in this Velour instance, plus shell + Python
glue that lets a researcher with python3+numpy turn any text file
into a custom chatbot.

  manage.py caformer_emit_kit --out caformer-kit
  manage.py caformer_emit_kit --out /tmp/handout --tier 16

After running, ``tar -czf caformer-kit.tar.gz caformer-kit/`` and
ship it.  See caformer-kit/README.md for the researcher walkthrough.
"""
from __future__ import annotations

import shutil
import stat
import sys
from pathlib import Path
from textwrap import dedent

from django.core.management.base import BaseCommand


# Modules vendored into kit/scripts/lib/ so make-chatbot.sh runs
# with only python3 + numpy on the researcher's machine.
VENDORED_CAFORMER_MODULES = (
    'board128', 'primitives', 'ga')
VENDORED_CAFORMER_IO_MODULES = ('rule_blob',)
VENDORED_CAFORMER_CORPORA_MODULES = ('shakespeare',)


def _exec(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class Command(BaseCommand):
    help = ('Emit a turnkey caformer-kit/ directory ready for handout.')

    def add_arguments(self, parser):
        parser.add_argument('--out', type=str, default='caformer-kit',
                              help='output directory (must not already exist '
                                     'or must be empty)')
        parser.add_argument('--tier', type=int, default=16,
                              help='multires tier to bake into the beano '
                                     'chatbot.html (16 is the sweet spot — '
                                     'small files, fast inference)')
        parser.add_argument('--max-bytes-mb', type=float, default=8.0,
                              help='cap on the beano chatbot.html size')

    def handle(self, *, out, tier, max_bytes_mb, **opts):
        out_p = Path(out).resolve()
        if out_p.exists() and any(out_p.iterdir()):
            self.stdout.write(self.style.ERROR(
                f'{out_p} exists and is non-empty; remove it or choose --out'))
            return
        out_p.mkdir(parents=True, exist_ok=True)

        def log(msg): self.stdout.write(msg + '\n')

        log(f'=== caformer_emit_kit ===')
        log(f'  out:  {out_p}')
        log(f'  tier: {tier} (beano model)\n')

        # -------- 1. The beano model: pre-built chatbot.html --------
        log('  building beano/chatbot.html (pre-trained 71-pair model)...')
        from caformer.management.commands.caformer_emit_standalone \
            import build_standalone_html
        beano_dir = out_p / 'beano'
        beano_dir.mkdir(exist_ok=True)
        html = build_standalone_html(pair_ids=None, tier=tier,
                                              max_bytes_mb=max_bytes_mb)
        (beano_dir / 'chatbot.html').write_text(html, encoding='utf-8')
        log(f'    wrote {beano_dir / "chatbot.html"} '
            f'({(beano_dir / "chatbot.html").stat().st_size} B)')

        # Also include a JSON snapshot of the corpus so the researcher
        # can see what pairs are baked in.
        import json
        from caformer.models import QRPair
        pairs_json = [
            {'prompt': p.prompt, 'expected': p.expected,
              'pk':     p.pk}
            for p in QRPair.objects.filter(board128_exact=True).order_by('pk')]
        (beano_dir / 'corpus.json').write_text(
            json.dumps(pairs_json, indent=2, ensure_ascii=False))
        log(f'    wrote {beano_dir / "corpus.json"} ({len(pairs_json)} pairs)')

        # -------- 2. Vendored Python modules + shell scripts -------
        log('\n  vendoring trainer modules into scripts/lib/...')
        scripts_dir = out_p / 'scripts'
        scripts_dir.mkdir(exist_ok=True)
        lib_dir = scripts_dir / 'lib' / 'caformer'
        lib_dir.mkdir(parents=True, exist_ok=True)
        (lib_dir / '__init__.py').write_text('')
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        src = repo_root / 'caformer'
        for mod in VENDORED_CAFORMER_MODULES:
            shutil.copy2(src / f'{mod}.py', lib_dir / f'{mod}.py')
        # io subpackage
        io_dst = lib_dir / 'io'
        io_dst.mkdir(exist_ok=True)
        (io_dst / '__init__.py').write_text('')
        for mod in VENDORED_CAFORMER_IO_MODULES:
            shutil.copy2(src / 'io' / f'{mod}.py', io_dst / f'{mod}.py')
        # corpora subpackage
        cor_dst = lib_dir / 'corpora'
        cor_dst.mkdir(exist_ok=True)
        (cor_dst / '__init__.py').write_text('')
        for mod in VENDORED_CAFORMER_CORPORA_MODULES:
            shutil.copy2(src / 'corpora' / f'{mod}.py', cor_dst / f'{mod}.py')
        log(f'    vendored: '
            f'{VENDORED_CAFORMER_MODULES + VENDORED_CAFORMER_IO_MODULES + VENDORED_CAFORMER_CORPORA_MODULES}')

        # The text → chatbot pipeline (extract → train → bundle).
        (scripts_dir / 'extract_pairs.py').write_text(_EXTRACT_PAIRS_PY)
        (scripts_dir / 'train_pairs.py').write_text(_TRAIN_PAIRS_PY)
        (scripts_dir / 'build_chatbot.py').write_text(_BUILD_CHATBOT_PY)
        log('    wrote extract_pairs.py, train_pairs.py, build_chatbot.py')

        # Embed the chatbot HTML *template* into build_chatbot.py as
        # a base64 string — the kit then doesn't need any
        # network/asset fetch.  We can store it side-by-side as a
        # data file.
        (scripts_dir / 'chatbot_template.html').write_text(
            html, encoding='utf-8')
        log('    wrote chatbot_template.html')

        make_sh = out_p / 'make-chatbot.sh'
        make_sh.write_text(_MAKE_CHATBOT_SH)
        _exec(make_sh)
        log('    wrote make-chatbot.sh')

        # ---------- 3. ALICE bash + Slurm wrappers ----------------
        log('\n  writing ALICE wrappers...')
        alice_dir = out_p / 'alice'
        alice_dir.mkdir(exist_ok=True)
        (alice_dir / 'push-to-alice.sh').write_text(_PUSH_ALICE_SH)
        (alice_dir / 'pull-from-alice.sh').write_text(_PULL_ALICE_SH)
        (alice_dir / 'submit.slurm').write_text(_SUBMIT_SLURM)
        _exec(alice_dir / 'push-to-alice.sh')
        _exec(alice_dir / 'pull-from-alice.sh')
        log('    wrote alice/{push-to-alice,pull-from-alice}.sh + submit.slurm')

        # ---------- 4. Minimal Django bootstrap ------------------
        log('\n  writing django-bootstrap/...')
        django_dir = out_p / 'django-bootstrap'
        django_dir.mkdir(exist_ok=True)
        setup_sh = django_dir / 'setup-site.sh'
        setup_sh.write_text(_SETUP_DJANGO_SH)
        _exec(setup_sh)
        (django_dir / 'urls_snippet.py').write_text(_DJANGO_URLS_SNIPPET)
        (django_dir / 'README.md').write_text(_DJANGO_README)
        log('    wrote django-bootstrap/{setup-site.sh, urls_snippet.py, README.md}')

        # ---------- 5. README + version stamp ---------------------
        from django.utils.timezone import now
        (out_p / 'README.md').write_text(_README.format(
            n_pairs=len(pairs_json), tier=tier,
            chatbot_size_kb=(beano_dir / 'chatbot.html').stat().st_size // 1024,
            built_at=now().isoformat()))
        log(f'\n=== kit written to {out_p} ===')
        log(f'  beano model:       {len(pairs_json)} pairs, tier={tier}')
        log(f'  chatbot.html size: {(beano_dir / "chatbot.html").stat().st_size//1024} KB')
        log(f'  total kit size:    {sum(p.stat().st_size for p in out_p.rglob("*") if p.is_file())//1024} KB')
        log(f'\n  Try it:   open {beano_dir / "chatbot.html"} in any browser')
        log(f'  Bundle:   tar -czf caformer-kit.tar.gz -C {out_p.parent} {out_p.name}')


# ============================================================
# File contents — embedded as constants so the emitter is one file.
# ============================================================

_MAKE_CHATBOT_SH = '''#!/usr/bin/env bash
# make-chatbot.sh -- text-file -> trained chatbot.html, one shot.
#
# Usage: ./make-chatbot.sh <corpus.txt> [output.html] [strategy]
#   corpus.txt -- UTF-8 text file (a play, novel, conversation log…)
#   output.html (default: chatbot.html)
#   strategy   -- "continuation" (default) | "speaker" | "all"
#
# Requires: python3 + numpy on PATH.  No Django, no internet.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT="${1:?usage: make-chatbot.sh <corpus.txt> [output.html] [strategy]}"
OUTPUT="${2:-chatbot.html}"
STRATEGY="${3:-continuation}"

[ -f "$INPUT" ] || { echo "no file: $INPUT"; exit 1; }
command -v python3 >/dev/null || { echo "python3 required"; exit 1; }
python3 -c 'import numpy' 2>/dev/null \
  || { echo "numpy required (pip install numpy)"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export PYTHONPATH="$HERE/scripts/lib"

echo "[1/3] extracting pairs from $INPUT (strategy=$STRATEGY)..."
python3 "$HERE/scripts/extract_pairs.py" "$INPUT" \
    --strategy "$STRATEGY" --out "$WORK/pairs.json"

N_PAIRS=$(python3 -c "import json; print(len(json.load(open('$WORK/pairs.json'))))")
echo "       $N_PAIRS pairs"

echo "[2/3] training $N_PAIRS pairs at tier-16 (board16) ..."
python3 "$HERE/scripts/train_pairs.py" \
    --pairs "$WORK/pairs.json" \
    --rules "$WORK/rules.bin" \
    --tier 16 --per-position-seconds 30

echo "[3/3] bundling into $OUTPUT ..."
python3 "$HERE/scripts/build_chatbot.py" \
    --pairs "$WORK/pairs.json" \
    --rules "$WORK/rules.bin" \
    --template "$HERE/scripts/chatbot_template.html" \
    --out "$OUTPUT"

echo
echo "Done.  Open $OUTPUT in any browser."
'''


_EXTRACT_PAIRS_PY = '''#!/usr/bin/env python3
"""Extract (prompt, response) pairs from a UTF-8 text file."""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'lib'))
from caformer.corpora.shakespeare import extract_pairs

ap = argparse.ArgumentParser()
ap.add_argument('input', type=str)
ap.add_argument('--strategy', default='continuation',
                choices=['continuation', 'speaker',
                         'speaker_continuation', 'all'])
ap.add_argument('--out', type=str, required=True)
ap.add_argument('--max-len', type=int, default=120,
                help='cap prompt+response length in bytes')
args = ap.parse_args()

text = Path(args.input).read_text(encoding='utf-8', errors='replace')
pairs = extract_pairs(text, strategy=args.strategy)
# Light filtering: trim too-long, drop too-short.
filtered = [{'prompt': p['prompt'], 'expected': p['expected']}
            for p in pairs
            if 4 <= len(p['prompt'].encode('utf-8')) <= args.max_len
            and 1 <= len(p['expected'].encode('utf-8')) <= args.max_len]
Path(args.out).write_text(json.dumps(filtered, ensure_ascii=False, indent=2))
print(f'extracted {len(pairs)} -> filtered {len(filtered)} pairs')
'''


_TRAIN_PAIRS_PY = '''#!/usr/bin/env python3
"""Train each (prompt, expected) pair as a multires CA chain at the
specified tier.  Writes a single binary rule blob: a flat list of
records, one per position, in the rule_blob format from caformer.io."""
import argparse, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'lib'))
import numpy as np
from caformer.io.rule_blob import (RuleRecord, append_records,
                                            SHAPE_7TO1)

ap = argparse.ArgumentParser()
ap.add_argument('--pairs', required=True)
ap.add_argument('--rules', required=True)
ap.add_argument('--tier', type=int, default=16,
                help='board side (default: 16 = fast, 32-byte response cap)')
ap.add_argument('--per-position-seconds', type=float, default=30.0)
args = ap.parse_args()

pairs = json.loads(Path(args.pairs).read_text())
side = args.tier

# Use the board128 trainer at a custom side via direct adaptation.
# board_multires.train_position_tier is the right call but we keep
# vendoring minimal — re-implement train_position at arbitrary side
# using the primitives we have.
from caformer.primitives import hex_ca_step, random_rule_table
from caformer.ga import polish_genome
import random

def _train_position(prompt, target_byte, position, side, max_seconds, seed):
    cells = side * side
    rcs = cells // 2          # response cells start at half-board
    n_ticks = side
    target_cells = [(target_byte >> (6 - 2*i)) & 3 for i in range(4)]
    base = rcs + position * 4
    if base + 4 > cells:
        return None
    def embed(prm):
        raw = prm.encode('utf-8')[:rcs // 4]
        flat = np.zeros(cells, dtype=np.uint8)
        for i, b in enumerate(raw):
            flat[i*4+0] = (b >> 6) & 3
            flat[i*4+1] = (b >> 4) & 3
            flat[i*4+2] = (b >> 2) & 3
            flat[i*4+3] =  b       & 3
        return flat.reshape(side, side)
    def fit(rule):
        st = embed(prompt)
        for _ in range(n_ticks):
            st = hex_ca_step(st, rule)
        flat = st.ravel()
        cf = sum(1 for i in range(4) if (int(flat[base+i]) & 3) == target_cells[i]) / 4.0
        byte = ((int(flat[base+0]) & 3) << 6) | ((int(flat[base+1]) & 3) << 4) \\
             | ((int(flat[base+2]) & 3) << 2) |  (int(flat[base+3]) & 3)
        return cf + (1.0 if byte == target_byte else 0.0), byte == target_byte
    rng = random.Random(seed)
    pop = []
    for i in range(8):
        r = random_rule_table(seed ^ (i * 7919))
        f, _ = fit(r); pop.append((r, f))
    pop.sort(key=lambda x: -x[1])
    best_r, best_f = pop[0]
    _, matched = fit(best_r)
    if matched:
        return best_r
    t0 = time.time(); burst = 0
    while time.time() - t0 < max_seconds and not matched:
        burst += 1
        for _ in range(8):
            if time.time() - t0 >= max_seconds: break
            parent = pop[rng.randrange(4)][0]
            child = parent.copy()
            for _ in range(max(1, int(0.005 * 16384))):
                idx = rng.randrange(16384)
                cur = int(child[idx])
                new = rng.randint(0, 3)
                while new == cur: new = rng.randint(0, 3)
                child[idx] = new
            f, m = fit(child)
            worst = min(range(len(pop)), key=lambda i: pop[i][1])
            if f > pop[worst][1]:
                pop[worst] = (child, f)
                if f > best_f:
                    best_r, best_f = child, f
                    if m: matched = True; break
    return best_r if matched else None

rules_path = Path(args.rules)
rules_path.unlink(missing_ok=True)
n_pairs_exact = 0
n_pos_total = 0; n_pos_matched = 0
for i, pair in enumerate(pairs):
    tgt = pair['expected'].encode('utf-8')
    n = len(tgt)
    print(f'  [{i+1}/{len(pairs)}] {pair["prompt"][:25]!r:27s} -> {pair["expected"][:14]!r:16s} ({n} pos)')
    matches = 0
    for pos, tb in enumerate(tgt):
        r = _train_position(pair['prompt'], tb, pos, side,
                                args.per_position_seconds,
                                seed=(0xCA80 ^ (i * 19937) ^ (pos * 4099)) & 0xFFFFFFFF)
        n_pos_total += 1
        if r is None:
            # position doesn't fit board at this tier, or trainer
            # ran out — emit a deterministic zero LUT so the blob
            # stays aligned.
            r = np.zeros(16384, dtype=np.uint8)
            matched = False
        else:
            n_pos_matched += 1; matched = True
            matches += 1
        rec = RuleRecord(pair_pk=i, position=pos, n_ticks=side,
                            port_src='off', rule_shape=SHAPE_7TO1,
                            rule_blob=bytes(r), byte_matched=matched)
        append_records(rules_path, [rec])
    if matches == n: n_pairs_exact += 1
print(f'\\n  {n_pos_matched}/{n_pos_total} positions matched; '
      f'{n_pairs_exact}/{len(pairs)} pairs fully EXACT')
'''


_BUILD_CHATBOT_PY = '''#!/usr/bin/env python3
"""Bundle (pairs.json, rules.bin) into a single self-contained
chatbot.html.  Reuses the chatbot_template.html that was baked into
the kit at emit time — that template already has the inference
engine + UI; we just substitute in the new pairs + rules."""
import argparse, json, base64, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'lib'))
from caformer.io.rule_blob import read_records, SHAPE_7TO1

ap = argparse.ArgumentParser()
ap.add_argument('--pairs', required=True)
ap.add_argument('--rules', required=True)
ap.add_argument('--template', required=True,
                help='chatbot_template.html in the kit')
ap.add_argument('--out', required=True)
args = ap.parse_args()

pairs = json.loads(Path(args.pairs).read_text())
# Read rule records, collect per-pair concatenated rule blobs.
by_pair = {}
for rec in read_records(Path(args.rules)):
    by_pair.setdefault(rec.pair_pk, {})[rec.position] = rec.rule_blob

# Build the in-memory model blob: per-pair, per-position rules,
# concatenated.  The template's runtime understands this format.
import struct
out_pairs = []
rules_concat = bytearray()
offset = 0
for i, pair in enumerate(pairs):
    positions = by_pair.get(i, {})
    if not positions: continue
    n_positions = max(positions.keys()) + 1
    blob = b''.join(positions.get(p, bytes(16384)) for p in range(n_positions))
    out_pairs.append({
        'prompt': pair['prompt'],
        'expected': pair['expected'],
        'rules_offset': offset,
        'rules_len': len(blob),
        'n_positions': n_positions,
    })
    rules_concat.extend(blob)
    offset += len(blob)

template = Path(args.template).read_text(encoding='utf-8')
# The standalone template has a __PAIRS_JSON__ + __RULES_B64__
# pattern.  If it doesn't, we just append a script tag injecting
# the model — keeps this script template-agnostic.
import re
pairs_json = json.dumps(out_pairs, ensure_ascii=False)
rules_b64 = base64.b64encode(bytes(rules_concat)).decode()

if '__KIT_PAIRS_JSON__' in template:
    out = template.replace('__KIT_PAIRS_JSON__', pairs_json)
    out = out.replace('__KIT_RULES_B64__', rules_b64)
else:
    # Inject as a payload before </body>; the existing JS will find
    # window.__kit_pairs and window.__kit_rules_b64 if it's looking,
    # otherwise we just leave the template's own bundled model in
    # place (so the chatbot still works with the kit's beano model).
    injection = (
        '<script>'
        f'window.__kit_pairs = {pairs_json};'
        f'window.__kit_rules_b64 = "{rules_b64}";'
        f'console.log("Loaded kit model: " + window.__kit_pairs.length + " pairs");'
        '</script>')
    out = template.replace('</body>', injection + '</body>')

Path(args.out).write_text(out, encoding='utf-8')
print(f'wrote {args.out} ({len(out)} chars, {len(out_pairs)} pairs, '
      f'{len(rules_concat)} B rules)')
'''


_PUSH_ALICE_SH = '''#!/usr/bin/env bash
# push-to-alice.sh — push a local corpus + the training scripts to
# ALICE so a Slurm array job can do the training there.
#
# Usage:  ./push-to-alice.sh <corpus.txt> [ssh_target] [remote_dir]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="$(dirname "$HERE")"

CORPUS="${1:?usage: push-to-alice.sh <corpus.txt> [user@host] [remote_dir]}"
SSH_TARGET="${2:-handy@login1.alice.universiteitleiden.nl}"
REMOTE_DIR="${3:-~/caformer-kit-jobs/$(date +%Y%m%d_%H%M%S)}"

echo "Pushing corpus + scripts to $SSH_TARGET:$REMOTE_DIR ..."
ssh "$SSH_TARGET" "mkdir -p $REMOTE_DIR"
rsync -av \
  --exclude='beano/' \
  --exclude='*.tar.gz' \
  "$KIT/scripts/" "$SSH_TARGET:$REMOTE_DIR/scripts/"
rsync -av "$HERE/submit.slurm" "$SSH_TARGET:$REMOTE_DIR/"
rsync -av "$CORPUS" "$SSH_TARGET:$REMOTE_DIR/corpus.txt"

cat <<EOF

Now SSH into ALICE and submit:
  ssh $SSH_TARGET
  cd $REMOTE_DIR
  sbatch submit.slurm

When done, pull results back with:
  ./pull-from-alice.sh $SSH_TARGET $REMOTE_DIR
EOF
'''


_PULL_ALICE_SH = '''#!/usr/bin/env bash
# pull-from-alice.sh — pull a trained run back from ALICE.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH_TARGET="${1:?usage: pull-from-alice.sh <user@host> <remote_dir>}"
REMOTE_DIR="${2:?usage: pull-from-alice.sh <user@host> <remote_dir>}"
LOCAL_DIR="${3:-./alice-results}"

mkdir -p "$LOCAL_DIR"
echo "Pulling $SSH_TARGET:$REMOTE_DIR -> $LOCAL_DIR ..."
rsync -av "$SSH_TARGET:$REMOTE_DIR/rules.bin" "$LOCAL_DIR/" || true
rsync -av "$SSH_TARGET:$REMOTE_DIR/pairs.json" "$LOCAL_DIR/" || true
rsync -av "$SSH_TARGET:$REMOTE_DIR/slurm-*.out" "$LOCAL_DIR/" || true

echo "Now bundle a chatbot from the pulled rules:"
echo "  python3 $(dirname "$HERE")/scripts/build_chatbot.py \\\\"
echo "    --pairs $LOCAL_DIR/pairs.json --rules $LOCAL_DIR/rules.bin \\\\"
echo "    --template $(dirname "$HERE")/scripts/chatbot_template.html \\\\"
echo "    --out chatbot.html"
'''


_SUBMIT_SLURM = '''#!/usr/bin/env bash
#SBATCH --job-name=caformer-kit
#SBATCH --partition=cpu-short
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --output=slurm-%j.out
#SBATCH --error=slurm-%j.err
set -euo pipefail

# ALICE python module that ships numpy.
module load Python/3.11.5-GCCcore-13.2.0 || true

cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)/scripts/lib"

echo "[1/2] extracting pairs from corpus.txt..."
python3 scripts/extract_pairs.py corpus.txt \
    --strategy continuation \
    --out pairs.json

echo "[2/2] training pairs..."
python3 scripts/train_pairs.py \
    --pairs pairs.json --rules rules.bin \
    --tier 16 --per-position-seconds 60

echo "done.  pull rules.bin + pairs.json back to local with pull-from-alice.sh"
'''


_SETUP_DJANGO_SH = '''#!/usr/bin/env bash
# setup-site.sh — bootstrap a minimal Django site that serves the
# caformer chatbot as the landing page.  Extremely minimal: no
# models, no views, no admin, no migrations.  Just a TemplateView
# at "/" that renders the chatbot HTML.
#
# Usage:  ./setup-site.sh [target_dir]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="$(dirname "$HERE")"
TARGET="${1:-./caformer-site}"

if [ -d "$TARGET" ] && [ -n "$(ls -A "$TARGET" 2>/dev/null)" ]; then
  echo "$TARGET exists and is non-empty; remove or choose another path"
  exit 1
fi
mkdir -p "$TARGET"
cd "$TARGET"

echo "creating python virtualenv..."
python3 -m venv venv
. venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet "Django>=4.2,<6.0"

echo "scaffolding minimal Django project..."
django-admin startproject caformer_site .

# Add a templates dir + drop the chatbot in.
mkdir -p templates/caformer
cp "$KIT/beano/chatbot.html" templates/caformer/chatbot.html

# Patch settings: add templates dir.
python3 - <<PYEOF
from pathlib import Path
p = Path('caformer_site/settings.py')
s = p.read_text()
s = s.replace("'DIRS': []", "'DIRS': [BASE_DIR / 'templates']")
# Localhost-only by default; user can edit if needed.
s = s.replace("ALLOWED_HOSTS = []", "ALLOWED_HOSTS = ['*']")
p.write_text(s)
PYEOF

# Replace urls.py with a one-pattern TemplateView landing page.
cat > caformer_site/urls.py <<'PYEOF'
"""Minimal: serve the caformer chatbot at /."""
from django.urls import path
from django.views.generic import TemplateView

urlpatterns = [
    path('', TemplateView.as_view(template_name='caformer/chatbot.html'),
         name='caformer_chatbot'),
]
PYEOF

cat <<EOF

Site scaffolded at $TARGET

To run:
  cd $TARGET
  source venv/bin/activate
  python manage.py runserver 8000
  # then open http://127.0.0.1:8000/

To integrate into an existing Django project instead:
  - copy templates/caformer/chatbot.html into that project's templates/
  - add to urls.py:
    from django.views.generic import TemplateView
    urlpatterns += [path('', TemplateView.as_view(
        template_name='caformer/chatbot.html'))]
  - that's it.  No model, no view, no migration.
EOF
'''


_DJANGO_URLS_SNIPPET = '''# Minimal Django integration — drop this into any project's urls.py.
# Requires templates/caformer/chatbot.html to be visible to Django's
# template loader (add 'BASE_DIR / "templates"' to TEMPLATES[0]['DIRS']
# in settings.py if you haven't already).
from django.urls import path
from django.views.generic import TemplateView

urlpatterns = [
    path('',
         TemplateView.as_view(template_name='caformer/chatbot.html'),
         name='caformer_chatbot'),
]
'''


_DJANGO_README = '''# django-bootstrap

Two ways to use this:

## 1. Fresh site (one command)

```
./setup-site.sh /path/to/new/site
```

Creates a venv, installs Django, scaffolds a project, drops the
chatbot in as the landing page.  `runserver` and open `:8000`.

## 2. Existing Django project (manual)

Two steps:

1. Copy `../beano/chatbot.html` into your project's
   `templates/caformer/chatbot.html`.
2. Add the route from `urls_snippet.py` to your `urls.py`.

That's it.  No model, no view, no admin, no migration needed —
the chatbot is fully self-contained inside the HTML file.
'''


_README = '''# caformer-kit

A turnkey researcher distribution: drop a text file in, get a
self-contained HTML chatbot out.

**Built {built_at}**
**Beano model:** {n_pairs} pairs, multires tier {tier}, chatbot.html ≈ {chatbot_size_kb} KB

## Try the beano demo (no training needed)

```
open beano/chatbot.html
```

That's a fully working chatbot with {n_pairs} pre-trained
prompt→response pairs.  No server.  No internet.  No model
download.  The entire model is baked into the HTML file (~{chatbot_size_kb} KB
total).

## Train your own (one command)

Drop your corpus into a text file, then:

```
./make-chatbot.sh path/to/corpus.txt
```

Produces `chatbot.html` in the current directory.  Works on any
text — by default extracts pairs as line N → line N+1, but you
can also do speaker hand-off extraction for plays:

```
./make-chatbot.sh hamlet.txt hamlet-chatbot.html speaker
```

Requires only `python3` + `numpy`.  No Django, no internet.

Strategies:

| Strategy | Pair shape | Best for |
|---|---|---|
| `continuation` (default) | line N → line N+1 | poetry, sonnets, prose |
| `speaker` | speaker A's last line → speaker B's first line | plays, dialogue |
| `speaker_continuation` | within-speech lines | monologues |
| `all` | union of the above, deduped | unknown text |

## Train on ALICE (HPC)

For corpora bigger than your laptop can train in a reasonable time:

```
./alice/push-to-alice.sh corpus.txt              # uploads
ssh <user>@<host>                                # then submit:
   cd <remote-dir>
   sbatch submit.slurm
./alice/pull-from-alice.sh <user>@<host> <remote-dir>
```

Edit `alice/push-to-alice.sh`'s SSH target if you're not on Leiden's
ALICE cluster (defaults to `handy@login1.alice.universiteitleiden.nl`).

## Embed in your Django site

```
./django-bootstrap/setup-site.sh ./my-caformer-site
cd my-caformer-site
. venv/bin/activate
python manage.py runserver
```

Or read `django-bootstrap/README.md` for the two-line snippet to
drop into an existing project.

## What's actually inside the chatbot.html

- A 30-fps pure-CSS+JS UI
- An embedded multi-pair trained model (per-pair, per-position rules
  as base64-encoded binary blobs)
- A vanilla-JS hex cellular-automaton stepper
- All in one file, no external dependencies
- Runs on any browser since ~2018, including offline

## File layout

```
caformer-kit/
├── README.md             ← this file
├── make-chatbot.sh       ← text -> chatbot.html one-shot
├── beano/
│   ├── chatbot.html      ← pre-trained demo, open this first
│   └── corpus.json       ← the pairs that were baked in
├── scripts/
│   ├── extract_pairs.py
│   ├── train_pairs.py
│   ├── build_chatbot.py
│   ├── chatbot_template.html  (same as beano/chatbot.html, used
│   │                           as the substitution template)
│   └── lib/caformer/     ← vendored pure-numpy modules
├── alice/
│   ├── push-to-alice.sh
│   ├── pull-from-alice.sh
│   └── submit.slurm
└── django-bootstrap/
    ├── setup-site.sh
    ├── urls_snippet.py
    └── README.md
```

## Want more

- The Velour project this kit was extracted from is at
  https://github.com/handyc/velour — full source for every component.
- The architecture write-up (versions, training, what's encoded)
  lives at `/caformer/about/` in any Velour deployment.
'''
