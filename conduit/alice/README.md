# ALICE HPC bundle protocol

A **bundle** is a self-contained directory of files that gets copied to
ALICE, submitted with `sbatch`, and pulled back when results are ready.
The split exists so AI generates the deterministic code, the human
operator approves and submits it, and ALICE runs the actual compute.

## Layout

```
conduit/alice/
├── README.md            ← this file
├── __init__.py
├── metapact_ga.py       ← one bundle generator (others land as siblings)
└── bundles/             ← generated bundles (gitignored except .gitkeep)
    └── <bundle-slug>/
        ├── README.md         ← what this bundle does + expected runtime
        ├── manifest.json     ← machine-readable: tasks, params, expected outputs
        ├── submit.sh         ← sbatch + array job
        ├── run_task.py       ← deterministic entry point (numpy + spoeqi only)
        ├── inputs/000.json   ← one input per array task (small JSON)
        ├── outputs/          ← empty locally; ALICE fills it
        ├── push.sh           ← rsync local → ALICE (one-liner)
        └── pull.sh           ← rsync ALICE → local (one-liner)
```

## Operator workflow

1. AI runs e.g. `manage.py alice_bundle_metapact --replicates 16` →
   bundle appears at `conduit/alice/bundles/<slug>/`.
2. Read `<slug>/README.md`, `submit.sh`, `run_task.py`. Refuse any that
   look wrong before any compute happens.
3. `bash conduit/alice/bundles/<slug>/push.sh` — rsyncs the bundle to
   `<ssh_host>:~/velour-dev/.alice_bundles/<slug>/`. (ssh host comes
   from `JobTarget(slug='alice-manual').config.host` by default; edit
   `push.sh` first if that's wrong.)
4. SSH to ALICE, `cd ~/velour-dev/.alice_bundles/<slug>`, `sbatch submit.sh`.
   `squeue -u $USER` to watch.
5. When done: `bash conduit/alice/bundles/<slug>/pull.sh` — rsyncs
   `outputs/` back.
6. AI runs `manage.py alice_analyze_metapact <slug>` → reads outputs,
   prints summary, proposes next bundle.

## Safety properties

Every bundle generator must honour these:

- **Determinism.** All randomness seeded from `seed_base + task_id` so
  reruns are byte-identical and disagreements are real bugs.
- **Independence.** Each array task is independent (no cross-task IPC,
  no shared state). One failed task ≤ one bad output.
- **No network access.** `run_task.py` imports only stdlib + numpy +
  Velour modules from the local checkout. No HTTP, no PyPI installs at
  runtime.
- **Pure-data outputs.** JSON or raw bytes; never executables, never
  shell-eval-able strings.
- **Bounded wall time.** Bundles set `#SBATCH --time` to ≤ 4 h so they
  fit the default partition, and to a value comfortably above the
  expected runtime (3× rule of thumb).
- **Bounded resource footprint.** `--cpus-per-task=1`, `--mem` no
  larger than the actual working set the run measured locally,
  array size <= 32 unless explicitly approved.

## Why the workflow looks like this

ALICE forbids automated `sbatch` from outside the cluster, and the user
running the jobs is responsible for everything that lands there. So:

- AI never `ssh`/`scp`/`sbatch`. AI only writes files into
  `conduit/alice/bundles/<slug>/`.
- The human reads them, runs `push.sh` themselves, runs `sbatch`
  themselves on ALICE.
- The human runs `pull.sh` to retrieve results. AI then reads them.

This keeps the human as the trust boundary on every cluster-touching
action while letting AI handle the deterministic-code-generation and
result-analysis parts where it's most useful.

## Adding a new bundle type

Sketch a sibling module to `metapact_ga.py` that exports:

- `BUNDLE_KIND` — short slug string used as default bundle prefix.
- `generate_bundle(out_dir: Path, **params) -> None` — writes the
  bundle directory.
- `run_task(input_path: Path, output_path: Path) -> None` — pure
  function the array tasks call (must be importable from a
  bundle-relative `run_task.py`).
- `analyse(bundle_dir: Path) -> dict` — local-side summary.

Then add two thin `manage.py` commands wrapping the bundle generator
and the analyser. See `metapact_ga.py` for the worked example.
