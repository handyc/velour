"""Seed the Velour Quine Keychain assembly + operations manual.

Creates one Manual with ~16 sections covering hardware bill of
materials, firmware build, host setup, sync, tagging, clocks,
archive snapshots, and reference appendices.

Usage:

    venv/bin/python manage.py seed_keychain_manual
        Idempotent — re-runs update existing sections rather than
        duplicating.

    venv/bin/python manage.py seed_keychain_manual --rebuild
        Drop and recreate the manual from scratch.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from codex.models import Manual, Section


MANUAL_SLUG = 'velour-quine-keychain'


# ─── Section bodies ──────────────────────────────────────────────────
#
# Each tuple: (slug, sort_order, title, body_markdown, sidenotes).
# Bodies use codex's markdown subset: # ## ### headings, paragraphs,
# "- " bullets, **bold**, *italic*, inline `code`, ``` fenced blocks.

SECTIONS = [
    (
        'about-the-keychain', 10, 'About the Keychain',
        """The Velour Quine Keychain is a USB pendant built on an ESP32-S3 SuperMini whose only job is to remember 16,384 bytes.  Those bytes are a *class-4 quine*: a hexagonal cellular-automaton rule that, when iterated, sits at the edge of chaos and reproduces structurally-similar states for tens of generations.  The device exposes the bytes over USB-CDC.  Nothing more.

What this enables is a small change in how you store data.  The host CLI takes the seed and deterministically regenerates a 16 MiB binary "database" — sixty-four chain levels of 256 KiB each, every byte recoverable from the same 16 KiB.  You do not back up the database.  You back up the device, or any copy of the seed file.

On the host filesystem only the *tags* persist: byte-range annotations into the regenerable stream.  Files in the conventional sense do not exist; they are extracted on demand.  The seed travels with the device, the tags travel with the host, and the bytes are derived.  Lose the keychain and the host has annotations into nothing.  Lose the host and the keychain is sixteen kilobytes of noise on a lanyard.  Together they reconstruct a working archive.""",
        """The seed itself fits comfortably in a QR code; the keychain is a convenience, not a secret-management device.
"Class-4" follows Wolfram's informal classification; we screen for it via activity, structural recurrence, and chain depth, not by appeal to authority.""",
    ),
    (
        'theory-of-operation', 20, 'Theory of Operation',
        """The seed is a lookup table for a K=4 hexagonal cellular automaton over a 7-cell neighbourhood.  The neighbourhood has `4^7 = 16,384` possible configurations, so the entire rule fits in 16,384 bytes — one output state per input.  This is not a coincidence we exploit; it is the property that makes the rule its own initial condition.

Reshape the 16,384 cells as a `128 x 128` grid.  The rule is now an image, and the image is now a rule.  Run the CA on itself for `t` ticks and you get another 16,384 bytes which, in turn, is another rule.  A *class-4* seed is one for which this iterated self-application stays structurally rich for many generations rather than collapsing to a fixed point (class 1), a limit cycle (class 2), or undifferentiated noise (class 3).

The host CLI exploits this directly.  Starting from the seed at *level 0*, it ticks the rule forward by a fixed number of generations to produce level 1, packs the result into 256 KiB (four K=4 cells per byte, since `4^4 = 256`), then uses *level 1* as the rule for *level 2*, and so on, for 64 levels.  The total output is `64 * 256 KiB = 16 MiB` of bytes that are completely determined by the seed and the chain parameters.  Re-run the chain on a different machine, in a different decade, with the same seed and the same parameters, and you get the same 16 MiB.

Determinism comes from three pinned things: the seed, the chain parameters (tick count per level, neighbourhood ordering, pack order), and the rule evaluator.  The first lives on the device.  The second and third live in the host code and are versioned.  Anything that breaks byte-for-byte reproduction is therefore a bug, not a feature, and the `verify` subcommand exists to catch it.""",
        """The packed K=4 layout means byte offset n in level L decodes to four cells at positions 4n..4n+3 of the level grid, in that order.
If you want to inspect a level visually, reshape its 262,144 cells as 512x512 and map K=4 to a four-colour palette.""",
    ),
    (
        'bill-of-materials', 30, 'Bill of Materials',
        """The keychain is intentionally a one-board build.  Total parts cost is well under five euro at the time of writing.

- **ESP32-S3 SuperMini board**, approximately three to four euro from the usual sources.  The critical features are the built-in USB-Serial-JTAG controller (no external USB chip to drive separately) and at least 4 MB of SPI flash.  PSRAM is *not* required; the seed and the resident firmware fit comfortably in internal SRAM.  Avoid the "ESP32-C3 SuperMini" lookalike unless you intend to port the firmware — the CDC stack and USB descriptors differ.
- **USB-C data-capable cable**.  This is the part most often missed.  Many cables shipped with phone chargers and battery banks are charge-only: the data pairs are simply not wired.  If your host does not see a CDC device on plug-in, swap the cable before debugging anything else.
- **Heat-shrink tubing**, optional but recommended.  A short length of clear or black 20 mm-flat tubing slid over the back of the SuperMini protects the exposed pads and components from pocket lint, keys, and skin oils.  Leave the USB connector and the keychain hole exposed.
- **Split-ring or lanyard**, whichever you prefer.  The SuperMini has a hole at the end opposite the USB connector that fits a standard 15 mm split-ring directly.  A 1 mm paracord lanyard threaded through the same hole works for badge-clip carriers.
- **Enclosure**, optional.  A small zip-lock pouch is sufficient for prototypes.  A 3D-printed two-piece snap case in PETG (wall thickness 1.2 mm) is the long-term option; STL files are not in scope for this manual.

Total assembled weight is approximately three grams.""",
        """The 4 MB flash limit is fine: the firmware image is under 1 MB and the seed is 16 KiB. Anything else is wasted partition space.
A jeweller's loupe is useful for confirming the board really is an S3 and not a C3 — the silkscreen is small.""",
    ),
    (
        'host-software-setup', 40, 'Host Software Setup',
        """This section assumes a working Velour checkout with the project virtualenv activated.  If you have reached this manual by way of `/codex/`, you already have all of the above.

Three additional pieces of software are required on the host.

First, `pyserial`.  This is already declared in Velour's requirements and should be importable as `serial` from the project virtualenv.  Confirm with:

```
venv/bin/python -c "import serial; print(serial.__version__)"
```

If the import fails, run `venv/bin/pip install pyserial` and try again.

Second, **PlatformIO Core**, used to build and flash the firmware.  The simplest installation path is into the same virtualenv:

```
venv/bin/pip install platformio
```

This pulls in the `pio` and `platformio` console scripts.  Alternatively, install the PlatformIO IDE extension into VS Code and use `~/.platformio/penv/bin/pio` directly.  Either works; the manual assumes the first.

On **Linux**, your user must belong to the `dialout` group (Debian/Ubuntu derivatives) or `uucp` (Arch) to open `/dev/ttyACM*` without sudo.  Check with `groups`.  If `dialout` is missing:

```
sudo usermod -aG dialout $USER
```

Log out and back in for the change to take effect.

On **macOS**, the USB-Serial-JTAG interface on the S3 enumerates as a native CDC device and does not need a vendor driver.  Look for the device under `/dev/cu.usbmodem*`.

On **Windows**, recent builds ship a generic USB-CDC driver that binds to the S3 automatically.  The device appears as `COMn` in Device Manager under *Ports (COM & LPT)*.""",
        """PlatformIO downloads its toolchain on first use, not on install; expect roughly 200 MB of download the first time you run `pio run`.
The dialout group quirk is the single most common reason a newcomer reports "the CLI hangs" on Linux.""",
    ),
    (
        'choose-a-seed', 50, 'Choose a Seed',
        """The seed is a class-4 hex CA rule.  Velour already maintains a population of these in the `caformer.ComponentChampion` table with `component_slug='class4_quine'`, scored on several metrics.  You do not need to evolve your own.

To inspect the available candidates, browse `/spoeqi/quine/` in the running Velour instance.  Each row lists a primary key, the SHA-256 of the 16 KiB ruleset, three fitness numbers (self-reproduction `sr`, class-4 indicator `c4`, activity `act`), and the *chain depth* — the number of chain levels for which the iterated rule remains class-4 before collapsing.

For the keychain you want a candidate with high chain depth, not necessarily the highest raw fitness.  Fitness scores measure rule-on-self behaviour at a single level; chain depth measures the more relevant quantity, which is how many of the 64 chain levels produce structurally interesting bytes before degenerating into a fixed point or pure noise.  A rule with `sr=0.99` and chain depth 3 is worse for our purpose than a rule with `sr=0.82` and chain depth 29.

At the time of writing, **PK 110** is the recommended default.  It has 64 distinct chain levels with no cycle within depth 64, 41 of which are class-4 by the strict criterion, `sr` around 0.60, and activity around 0.55.

If you intend to use a different candidate, note its primary key.  You will pass it to `keychain_provision` in the next section.  There is no harm in flashing several different seeds onto different boards; each device's identity is its seed SHA, and the host index keys off that.""",
        """There is currently no `keychain list-quines` subcommand; the inspection workflow is via `/spoeqi/quine/` in the browser.
Chain depth is measured by actually running the chain; it is not predicted from fitness scores, which are too unreliable.""",
    ),
    (
        'bake-the-seed-into-firmware', 60, 'Bake the Seed into Firmware',
        """Once you have chosen a `ComponentChampion` primary key, write its 16,384 bytes to the firmware project's data directory:

```
venv/bin/python manage.py keychain_provision 110
```

The command does three things.  It loads the `ComponentChampion` row, materialises the 16,384-byte rules blob, and writes it to:

```
isolation/artifacts/keychain_quine/data/seed.bin
```

It also emits the SHA-256 of the written file to stdout.  Confirm the printed hash matches what `/spoeqi/quine/` showed for that PK.  A mismatch indicates the seed has been edited by hand or a re-pack bug; do not flash a board with an unverified seed, because the host CLI keys every tag and clock off `seed_sha256`, and an unexpected hash will silently desynchronise every future operation.

Example output:

```
wrote 16,384 bytes -> isolation/artifacts/keychain_quine/data/seed.bin
  seed sha256 = 8f2c1a4b9d0e7f3c2a1b6e8d4c9f0a3b...
  quine #110  fit=0.6051

Next: cd isolation/artifacts/keychain_quine && pio run -t upload
```

The `seed.bin` file is embedded directly into the firmware image via PlatformIO's `board_build.embed_files`, not via a SPIFFS or LittleFS partition.  This means the seed lives in the read-only program image alongside the code, and the device has no writable filesystem to corrupt.  To change the seed you re-provision and reflash; there is no on-device update path, by design.""",
        """Re-running keychain_provision with a different PK overwrites seed.bin without prompting.
The seed.bin file is gitignored by default — commit it to a private branch if you want a paper trail of which device got which seed.""",
    ),
    (
        'build-and-flash-firmware', 70, 'Build and Flash Firmware',
        """With `seed.bin` in place, change into the firmware project and build.

```
cd isolation/artifacts/keychain_quine
pio run -t upload
```

The first invocation downloads the Espressif toolchain and the Arduino-ESP32 framework, totalling roughly 200 MB into `~/.platformio/`.  Subsequent builds are incremental and complete in a few seconds.  The default `platformio.ini` targets `board = esp32-s3-devkitc-1`, which the SuperMini is binary-compatible with for our purposes.

If `pio` cannot find the board, plug the device in via a known-good data cable and re-run with `--upload-port`:

```
pio run -t upload --upload-port /dev/ttyACM0
```

To watch the boot banner, open the device monitor in a second terminal:

```
pio device monitor -b 115200
```

A successful boot produces output similar to:

```
ESP-ROM:esp32s3-...
SPIWP:0xee
mode:DIO, clock div:1
...
VELOUR-KEYCHAIN v1 sha=8f2c1a4b9d0e7f3c2a1b6e8d4c9f0a3b5d7e1c2f4a6b8d0e3c5f7a9b1d4e6c8f
```

The 64-hex-digit string after `sha=` is the SHA-256 of the embedded `seed.bin`.  Cross-check it against what `keychain_provision` printed in the previous step.  If they match, the device is ready to be unplugged and handed to the host CLI.

Press Ctrl-T then Ctrl-C in `pio device monitor` to exit without resetting the device.  Leaving the monitor open while running `keychain sync` will cause a "port busy" error — only one process at a time can hold the CDC endpoint.""",
        """First-time PlatformIO users on macOS may see a Gatekeeper prompt the first time esptool runs; allow it once.
The Arduino-ESP32 core is large; a stripped ESP-IDF build would be smaller, but the embed-files convenience of the Arduino path wins in practice.""",
    ),
    (
        'first-sync', 80, 'First Sync',
        """Unplug the device after flashing, then plug it back in.  The freshly-booted firmware emits the banner, the host enumerates the CDC interface, and the device sits idle until spoken to.

From the Velour project root:

```
venv/bin/python manage.py keychain sync
```

The `sync` subcommand walks `/dev/ttyACM*` (or `/dev/cu.usbmodem*` on macOS, `COM*` on Windows) looking for a device that responds to `HELLO` with a valid Velour banner.  On success it registers the device in the host index at `.keychains/<sha>/index.json`, where `<sha>` is the seed SHA-256.  Expected output:

```
* source : serial:///dev/ttyACM0@115200
* seed   : sha256 = 8f2c1a4b9d0e7f3c...
           16,384 bytes in 23 ms
* keychain: new device registered.
* DB     : 16,777,216 bytes addressable, lazy backend ready
```

If auto-detection fails, pass the port explicitly:

```
venv/bin/python manage.py keychain sync --port /dev/ttyACM0
```

For development and CI work, you can bypass the device entirely and seed the index from a local file:

```
venv/bin/python manage.py keychain sync --seed-file path/to/seed.bin
```

This is the same code path the firmware would take, minus the serial transport.  The resulting index is indistinguishable from one populated by a physical sync.

After a successful sync, the static clock (`name=static`, `ticks_per_second=0`) is automatically present.  All subsequent `tag`, `extract`, and `verify` operations default to it unless a `--clock` is given.""",
        """sync is idempotent. Running it twice does not duplicate the index; pre-existing tags survive.
Lazy backend means no DB compute happens until something reads.""",
    ),
    (
        'tagging-and-reading', 90, 'Tagging and Reading',
        """The keychain stores no files.  The host stores tags — byte-range annotations — and reconstructs files from the seed on demand.

A typical workflow begins with *scanning* a chain level for plausible content boundaries.  The scanner walks the regenerated stream looking for runs of low-entropy bytes and likely format signatures:

```
venv/bin/python manage.py keychain scan 8f2c1a4b 12
```

The arguments are the seed SHA (any unique prefix is accepted) and the chain level.  The scanner prints candidate ranges with notes such as `zero-run`, `ascii-burst`, or `entropy-shift`.  None of these are authoritative; they are starting points.

Once you have a range you want to keep, tag it:

```
venv/bin/python manage.py keychain tag 8f2c1a4b \\
    --level 12 --start 0x14a00 --end 0x15c20 \\
    --name notes_2026_05.md --mime text/markdown
```

Each tag records the seed SHA, the clock (default `static`), the level, the byte range, the SHA-256 of the bytes at the moment of tagging, an optional MIME, and a human-readable name.  The byte-range hash is the anchor: a future `verify` confirms that the same range still hashes to the same value, catching firmware drift or chain-parameter regressions.

To list everything tagged for a device:

```
venv/bin/python manage.py keychain ls 8f2c1a4b
```

To extract a tagged file to disk:

```
venv/bin/python manage.py keychain extract 8f2c1a4b f0001 -o notes.md
```

To audit the index for drift:

```
venv/bin/python manage.py keychain verify 8f2c1a4b
```

`verify` regenerates each tagged range and re-hashes it.  Any mismatch is reported with the differing hashes and the suspect tag.  The exit code is non-zero if any tag fails.""",
        """The scanner is heuristic. It misses content that does not match common signatures and false-positives on incidental byte patterns.
File IDs are auto-assigned as f0001, f0002, … and never reused after deletion.""",
    ),
    (
        'clocks-and-time', 100, 'Clocks and Time',
        """A clock is a rule for how the level-0 input to the chain changes over wall-clock time.  The default clock, `static`, never ticks: the level-0 input is the seed itself, and every byte at every level is fixed forever.

A *time-evolving* clock advances the level-0 rule by applying the CA to its previous state at a configured rate.  The seed remains the genesis state.  After `n` ticks, level 0 is the CA applied to the seed `n` times.  The rest of the chain — levels 1 through 63 — is then computed from this advanced level-0 as usual.  The same coordinates `(level, byte_start, byte_end)` thus address different bytes at different instants.

Add a slow clock:

```
venv/bin/python manage.py keychain clock-add 8f2c1a4b \\
    --name slow --rate 1/day
```

Add a fast clock — the "1 GiB/day" archive clock:

```
venv/bin/python manage.py keychain clock-add 8f2c1a4b \\
    --name fast --rate 2.83/sec
```

The rate is parsed as `ticks_per_second`.  Suffixed forms `N/sec`, `N/min`, `N/hour`, and `N/day` are accepted and converted; bare numbers are treated as ticks per second.

To tag bytes at a specific wall-clock instant on a time-evolving clock:

```
venv/bin/python manage.py keychain tag 8f2c1a4b \\
    --clock slow --at 2026-05-20T08:00:00 \\
    --level 4 --start 0x0 --end 0x800 \\
    --name slow_morning_blob
```

The `--at` argument is recorded in the tag as `wall_anchor`.  When `extract` or `verify` later operates on this tag, it computes the exact tick that produced these bytes from `wall_anchor` and the clock parameters, regenerates that tick's level-0 state, runs the chain, and serves the bytes.  Tags on time-evolving clocks are not snapshots of mutable state; they are pinned coordinates in a time-indexed stream.""",
        """clock-add rejects negative or zero rates; the static clock is implicit and cannot be reconfigured.
A clock's start_epoch should never be changed after tags exist against it; the CLI refuses.""",
    ),
    (
        'archive-snapshots', 110, 'Archive Snapshots',
        """A time-evolving clock is interesting precisely because each tick produces a fresh 16 MiB of derived bytes.  Most of those bytes are never tagged.  The `archive` subcommand writes the mother CA state at one tick to disk so that downstream tools can index, search, or back up specific moments.

```
venv/bin/python manage.py keychain archive 8f2c1a4b \\
    --clock fast --packed
```

By default this archives *the current tick* of the named clock.  Output goes to:

```
.keychains/<sha>/archive/<clock>/<tick>.bin
```

where `<tick>` is the integer tick number computed from the clock's `start_epoch` and `ticks_per_second`.  With `--packed`, the file is the packed K=4 form (4 KiB); without, it is the raw 1-byte-per-cell form (16 KiB).

The storage cost scales linearly with tick rate.  Useful reference table:

- 1 tick/day → 4 KiB/day (journal-style)
- 1 tick/hour → 96 KiB/day (daily notes)
- 1 tick/min → 5.6 MiB/day (continuous capture)
- 1 tick/sec → 345 MiB/day
- 2.83 ticks/sec → 1 GiB/day (matches "1 GB/day" target)

For continuous capture, drive `archive` from cron or a systemd timer at a rate slightly higher than the clock rate to avoid missed ticks under host load.  A future `keychain archive-daemon` subcommand will hold the device open and drain ticks as they come.  Until then, a one-minute cron entry suffices for clocks up to `1/min`, and a `while true; sleep 0.3; manage.py keychain archive ...` loop covers the faster rates.""",
        """The archive directory grows without bound. Set up a retention policy at creation time; pruning later is harder.
Archive files are byte-identical across hosts running the same Velour version. Use this for off-site replication via rsync.""",
    ),
    (
        'physical-assembly', 120, 'Physical Assembly',
        """The keychain has effectively no electronics work.  The board is finished; assembly is mechanical protection and attachment.

Begin with a length of clear or black flat heat-shrink tubing, 20 mm flat width, cut to roughly 40 mm.  Slide it over the SuperMini from the back, leaving the USB-C connector and the small mounting hole at the opposite end exposed.  The board should sit centred inside the tube with components covered on both sides.  Heat evenly with a heat gun at low setting, or pass the assembly briefly over a soldering iron held flat — direct flame is not appropriate.  The tubing will conform tightly around the PCB outline and component bumps in about ten seconds.

Through the mounting hole at the non-USB end, thread either a 15 mm split-ring (for a key bunch) or a 1 mm paracord loop (for a badge clip).  The hole is large enough for both.  Do not thread the lanyard through the USB connector or around any exposed pad on the board edges; pulling on the cable should not transmit force through the solder joints.

If you want a more finished look, glue a small bezel of card or 3D-printed plastic around the USB-C connector — this protects the connector shell from lateral impacts and gives a clean visual edge to the heat-shrink.  Cyanoacrylate works; epoxy is overkill.

Total assembled weight is approximately three grams; the board is two, the heat-shrink under one, the split-ring under one.

A note on hygiene.  The USB-C connector pads are exposed by design and will be the failure point if anything is.  Avoid prolonged skin contact in humid environments — keep the device clipped to a lanyard rather than on a bare keyring against trouser fabric.  Salt and sebum corrode the contacts measurably over months.  A quick wipe with isopropyl alcohol every few weeks is sufficient for daily-carry use.

Do not attempt to coat the connector itself with anything.  Conformal coating on the rest of the board is fine if you know what you are doing, but the contact surfaces inside the USB-C shell must remain bare metal.""",
        """3D-printed snap-fit cases in PETG with 1.2 mm walls survive a pocket-with-keys environment for several months; PLA does not.
The mounting hole on some SuperMini batches has a thin copper ring on its inner surface; this is not a grounding pad and serves no electrical purpose, but do not drill it out.""",
    ),
    (
        'troubleshooting', 130, 'Troubleshooting',
        """**No ESP32 detected.**  The most common cause is a charge-only USB cable.  The S3's USB-Serial-JTAG controller needs the data pairs; many cables, especially those bundled with cheap battery banks, are wired only for power.  Swap to a cable known to enumerate a phone for file transfer.  If a known-good cable still does not work, pass `--port` explicitly to `keychain sync`.  On Linux, run `groups` and confirm `dialout` is present.  On macOS, check `ls /dev/cu.usbmodem*` after plug-in.  On Windows, Device Manager should show a new COM port; an "Unknown device" with code 43 is a cable problem.

**Sync hangs after the banner.**  The device is probably stuck in download mode — the USB stack is up but the application firmware never ran.  To recover, hold the BOOT button, tap RESET, then release BOOT.  This is the standard ESP32-S3 procedure to exit the ROM bootloader.  If the firmware *did* run (you saw `VELOUR-KEYCHAIN v1 ...` in the monitor) but `sync` still hangs, another process is holding the serial port — close any open `pio device monitor`, `screen`, `minicom`, or VS Code serial monitor.

**SHA mismatch on verify.**  `keychain verify` reports the expected and actual byte-range hashes.  The mismatch has three plausible causes.  First, the firmware was reflashed with a different seed.  Compare the device's banner SHA against the index's `seed_sha256`.  Second, the chain parameters changed in host code between tagging and verifying.  Third, a real bug in the chain evaluator was introduced; if you can rule out the first two, file an issue with the failing tag's coordinates.

If the mismatch is intentional (you deliberately rotated the seed), the right response depends on intent: `keychain untag <id>` followed by a fresh `tag` on the new bytes if you want to preserve the name on the new contents, or reflash the original seed if you want to recover the old tags.

**First boot shows no banner.**  USB-CDC enumeration on the S3 takes approximately 300 ms after the device-side stack initialises; if you open the monitor too quickly you may miss the banner.  Reset the device after the monitor is attached (Ctrl-T then Ctrl-R in `pio device monitor`).

**Bricked board.**  It is essentially not possible to brick an ESP32-S3 from software, because the boot ROM always exposes a download-mode USB endpoint that cannot be overwritten.  Hold BOOT, tap RESET, release BOOT to force download mode, then run `esptool.py --chip esp32s3 erase_flash` to wipe everything, followed by a fresh `pio run -t upload`.  If `esptool` cannot see the device in download mode, the cable is suspect again.""",
        """A multimeter in continuity mode across the unmated USB-C plug's pin 1 and pin 4 confirms a data-capable cable in five seconds.
If `esptool erase_flash` reports "no serial data received", you almost certainly have not entered download mode — the timing of BOOT/RESET matters.""",
    ),
    (
        'command-reference', 140, 'Command Reference',
        """All keychain subcommands are invoked as `venv/bin/python manage.py keychain <subcommand>` unless noted.  The provisioning command is a separate top-level management command.

- **archive** — write one tick of a clock's mother-CA state to the archive directory.
- **clock-add** — register a new clock with name, start epoch, and rate.
- **clock-remove** — remove a clock; refuses if tags reference it.
- **clocks** — list all clocks for a device with rates and tick counts.
- **dump** — write a chain level's full output to stdout or a file.
- **extract** — regenerate and write a tagged file to disk.
- **info** — print device metadata: seed SHA, clocks, chain params, tag count.
- **list** — list all devices known to the host index.
- **ls** — list all tags for a device.
- **regen** — eagerly materialise the full DB to a cache file.
- **register** — manually register a device from a seed file.
- **rename** — rename a tag in place; does not touch bytes.
- **scan** — heuristically search a chain level for content boundaries.
- **sync** — probe serial ports for a Velour keychain device and register it.
- **tag** — record a byte-range annotation with optional clock and wall anchor.
- **untag** — remove a tag by id; bytes are unaffected.
- **verify** — re-hash every tagged range and report mismatches.
- **keychain_provision** *(top-level)* — bake a `ComponentChampion` seed into the firmware data directory.""",
        """All subcommands accept --help for full argument lists; this reference is one-line orientation, not a complete man page.
dump is intended for debugging and bulk export; prefer extract for tagged content.""",
    ),
    (
        'wire-protocol-reference', 150, 'Wire Protocol Reference',
        """The USB-CDC protocol is line-oriented, ASCII, and small enough to drive by hand from a serial terminal if needed.  The device is always the responder; the host always speaks first after the initial banner.

**Boot banner**, emitted once after USB enumeration:

```
VELOUR-KEYCHAIN v1 sha=<hex64>\\n
```

The `v1` is the protocol version.  The 64-hex-digit value is the SHA-256 of the embedded seed.

**Commands.**  Each is a line terminated by `\\n` (LF, not CRLF).  Replies are explicit and ASCII.

- `HELLO\\n` — the device replies with `OK sha=<hex64> size=16384\\n` followed immediately by exactly 16,384 raw bytes (the seed itself, unframed).  The raw blob is not LF-terminated internally; the host must read exactly the announced byte count before resuming line-mode reads.
- `SHA\\n` — replies with `OK sha=<hex64>\\n`.  A fast handshake without transferring the full seed.
- `PING\\n` — replies with `PONG\\n`.
- `BYE\\n` — replies with `OK\\n`.

Unknown commands produce `ERR unknown command: <input>\\n`.  Lines longer than 32 bytes are silently truncated by the firmware's input buffer; commands have no payload, so this only matters for protocol fuzzing.

The protocol intentionally has no write commands.  The device exposes the seed and nothing else; there is no way to alter or partially overwrite the seed over the wire.  This is the security boundary: a malicious host can read but cannot modify.""",
        """v1 is the only protocol version. A future v2 may add a CHAIN command that emits a specific chain level to offload host compute.
The 16,384-byte blob is sent without framing because the size is fixed and announced — do not generalise this to variable-length transfers.""",
    ),
    (
        'index-format-reference', 160, 'Index Format Reference',
        """The host index lives at `.keychains/<seed_sha256>/index.json`.  It is a single JSON object, format version 2 at the time of writing.

Top-level fields:

- `seed_sha256` — 64-character lowercase hex string.  The device's identity.
- `format_version` — integer, currently `2`.  v1 indexes auto-migrate on load.
- `clocks` — list of clock objects.  Each has `name` (string), `start_epoch` (unix float), `ticks_per_second` (float; `0` for static), and `chain_params` (object with `depth`, `ticks_per_level`, `stream_ticks`, `streams_per_level`, `packed`).
- `notes` — free-form string for human use.
- `files` — list of tag objects.  Each has `id` (e.g. `f0001`), `name` (string), `clock_name` (references `clocks[].name`), `wall_anchor` (unix float or null; null implies static clock), `level` (int), `stream_index` (int, default 0), `byte_start` (inclusive), `byte_end` (exclusive), `sha256` (64-char hex of the byte range at tagging time), `mime`, `tags` (list of strings), `created_at` (unix float), and `overlay_path` (optional).

A minimal index immediately after first sync:

```
{
  "format_version": 2,
  "seed_sha256": "8f2c1a4b...",
  "clocks": [
    {
      "name": "static",
      "start_epoch": 0.0,
      "ticks_per_second": 0.0,
      "chain_params": {
        "depth": 64,
        "ticks_per_level": 16,
        "stream_ticks": 64,
        "streams_per_level": 1,
        "packed": true,
        "init_seed_fn": "spoeqi-v1"
      }
    }
  ],
  "notes": "",
  "files": []
}
```

The file is rewritten atomically — write to `index.json.tmp`, rename — on every mutation.  Concurrent CLI invocations against the same device are not supported.""",
        """The static clock is auto-injected on first creation and cannot be removed.
A future format v3 may rename "files" to "tags" with a one-time migration.""",
    ),
]


class Command(BaseCommand):
    help = 'Seed the Velour Quine Keychain assembly + operations manual.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--rebuild', action='store_true',
            help='Drop existing manual + sections before re-seeding.')

    def handle(self, *args, **opts):
        if opts['rebuild']:
            n = Manual.objects.filter(slug=MANUAL_SLUG).delete()
            self.stdout.write(self.style.WARNING(
                f'  dropped existing manual: {n}'))

        m, created = Manual.objects.get_or_create(
            slug=MANUAL_SLUG,
            defaults={
                'title': 'The Velour Quine Keychain',
                'subtitle': 'Assembly, flashing, and operation of a '
                            'pocket-DB pendant',
                'format': 'short',
                'author': 'Velour',
                'version': '1.0',
                'abstract': (
                    "A complete walkthrough for the Velour Quine Keychain: a "
                    "USB pendant that embeds one class-4 hex-CA quine seed in "
                    "flash and serves it to a host computer over USB-CDC. The "
                    "host regenerates a 16 MiB deterministic binary database "
                    "on demand and exposes it as a tag-based filesystem. "
                    "Covers bill of materials, firmware build, host setup, "
                    "tagging, the multi-clock time-evolving model, archive "
                    "snapshots, troubleshooting, and full CLI/protocol/index "
                    "reference appendices."),
            },
        )
        # Idempotent metadata refresh.
        m.title = 'The Velour Quine Keychain'
        m.subtitle = ('Assembly, flashing, and operation of a pocket-DB '
                          'pendant')
        m.format = 'short'
        m.version = '1.0'
        m.save()

        seen_slugs = []
        for slug, order, title, body, sidenotes in SECTIONS:
            s, s_created = Section.objects.get_or_create(
                manual=m, slug=slug,
                defaults={'sort_order': order, 'title': title})
            s.sort_order = order
            s.title = title
            s.body = body
            s.sidenotes = sidenotes
            s.save()
            seen_slugs.append(slug)
            tag = 'created' if s_created else 'updated'
            self.stdout.write(
                f'  [{tag}] {slug:<32s} {title}')

        # Drop any sections that aren't in the canonical list (in case a
        # previous version had extras we want to clean up).
        stale = m.sections.exclude(slug__in=seen_slugs)
        if stale.exists():
            n = stale.count()
            stale.delete()
            self.stdout.write(self.style.WARNING(
                f'  removed {n} stale section(s)'))

        action = 'created' if created else 'refreshed'
        self.stdout.write(self.style.SUCCESS(
            f'manual {action}: /codex/manuals/{m.slug}/  '
            f'({len(SECTIONS)} sections)'))
