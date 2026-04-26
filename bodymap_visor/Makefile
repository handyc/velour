CC       ?= gcc
CFLAGS   ?= -O2 -g -Wall -Wextra -Wno-unused-parameter -std=c11
CPPFLAGS := $(shell pkg-config --cflags libdrm gbm egl glesv2 libcurl libcjson)
LDLIBS   := $(shell pkg-config --libs   libdrm gbm egl glesv2 libcurl libcjson) -lm

SRC := src/main.c src/kms.c src/net.c src/world.c src/stereo.c src/pose.c
OBJ := $(SRC:.c=.o)

aether-visor: $(OBJ)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(OBJ) $(LDLIBS)

%.o: %.c
	$(CC) $(CFLAGS) $(CPPFLAGS) -c -o $@ $<

clean:
	rm -f aether-visor $(OBJ)

# Build dependencies (Debian / Raspberry Pi OS):
#     sudo apt install -y libdrm-dev libgbm-dev libegl1-mesa-dev \
#         libgles2-mesa-dev libcurl4-openssl-dev libcjson-dev pkg-config

.PHONY: clean
