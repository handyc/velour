CC      ?= cc
CFLAGS  ?= -DTINY -std=c99 -Os -Wall -Wextra \
           -fno-stack-protector \
           -fno-asynchronous-unwind-tables \
           -fno-unwind-tables \
           -fno-builtin -ffreestanding \
           -ffunction-sections -fdata-sections
LDFLAGS ?= -nostdlib -nostartfiles -static \
           -Wl,--gc-sections -Wl,--build-id=none -Wl,-z,noseparate-code -s

office: office.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office: $$(stat -c %s $@) bytes"

clean:
	rm -f office outbox.txt canvas.txt

.PHONY: clean
