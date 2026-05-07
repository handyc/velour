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

VERSIONS = office office2 office3 office4 office5 office6 office7 office8 office9 office10 office11 office12 office13 office14 office15 office16 office17 office18 office19 office20 office21 office22 office23 office24 office25 office26 office27 office28 office29 office30 office31 office32 office33 office34 office35 office36 office37 office38 office39 office40 office41 office42
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

office17: office17.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office17: $$(stat -c %s $@) bytes"

# office18 grows by ~4 KB for the .hxseed embedded payload.  Don't
# strip --remove-section=.hxseed obviously, and instruct ld to keep
# it via the implicit "orphan section" rules (the static const data
# is enough).
office18: office18.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office18: $$(stat -c %s $@) bytes"

office19: office19.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office19: $$(stat -c %s $@) bytes"

office20: office20.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office20: $$(stat -c %s $@) bytes"

office21: office21.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office21: $$(stat -c %s $@) bytes"

office22: office22.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office22: $$(stat -c %s $@) bytes"

office23: office23.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office23: $$(stat -c %s $@) bytes"

office24: office24.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office24: $$(stat -c %s $@) bytes"

office25: office25.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office25: $$(stat -c %s $@) bytes"

office26: office26.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office26: $$(stat -c %s $@) bytes"

office27: office27.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office27: $$(stat -c %s $@) bytes"

office28: office28.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office28: $$(stat -c %s $@) bytes"

office29: office29.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office29: $$(stat -c %s $@) bytes"

office30: office30.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office30: $$(stat -c %s $@) bytes"

office31: office31.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office31: $$(stat -c %s $@) bytes"

office32: office32.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office32: $$(stat -c %s $@) bytes"

office33: office33.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office33: $$(stat -c %s $@) bytes"

office34: office34.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office34: $$(stat -c %s $@) bytes"

office35: office35.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office35: $$(stat -c %s $@) bytes"

office36: office36.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office36: $$(stat -c %s $@) bytes"

office37: office37.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office37: $$(stat -c %s $@) bytes"

office38: office38.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office38: $$(stat -c %s $@) bytes"

office39: office39.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office39: $$(stat -c %s $@) bytes"

office40: office40.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office40: $$(stat -c %s $@) bytes"

office41: office41.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office41: $$(stat -c %s $@) bytes"

office42: office42.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office42: $$(stat -c %s $@) bytes"

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
	rm -f office office2 office3 office4 office5 office6 office7 office8 office9 office10 office11 office12 office13 office14 office15 office16 office17 office18 office19 office20 office21 office22 office23 office24 office25 office26 office27 office28 office29 office30 office31 office32 office33 office34 office35 office36 office37 office38 office39 office40 office41 office42 \
	      minimal jail $(DBG) jail.dbg \
	      outbox.txt canvas.txt office*.conf garden.bin hxhnt.seed hxhnt_winner_*.seed hxh-*

.PHONY: all dbg clean
