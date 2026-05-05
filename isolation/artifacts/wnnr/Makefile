CC      ?= cc
CFLAGS  ?= -std=c99 -Os -Wall -Wextra \
           -fno-stack-protector \
           -fno-asynchronous-unwind-tables \
           -fno-unwind-tables \
           -fno-builtin -ffreestanding \
           -ffunction-sections -fdata-sections
LDFLAGS ?= -nostdlib -nostartfiles -static \
           -Wl,--gc-sections -Wl,--build-id=none -Wl,-z,noseparate-code -s

wnnr: wnnr.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment --remove-section=.note.gnu.property $@ 2>/dev/null || true
	@strip --strip-section-headers $@ 2>/dev/null || true
	@echo "wnnr: $$(stat -c %s $@) bytes"

clean:
	rm -f wnnr wnnr.bak savepoint

.PHONY: clean
