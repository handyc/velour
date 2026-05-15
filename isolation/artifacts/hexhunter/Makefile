# hexhunter — reusable library form of the original ./hunter program.
#
#   make           # build static lib + cli + test runner
#   make test      # build + run the unit tests
#   make clean

CC      ?= cc
CFLAGS  ?= -O2 -Wall -Wextra -std=c99
AR      ?= ar

LIB     := libhexhunter.a
LIB_OBJ := hexhunter.o

CLI     := hh_cli
TEST    := test_hexhunter

all: $(LIB) $(CLI) $(TEST)

$(LIB): $(LIB_OBJ)
	$(AR) rcs $@ $^

$(LIB_OBJ): hexhunter.c hexhunter.h
	$(CC) $(CFLAGS) -c hexhunter.c -o $@

$(CLI): cli.c $(LIB)
	$(CC) $(CFLAGS) cli.c $(LIB) -o $@

$(TEST): test_hexhunter.c $(LIB)
	$(CC) $(CFLAGS) test_hexhunter.c $(LIB) -o $@

test: $(TEST)
	./$(TEST)

clean:
	rm -f $(LIB) $(LIB_OBJ) $(CLI) $(TEST) winner.bin

.PHONY: all test clean
