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

VERSIONS = office office2 office3 office4 office5 office6 office7 office8 office9 office10 office11 office12 office13 office14 office15 office16
DBG      = $(addsuffix .dbg,$(VERSIONS)) minimal.dbg

all: $(VERSIONS) minimal jail
dbg: $(DBG) jail.dbg

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

office8: office8.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office8: $$(stat -c %s $@) bytes"

office9: office9.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office9: $$(stat -c %s $@) bytes"

office10: office10.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office10: $$(stat -c %s $@) bytes"

office11: office11.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office11: $$(stat -c %s $@) bytes"

office12: office12.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office12: $$(stat -c %s $@) bytes"

office13: office13.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office13: $$(stat -c %s $@) bytes"

office14: office14.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office14: $$(stat -c %s $@) bytes"

office15: office15.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office15: $$(stat -c %s $@) bytes"

office16: office16.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office16: $$(stat -c %s $@) bytes"

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

# Namespace launcher used by office7's garden preview.  Sibling
# binary, not part of the suite — kept out of the office.c → office7.c
# fork lineage so the suite stays single-file.
jail: jail.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "jail: $$(stat -c %s $@) bytes"
jail.dbg: jail.c
	$(CC) $(CFLAGS) $(DBGFLAGS) -o $@ $<

clean:
	rm -f office office2 office3 office4 office5 office6 office7 office8 office9 office10 office11 office12 office13 office14 office15 office16 \
	      minimal jail $(DBG) jail.dbg \
	      outbox.txt canvas.txt office*.conf garden.bin hxhnt.seed hxhnt_winner_*.seed hxh-*

.PHONY: all dbg clean
