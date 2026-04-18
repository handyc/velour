CC       ?= gcc
CFLAGS   ?= -O2 -g -Wall -Wextra -Wno-unused-parameter -std=c11
CPPFLAGS := $(shell pkg-config --cflags libdrm gbm egl glesv2)
LDLIBS   := $(shell pkg-config --libs   libdrm gbm egl glesv2) -lm

SRC := src/main.c src/kms.c
OBJ := $(SRC:.c=.o)

aether-visor: $(OBJ)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(OBJ) $(LDLIBS)

%.o: %.c
	$(CC) $(CFLAGS) $(CPPFLAGS) -c -o $@ $<

clean:
	rm -f aether-visor $(OBJ)

.PHONY: clean
