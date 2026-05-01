# HexNN — HPC variants

Three planned ports of the `hexnn-class4-search` pipeline to the
ALICE cluster (Leiden HPC, up to ~288 CPU cores per user, plus a few
GPU nodes). Each variant addresses a different bottleneck.

| Variant         | Status        | File           | Slurm template      |
|-----------------|---------------|----------------|---------------------|
| Multi-CPU       | **Working**   | `cpu.py`       | `cpu.sbatch`        |
| GPU-only        | Planned       | `gpu.py`       | `gpu.sbatch`        |
| GPU + CPU hybrid | Planned       | `hybrid.py`    | `hybrid.sbatch`     |

## Multi-CPU (current)

`cpu.py` parallelises the per-generation scoring step using
`multiprocessing.Pool`. Each genome in the population is dispatched to
a worker process; the main process gathers fitnesses, breeds the next
generation, and loops. The breeding step itself is cheap (a few
mutations and a crossover per genome) so it stays sequential — the GA
is *embarrassingly parallel inside each generation, sequential between
generations*.

### When to use

- ALICE's `cpu-short` / `cpu-medium` partitions
- Population sizes from 32 up to ~512
- `n_log2` from 11 (S3-equivalent) up to 16 (4× the browser default)

### Submit through Velour

The `hexnn_hpc_submit` management command bundles `cpu.py` + a
parameter-filled `cpu.sbatch` into a Conduit `JobHandoff`:

```
venv/bin/python manage.py hexnn_hpc_submit \
    --pop 128 --gens 80 --workers 64 --partition cpu-short
```

The handoff page tells you exactly what to copy where. ALICE prohibits
automated sbatch, so this stays a human-in-the-loop step on purpose.

### Submit by hand

```
ssh username@login1.alice.universiteitleiden.nl
mkdir -p ~/jobs && cd ~/jobs
# Copy cpu.py, pi4.py, cpu.sbatch (rendered) into ~/jobs first.
sbatch cpu.sbatch
squeue -u $USER
```

### Expected speedup

Roughly **N×** for `N ≤ pop_size`, then flat. Each per-generation wave
finishes in `(per-genome score time) × ⌈pop_size / N⌉`. The breeding
step (sequential) is < 1% of wall-clock at typical configs.

Caveat: pickling each genome (8 × 2^n_log2 bytes) over `Pool.map`
costs a few ms per call. At small problem sizes this dominates. For
`n_log2 = 11`, pickle cost is ~50 ms / wave; for `n_log2 = 14`,
~400 ms / wave. Worth measuring before going to MPI.

## GPU-only (planned)

The inner step — squared Euclidean over a bin × broadcast over the
grid — maps almost exactly to a CUDA kernel. Plan: rewrite `step()`
and `score()` against `cupy` (or `torch`) tensors, batch-evaluate the
whole population in one device call.

**Pros:** 50–200× speedup at `n_log2=14`, `pop_size = 256+` becomes
practical, you can run `K=64`/`n_log2=16` configurations that are
infeasible on CPU.

**Cons:** uneven bin sizes cause warp divergence in the worst case;
mutation+crossover are CPU-natural and require either a second kernel
or back-and-forth host transfers. ALICE's GPU queue waits longer than
its CPU queue runs.

## GPU + CPU hybrid (planned)

GPU does scoring; CPU does bookkeeping (mutate, crossover, sort,
checkpoint). Or, **island GA**: many CPU islands each run their own
small GA, exchange champions every K gens, GPU services scoring waves
from any island.

**Pros:** best wall-clock for serious "find the best HexNN rule we
have ever seen" runs. Matches ALICE's mixed CPU+GPU node topology.
Island GA is genuinely better than single-population GA on multi-modal
landscapes like this one.

**Cons:** most engineering work, three code paths to maintain, harder
failure modes (deadlock vs. slow vs. wrong). Worst code reuse with
the existing `pi4.py` and the browser bench.

## Recommendation order

1. Ship `cpu.py` (done) — most return on least engineering.
2. Build `gpu.py` only after measuring a wall-clock that motivates it.
3. Build `hybrid.py` only if `gpu.py` says the GPU is bored mid-run.
