# hexhunter

Reusable library form of the original `oneclick_class4/hunter.c`
class-4 hex-CA evolver.  Same algorithm; everything that wasn't part
of the algorithm — ELF tail packing, argv parsing, ANSI render,
self-replicating winner binaries — has been stripped out.

## Files

| file                  | purpose                                     |
|-----------------------|---------------------------------------------|
| `hexhunter.h` / `.c`  | C library (`libhexhunter.a`)                |
| `cli.c`               | `hh_cli` command-line front-end             |
| `test_hexhunter.c`    | C unit tests                                |
| `Makefile`            | build the lib, CLI, and tests               |
| `hexhunter.py`        | pure-Python port (byte-identical output)    |

## C usage

```c
#include "hexhunter.h"

uint8_t out[HH_GENOME_BYTES];

hexhunter(NULL, out);                       // all defaults

hh_config_t cfg = {0};                      // {0} == defaults
cfg.population  = 60;
cfg.generations = 80;
cfg.rng_seed    = 12345;
hexhunter(&cfg, out);

uint8_t refined[HH_GENOME_BYTES];
hexhunter_refine(&cfg, out, refined);
```

Build + test:

```
make            # libhexhunter.a + hh_cli + test_hexhunter
make test       # build + run the C unit tests
./hh_cli 30 40 42 winner.bin
./hh_cli 30 40 99 winner_v2.bin winner.bin   # refine
```

## Python usage

```python
from hexhunter import hexhunter, hexhunter_refine, fitness

g = hexhunter()                             # all defaults
g = hexhunter(population=60, generations=80, rng_seed=12345)
r = hexhunter_refine(g, generations=20)
print(fitness(r))
```

CLI parity (same args, same byte-identical output as `hh_cli`):

```
python3 hexhunter.py 30 40 42 winner_py.bin
```

## Determinism

Both implementations use the same Park-Miller LCG (`state * 1103515245
+ 12345`) seeded from `cfg.rng_seed`.  A run with the same config and
seed always produces the same 4096-byte ruleset, regardless of host
or libc.  This was the main reason for breaking from the original
`hunter.c` which used `libc rand()` (RAND_MAX varies between platforms).

## Genome layout

Packed K=4 hex-CA genome.  16,384 situations × 2 bits / 8 = 4096 bytes.
Situation index is `(self * K^6) + (n0 * K^5) + ... + n5`, where
`n0..n5` are the six neighbour colours in row-parity-sensitive order
(see `DY` / `DXE` / `DXO` in `hexhunter.c`).
