# HexNN portable C engine — Linux CLI build.
#
# This is the seed driver; the engine itself (engine.c + engine.h) has
# zero platform deps and is meant to be reused unchanged by other
# drivers (MPI islands, Arduino-ESP32, WASM/emscripten, xcc700).

CC      ?= gcc
CFLAGS  ?= -O3 -Wall -Wextra -Wpedantic -std=c99
LDFLAGS ?=

# Quiet a couple of GCC pedantic warnings that don't apply to clean
# C99 code we care about. -Wno-unused-parameter for the on_gen ABI.
CFLAGS  += -Wno-unused-parameter

BIN  := hexnn
SRCS := engine.c cli_linux.c
OBJS := $(SRCS:.c=.o)

.PHONY: all clean tiny size

all: $(BIN)

$(BIN): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $(OBJS) $(LDFLAGS)

%.o: %.c engine.h
	$(CC) $(CFLAGS) -c -o $@ $<

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
	rm -f $(OBJS) $(BIN)
