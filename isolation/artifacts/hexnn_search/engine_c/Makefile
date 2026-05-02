# HexNN portable C engine — Linux CLI build.
#
# This is the seed driver; the engine itself (engine.c + engine.h) has
# zero platform deps and is meant to be reused unchanged by other
# drivers (MPI islands, Arduino-ESP32, WASM/emscripten, xcc700).

CC      ?= gcc
MPICC   ?= mpicc
CFLAGS  ?= -O3 -Wall -Wextra -Wpedantic -std=c99
LDFLAGS ?=

# Quiet a couple of GCC pedantic warnings that don't apply to clean
# C99 code we care about. -Wno-unused-parameter for the on_gen ABI.
CFLAGS  += -Wno-unused-parameter

BIN     := hexnn
ISLANDS := hexnn_islands
ISLANDS_NOMPI := hexnn_islands_nompi
OMP_BIN := hexnn_omp

SRCS := engine.c cli_linux.c
OBJS := $(SRCS:.c=.o)

# OpenMP build flags. -fopenmp turns on the runtime + spawns the
# threadpool. The driver uses clock_gettime(CLOCK_MONOTONIC), which
# needs -lrt on glibc < 2.17 (ALICE's GCC is recent, link is a no-op
# there but we keep it for portability).
OMP_FLAGS ?= -fopenmp
OMP_LIBS  ?= -lrt

.PHONY: all clean tiny size mpi mpi-check islands-nompi omp

all: $(BIN)

$(BIN): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $(OBJS) $(LDFLAGS)

%.o: %.c engine.h
	$(CC) $(CFLAGS) -c -o $@ $<

# MPI build — only when mpicc is available. ALICE has it via
# `module load OpenMPI`. On Debian/Ubuntu install with
# `sudo apt install libopenmpi-dev openmpi-bin`.
mpi: mpi-check $(ISLANDS)

mpi-check:
	@command -v $(MPICC) >/dev/null 2>&1 || { \
	  echo "error: $(MPICC) not on PATH."; \
	  echo "  ALICE: module load OpenMPI"; \
	  echo "  Debian/Ubuntu: sudo apt install libopenmpi-dev openmpi-bin"; \
	  exit 1; \
	}

$(ISLANDS): engine.c mpi_islands.c engine.h
	$(MPICC) $(CFLAGS) -o $@ engine.c mpi_islands.c $(LDFLAGS)

# No-MPI build of the islands driver — single-process sequential
# debug. Useful when there's no MPI runtime handy. Verifies the
# epoch loop wires up; merge phases turn into no-ops with world=1.
islands-nompi: $(ISLANDS_NOMPI)

$(ISLANDS_NOMPI): engine.c mpi_islands.c engine.h
	$(CC) $(CFLAGS) -DHEXNN_NO_MPI -o $@ engine.c mpi_islands.c $(LDFLAGS)

# OpenMP single-node build — scales the population across one node's
# cores. The intended ALICE shape is 1 task × 20 cpus-per-task × 4 h
# wall clock. See omp.sbatch for the Slurm template.
omp: $(OMP_BIN)

$(OMP_BIN): engine.c cli_openmp.c engine.h
	$(CC) $(CFLAGS) $(OMP_FLAGS) -o $@ engine.c cli_openmp.c $(LDFLAGS) $(OMP_LIBS)

# Tiny build with -Os for size comparisons (handy when sizing for
# constrained targets later in the porting story).
tiny: CFLAGS := -Os -Wall -Wextra -std=c99 -Wno-unused-parameter
tiny: clean $(BIN)
	@$(MAKE) size

size: $(BIN)
	@size $(BIN)
	@stat -c '  binary: %s bytes' $(BIN) 2>/dev/null || \
	  stat -f '  binary: %z bytes' $(BIN)

clean:
	rm -f $(OBJS) $(BIN) $(ISLANDS) $(ISLANDS_NOMPI) $(OMP_BIN)
