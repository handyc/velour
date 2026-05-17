# Build the workspace template ELFs.  Each app must fit in 4096 bytes
# after `strip`; the pad rule appends NUL bytes so the on-disk file is
# *exactly* 4096 bytes (one hexhunter slot).

# Office-suite minification recipe — combines code and data on a single
# page (-z noseparate-code), shrinks the page-alignment slack
# (common-page-size=512), and strips every chunk of metadata we don't
# need (build-id, unwind tables, comments).  Without these tricks the
# absolute minimum ELF is ~9 KB; with them, ~700 B + payload.
CFLAGS  = -DTINY -std=c99 -Os -fno-builtin -ffreestanding \
          -fno-stack-protector -fno-asynchronous-unwind-tables \
          -fno-unwind-tables -ffunction-sections -fdata-sections \
          -fno-pie -no-pie
LDFLAGS = -nostdlib -nostartfiles -static \
          -Wl,--gc-sections -Wl,--build-id=none \
          -Wl,-z,noseparate-code -Wl,-z,common-page-size=512 -s

APPS = app0_greeter app1_mandel app2_caview

.PHONY: all clean check
all: $(APPS:=.elf)

%.elf: %.c
	gcc $(CFLAGS) $(LDFLAGS) -o $@.raw $<
	@strip --remove-section=.comment --remove-section=.note.gnu.property $@.raw 2>/dev/null || true
	@sz=$$(stat -c %s $@.raw); \
	  echo "  raw $$sz B"; \
	  if [ $$sz -gt 4096 ]; then \
	    echo "ERROR: $@.raw is $$sz B, exceeds 4096"; rm $@.raw; exit 1; fi
	@dd if=$@.raw of=$@ bs=4096 count=1 conv=sync 2>/dev/null
	@chmod +x $@
	@rm $@.raw
	@echo "  $@ padded to 4096 B"

check: all
	@for a in $(APPS); do \
	  echo "[$$a]"; \
	  ./$$a.elf || true; \
	  printf '\n  size: %s B\n' $$(stat -c %s $$a.elf); \
	done

clean:
	rm -f *.elf *.raw
