# Build the cellular distillation. cc -O2 is the only requirement.
CC      ?= cc
CFLAGS  ?= -O2 -std=c99 -Wall

cellular: cellular_c.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f cellular

run: cellular
	./cellular

.PHONY: clean run
