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

VERSIONS = office office2 office3 office4 office5 office6 office7 office8 office9 office10 office11 office12 office13 office14 office15 office16 office17 office18 office19 office20 office21 office22 office23 office24 office25 office26 office27 office28 office29 office30 office31 office32 office33 office34 office35 office36 office37 office38 office39 office40 office41 office42 office43 office44 office45 office46 office47 office48 office49 office50 office51 office52 office53 office54 office55 office56 office57 office58 office59 office60 office61 office62 office63 office64 office65 office66 \
           officetiny officeproductivity officeresearcher officegamer officesysadmin officehoneypot \
           supercell officex officeagent officesoul officetiles officemandel officemandelshot officemangel officemangel2 officemangel3 officemangel4 officemangel5 officemangel6
DBG      = $(addsuffix .dbg,$(VERSIONS)) minimal.dbg

all: $(VERSIONS) minimal jail officesoulmin soulvote
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

office43: office43.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office43: $$(stat -c %s $@) bytes"

office44: office44.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office44: $$(stat -c %s $@) bytes"

office45: office45.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office45: $$(stat -c %s $@) bytes"

office46: office46.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office46: $$(stat -c %s $@) bytes"

office47: office47.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office47: $$(stat -c %s $@) bytes"

office48: office48.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office48: $$(stat -c %s $@) bytes"

office49: office49.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office49: $$(stat -c %s $@) bytes"

office50: office50.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office50: $$(stat -c %s $@) bytes"

office51: office51.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office51: $$(stat -c %s $@) bytes"

office52: office52.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office52: $$(stat -c %s $@) bytes"

office53: office53.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office53: $$(stat -c %s $@) bytes"

office54: office54.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office54: $$(stat -c %s $@) bytes"

office55: office55.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office55: $$(stat -c %s $@) bytes"

office56: office56.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office56: $$(stat -c %s $@) bytes"

office57: office57.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office57: $$(stat -c %s $@) bytes"

office58: office58.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office58: $$(stat -c %s $@) bytes"

office59: office59.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office59: $$(stat -c %s $@) bytes"

office60: office60.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office60: $$(stat -c %s $@) bytes"

office61: office61.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office61: $$(stat -c %s $@) bytes"

office62: office62.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office62: $$(stat -c %s $@) bytes"

office63: office63.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office63: $$(stat -c %s $@) bytes"

office64: office64.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office64: $$(stat -c %s $@) bytes"

office65: office65.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office65: $$(stat -c %s $@) bytes"

# office66: full build (every OFFICE_FEATURE_* defaults to 1).  The
# `office66-lite` target shows how to override the defaults to drop
# all the Tier-1..Tier-5 network code + the heaviest apps and produce
# a sub-64-KB binary.
office66: office66.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office66: $$(stat -c %s $@) bytes"

office67: office67.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office67: $$(stat -c %s $@) bytes"

office68: office68.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office68: $$(stat -c %s $@) bytes"

office66-lite: office66.c
	$(CC) $(CFLAGS) \
	    -DOFFICE_FEATURE_RPG=0      \
	    -DOFFICE_FEATURE_HXHNT=0    \
	    -DOFFICE_FEATURE_ASK=0      \
	    -DOFFICE_FEATURE_NET=0      \
	    -DOFFICE_FEATURE_HTTP=0     \
	    -DOFFICE_FEATURE_ECHO=0     \
	    -DOFFICE_FEATURE_FINGER=0   \
	    -DOFFICE_FEATURE_GOPHER=0   \
	    -DOFFICE_FEATURE_PROBE=0    \
	    -DOFFICE_FEATURE_DNS=0      \
	    -DOFFICE_FEATURE_FTP=0      \
	    -DOFFICE_FEATURE_SSHTEL=0   \
	    $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "office66-lite: $$(stat -c %s $@) bytes"

# Pre-baked named variants — each is a full self-contained source
# that's a copy of office66.c with the OFFICE_FEATURE_* matrix hard-
# set to one of OfficeForge's presets (Tiny / Productivity / Researcher
# / Gamer / Sysadmin / Honeypot).  They build like any other office
# fork and can be edited independently from here on.
officetiny: officetiny.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officetiny: $$(stat -c %s $@) bytes"

officeproductivity: officeproductivity.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officeproductivity: $$(stat -c %s $@) bytes"

officeresearcher: officeresearcher.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officeresearcher: $$(stat -c %s $@) bytes"

officegamer: officegamer.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officegamer: $$(stat -c %s $@) bytes"

officesysadmin: officesysadmin.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officesysadmin: $$(stat -c %s $@) bytes"

officehoneypot: officehoneypot.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officehoneypot: $$(stat -c %s $@) bytes"

officemandel: officemandel.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officemandel: $$(stat -c %s $@) bytes"

# One-shot random Mandelbrot snapshot.  Picks a curated center + a
# random log-span, renders, exits.  No keyboard, no raw mode.
officemandelshot: officemandelshot.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officemandelshot: $$(stat -c %s $@) bytes"

# Mangler: full-screen shot + N (default 10) random shrunken pastes.
# argv[1] sets N.  Same RNG + curated centers as officemandelshot.
officemangel: officemangel.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officemangel: $$(stat -c %s $@) bytes"

# Mangler v2: randomised iter→colour map per shot.
officemangel2: officemangel2.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officemangel2: $$(stat -c %s $@) bytes"

# Mangler v3: live + paced.  Initial shot + one mangel per second
# until 'q' / 'Q' / Ctrl-C.  Pacing is done in termios (VMIN=0
# VTIME=10) so the kernel tty timer is the only clock.
officemangel3: officemangel3.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officemangel3: $$(stat -c %s $@) bytes"

# Mangler v4: truecolour palettes derived from 4 random RGB bases
# per shot.  4 ramps of 64 entries each, 4 base + 252 derived = 256.
officemangel4: officemangel4.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officemangel4: $$(stat -c %s $@) bytes"

# Mangler v5: dominant palette slot per shot renders as transparent
# (cells whose both halves match the slot emit CSI 1C and leave the
# underlying screen pixels intact).  Histogram pre-pass picks the
# slot before the render pass.
officemangel5: officemangel5.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officemangel5: $$(stat -c %s $@) bytes"

# Mangler v6: keeps an in-memory shadow buffer of every painted half-
# pixel, then every tick exports a random 64×64-cell slice as
# mangel-YYYYMMDD-HHMMSS.ans.  cat the .ans in a truecolour terminal
# to see the snapshot.
officemangel6: officemangel6.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officemangel6: $$(stat -c %s $@) bytes"

PRESETS = officetiny officeproductivity officeresearcher \
          officegamer officesysadmin officehoneypot

presets: $(PRESETS)

# Hand-edited fork of office64 with notepad+sheet+files+ask+rpg+
# hxhnt+lsys, calc merged into sheet, plus a 4 KB persistent system-
# prompt slot for the LLM client.  Not built from OFFICE_FEATURE_*
# toggles; just an independent .c file that's free to diverge.
supercell: supercell.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "supercell: $$(stat -c %s $@) bytes"

# Tighter sibling of supercell — drops ask + the standalone hxhnt
# and lsys menu entries; rpg, hxhnt's CA/GA engine, and L-system
# sprite expansion are merged into a single app called `xpg`.
# Core productivity (notepad/sheet/hex/files/calc-via-sheet) plus
# xpg, nothing else.
officex: officex.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officex: $$(stat -c %s $@) bytes"

# Toy "Claude Code" classroom build.  6 visible apps:
# shell + sheet(+calc) + xpg + ask + prompt + coder.  coder is an
# iterative LLM-driven C generator with 4 × 4 KB persistent
# memory banks (personality / recent / longterm / project).
officeagent: officeagent.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officeagent: $$(stat -c %s $@) bytes"

# Embedded 25 K-parameter int8 transformer (port of
# gizmo64k/soulplayer-c64).  The whole soul + tokenizer + inference
# loop ships in one ELF — no runtime file I/O.  soul_data.h is
# generated by `python3 gen_soul_data.py` from a soul.bin /
# tokenizer.json pair (default: ../soulplayer/).  Re-train via the
# upstream train.py and re-bake to swap the soul.
officesoul: officesoul.c soul_data.h
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officesoul: $$(stat -c %s $@) bytes"

# Headless soul: same model, no Win95 chrome / banks / tdb / shell.
# Drop-in for piped use and the soulvote ensemble orchestrator.
officesoulmin: officesoulmin.c soul_data.h
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officesoulmin: $$(stat -c %s $@) bytes"

# N-agent ensemble over officesoulmin.  Forks N children with
# different --seed, votes per token position.  No isolation here —
# jail wrap-up is a separate fork once the ensemble proves out.
soulvote: soulvote.c soul_data.h
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "soulvote: $$(stat -c %s $@) bytes"

soul_data.h: gen_soul_data.py
	python3 gen_soul_data.py

# Wang tile generator + tessellator (sibling of officesoul).
# Self-contained; no runtime deps on the others, but `:dwell`
# inside officetiles exec's ./officesoul if present.
officetiles: officetiles.c
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $<
	@strip --remove-section=.comment $@ 2>/dev/null || true
	@echo "officetiles: $$(stat -c %s $@) bytes"

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
	rm -f office office2 office3 office4 office5 office6 office7 office8 office9 office10 office11 office12 office13 office14 office15 office16 office17 office18 office19 office20 office21 office22 office23 office24 office25 office26 office27 office28 office29 office30 office31 office32 office33 office34 office35 office36 office37 office38 office39 office40 office41 office42 office43 office44 office45 office46 office47 office48 office49 office50 office51 office52 office53 office54 office55 office56 office57 office58 office59 office60 office61 office62 office63 office64 office65 office66 office66-lite \
	      $(PRESETS) supercell officex officeagent officesoul officetiles \
	      minimal jail $(DBG) jail.dbg \
	      outbox.txt canvas.txt office*.conf garden.bin hxhnt.seed hxhnt_winner_*.seed hxh-*

.PHONY: all dbg clean
