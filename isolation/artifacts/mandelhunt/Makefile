# mandelhunt — C-port mass-scale fractal quine hunt.
#
# Combines officemandel (Mandelbrot rendering) with hexhunter
# (class-4 hex-CA classification) to mass-scan fractal regions
# for class-4 / Ouroboros-quine LUT candidates.
#
# Build:  make
# Smoke:  make smoke
# Run:    ./mandelhunt -h 4 -o pool/

CC      ?= cc
CFLAGS  ?= -std=c99 -O2 -Wall -D_POSIX_C_SOURCE=2
LDFLAGS ?= -lm

mandelhunt: mandelhunt.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

# 30-second smoke that exercises every code path.
smoke: mandelhunt
	rm -rf /tmp/mandelhunt_smoke
	./mandelhunt -h 0.01 -o /tmp/mandelhunt_smoke -r 50
	@echo "--- saved candidates: ---"
	@ls /tmp/mandelhunt_smoke | head
	@echo "--- leaderboard summary: ---"
	@cat /tmp/mandelhunt_smoke/leaderboard.json | head -20

clean:
	rm -f mandelhunt
