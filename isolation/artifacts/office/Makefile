CC      ?= cc
CFLAGS  ?= -DTINY -std=c99 -Os -Wall -Wextra \
           -fno-stack-protector \
           -fno-asynchronous-unwind-tables \
           -fno-unwind-tables \
           -fno-builtin -ffreestanding \
           -ffunction-sections -fdata-sections
LDFLAGS ?= -nostdlib -nostartfiles -static \
           -Wl,--gc-sections -Wl,--build-id=none -Wl,-z,noseparate-code \
           -Wl,-z,common-page-size=512 -s

all: office office2 office3

office: office.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office: $$(stat -c %s $@) bytes"

office2: office2.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office2: $$(stat -c %s $@) bytes"

office3: office3.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office3: $$(stat -c %s $@) bytes"

clean:
	rm -f office office2 office3 outbox.txt canvas.txt

.PHONY: clean
