CC      ?= cc
CFLAGS  ?= -DTINY -std=c99 -Os -Wall -Wextra \
           -fno-stack-protector \
           -fno-asynchronous-unwind-tables \
           -fno-unwind-tables \
           -fno-builtin -ffreestanding \
           -ffunction-sections -fdata-sections
LDFLAGS ?= -nostdlib -nostartfiles -static \
           -Wl,--gc-sections -Wl,--build-id=none -Wl,-z,noseparate-code -s

wnnr: wnnr.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@# Safe strips only: drop the gcc version stamp.
	@# Keep .note.gnu.property — some loaders (kernels with CET
	@# enforcement) refuse to exec a binary that doesn't carry it.
	@# Keep the section header table — older kernels' binfmt_elf
	@# treats e_shoff = 0 as malformed even though the ELF spec
	@# says section headers are optional for execution.
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "wnnr: $$(stat -c %s $@) bytes"

# Tiny target: more aggressive strip. May fail to exec on older
# Linux kernels (< 4.x) and on systems with strict CET enforcement.
# If it doesn't run for you, fall back to plain `make`.
tiny: wnnr.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o wnnr $<
	@strip --remove-section=.comment --remove-section=.note.gnu.property wnnr 2>/dev/null || true
	@strip --strip-section-headers wnnr 2>/dev/null || true
	@echo "wnnr (tiny): $$(stat -c %s wnnr) bytes"

clean:
	rm -f wnnr wnnr.bak savepoint

.PHONY: clean tiny
