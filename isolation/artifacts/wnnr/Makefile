CC      ?= cc
CFLAGS  ?= -std=c99 -O2 -Wall -Wextra -Wpedantic

wnnr: wnnr.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f wnnr savepoint

.PHONY: clean
