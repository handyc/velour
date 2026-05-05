CC      ?= cc
CFLAGS  ?= -DTINY -std=c99 -Os -Wall -Wextra \
           -fno-stack-protector \
           -fno-asynchronous-unwind-tables \
           -fno-unwind-tables \
           -fno-builtin -ffreestanding \
           -ffunction-sections -fdata-sections
# Shipping flags (stripped, smallest binary).
LDFLAGS ?= -nostdlib -nostartfiles -static \
           -Wl,--gc-sections -Wl,--build-id=none -Wl,-z,noseparate-code \
           -Wl,-z,common-page-size=512 -s
# Analysis flags — same minimisation, but symbols preserved so nm/objdump
# can attribute bytes to features.  Used by the officelab Django app.
DBGFLAGS ?= -nostdlib -nostartfiles -static \
            -Wl,--gc-sections -Wl,--build-id=none -Wl,-z,noseparate-code \
            -Wl,-z,common-page-size=512

VERSIONS = office office2 office3 office4 office5 office6 office7
DBG      = $(addsuffix .dbg,$(VERSIONS)) minimal.dbg

all: $(VERSIONS) minimal
dbg: $(DBG)

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

office4: office4.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office4: $$(stat -c %s $@) bytes"

office5: office5.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office5: $$(stat -c %s $@) bytes"

office6: office6.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office6: $$(stat -c %s $@) bytes"

office7: office7.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office7: $$(stat -c %s $@) bytes"

# Unstripped twins for the officelab analyser.  Same source, same
# CFLAGS, same LDFLAGS *minus* `-s` so nm can see every function.
%.dbg: %.c
	$(CC) $(CFLAGS) $(DBGFLAGS) -o $@ $<

# Empty-program baseline so officelab can subtract the "Linux ELF +
# raw _start + syscall stub" overhead from feature attribution.
# We build both a stripped binary (for the on-disk baseline number)
# and an unstripped twin (so nm sees the syscall stub + _start).
minimal: minimal.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "minimal: $$(stat -c %s $@) bytes"
minimal.dbg: minimal.c
	$(CC) $(CFLAGS) $(DBGFLAGS) -o $@ $<

clean:
	rm -f office office2 office3 office4 office5 office6 office7 \
	      minimal $(DBG) outbox.txt canvas.txt office7.conf garden.bin

.PHONY: all dbg clean
