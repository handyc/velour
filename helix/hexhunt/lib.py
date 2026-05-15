"""Standalone hexhunter library surface for Helix · Hex Hunt.

Wraps the pure-Python port at isolation/artifacts/hexhunter/hexhunter.py
and serves the C / Python / JS source files for download.  This module
is the *server-side* counterpart to /helix/hexhunt/lib/* views — it
holds the file paths, run-spec validation, and a thin "execute a small
GA on a request" helper.

The browser also has the JS port bundled into templates/helix/hexhunt/
so the run + refine pages can do their work entirely client-side; the
Python wrapper here is for headless / curl / scripted callers.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import importlib.util
import sys

from django.conf import settings


# ── Locating the standalone library ────────────────────────────────

# Single source of truth: the artifacts directory holds the C/Py/JS
# port files.  Velour does not vendor them — they live alongside the
# original hunter.c that begat them.
LIB_DIR: Path = Path(settings.BASE_DIR) / 'isolation' / 'artifacts' / 'hexhunter'


@dataclass(frozen=True)
class Port:
    slug:        str
    label:       str
    filename:    str
    language:    str
    description: str
    @property
    def path(self) -> Path: return LIB_DIR / self.filename
    @property
    def exists(self) -> bool: return self.path.is_file()
    @property
    def size_bytes(self) -> int:
        return self.path.stat().st_size if self.exists else 0


PORTS: dict[str, Port] = {
    p.slug: p for p in [
        Port('c',      'C',          'hexhunter.c',  'c',
             'Reference implementation. Static lib + CLI build with '
             '`make`. Drop into any C99 project.'),
        Port('c-h',    'C header',   'hexhunter.h',  'c',
             'Public API for libhexhunter. Always pair with hexhunter.c.'),
        Port('python', 'Python',     'hexhunter.py', 'python',
             'Pure Python (3.7+); no deps. Importable as a module or '
             'runnable as a CLI. Slow vs C but portable.'),
        Port('js',     'JavaScript', 'hexhunter.js', 'javascript',
             'Single-file UMD module. Runs in browsers (used by the run '
             'page here) and Node. Sync + async APIs.'),
        Port('cli',    'C CLI',      'cli.c',        'c',
             'Reference command-line driver: ./hh_cli POP GENS SEED OUT [IN].'),
        Port('test',   'C tests',    'test_hexhunter.c', 'c',
             'Unit tests for the C library (8 cases, identity helper, '
             'determinism, refine round-trip, progress callback).'),
        Port('makefile', 'Makefile', 'Makefile',     'makefile',
             '`make` builds libhexhunter.a + hh_cli + test_hexhunter.'),
        Port('readme', 'README',     'README.md',    'markdown',
             'Library overview + usage examples for both C and Python.'),
    ]
}


# ── Python port (lazy-loaded via importlib so we don't pollute the
#    Velour package namespace with an isolated-artifacts module) ────

_py_module = None
def _python_port():
    """Load isolation/artifacts/hexhunter/hexhunter.py as a module."""
    global _py_module
    if _py_module is None:
        spec = importlib.util.spec_from_file_location(
            'hexhunter_artifact', LIB_DIR / 'hexhunter.py')
        if spec is None or spec.loader is None:
            raise RuntimeError(
                f'cannot find Python port at {LIB_DIR / "hexhunter.py"}')
        mod = importlib.util.module_from_spec(spec)
        sys.modules['hexhunter_artifact'] = mod
        spec.loader.exec_module(mod)
        _py_module = mod
    return _py_module


# ── Run / refine spec (shared form validation) ─────────────────────

@dataclass
class RunSpec:
    population:           int
    generations:          int
    init_mutation_rate:   float
    breed_mutation_rate:  float
    rng_seed:             int

    @classmethod
    def defaults(cls) -> 'RunSpec':
        m = _python_port()
        return cls(population=m.DEF_POP, generations=m.DEF_GENS,
                    init_mutation_rate=m.DEF_INIT_MUT_RATE,
                    breed_mutation_rate=m.DEF_BREED_MUT_RATE,
                    rng_seed=m.DEF_RNG_SEED)

    @classmethod
    def from_form(cls, post) -> 'RunSpec':
        d = cls.defaults()
        try:
            return cls(
                population         = int(post.get('population',  d.population)),
                generations        = int(post.get('generations', d.generations)),
                init_mutation_rate = float(post.get('init_mutation_rate',  d.init_mutation_rate)),
                breed_mutation_rate= float(post.get('breed_mutation_rate', d.breed_mutation_rate)),
                rng_seed           = int(post.get('rng_seed',    d.rng_seed)),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f'bad run spec: {exc}') from exc

    def validate(self) -> None:
        if not (2 <= self.population <= 256):
            raise ValueError('population must be in [2, 256]')
        if not (1 <= self.generations <= 200):
            raise ValueError('generations must be in [1, 200]')
        if not (0 < self.init_mutation_rate <= 1):
            raise ValueError('init_mutation_rate must be in (0, 1]')
        if not (0 < self.breed_mutation_rate <= 1):
            raise ValueError('breed_mutation_rate must be in (0, 1]')
        if not (0 <= self.rng_seed < 2**32):
            raise ValueError('rng_seed must be in [0, 2^32)')


def run(spec: RunSpec) -> bytes:
    spec.validate()
    m = _python_port()
    return m.hexhunter(
        population          = spec.population,
        generations         = spec.generations,
        init_mutation_rate  = spec.init_mutation_rate,
        breed_mutation_rate = spec.breed_mutation_rate,
        rng_seed            = spec.rng_seed)


def refine(spec: RunSpec, in_genome: bytes) -> bytes:
    spec.validate()
    m = _python_port()
    if len(in_genome) != m.GENOME_BYTES:
        raise ValueError(f'in_genome must be {m.GENOME_BYTES} bytes, '
                          f'got {len(in_genome)}')
    return m.hexhunter_refine(
        in_genome,
        population          = spec.population,
        generations         = spec.generations,
        init_mutation_rate  = spec.init_mutation_rate,
        breed_mutation_rate = spec.breed_mutation_rate,
        rng_seed            = spec.rng_seed)


def fitness(genome: bytes, spec: RunSpec | None = None) -> float:
    if spec is None: spec = RunSpec.defaults()
    m = _python_port()
    return m.fitness(genome, rng_seed=spec.rng_seed)
