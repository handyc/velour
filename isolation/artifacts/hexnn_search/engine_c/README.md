# HexNN portable C engine

One pure-C99 engine that drivers wrap for every target. The truth
lives in `engine.c` + `engine.h`; the drivers are thin.

## Goals

- **One algorithm, four targets.** Same `engine.c` compiles for
  Linux/HPC, Arduino-ESP32, WASM (browser), and (eventually) xcc700
  self-hosting on-device.
- **No platform deps, no malloc, no `<math.h>`.** The caller provides
  the memory arena; the engine carves it up internally.
- **Q16.16 fixed-point fitness.** Bit-exact reproducibility across
  architectures with different float rounding modes.
- **Mirrors the browser bench at /hexnn/.** Same mulberry32 PRNG,
  same flat-top hex neighbour math, same edge-of-chaos parabola
  fitness on the K=4-quantized change rate.

## Layout

```
engine_c/
  engine.h            ← public API
  engine.c            ← pure C99, no platform deps
  cli_linux.c         ← driver: argv → engine, prints fitness     (single thread)
  cli_openmp.c        ← driver: parallel-population GA via OpenMP  (one node, ALICE)
  mpi_islands.c       ← driver: MPI ranks = islands               (multi-node)
  Makefile            ← gcc -O3 -Wall + targets (default / mpi / omp / tiny)
  islands.sbatch      ← Slurm template for the MPI islands variant
  omp.sbatch          ← Slurm template for the OpenMP variant
  README.md           ← you are here
  (planned)
  arduino_s3.cpp      ← Arduino-ESP32 wrapper, replaces parts of
                        ../esp32_s3/src/main.cpp
  wasm_browser.c      ← emscripten exports, replaces the JS engine
                        in templates/hexnn/index.html
  selfhost_xcc.c      ← xcc700-dialect-only subset for on-device
                        self-compilation
```

## Build & run

```
make
./hexnn --seed 42 --k 4 --n-log2 11 --grid 16 --pop 16 --gens 30
```

Without `--no-json`, the elite genome lands on stdout in the same
`hexnn-genome-v1` shape the browser "Download JSON" button writes.
That makes round-trips trivial:

```
./hexnn --seed 42 --output winner.json
# upload winner.json into the /hexnn/ page → see what the engine evolved
```

## Memory shape

All sizing is config-driven. Caller queries with `engine_arena_size`
and provides a buffer of at least that many bytes:

```
size_t need = engine_arena_size(&cfg);
void* arena = malloc(need);
engine_t* eng;
engine_init(&eng, arena, need, &cfg);
```

Approximate sizes (POP_SIZE × N×8 dominates; N = 1<<n_log2):

| K | n_log2 | pop | arena |
|---|---|---|---|
| 4 | 11  (2,048) | 16   | 530 KB |
| 4 | 14  (16,384) | 16   | 4.2 MB |
| 64 | 14 | 1000 | 256 MB |
| 256 | 14 | 1000 | 256 MB |

Linux/HPC fits up to ~tens of GB easily. The S3 fits up to
n_log2=11, pop=8. The browser via WASM is fine up to a few hundred
MB of `WebAssembly.Memory`.

## Relationship to siblings

- **`../pi4.py`** — slow numpy reference. Will rot gracefully once
  the C engine is verified equivalent. Useful to keep as a
  cross-check oracle.
- **`../esp32_s3/src/main.cpp`** — current Arduino sketch with
  inlined algorithm. Will be refactored to call the engine.
- **`../hpc/cpu.py`** — multiprocessing.Pool driver against pi4.py.
  Will be superseded by `mpi_islands.c` for the actual scaling work.

## Phase 1 status (verified)

- Engine: `engine.h` + `engine.c`, ~700 lines pure C99, no platform deps.
- Driver: `cli_linux.c` matches pi4.py's CLI surface.
- **Smoke test passes.**

### Tiny config (K=4 N=256 grid=8×8 pop=4 gens=2)

Bit-exact match to pi4.py at every generation:

| phase / gen | pi4.py        | engine_c      |
|-------------|---------------|---------------|
| hunt 1/2    | 0.8474 r=0.695 | 0.8474 r=0.695 |
| hunt 2/2    | 0.8633 r=0.685 | 0.8633 r=0.685 |
| refine 1/2  | 0.8242 r=0.710 | 0.8242 r=0.710 |
| refine 2/2  | 0.8350 r=0.703 | 0.8350 r=0.703 |

### Production-ish config (K=4 N=2048 grid=16×16 pop=16 gens=10)

| version    | wall-clock | final fitness |
|------------|------------|---------------|
| pi4.py     | 110 s      | 0.8374        |
| engine_c   | **5.5 s**  | 0.8401        |

That's **20× faster**. Generations 1–7 match pi4.py bit-exactly; from
gen 8 onward the populations drift because pi4 stores fitness as
float64 while engine_c uses Q16.16 — when two genomes tie at the
ULP level in pi4's float, they round to identical Q16 values here,
and the elite-tie-break lands on a different individual. The drift
is sub-noise: engine_c happened to find a slightly *better* final
elite (0.8401 vs 0.8374) on this seed.

## Phase 2 — MPI islands (shipped)

`mpi_islands.c` runs one island per MPI rank. Each rank has its own
`engine_t` with its own population; islands run their local Hunt +
Refine GA between merge points. The merge strategy is picked at
submit time:

- **migrate-best** — ring topology, conditional replace if peer
  scores better on a shared grid_seed. Lowest-disruption.
- **crossover-merge** — paired ranks exchange elites and adopt a
  hybrid crossover. Injects genuine recombination.
- **tournament-merge** — Allgather, score every elite on a common
  seed, every rank adopts the global winner. Aggressive.
- **diversity-filter** — like migrate-best but reject incoming peers
  whose Hamming distance from the local elite is below threshold.
  Best for multi-modal landscapes.

After all epochs finish, every island's elite is gathered, scored on
a shared seed, and rank 0 emits the global winner JSON.

### Build

```
make mpi          # needs mpicc (ALICE: module load OpenMPI)
```

For local correctness checks without an MPI runtime:

```
make islands-nompi
./hexnn_islands_nompi --no-mpi --pop-per-island 16 --gens-per-epoch 5 \
                      --epochs 3
```

The no-mpi build runs with `world=1`; merge phases turn into no-ops.
Validates the epoch loop, argv parsing, and JSON output.

### Submit through Velour

```
venv/bin/python manage.py hexnn_hpc_submit --variant islands \
    --ntasks 16 --pop-per-island 64 --gens-per-epoch 30 --epochs 20 \
    --merge-strategy diversity-filter --partition cpu-medium \
    --time-limit 04:00:00
```

The Conduit handoff lists the four files to scp into the remote dir
(engine.h / engine.c / mpi_islands.c / Makefile); the sbatch script
runs `make mpi` on the head node before `mpirun`.

### Phase 2.5 — OpenMP single-node (shipped)

`cli_openmp.c` is the lineage descendant of `distill_hexnn_esp32s3(with_tft=True)`
ported back to a host CPU and parallelised across one node's cores.
It exists for the standard ALICE allocation: **1 node × 20 cores ×
4 hours**. MPI over that shape would buy nothing — shared-memory
OpenMP is strictly faster within one node.

Architecture: one *master engine* holds the GA population storage,
plus one *scoring engine per OpenMP thread* (~900 KB each). The hot
loop scores every genome in parallel, then the master serially
sorts + breeds. Driver-implemented mutation + `engine_crossover_bytes`
cover the breeding ABI.

```
make omp
OMP_NUM_THREADS=20 OMP_PROC_BIND=close OMP_PLACES=cores \
  ./hexnn_omp --pop 20 --seconds 14000 --output winner.json -v
```

Time-budget loop instead of fixed generations — the GA keeps
breeding until the wall clock hits `--seconds`. A checkpoint is
written every `--ckpt` generations (default 25) so a slurm
wall-time kill leaves a recoverable winner on disk.

The Slurm template `omp.sbatch` is set up for the standard ALICE
slot: `--nodes=1 --ntasks=1 --cpus-per-task=20 --time=4:00:00`,
with `OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK` and
`OMP_PROC_BIND=close OMP_PLACES=cores` for cache locality.

### What's next (Phase 3+ candidates)

- Refactor `../esp32_s3/src/main.cpp` to call into `engine.c`
  instead of inlining the algorithm. One source of truth.
- `wasm_browser.c` via emscripten to replace the JS engine in
  `templates/hexnn/index.html`.
- Trim `engine.c` to the xcc700 dialect (no structs, no `<stdint.h>`,
  no `for(int i…` declarations — already mostly there) so the chip
  can self-compile.
- GPU + GPU/CPU hybrid drivers, once we have wall-clock numbers
  from a real ALICE islands run that motivate the GPU work.
