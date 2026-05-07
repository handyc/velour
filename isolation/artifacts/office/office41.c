/* office41.c — Win95-style 17-app suite. Linux x86_64. No libc.
 *
 *   shell  notepad  word  mail  sheet  paint  hex  bfc  files
 *   find  calc  mines  ask   garden  hxhnt  rpg  lsys  bytebeat
 *
 * office41 makes the rpg overworld seamless.  The world-cell arrays
 * grow from 64×64 to 192×192 — a 3×3 mosaic of 64×64 sub-overworlds,
 * each independently seeded by its level-1 (mx, my) coordinate (with
 * carry up the world stack for neighbours that cross 0/64).  The
 * player is always centred near (96, 96), and the eight neighbouring
 * overworlds are pre-loaded so visible cells beyond the central
 * 64×64 region come from the right neighbour — no edges, no black,
 * just one continuous world.  When the player crosses out of the
 * central sub-region, the mosaic shifts: the world stack advances by
 * (dx, dy) and the 192×192 tile is regenerated centred on the new
 * sub-overworld.  Memory: ~1 MB extra BSS (mostly the texture cache
 * for 192×192 cells); binary file is unaffected.
 *
 * Carried forward from office40: closed-loop wander paths.  Every animal and NPC its own private wandering
 * loop.  When a tile is generated, every animal/NPC cell deals out a
 * deterministic random closed path of 0..60 hex steps: pick three
 * counts a, b, c in [0..10] and assemble 2*(a+b+c) directions —
 * a copies of E paired with a of W, b of NE with b of SW, c of NW
 * with c of SE — then Fisher-Yates shuffle the full sequence.  The
 * opposite-pair balance guarantees the walk closes geometrically
 * regardless of the shuffle order, so loops can be wandering and
 * self-intersecting without collapsing into a there-and-back.
 *
 * One step per player turn; if the destination is blocked (by the
 * player, another mover, or a building) the entity stalls and
 * retries next turn — never breaks closure.  When the step counter
 * wraps, a fresh path is generated from a new seed.
 *
 * Carried forward from office39: bytebeat synth.  Five preset PCM formulas
 * (Crowd, 42 Melody, Three Note, Skyline, Phaser); generate 4 s of
 * 8000 Hz u8 mono into /tmp/office41_bb.raw and pipe to aplay via
 * fork+execve, mirroring run_ask's curl pattern.  Safe — integer
 * arithmetic on a sample counter, no parsing, no network, just a
 * one-way write to disk + aplay invocation.  Falls back gracefully
 * to a status-line error if aplay (alsa-utils) isn't installed.
 *
 * Carried forward from office38: NPCs as 1×2 head/body sprites.  An NPC is a 1×2
 * sprite — head row + body row in distinct xterm-256 colours, the
 * same render style as the player but with per-NPC palette pulled
 * from a 16-entry colour table indexed by the procedural NPC byte.
 * One in every ~30 spawn-eligible cells (soil + sand only) gets an
 * NPC at world generation; the byte is stored in rpg_npc_at[] which
 * the meta-overworld machinery already regenerates per tile.  Bumping
 * an NPC writes a "hello" greeting to the action line — no movement,
 * the NPC blocks like a building.  Stationary for now; a later fork
 * can add wander, dialog branches, and quests.
 *
 * Carried forward from office37: meta-overworld with 64-deep
 * coordinate stack.  Walking off the edge of the rpg overworld
 * advances the level-1 (mx, my) by ±1 (wrapping at 64 with carry
 * into level 2, etc.) and re-seeds a fresh 64×64 map for the new
 * tile.  The world is deterministic — same coords always rehydrate
 * the same map — and the position vector is 63 levels deep, giving
 * 64^126 unique overworlds.
 *
 * Carried forward from office36: four terrain benders (0/1/2/3) +
 * four category benders (4/5/6/7).  The bend salt is per-category
 * and travels with the player across overworlds — bend a plant in
 * one, and every plant in every overworld you visit afterwards
 * inherits the new palette family.
 *
 *     4   plant     5   building     6   animal     7   item
 *
 * Each entity bender costs (5 - skill) mana — same scaling as the
 * terrain benders, with its own per-category skill levelling up to
 * a cap of 9.  A bend increments that category's "bend counter",
 * which feeds into the sprite-palette hash, then invalidates the
 * sprite cache for the category so every instance of plants /
 * buildings / animals / items repaints with a fresh palette family.
 * The L-system geometry is preserved (same archetypes, same shapes)
 * — only the colours rotate.  A skilled plant-bender can recolour
 * every plant in the world for ~1 mana.
 *
 *     4   plant     5   building     6   animal     7   item
 *
 * Each entity bender costs (5 - skill) mana — same scaling as the
 * terrain benders, with its own per-category skill levelling up to
 * a cap of 9.  A bend increments that category's "bend counter",
 * which feeds into the sprite-palette hash, then invalidates the
 * sprite cache for the category so every instance of plants /
 * buildings / animals / items repaints with a fresh palette family.
 * The L-system geometry is preserved (same archetypes, same shapes)
 * — only the colours rotate.  A skilled plant-bender can recolour
 * every plant in the world for ~1 mana.
 *
 * Carried forward from office35: status clamp + 256-entry library
 * roster from 8 hand-coded kinds to a 256-entry library:
 *
 *   1. Status fix.  hxhnt's display hint had grown long enough to
 *      run past the 80-col terminal width, wrapping and scrolling
 *      the screen on every paint.  status() now clamps the message
 *      to (SCREEN_W - 1) before printing, and the display hint is
 *      shortened to the smaller "g/h/[/] r d x q" mnemonics — both
 *      changes guarantee one row of status, no wrap.
 *
 *   2. L-system library.  Each rpg map cell now stores (cat, idx)
 *      where cat is one of P/B/A/I and idx is 0..63.  cat × idx =
 *      4 × 64 = 256 distinct entity variants, each with its own
 *      L-system axiom + rule + iters + angle and its own 4-colour
 *      palette derived from a hash of those choices.  Every rule
 *      mutation moves the palette in lock-step (carried over from
 *      office30).
 *
 *      We don't store 256 fully-spelled variants — that would blow
 *      the rodata budget.  Instead each category has 4 archetype
 *      L-systems, and the 64 variants per category are derived by
 *      mixing archetype × iteration depth × angle step from the
 *      idx bits.  Total rodata cost ≈ 600 bytes for templates;
 *      sprites + palettes are cached per (cat, idx) on first use.
 *
 *      Behaviours stay at the category level: P plants are tall +
 *      blocking unless walkable, B buildings are blocking, A animals
 *      have HP (combat), I items are walkable + picked up.
 *
 * Carried forward from office34: edge fix (cells region painted black
 * power to the rpg player.
 *
 *   1. Edge fix.  The hex layout shifts each cell's middle row by
 *      +2 cols, leaving 2-col gaps on the sides that paint_desktop
 *      had filled with teal.  At map edges (where some visible cells
 *      are off-map and paint black), the mix of teal gaps + black
 *      off-map cells + coloured real cells looked busy.  rpg now
 *      paints the cell-region rows pure black before pass 1, so
 *      gaps and off-map cells both read as void.
 *
 *   2. Bending.  0 / 1 / 2 / 3 in rpg target a terrain for "bending"
 *      — an inline GA session that evolves the global ruleset +
 *      palette, with the winner adopted as the new default.  Cost
 *      per generation is max(1, 5 - skill[t]) mana; total gens =
 *      min(10, mp / cost).  Each successful bend levels that
 *      terrain's skill up to a cap of 9, so a master water-bender
 *      pays nearly nothing per generation but costs the same to
 *      bend rock.  After the bend, rpg re-derives terrain RGBs from
 *      the new palette and invalidates cell caches so the world
 *      immediately reflects the evolved CA.
 *
 * Carried forward from office33: hxhnt mut knob ([/]) + 'h'
 *
 *   • Mutation rate is now a live knob.  hx_mut_init (parent-pool
 *     mutation, 1/2^24 fixed-point) defaults to 5 % and the offspring
 *     mutation tracks at 1/10 of that.  Display mode shows "mut=5.0%"
 *     in the status bar; '[' / ']' nudge it down/up through 0.5 %,
 *     1 %, 2 %, 5 %, 10 %, 15 %, 20 %, 30 %.  Single GA sessions and
 *     the continuous hunt both pick up the current value at start.
 *
 *   • New 'h' key in display mode kicks off a *continuous hunt* — a
 *     loop of short GA sessions (POP=20, GENS=10), each adopting its
 *     winner as the seed for the next, until you press q/ESC.  Inter-
 *     session pauses are skipped (no winners screen between rounds);
 *     the same per-generation progress paint is your view.  When you
 *     abort, the latest evolved winner is on disk + in memory and rpg
 *     immediately reflects the new palette + ruleset.
 *
 *   • 'g' still runs a single GA session and ends with the binary-
 *     export winners screen; that path is unchanged.
 *
 * Carried forward from office32: terrains rock/sand/soil/water,
 *
 *   1. Terrain types renamed.  CA states 0..3 now mean rock / sand /
 *      soil / water (was water/grass/dirt/lava).  Embedded default
 *      palette swapped to match: gray rock, tan sand, brown soil,
 *      deep blue water.
 *
 *   2. Each terrain has its own animation rate, expressed in *frames
 *      per minute*.  The animator runs at 10 fps; per-terrain
 *      accumulators tick by `fpm` each frame and trigger a CA step
 *      whenever they cross 600 (one minute's worth of frames).  So
 *      water at 600 fpm steps every frame, rock at 2 fpm steps once
 *      every 30 seconds, etc.  Each terrain has its own enable flag,
 *      so you can stop rock entirely while water keeps churning.
 *
 *   3. Press 'k' in rpg to open the speed-settings panel.  Up/down
 *      navigate, space toggles a terrain on/off, +/- adjust its rate
 *      (with non-linear steps so you can sweep 1..1200 fpm in a
 *      reasonable number of presses), 0 resets to default, q closes.
 *
 *   4. Entity seeding now follows terrain.  Buildings live on rock +
 *      soil.  Trees + bushes live on sand + soil.  Animals roam
 *      sand + soil + water.  Items (chests, gems) sit on rock + soil
 *      where they're naturally found.
 *
 * Carried forward from office31: 'l' toggles live animation; each  Press 'l' to toggle
 * animation; while it's on, each of the 64 visible cells holds its
 * own 64×64 hex-CA state, the state steps under hx_seed_genome each
 * frame, the 8×3 sample re-aggregates, and the cell repaints — so
 * the terrain breathes instead of sitting still.  Polling termios
 * (VMIN=0, VTIME=1 → 100 ms) so the loop ticks even when the user
 * isn't typing; movement keys + i / m / q still work.
 *
 * Per-slot 64×64 state cache lives in BSS (~256 KB).  Each state
 * carries which world cell currently owns the slot; when the player
 * moves and the visible window shifts, mismatched slots get re-seeded
 * from their new owner's deterministic cell-hash.  When the embedded
 * genome is all zeros (fresh build, no hxhnt evolution), stepping
 * would collapse the CA to uniform 0, so we re-seed every frame
 * instead — gives a churning random animation rather than a freeze.
 *
 * Carried forward from office30: L-system entity sprites with  Each entity
 * kind is now a real L-system — axiom + single F-rule + iterations
 * + 45°-step angle — and the 5×3 block sprite is the L-system
 * rasterised + downsampled at startup.  Walk the turtle, dump every
 * F-step position into a point cloud, bucket the points into 3 cols
 * × 5 rows, count hits per bucket, threshold the count to one of
 * 4 palette indices (0=transparent, 1=light/sparse, 2=mid, 3=dense).
 *
 * Each entity also derives its own 4-colour palette from a hash of
 * its (axiom + rule + iterations + angle) string — same input mutates
 * → same output palette, so rule mutations carry palette mutations.
 * Category sets the base RGB family (plant=green, building=tan,
 * animal=warm, item=gold), and three intensity shades flank that
 * base for the 1/2/3 indices: pal[1] = lighter, pal[2] = base,
 * pal[3] = darker.  Sparse parts of the L-system render as light
 * highlights (pal[1]); dense overlapping branches render as deep
 * shadow (pal[3]); empty buckets stay transparent (terrain shows
 * through), giving even a 5×3 grid plenty of variation.
 *
 * Sprite + palette are cached per entity kind at startup; render
 * path just looks up sample + palette by index.
 *
 * Carried forward from office29: hxhnt GA polling termios, hxhnt  office28 set polling termios
 * inside hx_display_seed but restored blocking mode (VMIN=1) before
 * returning, so when 'g' kicked off hx_run_ga the per-generation
 * read_key blocked until the user pressed a key — making the GA
 * feel like a manual single-step debugger.  hx_run_ga now installs
 * its own polling termios (VMIN=0, VTIME=2 → 200 ms), so each
 * generation advances as soon as scoring + sorting finishes; ESC/q
 * still aborts the run, the call just doesn't block waiting for it.
 *
 * Carried forward from office28: hxhnt usable evolver, rpg inherits
 * its results into rpg.  Three changes:
 *
 *   1. The hxhnt bootstrap (hxhnt.seed → embedded → random fallback)
 *      now runs once at office startup via hx_active_init(), so
 *      hx_seed_genome / hx_seed_pal are populated for every app
 *      regardless of which one launched first.
 *
 *   2. rpg inherits its 4 terrain base RGBs from hx_seed_pal — the
 *      xterm-256 codes are decoded back into 24-bit RGB via the
 *      cube/grayscale tables.  Each cell's per-cell palette still
 *      diverges with random RGB offsets, but the *base* now reflects
 *      whatever palette hxhnt last evolved or randomised.  Replacing
 *      the hardcoded water/grass/dirt/lava table.
 *
 *   3. hxhnt display mode gains a real keymap so you can drive it
 *      without command-line arguments:
 *        g   start a GA at sane defaults (POP=20, GENS=20)
 *        r   randomise the current palette (in-memory, instant)
 *        d   save the current genome+palette as the default
 *            (writes ./hxhnt.seed; loaded on next startup)
 *        x   splice-export current as a runnable hxh-* binary
 *        q   quit
 *      Status bar advertises the keys; the GA ends with the same
 *      winners screen as before, with 1/2/3 still binary-exporting.
 *
 * Default embedded palette bumped to {26, 71, 131, 166} — xterm-256
 * cube codes whose RGB approximates water/grass/dirt/lava, so a
 * fresh build's rpg looks reasonable even before any evolution.
 *
 * Carried forward from office27: rpg accepts 'x' as SE.  office20 mapped SE to
 * 'c' but garden's hex mode (office13+) had already standardised
 * on 'x' for SE in the wasdzx pattern, so users naturally tried
 * 'x' in rpg and got no response.  rpg_move now accepts both 'x'
 * (canonical, matches garden) and 'c' (legacy alias kept so muscle
 * memory from office20-26 still works).  Status-bar hint reads
 * w/e/a/d/z/x to advertise the new canonical layout.
 *
 * Carried forward from office26: 1×2 player sprite —
 * a "head" cell stacked above a "body" cell, each in its own colour
 * so the player reads visually as a tiny figure standing on the
 * terrain.  The two colours (yellow + red, xterm-256 codes 226/124)
 * are deliberately *outside* the terrain RGB families (water/grass/
 * dirt/lava bases) so the sprite never blends into the cell texture
 * even after the per-cell palette diverges.
 *
 * The body lands on the cell's middle row (the x-shifted line) and
 * the head sits one row above, so the figure aligns with the cell
 * centre regardless of hex-row parity.  Pass 2 (entity sprites) and
 * the player paint sequence are unchanged otherwise — the head/body
 * just replaces the single '@' write at the end of rpg_render_view.
 *
 * Carried forward from office25: mode-vote aggregation across 8×3  office23/24 sampled
 * 24 single cells from the 64×64 inner grid — if the CA converged to
 * a near-uniform state (which the parent ruleset often does in just
 * 2-4 steps), all 24 samples landed in the dominant region and the
 * cell painted as a solid block.
 *
 * office25 aggregates instead: the inner 64×64 is partitioned into a
 * 8×3 grid of sub-blocks (each ~8×21 cells, ~170 cells total), and
 * each block votes by majority — the mode of its 4 CA states becomes
 * the chunky pixel for that character.  Two sub-blocks with subtly
 * different distributions can vote for different states, so the
 * cell now shows actual grain instead of a flat colour.
 *
 * To keep the votes interesting we drop the inner-CA step count from
 * office23's 2-4 down to 1-2.  Fewer steps means the random initial
 * 4-state grid mostly survives, so each sub-block has a healthy mix
 * of all 4 states and the mode varies across the cell.
 *
 * Carried forward from office24: framebuffer 64K + sgr-skip cache. when the
 * 64-cell rpg viewport painted every character with its own per-cell
 * palette, the framebuffer (16 KB) overflowed mid-frame.  fbw() was
 * silently dropping atomic sgrbg() chunks past the limit, so the
 * terminal would receive partial escape sequences — naked digit
 * runs without the leading `\033[` or trailing `m`, which is what
 * the user saw streaming off the bottom of the map.
 *
 * Two fixes:
 *   • framebuffer bumped 16 KB → 64 KB.  Plenty of headroom even at
 *     full per-cell-character paint.
 *   • sgrbg() / sgrfg() / sgrbgfg() now skip emission when the
 *     requested colour matches the last one written.  The rpg cell
 *     loop paints lots of adjacent same-colour spaces, so this both
 *     halves the bytes-per-frame and keeps the terminal protocol
 *     well-formed.  Tracked via static `last_bg`/`last_fg`; a fresh
 *     `sgr0()` resets them so palette changes after a reset re-emit.
 *
 * Carried forward from office23: nested hex CA — each overworld cell each overworld cell is itself a 64×64
 * hex grid that runs the *same* 4096-byte parent ruleset for 2-4
 * steps from a deterministic per-cell seed, then sampled down to
 * fit the 8×3 character window of that overworld cell.  Two CAs at
 * two scales, same rules — a tiny fractal.
 *
 * The 4 CA states map to fixed terrain types:
 *
 *      0 = water   ( 30,  90, 200) base RGB
 *      1 = grass   ( 60, 180,  80)
 *      2 = dirt    (160, 110,  60)
 *      3 = lava    (220,  60,  40)
 *
 * Each overworld cell gets a 4-colour palette diverged from its
 * terrain's base RGB by four independent random RGB offsets (drawn
 * from the cell's deterministic hash), then snapped onto the
 * xterm-256 cube.  Different cells of the same terrain therefore
 * paint with different — but related — colour palettes; the texture
 * inside one cell is the inner CA's pattern coloured by that cell's
 * private 4-colour palette.
 *
 * The inner-CA result + palette are cached per overworld cell on
 * first render (lazy fill) so revisited cells repaint instantly and
 * deterministically.  ~120 KB BSS for the cache; the binary itself
 * stays under the 64 KB cap because BSS is zero-init.
 *
 * Carried forward from office22: rpg deepens into a real little game.  The 64×64 terrain
 * map is now seeded with three parallel layers:
 *
 *   • terrain         (4-colour hex CA, unchanged from office20)
 *   • entity kind     (plant/building/animal/item, per-cell, 0 = empty)
 *   • entity HP       (per-cell, only animals use it)
 *
 * Plants and buildings are 1-5 lines of block art tall.  When the
 * 8×8 view paints itself, cells are rendered north-to-south so a
 * tall entity in row vy paints upward into row vy-1 — effectively
 * occluding the cell "behind" it (further from the camera).  Same
 * back-to-front painter's trick the Velour bridge does in 3D, just
 * with character cells.
 *
 * The player gains HP, mana, and a 16-slot inventory.  Walking onto
 *   • an item        picks it up (item removed from map)
 *   • an animal      melee attack (you deal d4, take d3 in return)
 *   • a building     blocked (immovable)
 *   • a plant        blocked unless it's a small bush (h<=2)
 *
 * 'i' opens an inventory popup; 'm' casts the spell at the cursor
 * (zap nearest animal within 3 hex steps for 6 damage).  HP/MP
 * regenerate slowly on idle ticks.
 *
 * Carried forward from office21: lsys — a character-mode L-system
 * viewer.  Six hard-
 * coded grammars (Pine, Bush, Tower, Coral, Snake, Crystal), each
 * an axiom + a single F-rule + iteration count + 45°-stepped angle.
 * Same rules, four interpretations: TAB cycles category and the
 * picture redraws with a different glyph + colour:
 *
 *     plant     '*'  green   F = leaf node
 *     building  '#'  tan     F = wall stone
 *     creature  '@'  red     F = body segment
 *     item      '+'  gold    F = filigree
 *
 * 1..6 picks the grammar; the expander walks F → rule_body N times
 * into a 16 KB ping-pong buffer, then a tiny 8-direction turtle (45°
 * per +/-, 64-deep [/] stack) renders into the framebuffer in the
 * current category's glyph + colour.  Inspired by Velour's lsystem
 * app (Django/three.js) — same axiom+rules+iterations+angle data
 * model, just block-character output instead of 3D meshes.
 *
 * Carried forward from office20: rpg — a tiny tile-based explorer
 * that turns the embedded 4096-byte ruleset into a 4-colour hex map.
 * On launch:
 * embedded 4096-byte ruleset into a 4-colour hex map.  On launch:
 *   1. Fill a 64×64 grid with random 0..3 cells.
 *   2. Step the grid through the .hxseed ruleset for 5 ticks (the
 *      same hex-CA stepper hxhnt uses, just sized 64×64).
 *   3. Drop the player at world (32, 32) and centre an 8×8 visible
 *      window on them.
 *
 * Cells: 8 chars wide × 3 tall.  Two stages of hex offset:
 *   • Every other row of cells shifts +4 cols (matches garden 'h').
 *   • Each cell's middle line shifts +2 cols, so each cell looks
 *     vaguely hex-shaped on its own.
 *
 * Movement: w=NW, e=NE, a=W, d=E, z=SW, x=SE (c also accepted as
 * an alias for SE for backward compat with office20-26).  s is
 * reserved.  q
 * quits.  As the player moves, the world stays put and the visible
 * window slides — so the player glyph '@' is always at the centre
 * cell.  Map clamps at the 64×64 edges (no wrap).
 *
 * Garden gets the same kind of manual splice export that hxhnt got
 * in office18.  Both apps now share a single core function:
 *
 *     office_splice(dst, marker, marker_len, payload, payload_len)
 *
 * which reads /proc/self/exe, locates `marker` (15+1 = 16 bytes,
 * unique to the region), overwrites the next `payload_len` bytes
 * with `payload`, and writes the result to `dst`.  The two regions
 * — `.hxseed` for hxhnt, `.gdnseed` for garden — live side by side
 * in the binary, so an export from one app updates only its own
 * region while the other passes through unchanged.  Chained exports
 * preserve both payloads:
 *
 *     fresh office19 → garden X → exportA           (custom chrome)
 *     ./exportA  →  hxhnt 4 2  →  press 1            (custom CA on top)
 *                              →  exportB has BOTH custom chrome AND custom CA.
 *
 * Garden export trigger: Edit menu → "Export X", or just press 'x'
 * with the cursor on the thumbnail you want.  Same fixed 29-char
 * filename as hxhnt's exports.  The bootstrap copies gd_embedded
 * into the live g_genome on launch, so a spliced binary's chrome
 * matches the gene baked into its .gdnseed region.
 *
 * hxhnt's exported binary is now the entire office19 program with
 * the 4-byte palette + 4096-byte ruleset spliced in place.  Earlier
 * forks appended the genome as a 4104-byte tail and read it back
 * via /proc/self/exe; office18 drops that and instead carves out a
 * `.hxseed` section in the binary with sentinel markers around a
 * fixed-size payload:
 *
 *     [16 bytes "<<HXSEED-OPEN>>"][4 palette][4096 genome]
 *     [16 bytes "<<HXSEED-CLOSE>"]
 *
 * The bootstrap reads the embedded palette + genome directly out of
 * .hxseed (./hxhnt.seed remains an optional runtime override); the
 * splice exporter loads the running ELF, finds the OPEN sentinel,
 * overwrites the next 4100 bytes with the chosen winner's data, and
 * writes the result to a fixed-29-char filename.
 *
 * The export is now *manually triggered*, never automatic:
 *   - GA winners screen: press 1/2/3 to export winner #1/#2/#3 as a
 *     binary; q returns to shell.  Multiple exports per session OK.
 *   - Display mode: press 'x' during animation to export the genome
 *     currently being animated; a brief status flash confirms.
 *
 * hxhnt's display mode now animates continuously — q or ESC quits.
 * Earlier forks ran a fixed 10-tick demo with the inter-tick read
 * stuck on VMIN=1 (each tick required a keystroke to advance).
 * Switching the animation loop to VMIN=0 / VTIME=2 (200 ms timeout)
 * gives a proper hands-off display: the grid steps every ~200 ms
 * regardless of input, and the read still wakes immediately on
 * q/ESC so quitting feels snappy.  The blocking termios is restored
 * before the function returns so the GA-mode key checks still work.
 *
 * hxhnt now exports each winner as a *fully functional self-replicating
 * binary* — the running office16 ELF is copied in front of the
 * winner's 4-magic + 4-palette + 4096-genome tail and chmod'd 0755.
 * Launching the export runs office, which on first hxhnt invocation
 * reads its own /proc/self/exe tail to recover the embedded seed
 * (the original hunter.c trick).  No tail → fall back to ./hxhnt.seed.
 *
 * Export filenames are fixed-length 29 chars in the regex
 * [a-zA-Z0-9.-]+, identical length for every export so they sort
 * lexicographically by time:
 *
 *     hxh-PPPPPPP-YYYYMMDDHHMMSS-NN
 *      ^   ^       ^              ^
 *      |   |       |              `── 2-digit sequence number
 *      |   |       `── 14-digit YYYYMMDDHHMMSS
 *      |   `── 7-digit zero-padded PID
 *      `── 3-char "hxh" prefix
 *
 * .seed files are still produced alongside the binaries for in-office
 * re-loading, but the binaries are the canonical exports — they're
 * standalone, runnable, and keep the genome with them as they move.
 *
 * Carried forward from office15: hxhnt port (class-4 hex-CA hunter
 * with display + GA modes).  All helpers reuse office's existing
 * fb/syscall/raw-mode kit.
 *
 * Shell home-screen clock now ticks every second.  Until office13
 * the clock only advanced when the user touched a key, because the
 * shell loop blocked on read() with VMIN=1.  office14 introduces
 * `term_raw_polling()` which sets VMIN=0 / VTIME=10 (1 s timeout):
 * read returns 0 if no key arrives within a second, the shell loop
 * repaints (re-running clock_render against fresh SYS_time), then
 * waits another second.  Sub-apps still call regular term_raw() so
 * notepad / sheet / etc. don't burn cycles repainting on idle; on
 * return to the shell it re-applies the polling mode so the clock
 * picks up the time the user spent in the sub-app.
 *
 * Carried forward from office13: garden hex grid mode + wasdzx
 * movement.  From office11: the home-screen clock + per-process
 * ID, with the clock display style as a gene that mutates via
 * garden's GA.  From office9: garden V key (jailed shell under the
 * chosen genome).
 *
 * Adds hex-grid mode to garden.  'h' toggles between the original
 * square 8×8 layout and a hex layout where every other row of
 * thumbnails is x-shifted by half a thumb width, giving the
 * staggered honeycomb arrangement.  Hex-aware movement keys map to
 * the six neighbours of a flat-top offset grid:
 *
 *     w   e          (NW, NE)
 *      \ /
 *   a — . — d        (W, E)
 *      / \
 *     z   x          (SW, SE)
 *
 * The 's' key in hex mode selects the cell under the cursor (toggles
 * its marked bit); save in hex mode is on the menu (Alt+F → Save) or
 * via ^S.  Normal-mode keys (arrows + space + s = save) are unchanged.
 *
 * thumb_w is recomputed in hex mode so 8.5×w fits in cols
 * (`(cols * 2) / 17`), then floored at 6.  Odd rows are drawn at
 * `origin_x + thumb_w / 2` so the rightmost thumb on an odd row
 * stays inside the viewport.
 *
 * Same apps as office10 plus a live home-screen clock + per-process ID:
 *
 * The shell home screen now paints a real clock + this instance's PID
 * just below the menu bar.  The clock's *display style* is genome
 * byte 14 (formerly reserved[0]) → 8 styles, mutated by garden:
 *   0  HH:MM             4  M-D HH:MM
 *   1  HH:MM:SS          5  Y-M-D HH:MM
 *   2  h:MM PM           6  HHmm
 *   3  h:MM:SS PM        7  HH.MM.SS
 * Time is read via SYS_time, converted to a Gregorian Y-M-D h:m:s by
 * a small no-libc routine, offset by $TZ_OFFSET seconds (so the user
 * can `TZ_OFFSET=7200 ./office11` for CEST; defaults to UTC).
 *
 * The PID comes from SYS_getpid and is drawn as `pid N` next to the
 * clock.  Every spawned office instance — V mode children, ask's
 * curl exec, even nested shells — gets its own PID, so the same
 * binary running twice shows two different IDs.  Inside the jail
 * (PID namespace) the child sees pid=1, which still distinguishes
 * "I'm in a sandbox" from "I'm the host process".
 *
 * Both the clock and the PID render with the genome's accent colour
 * (byte 9), so a breeding session inside garden V mode will see them
 * shift palette + format together.
 *
 * Carried forward from earlier forks: garden V key (jailed shell
 * under the chosen genome, office9), TIOCGWINSZ-aware width chrome
 * (office8), 64-genome GA + ask LLM (office7).
 */

/* ── identity ───────────────────────────────────────────
 * Single source of truth for this fork's name + version.  Adjacent
 * string literals concatenate at compile time, so call sites can
 * write `APP_NAME " — Win95-style suite"` and the linker stitches
 * them into one .rodata constant. */
#define APP_NAME    "office41"
#define APP_VERSION "36"


/* ── syscalls ──────────────────────────────────────────── */
typedef long  ssize_t;
typedef unsigned long size_t;

static long sys3(long n, long a, long b, long c) {
    long r;
    __asm__ volatile ("syscall" : "=a"(r) : "0"(n), "D"(a), "S"(b), "d"(c)
                      : "rcx", "r11", "memory");
    return r;
}
static long sys4(long n, long a, long b, long c, long d) {
    long r;
    register long r10 __asm__("r10") = d;
    __asm__ volatile ("syscall" : "=a"(r)
                      : "0"(n), "D"(a), "S"(b), "d"(c), "r"(r10)
                      : "rcx", "r11", "memory");
    return r;
}

#define SYS_read  0
#define SYS_write 1
#define SYS_open  2
#define SYS_close 3
#define SYS_lseek 8
#define SYS_ioctl 16
#define SYS_nanosleep 35
#define SYS_getpid 39
#define SYS_fork  57
#define SYS_execve 59
#define SYS_wait4  61
#define SYS_chmod  90
#define SYS_time   201
#define SYS_getdents64 217
#define SYS_exit_group 231

#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT  64
#define O_TRUNC  512

#define rd(f, p, n)        sys3(SYS_read,  f, (long)(p), (long)(n))
#define wr(f, p, n)        sys3(SYS_write, f, (long)(p), (long)(n))
#define op(p, fl, m)       sys3(SYS_open,  (long)(p), (long)(fl), (long)(m))
#define cl(f)              sys3(SYS_close, f, 0, 0)
#define io(f, r, p)        sys3(SYS_ioctl, f, (long)(r), (long)(p))
#define qu(c)              sys3(SYS_exit_group, (long)(c), 0, 0)
#define forkk()            sys3(SYS_fork, 0, 0, 0)
#define execvee(p, a, e)   sys3(SYS_execve, (long)(p), (long)(a), (long)(e))
#define wait4_(s)          sys4(SYS_wait4, -1, (long)(s), 0, 0)
#define getpid_()          sys3(SYS_getpid, 0, 0, 0)
#define time_()            sys3(SYS_time,   0, 0, 0)


/* ── string + memory helpers (no libc) ─────────────────── */
static int slen(const char *s) { int n = 0; while (s[n]) n++; return n; }

static int scmp(const char *a, const char *b) {
    while (*a && *a == *b) { a++; b++; }
    return (unsigned char)*a - (unsigned char)*b;
}

static void *mcpy(void *d, const void *s, size_t n) {
    char *dd = (char *)d;
    const char *ss = (const char *)s;
    while (n--) *dd++ = *ss++;
    return d;
}

static void *mset(void *d, int v, size_t n) {
    char *dd = (char *)d;
    while (n--) *dd++ = (char)v;
    return d;
}


/* ── itoa for small unsigned ints ──────────────────────── */
static int utoa(unsigned u, char *out) {
    char t[12]; int n = 0;
    if (!u) t[n++] = '0';
    while (u) { t[n++] = '0' + u % 10; u /= 10; }
    for (int i = 0; i < n; i++) out[i] = t[n - 1 - i];
    return n;
}

/* Two-digit zero-padded out (e.g. "07", "23"). */
static int u2(unsigned u, char *out) {
    out[0] = '0' + (char)((u / 10) % 10);
    out[1] = '0' + (char)(u % 10);
    return 2;
}


/* ── clock: time + Gregorian conversion + 8 display styles ──
 * No libc → no localtime_r → we do the conversion by hand.  TZ
 * offset (seconds east of UTC) is read once at startup from the
 * TZ_OFFSET env var; default 0 = UTC.  Suite-wide because every
 * fork that paints a clock should agree on the same offset. */
static long g_tz_offset_sec;

/* "Days from 1970-01-01" → year. Uses the standard 4/100/400 leap
 * cycle.  Range valid 1970..2399 (well past anyone caring). */
static int year_is_leap(int y) {
    return (y % 4 == 0 && y % 100 != 0) || (y % 400 == 0);
}

static void unix_to_calendar(long epoch, int *Y, int *Mo, int *D,
                             int *h, int *mi, int *se) {
    long secs = epoch % 86400;
    if (secs < 0) secs += 86400;
    long days = (epoch - secs) / 86400;
    *h = (int)(secs / 3600);
    *mi = (int)((secs / 60) % 60);
    *se = (int)(secs % 60);

    int y = 1970;
    while (1) {
        int yd = year_is_leap(y) ? 366 : 365;
        if (days < yd) break;
        days -= yd;
        y++;
    }
    *Y = y;

    static const unsigned char mdays[12] = {
        31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31
    };
    int leap = year_is_leap(y);
    int m = 0;
    while (1) {
        int md = mdays[m] + ((m == 1) ? leap : 0);
        if (days < md) break;
        days -= md;
        m++;
    }
    *Mo = m + 1;
    *D = (int)days + 1;
}

/* Render the clock for `style` into out[].  Returns the number of
 * characters written (out is zero-padded to that length).  out
 * needs ≥ 24 bytes for the longest style ("YYYY-MM-DD HH:MM"). */
static int clock_render(unsigned style, char *out) {
    long t = time_() + g_tz_offset_sec;
    int Y, Mo, D, h, mi, se;
    unix_to_calendar(t, &Y, &Mo, &D, &h, &mi, &se);
    int p = 0;
    int h12 = h % 12; if (h12 == 0) h12 = 12;
    int pm = h >= 12;
    switch (style & 7) {
    case 0:                                          /* HH:MM */
        p += u2((unsigned)h, out + p);
        out[p++] = ':';
        p += u2((unsigned)mi, out + p);
        break;
    case 1:                                          /* HH:MM:SS */
        p += u2((unsigned)h, out + p);
        out[p++] = ':';
        p += u2((unsigned)mi, out + p);
        out[p++] = ':';
        p += u2((unsigned)se, out + p);
        break;
    case 2:                                          /* h:MM PM */
        p += utoa((unsigned)h12, out + p);
        out[p++] = ':';
        p += u2((unsigned)mi, out + p);
        out[p++] = ' ';
        out[p++] = pm ? 'P' : 'A';
        out[p++] = 'M';
        break;
    case 3:                                          /* h:MM:SS PM */
        p += utoa((unsigned)h12, out + p);
        out[p++] = ':';
        p += u2((unsigned)mi, out + p);
        out[p++] = ':';
        p += u2((unsigned)se, out + p);
        out[p++] = ' ';
        out[p++] = pm ? 'P' : 'A';
        out[p++] = 'M';
        break;
    case 4:                                          /* M-D HH:MM */
        p += utoa((unsigned)Mo, out + p);
        out[p++] = '-';
        p += utoa((unsigned)D, out + p);
        out[p++] = ' ';
        p += u2((unsigned)h, out + p);
        out[p++] = ':';
        p += u2((unsigned)mi, out + p);
        break;
    case 5:                                          /* Y-M-D HH:MM */
        p += utoa((unsigned)Y, out + p);
        out[p++] = '-';
        p += u2((unsigned)Mo, out + p);
        out[p++] = '-';
        p += u2((unsigned)D, out + p);
        out[p++] = ' ';
        p += u2((unsigned)h, out + p);
        out[p++] = ':';
        p += u2((unsigned)mi, out + p);
        break;
    case 6:                                          /* HHmm */
        p += u2((unsigned)h, out + p);
        p += u2((unsigned)mi, out + p);
        break;
    case 7:                                          /* HH.MM.SS */
        p += u2((unsigned)h, out + p);
        out[p++] = '.';
        p += u2((unsigned)mi, out + p);
        out[p++] = '.';
        p += u2((unsigned)se, out + p);
        break;
    }
    out[p] = 0;
    return p;
}


/* ── frame buffer (one write per draw) ─────────────────── */
/* 64 KB headroom so the rpg per-cell paint can't overflow.  The
 * old 16 KB cap dropped atomic sgrbg() chunks mid-frame, leaving
 * partial escape sequences on the terminal. */
static char fb[65536];
static int  fbn;

static void fbw(const char *s, int n) {
    if (fbn + n > (int)sizeof fb) return;
    mcpy(fb + fbn, s, n);
    fbn += n;
}
static void fbs(const char *s) { fbw(s, slen(s)); }
static void fbu(unsigned u)    { fbn += utoa(u, fb + fbn); }
static void fbflush(void)      { wr(1, fb, fbn); fbn = 0; }


/* ── ANSI escape composers ─────────────────────────────── */
#define ESC "\x1b"
/* Skip redundant SGR emits: most adjacent paints share a colour
 * (especially the rpg per-cell loop), so caching the last bg/fg
 * roughly halves the bytes per frame.  -1 means "unknown / will
 * always re-emit on the next call". */
static int g_last_bg = -1;
static int g_last_fg = -1;
static void cls(void)         {
    fbs(ESC "[0m" ESC "[2J" ESC "[H");
    g_last_bg = g_last_fg = -1;
}
static void cup(int x, int y) { fbs(ESC "["); fbu(y + 1); fbs(";"); fbu(x + 1); fbs("H"); }
static void sgrbgfg(int b, int f) {
    if (b == g_last_bg && f == g_last_fg) return;
    if (b != g_last_bg && f != g_last_fg) {
        fbs(ESC "[48;5;"); fbu(b); fbs(";38;5;"); fbu(f); fbs("m");
    } else if (b != g_last_bg) {
        fbs(ESC "[48;5;"); fbu(b); fbs("m");
    } else {
        fbs(ESC "[38;5;"); fbu(f); fbs("m");
    }
    g_last_bg = b; g_last_fg = f;
}
static void sgrbg(int b) {
    if (b == g_last_bg) return;
    fbs(ESC "[48;5;"); fbu(b); fbs("m");
    g_last_bg = b;
}
static void sgrfg(int f) {
    if (f == g_last_fg) return;
    fbs(ESC "[38;5;"); fbu(f); fbs("m");
    g_last_fg = f;
}
static void sgr0(void) {
    fbs(ESC "[0m");
    g_last_bg = g_last_fg = -1;
}


/* ── terminal raw mode ─────────────────────────────────── */
struct ti {
    unsigned int  iflag, oflag, cflag, lflag;
    unsigned char line, cc[19];
};
#define ICANON 0x002
#define ECHO   0x008
#define IXON   0x400         /* iflag: ^S/^Q flow-control intercept */
#define ICRNL  0x100         /* iflag: CR→NL translation */
#define TCGETS 0x5401
#define TCSETS 0x5402

static struct ti term_orig;

static void term_raw(void) {
    io(0, TCGETS, &term_orig);
    struct ti t = term_orig;
    t.lflag &= ~(ICANON | ECHO);
    t.iflag &= ~(IXON | ICRNL); /* let Ctrl-S/Ctrl-Q + CR pass through */
    t.cc[6] = 1;        /* VMIN  */
    t.cc[5] = 2;        /* VTIME (200 ms) */
    io(0, TCSETS, &t);
    fbs(ESC "[?25l");   /* hide cursor */
    fbflush();
}
/* Same raw mode but with VMIN=0 / VTIME=10 so read() returns 0 after
 * 1 s of idle, letting the shell loop wake to repaint a fresh clock
 * each second.  Sub-apps still use term_raw() (blocking) so they
 * don't spin painting while waiting for input. */
static void term_raw_polling(void) {
    io(0, TCGETS, &term_orig);
    struct ti t = term_orig;
    t.lflag &= ~(ICANON | ECHO);
    t.iflag &= ~(IXON | ICRNL);
    t.cc[6] = 0;        /* VMIN  = 0 — don't block on byte count */
    t.cc[5] = 10;       /* VTIME = 1 s  */
    io(0, TCSETS, &t);
    fbs(ESC "[?25l");
    fbflush();
}
static void term_cooked(void) {
    io(0, TCSETS, &term_orig);
    fbs(ESC "[0m" ESC "[?25h" ESC "[2J" ESC "[H");
    fbflush();
}


/* ── read a key (or escape sequence) ───────────────────── */
static int read_key(unsigned char *out, int max) {
    long n = rd(0, out, (size_t)max);
    return n < 0 ? 0 : (int)n;
}


/* ── Win95 chrome around the active app ────────────────── *
 * Colours (and a couple of layout flags) live in a 16-byte Genome
 * struct so the garden app can breed UI variants by mutating bytes.
 * Default values match office6 exactly, so apps that don't touch
 * g_genome render identically to the previous fork. */
struct Genome {
    unsigned char title_bg;      /* 0  default 21 (blue) */
    unsigned char title_fg;      /* 1  default 15 (white) */
    unsigned char bar_bg;        /* 2  default  7 (light grey) */
    unsigned char bar_fg;        /* 3  default  0 (black) */
    unsigned char desktop;       /* 4  default 30 (teal) */
    unsigned char select_bg;     /* 5  default 15 (white) */
    unsigned char select_fg;     /* 6  default  0 (black) */
    unsigned char shadow_bg;     /* 7  default  0 (black) */
    unsigned char shadow_fg;     /* 8  default  8 (dim grey) */
    unsigned char accent;        /* 9  for thumbnail title trim */
    unsigned char clock_corner;  /* 10 0=TL 1=TR 2=BL 3=BR */
    unsigned char show_clock;    /* 11 0=off, 1=on */
    unsigned char border;        /* 12 0='-' 1='=' 2='_' 3='~' */
    unsigned char menu_under;    /* 13 underline mnemonic letter */
    unsigned char clock_style;   /* 14 0..7 — display style for the home-screen clock */
    unsigned char reserved;      /* 15 */
};
static struct Genome g_genome = {
    21, 15, 7, 0, 30, 15, 0, 0, 8, 21, 1, 0, 0, 1, 1, 0
};

#define COL_TITLE_BG  (g_genome.title_bg)
#define COL_TITLE_FG  (g_genome.title_fg)
#define COL_BAR_BG    (g_genome.bar_bg)
#define COL_BAR_FG    (g_genome.bar_fg)
#define COL_DESKTOP   (g_genome.desktop)
#define COL_SEL_BG    (g_genome.select_bg)
#define COL_SEL_FG    (g_genome.select_fg)
#define COL_SHADOW_BG (g_genome.shadow_bg)
#define COL_SHADOW_FG (g_genome.shadow_fg)

/* Terminal dimensions — queried once at startup via TIOCGWINSZ.  All
 * existing call-sites read SCREEN_W / SCREEN_H, which now resolve to
 * runtime variables instead of compile-time constants, so the suite
 * paints to the actual terminal size and we don't wrap the rightmost
 * (80 - termwidth) cols of the status row onto line 25.  Fall back
 * to 80×24 when the ioctl fails or the terminal is too small. */
#define TIOCGWINSZ 0x5413
struct winsize { unsigned short ws_row, ws_col, ws_xpx, ws_ypx; };

static int screen_w = 80;
static int screen_h = 24;
#define SCREEN_W screen_w
#define SCREEN_H screen_h

static void term_init(void) {
    struct winsize ws = { 0, 0, 0, 0 };
    long r = io(0, TIOCGWINSZ, &ws);
    if (r >= 0 && ws.ws_col >= 40 && ws.ws_row >= 10) {
        screen_w = ws.ws_col;
        screen_h = ws.ws_row;
    }
}

/* Walk envp looking for "TZ_OFFSET=" (decimal seconds, optional
 * leading minus).  Skipped if the var is missing or malformed —
 * the clock then ticks in UTC. */
static int scmp_n(const char *a, const char *b, int n) {
    for (int i = 0; i < n; i++) {
        if (a[i] != b[i]) return (unsigned char)a[i] - (unsigned char)b[i];
        if (!a[i]) return 0;
    }
    return 0;
}
static void tz_init_from_envp(char **envp) {
    g_tz_offset_sec = 0;
    if (!envp) return;
    for (int i = 0; envp[i]; i++) {
        const char *e = envp[i];
        if (scmp_n(e, "TZ_OFFSET=", 10) != 0) continue;
        const char *p = e + 10;
        long sign = 1, v = 0;
        if (*p == '-') { sign = -1; p++; }
        else if (*p == '+') p++;
        while (*p >= '0' && *p <= '9') {
            v = v * 10 + (*p - '0');
            p++;
        }
        g_tz_offset_sec = sign * v;
        return;
    }
}

static void blanks(int n) {
    static const char sp[64] =
        "                                                                ";
    while (n > 64) { fbw(sp, 64); n -= 64; }
    if (n > 0) fbw(sp, n);
}

/* Paint the desktop teal. */
static void paint_desktop(void) {
    cls();
    sgrbg(COL_DESKTOP);
    for (int r = 0; r < SCREEN_H; r++) {
        cup(0, r);
        blanks(SCREEN_W);
    }
}

/* The active app's menu spec, set at the top of each run_* function.
 * menu_bar reads this so it can dim titles for menus that have no
 * entries in the current app (so Edit looks faint in paint, etc.). */
typedef struct MS_t MS;
static const MS *current_ms;
static int ms_count(const MS *m, int idx);   /* fwd decl */

/* Win95 title bar + menu bar across the top of the screen.
 * Mnemonic letters (F/E/V/H) are underlined with SGR 4 / 24 so the
 * user can see which Alt+letter opens which menu. Titles whose menu
 * is empty for the current app render in dim grey (fg=8). */
static void menu_bar(int active_idx) {
    static const char *titles[4] = { "File", "Edit", "View", "Help" };
    cup(0, 1);
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    fbs(" ");
    int used = 1;
    for (int i = 0; i < 4; i++) {
        int empty = current_ms && ms_count(current_ms, i) == 0;
        if (i == active_idx) sgrbgfg(COL_SEL_BG, COL_SEL_FG);
        else if (empty)      sgrbgfg(COL_BAR_BG, 8);     /* dim fg */
        else                 sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        fbs(" ");
        fbs(ESC "[4m");                 /* underline mnemonic */
        fbw(titles[i], 1);
        fbs(ESC "[24m");
        fbs(titles[i] + 1);
        fbs(" ");
        used += slen(titles[i]) + 2;    /* per-title actual width */
        sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    }
    blanks(SCREEN_W - used);
}

static void chrome(const char *title) {
    cup(0, 0);
    sgrbgfg(COL_TITLE_BG, COL_TITLE_FG);
    fbs(" ");
    fbs(title);
    int used = slen(title) + 1;
    blanks(SCREEN_W - used - 8);
    fbs(" _ [] X ");
    menu_bar(-1);
}

/* Status line at the bottom. */
static void status(const char *s) {
    cup(0, SCREEN_H - 1);
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    /* Clamp to (SCREEN_W - 1) chars so a too-long hint can't wrap
     * past col SCREEN_W and scroll the terminal.  Pre-office35 the
     * hxhnt display hint outgrew 80 cols and did exactly that. */
    int avail = SCREEN_W - 1;
    if (avail < 0) avail = 0;
    int sl = slen(s);
    if (sl > avail) sl = avail;
    fbs(" ");
    fbw(s, sl);
    blanks(avail - sl);
}

/* Body area — clear it to grey. */
static void body_clear(void) {
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    for (int r = 2; r < SCREEN_H - 1; r++) {
        cup(0, r);
        blanks(SCREEN_W);
    }
}

/* Print str into the body at (x, y) up to max chars (no wrap). */
static void body_at(int x, int y, const char *s, int max) {
    cup(x, y);
    int n = slen(s);
    if (n > max) n = max;
    fbw(s, n);
}


/* ── shared buffer (text + hex + paint + sheet) ────────── */
#define BUF_CAP 65536
static char  buf[BUF_CAP];
static int   blen;
static int   bcur;     /* cursor offset */
static int   btop;     /* top-of-view byte offset */
static char  fname[256];

static int load_file(const char *path) {
    /* Always remember the path so a subsequent save targets it,
     * even if the file doesn't exist yet (new-file case). */
    int i = 0;
    while (i < (int)sizeof fname - 1 && path[i]) { fname[i] = path[i]; i++; }
    fname[i] = 0;
    int fd = (int)op(path, O_RDONLY, 0);
    if (fd < 0) { blen = 0; return 0; }
    blen = (int)rd(fd, buf, BUF_CAP - 1);
    if (blen < 0) blen = 0;
    cl(fd);
    return blen;
}

static int save_file(const char *path) {
    int fd = (int)op(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return -1;
    long n = wr(fd, buf, (size_t)blen);
    cl(fd);
    return (int)n;
}

static void buf_insert(int at, char ch) {
    if (blen >= BUF_CAP - 1) return;
    if (at < 0) at = 0;
    if (at > blen) at = blen;
    for (int i = blen; i > at; i--) buf[i] = buf[i - 1];
    buf[at] = ch;
    blen++;
}

static void buf_erase(int at) {
    if (at < 0 || at >= blen) return;
    for (int i = at; i < blen - 1; i++) buf[i] = buf[i + 1];
    blen--;
}


/* ── shared clipboard ─────────────────────────────────── */
/* All apps that participate in copy/paste read and write the same
 * buffer. ^C/^X/^V map onto cb_copy / cb_cut / cb_paste with app-
 * specific notions of "selection" (line for notepad/word, cell for
 * sheet, 16-byte row for hex). Survives across app launches because
 * .bss is module-static. */
#define CB_CAP 4096
static char cb[CB_CAP];
static int  cb_n;

static void cb_set(const char *s, int n) {
    if (n > CB_CAP) n = CB_CAP;
    mcpy(cb, s, n);
    cb_n = n;
}


/* ── menu engine (Alt+letter / F10 activates) ──────────── */
/* Action codes reuse the corresponding control byte where one
 * exists, so most actions slot back into the apps' existing
 * keypress handlers. Specials use 0xA0+ — apps handle separately. */
typedef struct { const char *label; unsigned char act; } MI;

#define MA_NEW    0x0e   /* ^N */
#define MA_SAVE   0x13   /* ^S */
#define MA_QUIT   0x11   /* ^Q */
#define MA_CUT    0x18   /* ^X */
#define MA_COPY   0x03   /* ^C */
#define MA_PASTE  0x16   /* ^V */
#define MA_REFLOW 0x0a   /* ^J */
#define MA_HEXTOG 0x09   /* tab */
#define MA_ABOUT  0xa0
#define MA_RESET  0xa5

struct MS_t {
    const MI *fi; int fn;
    const MI *ei; int en;
    const MI *vi; int vn;
    const MI *hi; int hn;
};

static int ms_count(const MS *m, int idx) {
    if (!m) return 1;
    switch (idx) {
    case 0: return m->fn;
    case 1: return m->en;
    case 2: return m->vn;
    case 3: return m->hn;
    }
    return 0;
}

static const MI mF_full[]   = {{"New     ^N", MA_NEW},
                               {"Save    ^S", MA_SAVE},
                               {"Quit    ^Q", MA_QUIT}};
static const MI mF_save[]   = {{"Save    ^S", MA_SAVE},
                               {"Quit    q ", MA_QUIT}};
static const MI mF_quit[]   = {{"Quit    q ", MA_QUIT}};
static const MI mF_mines[]  = {{"Reset   r ", MA_RESET},
                               {"Quit    q ", MA_QUIT}};
static const MI mE_full[]   = {{"Cut     ^X", MA_CUT},
                               {"Copy    ^C", MA_COPY},
                               {"Paste   ^V", MA_PASTE}};
static const MI mE_paste[]  = {{"Paste   ^V", MA_PASTE}};
static const MI mV_word[]   = {{"Reflow  ^J", MA_REFLOW}};
static const MI mV_hex[]    = {{"Hex/ASC Tab", MA_HEXTOG}};
static const MI mH_about[]  = {{"About...  ", MA_ABOUT}};

#define NA(a) ((int)(sizeof(a)/sizeof((a)[0])))

static const MS ms_notepad = { mF_full, NA(mF_full), mE_full, NA(mE_full),
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_word    = { mF_full, NA(mF_full), mE_full, NA(mE_full),
                               mV_word, NA(mV_word), mH_about, NA(mH_about) };
static const MS ms_sheet   = { mF_save, NA(mF_save), mE_full, NA(mE_full),
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_hex     = { mF_save, NA(mF_save), mE_full, NA(mE_full),
                               mV_hex, NA(mV_hex), mH_about, NA(mH_about) };
static const MS ms_mail    = { mF_save, NA(mF_save), mE_paste, NA(mE_paste),
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_paint   = { mF_save, NA(mF_save), 0, 0,
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_calc    = { mF_quit, NA(mF_quit), mE_paste, NA(mE_paste),
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_files   = { mF_quit, NA(mF_quit), 0, 0,
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_find    = { mF_quit, NA(mF_quit), 0, 0,
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_mines   = { mF_mines, NA(mF_mines), 0, 0,
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_shell   = { mF_quit, NA(mF_quit), 0, 0,
                               0, 0, mH_about, NA(mH_about) };
#define MA_SETTINGS 0xa6
#define MA_BREED    0xa7   /* garden: ENTER */
#define MA_PREVIEW  0xa8   /* garden: P */
#define MA_RANDOM   0xa9   /* garden: R */
#define MA_VIEW     0xaa   /* garden: V */
#define MA_EXPORT   0xab   /* garden: X — splice export */
#define MA_EVOLVE   0xab   /* hxhnt: Edit → Evolve */
/* ask: New = clear chat, Settings = edit api_key/endpoint/model, Quit. */
static const MI mF_ask[]   = {{"New     ^N", MA_NEW},
                              {"Settings^E", MA_SETTINGS},
                              {"Quit    ^Q", MA_QUIT}};
static const MS ms_ask     = { mF_ask, NA(mF_ask), 0, 0,
                               0, 0, mH_about, NA(mH_about) };
/* garden: File = Save/Random/Quit; Edit = Breed/Preview/View. */
static const MI mF_garden[] = {{"Save    ^S", MA_SAVE},
                               {"Random  ^R", MA_RANDOM},
                               {"Quit    ^Q", MA_QUIT}};
static const MI mE_garden[] = {{"Breed   ENT", MA_BREED},
                               {"Preview P  ", MA_PREVIEW},
                               {"View    V  ", MA_VIEW},
                               {"Export  X  ", MA_EXPORT}};
static const MS ms_garden  = { mF_garden, NA(mF_garden),
                               mE_garden, NA(mE_garden),
                               0, 0, mH_about, NA(mH_about) };
/* hxhnt: File = Save/Quit; Edit = Evolve. */
static const MI mF_hxhnt[] = {{"Save    ^S", MA_SAVE},
                              {"Quit    ^Q", MA_QUIT}};
static const MI mE_hxhnt[] = {{"Evolve  E ", MA_EVOLVE}};
static const MS ms_hxhnt   = { mF_hxhnt, NA(mF_hxhnt),
                               mE_hxhnt, NA(mE_hxhnt),
                               0, 0, mH_about, NA(mH_about) };

/* Read a key into k[]. Returns -1 if k is not a menu-activation
 * (Alt+f/e/v/h or F10), else the menu index 0..3 to start at. */
static int menu_activation(const unsigned char *k, int kn) {
    if (kn < 2 || k[0] != 0x1b) return -1;
    if (kn >= 5 && k[1] == '[' && k[2] == '2' && k[3] == '1' && k[4] == '~')
        return 0;                  /* F10 */
    char c = (char)k[1];
    if (c >= 'A' && c <= 'Z') c = (char)(c + 32);
    if (c == 'f') return 0;
    if (c == 'e') return 1;
    if (c == 'v') return 2;
    if (c == 'h') return 3;
    return -1;
}

/* Drop down the chosen menu; returns the action byte the user picked,
 * or 0 if they cancelled (or the start menu was empty — Alt+V on an
 * app without a View menu is a no-op, not a silent jump elsewhere).
 *
 * Layout: each title in the bar takes slen+2 cols (1 leading + slen
 * + 1 trailing), so pulldown column for menu mi is
 *   1 + sum_{j<mi} (slen(names[j]) + 2)
 * which puts the pulldown's own leading space directly under the
 * title's leading space, and the label letter directly under the
 * title's first letter. */
static int menu_run(const MS *m, int start) {
    const MI *items[4] = { m->fi, m->ei, m->vi, m->hi };
    int        n[4]    = { m->fn, m->en, m->vn, m->hn };
    static const char *names[4] = { "File", "Edit", "View", "Help" };
    if (n[start] == 0) return 0;          /* don't auto-advance */
    int mi = start;
    int sel = 0;
    while (1) {
        /* Wipe the body area each iteration so the previous menu's
         * pulldown is gone before the new one draws. Without this,
         * arrowing right from File to Edit leaves File's pulldown on
         * screen — two menus visible at once. We can clobber the
         * app's body freely; it'll redraw when menu_run returns. */
        sgrbg(COL_DESKTOP);
        for (int r = 2; r < SCREEN_H - 1; r++) {
            cup(0, r);
            blanks(SCREEN_W);
        }

        menu_bar(mi);

        int x = 1;
        for (int j = 0; j < mi; j++) x += slen(names[j]) + 2;
        int max_w = 0;
        for (int i = 0; i < n[mi]; i++) {
            int w = slen(items[mi][i].label);
            if (w > max_w) max_w = w;
        }
        int box_w = max_w + 2;            /* leading + trailing space */

        for (int i = 0; i < n[mi]; i++) {
            cup(x, 2 + i);
            sgrbgfg(i == sel ? COL_SEL_BG : COL_BAR_BG,
                    i == sel ? COL_SEL_FG : COL_BAR_FG);
            fbs(" ");
            int w = slen(items[mi][i].label);
            fbw(items[mi][i].label, w);
            blanks(max_w - w + 1);
        }
        /* drop shadow: 1-cell dark band on the right and bottom. */
        sgrbgfg(COL_SHADOW_BG, COL_SHADOW_FG);
        for (int i = 0; i < n[mi]; i++) {
            cup(x + box_w, 2 + i);
            fbs(" ");
        }
        cup(x + 1, 2 + n[mi]);
        for (int i = 0; i < box_w; i++) fbs(" ");

        /* menu-mode status line — overrides whatever the app set. */
        sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        status("  ESC cancel  |  ARROWS navigate  |  ENTER select");
        fbflush();

        unsigned char k[8];
        int kn = read_key(k, sizeof k);
        if (kn <= 0) continue;
        if (k[0] == 0x1b && kn == 1) return 0;
        if (k[0] == '\r' || k[0] == '\n' || k[0] == ' ')
            return items[mi][sel].act;
        if (kn >= 3 && k[0] == 0x1b && k[1] == '[') {
            switch (k[2]) {
            case 'A': if (sel > 0) sel--; break;
            case 'B': if (sel < n[mi] - 1) sel++; break;
            case 'C': {
                int t = 0;
                do { mi = (mi + 1) % 4; } while (n[mi] == 0 && ++t < 4);
                sel = 0;
                break;
            }
            case 'D': {
                int t = 0;
                do { mi = (mi - 1 + 4) % 4; } while (n[mi] == 0 && ++t < 4);
                sel = 0;
                break;
            }
            }
            continue;
        }
    }
}

/* Suite-wide About — shown by every app's Help->About so that we
 * pay for the body text exactly once. The active app's title is
 * still shown in the title bar. */
static void show_about(const char *title) {
    paint_desktop();
    chrome(title);
    body_clear();
    body_at(2, 3, APP_NAME " — Win95-style suite, no libc.", SCREEN_W - 4);
    body_at(2, 5, "  notepad word mail sheet paint hex bfc files", SCREEN_W - 4);
    body_at(2, 6, "  find calc mines ask garden hxhnt rpg lsys bytebeat", SCREEN_W - 4);
    body_at(2, 8, "  Alt+F / F10 opens menus everywhere.", SCREEN_W - 4);
    body_at(2, 9, "  ^X / ^C / ^V copy across editors.", SCREEN_W - 4);
    status(" press any key ");
    fbflush();
    unsigned char k[4];
    read_key(k, 4);
}


/* ── forward declarations of apps ──────────────────────── */
static int run_shell(int, char**);
static int run_notepad(int, char**);
static int run_word(int, char**);
static int run_mail(int, char**);
static int run_sheet(int, char**);
static int run_paint(int, char**);
static int run_hex(int, char**);
static int run_bfc(int, char**);
static int run_files(int, char**);
static int run_find(int, char**);
static int run_calc(int, char**);
static int run_mines(int, char**);
static int run_ask(int, char**);
static int run_garden(int, char**);
static int run_lsys  (int, char**);
static int run_hxhnt(int, char**);
static int run_rpg(int, char**);
static int run_bytebeat(int, char**);

/* Splice-export helpers used by both run_garden and run_hxhnt.  The
 * full definitions live further down (in the hxhnt section) but
 * run_garden's MA_EXPORT handler needs them too. */
#define HX_EXPORT_NAME_LEN 29
static void hx_make_export_name(char *out, int seq);
static int  gd_splice_export(const char *dst,
                             const unsigned char *garden_genome);
static int  gd_export_seq = 1;

/* Captured at startup so the ask app can hand curl an inherited
 * environment (PATH, HOME, SSL_CERT_FILE, etc). _start passes envp
 * as the third arg. */
static char **g_envp;

/* notepad lets a caller (find) request "open at line N" */
static int npad_target_line;


/* ── shell: run apps by name + a few built-ins ─────────── */
static int run_shell(int argc, char **argv) {
    current_ms = &ms_shell;
    (void)argc; (void)argv;
    term_raw_polling();   /* 1-s tick so the home-screen clock advances */
    int running = 1;
    char line[256];
    int  llen = 0;
    int  cur_y = 3;
    int  msg_kind = 0;       /* 0 = none, 1 = ok, 2 = err */
    char msg[64];
    msg[0] = 0;

    while (running) {
        paint_desktop();
        chrome("Office Shell");
        body_clear();
        /* Live clock + this instance's pid in the genome's accent
         * colour, just below the menu bar.  Each office process
         * (host shell, V-mode jail child, future spawns) shows its
         * own pid here. */
        {
            char buf[64];
            int p = 2;
            buf[0] = ' '; buf[1] = ' ';
            p += clock_render(g_genome.clock_style, buf + p);
            buf[p++] = ' '; buf[p++] = ' '; buf[p++] = ' ';
            buf[p++] = 'p'; buf[p++] = 'i'; buf[p++] = 'd'; buf[p++] = ' ';
            p += utoa((unsigned)getpid_(), buf + p);
            buf[p] = 0;
            cup(2, 2);
            sgrbgfg(COL_BAR_BG, g_genome.accent);
            fbw(buf, p);
            sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        }
        body_at(2, 3, "Welcome to Office. Built-in commands:", SCREEN_W - 4);
        body_at(2, 4, "  notepad  word  mail  sheet  paint  hex  bfc",
                SCREEN_W - 4);
        body_at(2, 5, "  files  find  calc  mines  ask  garden  hxhnt  rpg  lsys  exit",
                SCREEN_W - 4);
        body_at(2, 6, "  (Alt+F / F10 opens menus in every app)", SCREEN_W - 4);
        if (msg[0]) {
            sgrbgfg(COL_BAR_BG, msg_kind == 2 ? 88 : 22);
            body_at(2, 7, msg, SCREEN_W - 4);
            sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        }
        cup(2, cur_y + 6);
        sgrbgfg(15, 0);
        fbs(" > ");
        fbw(line, llen);
        blanks(SCREEN_W - 7 - llen);
        status("type a command, ENTER to run, q to quit");
        fbflush();

        unsigned char k[16];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, ami = menu_activation(k, n);
        if (ami >= 0) act = menu_run(&ms_shell, ami);
        if (act == MA_ABOUT) {
            show_about("Office Shell");
            continue;
        }
        if (act == MA_QUIT) { running = 0; break; }

        if (k[0] == '\r' || k[0] == '\n') {
            line[llen] = 0;
            msg[0] = 0; msg_kind = 0;
            if (llen == 0) { continue; }
            if (scmp(line, "exit") == 0 || scmp(line, "quit") == 0) {
                running = 0;
                break;
            }
            /* Tokenise by spaces (just first arg) */
            int sp = 0;
            while (sp < llen && line[sp] != ' ') sp++;
            char cmd[32];
            int cn = sp < (int)sizeof cmd - 1 ? sp : (int)sizeof cmd - 1;
            mcpy(cmd, line, cn); cmd[cn] = 0;
            char *path = (sp < llen) ? line + sp + 1 : (char *)"";
            char *sub_argv[3] = { cmd, path, 0 };
            int sub_argc = (sp < llen) ? 2 : 1;

            int rc = -1;
            if (scmp(cmd, "notepad") == 0) rc = run_notepad(sub_argc, sub_argv);
            else if (scmp(cmd, "word") == 0)  rc = run_word(sub_argc, sub_argv);
            else if (scmp(cmd, "mail") == 0)  rc = run_mail(sub_argc, sub_argv);
            else if (scmp(cmd, "sheet") == 0) rc = run_sheet(sub_argc, sub_argv);
            else if (scmp(cmd, "paint") == 0) rc = run_paint(sub_argc, sub_argv);
            else if (scmp(cmd, "hex") == 0)   rc = run_hex(sub_argc, sub_argv);
            else if (scmp(cmd, "bfc") == 0)   rc = run_bfc(sub_argc, sub_argv);
            else if (scmp(cmd, "files") == 0) rc = run_files(sub_argc, sub_argv);
            else if (scmp(cmd, "find") == 0)  rc = run_find(sub_argc, sub_argv);
            else if (scmp(cmd, "calc") == 0)  rc = run_calc(sub_argc, sub_argv);
            else if (scmp(cmd, "mines") == 0) rc = run_mines(sub_argc, sub_argv);
            else if (scmp(cmd, "ask") == 0)   rc = run_ask(sub_argc, sub_argv);
            else if (scmp(cmd, "garden") == 0) rc = run_garden(sub_argc, sub_argv);
            else if (scmp(cmd, "hxhnt") == 0)  rc = run_hxhnt (sub_argc, sub_argv);
            else if (scmp(cmd, "rpg") == 0)    rc = run_rpg   (sub_argc, sub_argv);
            else if (scmp(cmd, "lsys") == 0)   rc = run_lsys  (sub_argc, sub_argv);
            else if (scmp(cmd, "bytebeat") == 0 || scmp(cmd, "bb") == 0)
                                                rc = run_bytebeat(sub_argc, sub_argv);
            else { mcpy(msg, "unknown command", 16); msg_kind = 2; }

            (void)rc;
            llen = 0;
            /* Sub-app left the tty in regular raw mode (VMIN=1).  Put
             * the polling mode back so the clock keeps ticking. */
            term_raw_polling();
            continue;
        }
        if (k[0] == 0x7f || k[0] == 8) {  /* backspace */
            if (llen > 0) llen--;
            continue;
        }
        if (k[0] == 'q' && llen == 0) { running = 0; break; }
        if (k[0] >= 32 && k[0] < 127 && llen < (int)sizeof line - 1) {
            line[llen++] = (char)k[0];
        }
    }

    term_cooked();
    return 0;
}


/* ── notepad: cursor-driven edit ───────────────────────── */
/* Helpers over `buf`/`blen` for line navigation. */
static int line_start_at(int p) {
    while (p > 0 && buf[p - 1] != '\n') p--;
    return p;
}
static int line_start_after(int p) {
    while (p < blen && buf[p] != '\n') p++;
    if (p < blen) p++;
    return p;
}
static int line_count_between(int a, int b) {
    int n = 0;
    if (a > b) { int t = a; a = b; b = t; }
    for (int i = a; i < b; i++) if (buf[i] == '\n') n++;
    return n;
}

static int col_of(int p) { return p - line_start_at(p); }

static int move_up(int p) {
    int ls = line_start_at(p);
    if (ls == 0) return p;
    int col = p - ls;
    int prev_start = line_start_at(ls - 1);
    int prev_end = ls - 1;
    int prev_len = prev_end - prev_start;
    if (col > prev_len) col = prev_len;
    return prev_start + col;
}
static int move_down(int p) {
    int next_start = line_start_after(p);
    if (next_start > blen) return p;
    int col = col_of(p);
    int next_end = next_start;
    while (next_end < blen && buf[next_end] != '\n') next_end++;
    int next_len = next_end - next_start;
    if (col > next_len) col = next_len;
    return next_start + col;
}

/* Keep btop so that bcur is visible. */
static void adjust_btop(int rows) {
    if (bcur < btop) btop = line_start_at(bcur);
    while (line_count_between(btop, bcur) >= rows && btop < blen) {
        btop = line_start_after(btop);
    }
}

static int cur_sx, cur_sy;

static void notepad_draw(const char *title, int word_wrap) {
    paint_desktop();
    chrome(title);
    body_clear();
    cur_sx = -1; cur_sy = -1;
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    int y = 2;
    int o = btop;
    int maxw = SCREEN_W - 4;
    while (y < SCREEN_H - 1) {
        cup(2, y);
        int xil = 0;
        if (o == bcur) { cur_sx = 2 + xil; cur_sy = y; }
        while (o < blen && buf[o] != '\n') {
            if (xil >= maxw) {
                if (word_wrap) {
                    y++;
                    if (y >= SCREEN_H - 1) goto rendered;
                    cup(2, y);
                    xil = 0;
                    if (o == bcur) { cur_sx = 2 + xil; cur_sy = y; }
                } else {
                    while (o < blen && buf[o] != '\n') o++;
                    break;
                }
            }
            char c = buf[o];
            if (c == '\t') c = ' ';
            if (c >= 32 && c < 127) fbw(&c, 1);
            else fbw(".", 1);
            xil++;
            o++;
            if (o == bcur && cur_sx < 0) { cur_sx = 2 + xil; cur_sy = y; }
        }
        if (o < blen && buf[o] == '\n') o++;
        else if (o >= blen) { y++; break; }
        y++;
    }
rendered:
    if (cur_sx < 0) {
        cur_sx = 2;
        cur_sy = y < SCREEN_H - 1 ? y : SCREEN_H - 2;
    }
    if (cur_sy >= SCREEN_H - 1) cur_sy = SCREEN_H - 2;
    status(word_wrap
        ? "  arrows | enter | bksp | ^J reflow | ^S save | ^Q quit"
        : "  arrows | enter | bksp | ^S save | ^Q quit");
    cup(cur_sx, cur_sy);
    fbs(ESC "[?25h");
    fbflush();
}

/* Reflow paragraph (bounded by \n\n) to `width`: collapse whitespace,
 * break at last space. Static scratch keeps logic simple. */
static char rscratch[4096];
static void reflow_paragraph(int width) {
    int s = bcur;
    while (s > 0) {
        if (s >= 2 && buf[s - 1] == '\n' && buf[s - 2] == '\n') break;
        s--;
    }
    int e = bcur;
    while (e < blen) {
        if (e + 1 < blen && buf[e] == '\n' && buf[e + 1] == '\n') break;
        e++;
    }
    int olen = 0, col = 0, last_sp = -1, saw_sp = 1;
    for (int i = s; i < e && olen < (int)sizeof rscratch - 1; i++) {
        char c = buf[i];
        if (c == ' ' || c == '\t' || c == '\n') {
            if (!saw_sp && olen > 0) {
                rscratch[olen] = ' ';
                last_sp = olen;
                olen++; col++;
                saw_sp = 1;
            }
        } else {
            rscratch[olen++] = c;
            col++;
            saw_sp = 0;
        }
        if (col >= width && last_sp >= 0) {
            rscratch[last_sp] = '\n';
            col = olen - last_sp - 1;
            last_sp = -1;
        }
    }
    while (olen > 0 && rscratch[olen - 1] == ' ') olen--;
    int new_blen = blen - (e - s) + olen;
    if (new_blen > BUF_CAP - 1) return;
    int delta = olen - (e - s);
    if (delta > 0)
        for (int i = blen - 1; i >= e; i--) buf[i + delta] = buf[i];
    else if (delta < 0)
        for (int i = e; i < blen; i++) buf[i + delta] = buf[i];
    for (int i = 0; i < olen; i++) buf[s + i] = rscratch[i];
    blen = new_blen;
    if (bcur > blen) bcur = blen;
}

/* Copy / cut the current line (start..\n) into the clipboard.
 * "Cut" also removes the line from the buffer. */
static void notepad_yank_line(int cut) {
    int s = line_start_at(bcur);
    int e = s;
    while (e < blen && buf[e] != '\n') e++;
    cb_set(buf + s, e - s);
    if (cut) {
        int span = e - s;
        if (e < blen) span++;            /* swallow the trailing \n too */
        for (int i = s; i + span < blen; i++) buf[i] = buf[i + span];
        blen -= span;
        if (bcur > blen) bcur = blen;
        if (bcur > s)    bcur = s;
    }
}

/* Paste raw clipboard bytes at cursor. */
static void cb_paste_at_cur(void) {
    for (int i = 0; i < cb_n; i++) {
        if (blen >= BUF_CAP - 1) break;
        buf_insert(bcur, cb[i]);
        bcur++;
    }
}

static int notepad_loop(const char *title, int word_wrap) {
    term_raw();
    while (1) {
        adjust_btop(SCREEN_H - 4);
        notepad_draw(title, word_wrap);
        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, mi = menu_activation(k, n);
        if (mi >= 0) act = menu_run(word_wrap ? &ms_word : &ms_notepad, mi);
        if (act == MA_ABOUT) {
            show_about(title);
            continue;
        }
        if (act > 0) { k[0] = (unsigned char)act; n = 1; }

        if (k[0] == 0x11) break;                              /* ^Q */
        if (k[0] == 0x13) { save_file(fname); continue; }     /* ^S */
        if (k[0] == 0x0e) { blen = 0; bcur = 0; btop = 0; fname[0] = 0; continue; }  /* ^N */
        if (k[0] == 0x03) { notepad_yank_line(0); continue; } /* ^C */
        if (k[0] == 0x18) { notepad_yank_line(1); continue; } /* ^X */
        if (k[0] == 0x16) { cb_paste_at_cur(); continue; }    /* ^V */
        if (k[0] == 0x0a && word_wrap) { reflow_paragraph(SCREEN_W - 4); continue; }
        if (k[0] == 0x7f || k[0] == 8) {
            if (bcur > 0) { buf_erase(bcur - 1); bcur--; }
            continue;
        }
        if (k[0] == '\r' || k[0] == '\n') {
            buf_insert(bcur, '\n');
            bcur++;
            continue;
        }
        if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
            switch (k[2]) {
            case 'A': bcur = move_up(bcur);     break;
            case 'B': bcur = move_down(bcur);   break;
            case 'C': if (bcur < blen) bcur++;  break;
            case 'D': if (bcur > 0)    bcur--;  break;
            }
            continue;
        }
        if (k[0] >= 32 && k[0] < 127) {
            buf_insert(bcur, (char)k[0]);
            bcur++;
        }
    }
    fbs(ESC "[?25l");
    fbflush();
    return 0;
}

static int run_notepad(int argc, char **argv) {
    current_ms = &ms_notepad;
    if (argc > 1 && argv[1][0]) load_file(argv[1]);
    else { blen = 0; fname[0] = 0; }
    bcur = 0; btop = 0;
    /* find may have set a target line: walk to it. */
    if (npad_target_line > 1) {
        int p = 0, ln = 1;
        while (p < blen && ln < npad_target_line) {
            if (buf[p] == '\n') ln++;
            p++;
        }
        bcur = p;
        npad_target_line = 0;
    }
    return notepad_loop("Notepad", 0);
}

static int run_word(int argc, char **argv) {
    current_ms = &ms_word;
    if (argc > 1 && argv[1][0]) load_file(argv[1]);
    else { blen = 0; fname[0] = 0; }
    bcur = 0; btop = 0;
    return notepad_loop("Word", 1);
}


/* ── mail: compose to ./outbox.txt ─────────────────────── */
static int run_mail(int argc, char **argv) {
    current_ms = &ms_mail;
    (void)argc; (void)argv;
    term_raw();
    char to_[80]    = {0};
    char subj[80]   = {0};
    char body[1024] = {0};
    int  field = 0;     /* 0=to, 1=subject, 2=body */
    int  to_n = 0, subj_n = 0, body_n = 0;
    int  done = 0, sent = 0;

    while (!done) {
        paint_desktop();
        chrome("Mail");
        body_clear();
        body_at(2, 3, "To:      ", SCREEN_W - 4);
        body_at(11, 3, to_, SCREEN_W - 14);
        body_at(2, 4, "Subject: ", SCREEN_W - 4);
        body_at(11, 4, subj, SCREEN_W - 14);
        body_at(2, 6, "Body:", SCREEN_W - 4);
        /* render body across lines 7..16 */
        {
            int x = 2, y = 7;
            cup(x, y);
            for (int i = 0; i < body_n; i++) {
                if (body[i] == '\n' || x >= SCREEN_W - 2) {
                    y++; x = 2;
                    if (y >= SCREEN_H - 4) break;
                    cup(x, y);
                    if (body[i] == '\n') continue;
                }
                fbw(body + i, 1);
                x++;
            }
        }
        cup(2, SCREEN_H - 3);
        sgrbgfg(COL_BAR_BG, 88);
        fbs(field == 0 ? "[To]    " :
            field == 1 ? "[Subj]  " : "[Body]  ");
        sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        if (sent) fbs(" — saved to ./outbox.txt");
        status(" tab switch field | enter newline in body | "
               "ctrl-s save | q quit");
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, mi = menu_activation(k, n);
        if (mi >= 0) act = menu_run(&ms_mail, mi);
        if (act == MA_ABOUT) {
            show_about("Mail");
            continue;
        }
        if (act > 0) { k[0] = (unsigned char)act; n = 1; }

        if (k[0] == 0x16 && field == 2) {            /* ^V paste in body */
            for (int i = 0; i < cb_n && body_n < (int)sizeof body - 1; i++) {
                body[body_n++] = cb[i];
            }
            continue;
        }
        if (k[0] == 'q' && field != 2) break;
        if (k[0] == '\t')   { field = (field + 1) % 3; continue; }
        if (k[0] == 0x13) {                /* Ctrl-S */
            /* Build outbox content into buf and save */
            blen = 0;
            const char *t = "To: ";
            for (int i = 0; t[i]; i++) buf[blen++] = t[i];
            for (int i = 0; i < to_n; i++) buf[blen++] = to_[i];
            buf[blen++] = '\n';
            t = "Subject: ";
            for (int i = 0; t[i]; i++) buf[blen++] = t[i];
            for (int i = 0; i < subj_n; i++) buf[blen++] = subj[i];
            buf[blen++] = '\n';
            buf[blen++] = '\n';
            for (int i = 0; i < body_n; i++) buf[blen++] = body[i];
            mcpy(fname, "outbox.txt", 11);
            save_file(fname);
            sent = 1;
            continue;
        }
        if (k[0] == 0x7f || k[0] == 8) {
            if (field == 0 && to_n   > 0) to_  [--to_n  ] = 0;
            if (field == 1 && subj_n > 0) subj [--subj_n] = 0;
            if (field == 2 && body_n > 0) body [--body_n] = 0;
            continue;
        }
        if (k[0] == '\r' || k[0] == '\n') {
            if (field == 2 && body_n < (int)sizeof body - 1)
                body[body_n++] = '\n';
            else
                field = (field + 1) % 3;
            continue;
        }
        if (k[0] >= 32 && k[0] < 127) {
            if (field == 0 && to_n   < (int)sizeof to_  - 1) to_ [to_n++ ] = (char)k[0];
            if (field == 1 && subj_n < (int)sizeof subj - 1) subj[subj_n++] = (char)k[0];
            if (field == 2 && body_n < (int)sizeof body - 1) body[body_n++] = (char)k[0];
        }
    }
    return 0;
}


/* ── sheet: CSV view + arrow-key navigation, single-cell edit ── */
#define SHEET_COLS 8
#define SHEET_ROWS 12
#define CELL_W     9

static char  cell[SHEET_ROWS][SHEET_COLS][16];
static int   cellrow, cellcol;

/* tiny formula evaluator: =EXPR with + - * /, parens, cell refs A1..H12 */
static const char *fp;
static int feval_expr(int depth);

static void fskip_ws(void) { while (*fp == ' ' || *fp == '\t') fp++; }

static int parse_int_literal(const char *s) {
    int v = 0, neg = 0;
    if (*s == '-') { neg = 1; s++; }
    while (*s >= '0' && *s <= '9') { v = v * 10 + (*s - '0'); s++; }
    return neg ? -v : v;
}

static int feval_cell(int row, int col, int depth) {
    if (row < 0 || row >= SHEET_ROWS || col < 0 || col >= SHEET_COLS) return 0;
    if (depth <= 0) return 0;
    const char *t = cell[row][col];
    if (t[0] == '=') {
        const char *save = fp;
        fp = t + 1;
        int v = feval_expr(depth - 1);
        fp = save;
        return v;
    }
    return parse_int_literal(t);
}

/* Try to parse a cell ref at *fp. Returns 1 + advances fp on success. */
static int try_cellref(int *row, int *col) {
    char L = *fp;
    int c = -1;
    if (L >= 'a' && L <= 'h') c = L - 'a';
    else if (L >= 'A' && L <= 'H') c = L - 'A';
    if (c < 0) return 0;
    if (!(fp[1] >= '0' && fp[1] <= '9')) return 0;
    fp++;
    int r = 0;
    while (*fp >= '0' && *fp <= '9') { r = r * 10 + (*fp - '0'); fp++; }
    *col = c;
    *row = r - 1;
    return 1;
}

/* Match a 3-letter uppercase keyword followed by '(' . On match, fp
 * advances past the opening paren and returns 1. Otherwise unchanged. */
static int match_func(const char *kw) {
    int i = 0;
    while (kw[i]) {
        char c = fp[i];
        if (c >= 'a' && c <= 'z') c = (char)(c - 32);
        if (c != kw[i]) return 0;
        i++;
    }
    if (fp[i] != '(') return 0;
    fp += i + 1;
    return 1;
}

/* Reduce a SUM/AVG/MIN/MAX range to a single int. kind: 0 sum, 1 avg, 2 min, 3 max */
static int range_reduce(int kind, int depth) {
    int r1, c1, r2, c2;
    fskip_ws();
    if (!try_cellref(&r1, &c1)) { /* swallow until ')' */
        while (*fp && *fp != ')') fp++;
        if (*fp == ')') fp++;
        return 0;
    }
    fskip_ws();
    if (*fp != ':') {
        /* single cell */
        if (*fp == ')') fp++;
        return feval_cell(r1, c1, depth);
    }
    fp++;
    fskip_ws();
    if (!try_cellref(&r2, &c2)) {
        if (*fp == ')') fp++;
        return feval_cell(r1, c1, depth);
    }
    fskip_ws();
    if (*fp == ')') fp++;
    if (r2 < r1) { int t = r1; r1 = r2; r2 = t; }
    if (c2 < c1) { int t = c1; c1 = c2; c2 = t; }
    if (r1 < 0) r1 = 0;
    if (c1 < 0) c1 = 0;
    if (r2 >= SHEET_ROWS) r2 = SHEET_ROWS - 1;
    if (c2 >= SHEET_COLS) c2 = SHEET_COLS - 1;
    long acc = 0;
    int  count = 0;
    int  best = 0, has = 0;
    for (int r = r1; r <= r2; r++) {
        for (int c = c1; c <= c2; c++) {
            int v = feval_cell(r, c, depth);
            acc += v; count++;
            if (!has) { best = v; has = 1; }
            else if (kind == 2 && v < best) best = v;
            else if (kind == 3 && v > best) best = v;
        }
    }
    if (kind == 0) return (int)acc;
    if (kind == 1) return count ? (int)(acc / count) : 0;
    return best;
}

static int feval_atom(int depth) {
    fskip_ws();
    if (*fp == '(') {
        fp++;
        int v = feval_expr(depth);
        fskip_ws();
        if (*fp == ')') fp++;
        return v;
    }
    if (*fp == '-') { fp++; return -feval_atom(depth); }
    if (*fp == '+') { fp++; return  feval_atom(depth); }
    if (*fp >= '0' && *fp <= '9') {
        int v = 0;
        while (*fp >= '0' && *fp <= '9') { v = v * 10 + (*fp - '0'); fp++; }
        return v;
    }
    if (match_func("SUM")) return range_reduce(0, depth);
    if (match_func("AVG")) return range_reduce(1, depth);
    if (match_func("MIN")) return range_reduce(2, depth);
    if (match_func("MAX")) return range_reduce(3, depth);
    int row, col;
    if (try_cellref(&row, &col)) return feval_cell(row, col, depth);
    return 0;
}

static int feval_term(int depth) {
    int v = feval_atom(depth);
    while (1) {
        fskip_ws();
        if (*fp == '*') { fp++; v *= feval_atom(depth); }
        else if (*fp == '/') { fp++; int d = feval_atom(depth); v = d ? v / d : 0; }
        else break;
    }
    return v;
}

static int feval_expr(int depth) {
    int v = feval_term(depth);
    while (1) {
        fskip_ws();
        if (*fp == '+') { fp++; v += feval_term(depth); }
        else if (*fp == '-') { fp++; v -= feval_term(depth); }
        else break;
    }
    return v;
}

static int sheet_eval(const char *formula) {
    fp = formula + 1;
    return feval_expr(8);
}

static int itoa_(int v, char *out) {
    int n = 0;
    if (v < 0) {
        out[n++] = '-';
        n += utoa((unsigned)(-(long)v), out + n);
    } else {
        n = utoa((unsigned)v, out);
    }
    return n;
}

static void sheet_load_csv(void) {
    mset(cell, 0, sizeof cell);
    int r = 0, c = 0, i = 0;
    for (int o = 0; o < blen && r < SHEET_ROWS; o++) {
        char ch = buf[o];
        if (ch == ',') {
            cell[r][c][i] = 0;
            if (c < SHEET_COLS - 1) c++;
            i = 0;
        } else if (ch == '\n') {
            cell[r][c][i] = 0;
            r++; c = 0; i = 0;
        } else if (i < 15) {
            cell[r][c][i++] = ch;
        }
    }
}

static void sheet_save_csv(void) {
    blen = 0;
    for (int r = 0; r < SHEET_ROWS; r++) {
        for (int c = 0; c < SHEET_COLS; c++) {
            int n = slen(cell[r][c]);
            for (int i = 0; i < n && blen < BUF_CAP - 2; i++) buf[blen++] = cell[r][c][i];
            if (c < SHEET_COLS - 1 && blen < BUF_CAP - 1) buf[blen++] = ',';
        }
        if (blen < BUF_CAP - 1) buf[blen++] = '\n';
    }
    save_file(fname);
}

static int run_sheet(int argc, char **argv) {
    current_ms = &ms_sheet;
    if (argc > 1 && argv[1][0]) {
        load_file(argv[1]);
        sheet_load_csv();
    } else {
        mset(cell, 0, sizeof cell);
        fname[0] = 0;
    }
    cellrow = 0; cellcol = 0;
    term_raw();

    int editing = 0;
    int eidx = 0;

    while (1) {
        paint_desktop();
        chrome("Sheet");
        body_clear();
        /* Column headers */
        cup(2, 2);
        sgrbgfg(7, 8);
        fbs("    ");
        for (int c = 0; c < SHEET_COLS; c++) {
            char h = 'A' + c;
            fbw(" ", 1);
            fbw(&h, 1);
            for (int j = 0; j < CELL_W - 2; j++) fbw(" ", 1);
        }
        for (int r = 0; r < SHEET_ROWS && r + 3 < SCREEN_H - 1; r++) {
            cup(2, 3 + r);
            sgrbgfg(7, 8);
            char rh[3] = { ' ', (char)('1' + r % 9), ' ' };
            fbw(rh, 3);
            fbw(" ", 1);
            for (int c = 0; c < SHEET_COLS; c++) {
                int sel = (r == cellrow && c == cellcol);
                if (sel) sgrbgfg(15, 0);
                else     sgrbgfg(7, 0);
                char shown[16];
                int  len;
                int  is_formula = (cell[r][c][0] == '=');
                if (is_formula && !(editing && sel)) {
                    int v = sheet_eval(cell[r][c]);
                    len = itoa_(v, shown);
                    if (len > CELL_W - 1) len = CELL_W - 1;
                    sgrbgfg(sel ? 15 : 7, sel ? 0 : 21);   /* blue fg = formula */
                    fbw(shown, len);
                } else {
                    len = slen(cell[r][c]);
                    if (len > CELL_W - 1) len = CELL_W - 1;
                    fbw(cell[r][c], len);
                }
                sgrbgfg(sel ? 15 : 7, 0);
                blanks(CELL_W - len);
            }
        }
        char hint[80] = { 0 };
        int hn = 0;
        const char *h = editing
            ? "  editing — enter commits, esc cancels  (=A1+B2 for formulas)"
            : "  arrows move | e edit | s save csv | q back";
        while (h[hn]) { hint[hn] = h[hn]; hn++; }
        status(hint);
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        if (editing) {
            if (k[0] == '\r' || k[0] == '\n') {
                cell[cellrow][cellcol][eidx] = 0;
                editing = 0;
                continue;
            }
            if (k[0] == 0x1b && n == 1) {
                editing = 0;
                continue;
            }
            if (k[0] == 0x7f || k[0] == 8) {
                if (eidx > 0) cell[cellrow][cellcol][--eidx] = 0;
                continue;
            }
            if (k[0] == 0x16) {                          /* ^V paste in edit */
                for (int i = 0; i < cb_n && eidx < 15; i++) {
                    if (cb[i] >= 32 && cb[i] < 127)
                        cell[cellrow][cellcol][eidx++] = cb[i];
                }
                cell[cellrow][cellcol][eidx] = 0;
                continue;
            }
            if (k[0] >= 32 && k[0] < 127 && eidx < 15) {
                cell[cellrow][cellcol][eidx++] = (char)k[0];
            }
            continue;
        }

        int act = -1, ami = menu_activation(k, n);
        if (ami >= 0) act = menu_run(&ms_sheet, ami);
        if (act == MA_ABOUT) {
            show_about("Sheet");
            continue;
        }
        if (act > 0) { k[0] = (unsigned char)act; n = 1; }

        if (k[0] == 'q' || k[0] == MA_QUIT) break;
        if (k[0] == 's' || k[0] == MA_SAVE) sheet_save_csv();
        if (k[0] == 'e') {
            editing = 1;
            eidx = slen(cell[cellrow][cellcol]);
        }
        if (k[0] == 0x03 || k[0] == 0x18) {              /* copy / cut cell */
            cb_set(cell[cellrow][cellcol], slen(cell[cellrow][cellcol]));
            if (k[0] == 0x18) cell[cellrow][cellcol][0] = 0;
        }
        if (k[0] == 0x16) {                              /* paste cell */
            int put = cb_n; if (put > 15) put = 15;
            int j = 0;
            for (int i = 0; i < put; i++) {
                if (cb[i] >= 32 && cb[i] < 127) cell[cellrow][cellcol][j++] = cb[i];
            }
            cell[cellrow][cellcol][j] = 0;
        }
        if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
            switch (k[2]) {
            case 'A': if (cellrow > 0) cellrow--; break;
            case 'B': if (cellrow < SHEET_ROWS - 1) cellrow++; break;
            case 'C': if (cellcol < SHEET_COLS - 1) cellcol++; break;
            case 'D': if (cellcol > 0) cellcol--; break;
            }
        }
    }
    return 0;
}


/* ── paint: ASCII canvas, per-cell colour ─────────────── */
#define PAINT_W 60
#define PAINT_H 16
static char           canvas[PAINT_H][PAINT_W];
static unsigned char  canvas_fg[PAINT_H][PAINT_W];
static int  px, py;
static int  brush = 1;     /* foreground colour (xterm-256) */
static char brush_char = '#';

static int paint_load(const char *path) {
    int fd = (int)op(path, O_RDONLY, 0);
    if (fd < 0) return 0;
    int n = (int)rd(fd, buf, BUF_CAP - 1);
    cl(fd);
    if (n <= 0) return 0;
    /* Format: "<hex><char> <hex><char> ... \n" per row. */
    int o = 0, r = 0;
    while (r < PAINT_H && o + 1 < n) {
        int c = 0;
        while (c < PAINT_W && o + 1 < n && buf[o] != '\n') {
            char hx = buf[o++];
            int fg = (hx >= 'a' && hx <= 'f') ? hx - 'a' + 10
                   : (hx >= 'A' && hx <= 'F') ? hx - 'A' + 10
                   : (hx >= '0' && hx <= '9') ? hx - '0' : 0;
            canvas_fg[r][c] = (unsigned char)fg;
            canvas[r][c] = buf[o++];
            c++;
        }
        if (o < n && buf[o] == '\n') o++;
        r++;
    }
    return 1;
}

static int run_paint(int argc, char **argv) {
    current_ms = &ms_paint;
    mset(canvas, ' ', sizeof canvas);
    mset(canvas_fg, 0, sizeof canvas_fg);
    if (argc > 1 && argv[1][0]) {
        int i = 0;
        while (i < (int)sizeof fname - 1 && argv[1][i]) {
            fname[i] = argv[1][i]; i++;
        }
        fname[i] = 0;
        paint_load(fname);
    } else {
        mcpy(fname, "canvas.txt", 11);
    }
    px = PAINT_W / 2; py = PAINT_H / 2;
    term_raw();
    while (1) {
        paint_desktop();
        chrome("Paint");
        body_clear();
        int prev_fg = -1;
        for (int r = 0; r < PAINT_H; r++) {
            cup(2, 3 + r);
            for (int c = 0; c < PAINT_W; c++) {
                int fg = canvas_fg[r][c];
                if (fg != prev_fg) { sgrbgfg(15, fg); prev_fg = fg; }
                fbw(&canvas[r][c], 1);
            }
        }
        cup(2 + px, 3 + py);
        sgrbgfg(brush, 0);
        fbw(&canvas[py][px], 1);
        char info[40] = { 0 };
        int n = 0;
        const char *l = "  arrows move | letters paint | 0-7 colour | s save | q back";
        while (l[n]) { info[n] = l[n]; n++; }
        status(info);
        fbflush();

        unsigned char k[8];
        int rn = read_key(k, sizeof k);
        if (rn <= 0) continue;

        int act = -1, mi = menu_activation(k, rn);
        if (mi >= 0) act = menu_run(&ms_paint, mi);
        if (act == MA_ABOUT) {
            show_about("Paint");
            continue;
        }
        if (act > 0) { k[0] = (unsigned char)act; rn = 1; }

        if (k[0] == 'q' || k[0] == MA_QUIT) break;
        if (k[0] == 's' || k[0] == MA_SAVE) {
            blen = 0;
            for (int r = 0; r < PAINT_H && blen < BUF_CAP - 1; r++) {
                for (int c = 0; c < PAINT_W && blen + 2 < BUF_CAP - 1; c++) {
                    int fg = canvas_fg[r][c] & 0xf;
                    buf[blen++] = (char)(fg < 10 ? '0' + fg : 'a' + fg - 10);
                    buf[blen++] = canvas[r][c];
                }
                if (blen < BUF_CAP - 1) buf[blen++] = '\n';
            }
            if (!fname[0]) mcpy(fname, "canvas.txt", 11);
            save_file(fname);
        }
        if (k[0] >= '0' && k[0] <= '7') brush = k[0] - '0';
        if (rn >= 3 && k[0] == 0x1b && k[1] == '[') {
            switch (k[2]) {
            case 'A': if (py > 0) py--; break;
            case 'B': if (py < PAINT_H - 1) py++; break;
            case 'C': if (px < PAINT_W - 1) px++; break;
            case 'D': if (px > 0) px--; break;
            }
        }
        if (k[0] >= 32 && k[0] < 127 && k[0] != 'q' && k[0] != 's' &&
            !(k[0] >= '0' && k[0] <= '7')) {
            brush_char = (char)k[0];
            canvas[py][px] = brush_char;
            canvas_fg[py][px] = (unsigned char)brush;
        }
    }
    return 0;
}


/* ── hex editor: 16 bytes/line view + nibble write ─────── */
static int run_hex(int argc, char **argv) {
    current_ms = &ms_hex;
    if (argc > 1 && argv[1][0]) load_file(argv[1]);
    else { blen = 0; fname[0] = 0; }
    bcur = 0; btop = 0;
    int nibhi = 1;            /* next digit goes to high nibble */
    int ascii_pane = 0;       /* 0 = hex side, 1 = ascii side */
    term_raw();
    while (1) {
        int rows = SCREEN_H - 4;
        if (bcur < btop) btop = (bcur / 16) * 16;
        if (bcur >= btop + rows * 16) btop = ((bcur / 16) - rows + 1) * 16;
        if (btop < 0) btop = 0;

        paint_desktop();
        chrome("Hex");
        body_clear();
        for (int r = 0; r < rows; r++) {
            int o = btop + r * 16;
            cup(2, 3 + r);
            sgrbgfg(7, 8);
            char hx[8];
            unsigned u = (unsigned)o;
            for (int s = 16, i = 0; s; s -= 4, i++) {
                int v = (u >> (s - 4)) & 0xf;
                hx[i] = (char)(v < 10 ? '0' + v : 'a' + v - 10);
            }
            fbw(hx, 8);
            fbw("  ", 2);
            char asc[16];
            int  cur_in_row = -1;
            int  an = 0;
            for (int j = 0; j < 16; j++) {
                int oo = o + j;
                int is_cur = (oo == bcur);
                if (is_cur) cur_in_row = j;
                if (oo >= blen) {
                    sgrbgfg(is_cur && !ascii_pane ? 15 : 7, 8);
                    fbw("__ ", 3);
                    asc[an++] = ' ';
                    continue;
                }
                unsigned u8 = (unsigned char)buf[oo];
                int hi = (u8 >> 4) & 0xf, lo = u8 & 0xf;
                char hh = (char)(hi < 10 ? '0' + hi : 'a' + hi - 10);
                char ll = (char)(lo < 10 ? '0' + lo : 'a' + lo - 10);
                int hex_hi_hi = is_cur && !ascii_pane && nibhi;
                int hex_hi_lo = is_cur && !ascii_pane && !nibhi;
                sgrbgfg(hex_hi_hi ? 15 : 7, 0); fbw(&hh, 1);
                sgrbgfg(hex_hi_lo ? 15 : 7, 0); fbw(&ll, 1);
                sgrbgfg(7, 0); fbw(" ", 1);
                asc[an++] = (u8 >= 32 && u8 < 127) ? (char)u8 : '.';
            }
            fbw(" ", 1);
            /* render ascii column with selective highlight */
            for (int j = 0; j < an; j++) {
                int hl = (ascii_pane && cur_in_row == j);
                sgrbgfg(hl ? 15 : 7, 0);
                fbw(asc + j, 1);
            }
        }
        status(ascii_pane
            ? "  ASCII mode | tab→hex | printable overwrites | ^S save | q"
            : "  HEX mode | tab→ASCII | 0-9 a-f write | i ins | x del | ^S save | q");
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, mi = menu_activation(k, n);
        if (mi >= 0) act = menu_run(&ms_hex, mi);
        if (act == MA_ABOUT) {
            show_about("Hex");
            continue;
        }
        if (act > 0) { k[0] = (unsigned char)act; n = 1; }

        if (k[0] == 0x13) { save_file(fname); continue; }
        if (k[0] == '\t' || k[0] == MA_HEXTOG) {
            ascii_pane = !ascii_pane; nibhi = 1; continue;
        }
        if (k[0] == 0x03 || k[0] == 0x18) {                 /* copy/cut row */
            int s = (bcur / 16) * 16;
            int e = s + 16; if (e > blen) e = blen;
            cb_set(buf + s, e - s);
            if (k[0] == 0x18) {
                int span = e - s;
                for (int i = s; i + span < blen; i++) buf[i] = buf[i + span];
                blen -= span;
                if (bcur > blen) bcur = blen;
            }
            nibhi = 1;
            continue;
        }
        if (k[0] == 0x16) {                                  /* paste */
            for (int i = 0; i < cb_n; i++) {
                if (blen >= BUF_CAP - 1) break;
                for (int j = blen; j > bcur; j--) buf[j] = buf[j - 1];
                buf[bcur] = cb[i];
                blen++; bcur++;
            }
            nibhi = 1;
            continue;
        }
        if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
            switch (k[2]) {
            case 'A': if (bcur >= 16) bcur -= 16; nibhi = 1; break;
            case 'B': if (bcur + 16 <= blen) bcur += 16;
                      else if (bcur < blen) bcur = blen;
                      nibhi = 1; break;
            case 'C': if (bcur < blen) bcur++; nibhi = 1; break;
            case 'D': if (bcur > 0) bcur--; nibhi = 1; break;
            }
            continue;
        }
        if (ascii_pane) {
            if (k[0] == 'q' || k[0] == 0x11) break;     /* q or Ctrl-Q */
            if (k[0] >= 32 && k[0] < 127) {
                if (bcur >= blen) {
                    if (blen >= BUF_CAP - 1) continue;
                    buf[blen++] = 0;
                }
                buf[bcur] = (char)k[0];
                if (bcur < BUF_CAP - 1 && bcur + 1 <= blen) bcur++;
            }
            continue;
        }
        if (k[0] == 'q') break;
        if (k[0] == 'i') {
            if (blen < BUF_CAP - 1) {
                for (int i = blen; i > bcur; i--) buf[i] = buf[i - 1];
                buf[bcur] = 0; blen++; nibhi = 1;
            }
            continue;
        }
        if (k[0] == 'x') {
            if (bcur < blen) {
                buf_erase(bcur);
                if (bcur >= blen && bcur > 0) bcur--;
                nibhi = 1;
            }
            continue;
        }
        int hv = -1;
        if (k[0] >= '0' && k[0] <= '9') hv = k[0] - '0';
        else if (k[0] >= 'a' && k[0] <= 'f') hv = k[0] - 'a' + 10;
        else if (k[0] >= 'A' && k[0] <= 'F') hv = k[0] - 'A' + 10;
        if (hv >= 0) {
            if (bcur >= blen) {
                if (blen >= BUF_CAP - 1) continue;
                buf[blen++] = 0;
            }
            unsigned char b = (unsigned char)buf[bcur];
            if (nibhi) {
                buf[bcur] = (char)((b & 0x0f) | (hv << 4));
                nibhi = 0;
            } else {
                buf[bcur] = (char)((b & 0xf0) | hv);
                if (bcur < BUF_CAP - 1) bcur++;
                nibhi = 1;
            }
        }
    }
    return 0;
}


/* ── bfc: brainfuck compiler/interpreter — runs the program ── */
#define TAPE_LEN 4096
static unsigned char tape[TAPE_LEN];

static int run_bfc(int argc, char **argv) {
    current_ms = &ms_files;
    if (argc < 2 || !argv[1][0]) return 1;
    load_file(argv[1]);
    term_raw();
    /* Run BF program: emit output to a captured buffer, then show. */
    char out[4096];
    int  on = 0;
    int  ip = 0, dp = 0;
    mset(tape, 0, sizeof tape);
    while (ip < blen && on < (int)sizeof out - 1) {
        char c = buf[ip++];
        if (c == '+') tape[dp]++;
        else if (c == '-') tape[dp]--;
        else if (c == '>') { if (dp < TAPE_LEN - 1) dp++; }
        else if (c == '<') { if (dp > 0) dp--; }
        else if (c == '.') out[on++] = (char)tape[dp];
        else if (c == ',') { /* no input */ tape[dp] = 0; }
        else if (c == '[' && tape[dp] == 0) {
            int d = 1;
            while (ip < blen && d) {
                if (buf[ip] == '[') d++;
                else if (buf[ip] == ']') d--;
                ip++;
            }
        }
        else if (c == ']' && tape[dp] != 0) {
            int d = 1;
            ip -= 2;
            while (ip >= 0 && d) {
                if (buf[ip] == ']') d++;
                else if (buf[ip] == '[') d--;
                if (d) ip--;
            }
        }
    }
    out[on] = 0;
    /* Render */
    while (1) {
        paint_desktop();
        chrome("BF Compiler — output");
        body_clear();
        int x = 2, y = 3;
        cup(x, y);
        for (int i = 0; i < on; i++) {
            char c = out[i];
            if (c == '\n' || x >= SCREEN_W - 2) {
                y++; x = 2;
                if (y >= SCREEN_H - 2) break;
                cup(x, y);
                if (c == '\n') continue;
            }
            fbw(&c, 1);
            x++;
        }
        char st[80] = { 0 };
        int  sn = 0;
        const char *t = "  q to quit";
        while (t[sn]) { st[sn] = t[sn]; sn++; }
        status(st);
        fbflush();
        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;
        int ami = menu_activation(k, n);
        if (ami >= 0) {
            int act = menu_run(&ms_files, ami);
            if (act == MA_ABOUT) {
                show_about("BFC");
                continue;
            }
            if (act == MA_QUIT) break;
            continue;
        }
        if (k[0] == 'q') break;
    }
    return 0;
}


/* ── files: directory browser ─────────────────────────── */
struct linux_dirent64 {
    long          d_ino;
    long          d_off;
    unsigned short d_reclen;
    unsigned char  d_type;
    char           d_name[];
};

#define FILES_MAX 64
static char files_name[FILES_MAX][64];
static unsigned char files_type[FILES_MAX];   /* 4 = dir, 8 = file */
static int  files_count;

static int files_scan(const char *path) {
    files_count = 0;
    int fd = (int)op(path, O_RDONLY, 0);
    if (fd < 0) return 0;
    char db[4096];
    while (files_count < FILES_MAX) {
        long n = sys3(SYS_getdents64, fd, (long)db, (long)sizeof db);
        if (n <= 0) break;
        long o = 0;
        while (o < n && files_count < FILES_MAX) {
            struct linux_dirent64 *de = (struct linux_dirent64 *)(db + o);
            const char *nm = de->d_name;
            if (!(nm[0] == '.' && nm[1] == 0)) {
                int i = 0;
                while (i < 63 && nm[i]) { files_name[files_count][i] = nm[i]; i++; }
                files_name[files_count][i] = 0;
                files_type[files_count] = de->d_type;
                files_count++;
            }
            o += de->d_reclen;
        }
    }
    cl(fd);
    return files_count;
}

static int run_files(int argc, char **argv) {
    current_ms = &ms_files;
    (void)argc; (void)argv;
    files_scan(".");
    int sel = 0;
    term_raw();
    while (1) {
        paint_desktop();
        chrome("Files");
        body_clear();
        body_at(2, 2, "  ./", SCREEN_W - 4);
        int top = sel < SCREEN_H - 7 ? 0 : sel - (SCREEN_H - 7);
        for (int i = 0; i < SCREEN_H - 5 && top + i < files_count; i++) {
            int idx = top + i;
            cup(2, 4 + i);
            if (idx == sel) sgrbgfg(15, 0); else sgrbgfg(7, 0);
            char tag = files_type[idx] == 4 ? '/' : ' ';
            fbw(" ", 1);
            fbw(&tag, 1);
            fbw(" ", 1);
            int nl = slen(files_name[idx]);
            if (nl > SCREEN_W - 8) nl = SCREEN_W - 8;
            fbw(files_name[idx], nl);
            blanks(SCREEN_W - 8 - nl);
        }
        status("  arrows | enter open in notepad | h hex | q back");
        fbflush();
        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, ami = menu_activation(k, n);
        if (ami >= 0) act = menu_run(&ms_files, ami);
        if (act == MA_ABOUT) {
            show_about("Files");
            continue;
        }
        if (k[0] == 'q' || act == MA_QUIT) break;
        if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
            if (k[2] == 'A' && sel > 0) sel--;
            if (k[2] == 'B' && sel + 1 < files_count) sel++;
            continue;
        }
        if (k[0] == '\r' || k[0] == '\n') {
            if (sel >= 0 && sel < files_count) {
                if (files_type[sel] == 4) {
                    /* descend not supported in v1 — would need cwd tracking */
                    continue;
                }
                char *sub_argv[3] = { (char *)"notepad", files_name[sel], 0 };
                run_notepad(2, sub_argv);
                term_raw();
            }
            continue;
        }
        if (k[0] == 'h') {
            if (sel >= 0 && sel < files_count && files_type[sel] != 4) {
                char *sub_argv[3] = { (char *)"hex", files_name[sel], 0 };
                run_hex(2, sub_argv);
                term_raw();
            }
            continue;
        }
    }
    return 0;
}


/* ── find: grep across files in cwd ───────────────────── */
#define FIND_MAX 80
static char find_q[80];
static int  find_qn;
static char find_path[FIND_MAX][64];
static int  find_line[FIND_MAX];
static char find_text[FIND_MAX][64];
static int  find_count;

/* Append matches from `path` to the find_* arrays. Reads via the
 * shared `buf` scratch; that means find clobbers any in-memory
 * notepad buffer, but find always runs as its own app instance. */
static void find_in_file(const char *path) {
    int fd = (int)op(path, O_RDONLY, 0);
    if (fd < 0) return;
    int n = (int)rd(fd, buf, BUF_CAP - 1);
    cl(fd);
    if (n <= 0) return;
    int line_no = 1, line_start = 0;
    for (int i = 0; i <= n; i++) {
        if (i == n || buf[i] == '\n') {
            int line_end = i;
            int matched = 0;
            for (int s = line_start; s + find_qn <= line_end; s++) {
                int ok = 1;
                for (int j = 0; j < find_qn; j++)
                    if (buf[s + j] != find_q[j]) { ok = 0; break; }
                if (ok) { matched = 1; break; }
            }
            if (matched && find_count < FIND_MAX) {
                int p = 0; while (p < 63 && path[p]) { find_path[find_count][p] = path[p]; p++; }
                find_path[find_count][p] = 0;
                find_line[find_count] = line_no;
                int len = line_end - line_start;
                if (len > 63) len = 63;
                for (int j = 0; j < len; j++)
                    find_text[find_count][j] = buf[line_start + j];
                find_text[find_count][len] = 0;
                find_count++;
            }
            line_no++;
            line_start = i + 1;
        }
    }
}

static int run_find(int argc, char **argv) {
    current_ms = &ms_find;
    (void)argc; (void)argv;
    term_raw();
    find_qn = 0; find_count = 0;
    int phase = 0;       /* 0 = entering query, 1 = browsing results */
    int sel = 0;
    while (1) {
        paint_desktop();
        chrome("Find");
        body_clear();
        body_at(2, 3, "Search for:", SCREEN_W - 4);
        cup(2, 5);
        sgrbgfg(phase == 0 ? 15 : 7, 0);
        fbs(" "); fbw(find_q, find_qn);
        blanks(40 - find_qn);
        if (phase == 1) {
            int top = sel < SCREEN_H - 9 ? 0 : sel - (SCREEN_H - 9);
            for (int i = 0; i < SCREEN_H - 8 && top + i < find_count; i++) {
                int idx = top + i;
                cup(2, 7 + i);
                sgrbgfg(idx == sel ? 15 : 7, 0);
                fbs(" ");
                int pn = slen(find_path[idx]);
                fbw(find_path[idx], pn);
                fbw(":", 1);
                char ln[8]; int ln_n = utoa(find_line[idx], ln);
                fbw(ln, ln_n);
                fbs(": ");
                int tn = slen(find_text[idx]);
                if (tn > SCREEN_W - 8 - pn - ln_n) tn = SCREEN_W - 8 - pn - ln_n;
                fbw(find_text[idx], tn);
            }
            if (find_count == 0) body_at(2, 7, "  (no matches)", 40);
        }
        status(phase == 0
            ? "  type query | enter search | q back"
            : "  arrows | enter open hit | / new query | q back");
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, ami = menu_activation(k, n);
        if (ami >= 0) act = menu_run(&ms_find, ami);
        if (act == MA_ABOUT) {
            show_about("Find");
            continue;
        }
        if (act == MA_QUIT) break;

        if (phase == 0) {
            if (k[0] == 'q' && find_qn == 0) break;
            if (k[0] == '\r' || k[0] == '\n') {
                if (find_qn == 0) continue;
                find_count = 0;
                files_scan(".");
                for (int i = 0; i < files_count && find_count < FIND_MAX; i++) {
                    if (files_type[i] == 8) find_in_file(files_name[i]);
                }
                phase = 1;
                sel = 0;
                continue;
            }
            if (k[0] == 0x7f || k[0] == 8) {
                if (find_qn) find_qn--;
                continue;
            }
            if (k[0] >= 32 && k[0] < 127 && find_qn < 79)
                find_q[find_qn++] = (char)k[0];
        } else {
            if (k[0] == 'q') break;
            if (k[0] == '/') { phase = 0; continue; }
            if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
                if (k[2] == 'A' && sel > 0) sel--;
                if (k[2] == 'B' && sel + 1 < find_count) sel++;
                continue;
            }
            if (k[0] == '\r' || k[0] == '\n') {
                if (sel < find_count) {
                    char *sub_argv[3] = { (char *)"notepad", find_path[sel], 0 };
                    npad_target_line = find_line[sel];
                    run_notepad(2, sub_argv);
                    npad_target_line = 0;
                    term_raw();
                }
            }
        }
    }
    return 0;
}


/* ── calc: single-line expression input ────────────────── */
static int run_calc(int argc, char **argv) {
    current_ms = &ms_calc;
    (void)argc; (void)argv;
    term_raw();
    char line[80]; int llen = 0;
    int has_result = 0; int result = 0;
    /* Calc reuses the sheet's formula engine, which references
     * `cell[][]`. Zero-init keeps cell refs evaluating to 0. */
    mset(cell, 0, sizeof cell);
    while (1) {
        paint_desktop();
        chrome("Calc");
        body_clear();
        body_at(2, 3, "Expression (e.g. 2*(3+4) or =5+6):", SCREEN_W - 4);
        cup(2, 5);
        sgrbgfg(15, 0);
        fbs(" "); fbw(line, llen); fbs(" ");
        blanks(40 - llen);
        if (has_result) {
            cup(2, 7);
            sgrbgfg(COL_BAR_BG, 22);
            fbs(" = ");
            char r[16]; int rn = itoa_(result, r);
            fbw(r, rn);
        }
        status("  enter compute | ^V paste | q back");
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, ami = menu_activation(k, n);
        if (ami >= 0) act = menu_run(&ms_calc, ami);
        if (act == MA_ABOUT) {
            show_about("Calc");
            continue;
        }
        if (act == MA_QUIT) break;
        if (act > 0) k[0] = (unsigned char)act;

        if (k[0] == 'q' && llen == 0) break;
        if (k[0] == 0x16) {                                /* ^V paste */
            for (int i = 0; i < cb_n && llen < 79; i++)
                if (cb[i] >= 32 && cb[i] < 127) line[llen++] = cb[i];
            continue;
        }
        if (k[0] == '\r' || k[0] == '\n') {
            line[llen] = 0;
            fp = (line[0] == '=') ? line + 1 : line;
            result = feval_expr(8);
            has_result = 1;
            continue;
        }
        if (k[0] == 0x7f || k[0] == 8) { if (llen) llen--; continue; }
        if (k[0] >= 32 && k[0] < 127 && llen < 79) line[llen++] = (char)k[0];
    }
    return 0;
}


/* ── mines: 16x16 Minesweeper ─────────────────────────── */
#define M_W 16
#define M_H 16
#define M_COUNT 40

/* per-cell bits: 0x10=mine, 0x20=revealed, 0x40=flagged, low4=neighbours */
static unsigned char m_grid[M_H][M_W];
static int m_cx, m_cy, m_lost, m_won, m_first;

static unsigned long rdtsc_(void) {
    unsigned int hi, lo;
    __asm__ volatile ("rdtsc" : "=a"(lo), "=d"(hi));
    return ((unsigned long)hi << 32) | lo;
}

static void mines_layout(int avoid_r, int avoid_c) {
    unsigned long s = rdtsc_();
    int placed = 0;
    while (placed < M_COUNT) {
        s = s * 6364136223846793005UL + 1442695040888963407UL;
        int idx = (int)((s >> 16) % (M_W * M_H));
        int r = idx / M_W, c = idx % M_W;
        if (r == avoid_r && c == avoid_c) continue;
        if (m_grid[r][c] & 0x10) continue;
        m_grid[r][c] |= 0x10;
        placed++;
    }
    for (int r = 0; r < M_H; r++)
        for (int c = 0; c < M_W; c++) {
            if (m_grid[r][c] & 0x10) continue;
            int n = 0;
            for (int dr = -1; dr <= 1; dr++)
                for (int dc = -1; dc <= 1; dc++) {
                    int nr = r + dr, nc = c + dc;
                    if (nr < 0 || nr >= M_H || nc < 0 || nc >= M_W) continue;
                    if (m_grid[nr][nc] & 0x10) n++;
                }
            m_grid[r][c] |= (unsigned char)n;
        }
}

static void mines_init(void) {
    mset(m_grid, 0, sizeof m_grid);
    m_lost = 0; m_won = 0; m_first = 1;
    m_cx = M_W / 2; m_cy = M_H / 2;
}

/* Iterative flood-fill via a local queue (avoids deep recursion). */
static void mines_reveal(int r0, int c0) {
    static unsigned short q[M_W * M_H];
    int head = 0, tail = 0;
    q[tail++] = (unsigned short)(r0 * M_W + c0);
    while (head < tail) {
        int idx = q[head++];
        int r = idx / M_W, c = idx % M_W;
        if (m_grid[r][c] & 0x20) continue;
        if (m_grid[r][c] & 0x40) continue;
        m_grid[r][c] |= 0x20;
        if (m_grid[r][c] & 0x10) { m_lost = 1; return; }
        if ((m_grid[r][c] & 0x0f) == 0) {
            for (int dr = -1; dr <= 1; dr++)
                for (int dc = -1; dc <= 1; dc++) {
                    int nr = r + dr, nc = c + dc;
                    if (nr < 0 || nr >= M_H || nc < 0 || nc >= M_W) continue;
                    if (m_grid[nr][nc] & 0x20) continue;
                    q[tail++] = (unsigned short)(nr * M_W + nc);
                }
        }
    }
}

static void mines_check_win(void) {
    int unrevealed = 0;
    for (int r = 0; r < M_H; r++)
        for (int c = 0; c < M_W; c++)
            if (!(m_grid[r][c] & 0x20)) unrevealed++;
    if (unrevealed == M_COUNT) m_won = 1;
}

static int run_mines(int argc, char **argv) {
    current_ms = &ms_mines;
    (void)argc; (void)argv;
    mines_init();
    term_raw();
    while (1) {
        paint_desktop();
        chrome("Mines");
        body_clear();
        for (int r = 0; r < M_H; r++) {
            cup(2, 3 + r);
            for (int c = 0; c < M_W; c++) {
                int sel = (r == m_cy && c == m_cx);
                unsigned char g = m_grid[r][c];
                if (g & 0x20) {
                    if (g & 0x10) {
                        sgrbgfg(sel ? 15 : 7, 88);
                        fbs("*");
                    } else {
                        int nb = g & 0x0f;
                        sgrbgfg(sel ? 15 : 8, nb ? 16 + nb : 8);
                        char ch = nb ? (char)('0' + nb) : ' ';
                        fbw(&ch, 1);
                    }
                } else if (g & 0x40) {
                    sgrbgfg(sel ? 15 : 7, 196);
                    fbs("F");
                } else {
                    sgrbgfg(sel ? 15 : 8, 0);
                    fbs(".");
                }
                fbs(" ");
            }
        }
        sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        const char *s = m_lost ? "  BOOM — r reset | q back"
                       : m_won  ? "  YOU WIN — r reset | q back"
                                : "  arrows | space reveal | f flag | r reset | q back";
        status(s);
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, ami = menu_activation(k, n);
        if (ami >= 0) act = menu_run(&ms_mines, ami);
        if (act == MA_ABOUT) {
            show_about("Mines");
            continue;
        }
        if (act == MA_QUIT) break;
        if (act == MA_RESET) { mines_init(); continue; }

        if (k[0] == 'q') break;
        if (k[0] == 'r') { mines_init(); continue; }
        if (m_lost || m_won) continue;
        if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
            if (k[2] == 'A' && m_cy > 0) m_cy--;
            if (k[2] == 'B' && m_cy < M_H - 1) m_cy++;
            if (k[2] == 'C' && m_cx < M_W - 1) m_cx++;
            if (k[2] == 'D' && m_cx > 0) m_cx--;
            continue;
        }
        if (k[0] == ' ') {
            if (m_first) { mines_layout(m_cy, m_cx); m_first = 0; }
            mines_reveal(m_cy, m_cx);
            mines_check_win();
        }
        if (k[0] == 'f') {
            if (!(m_grid[m_cy][m_cx] & 0x20))
                m_grid[m_cy][m_cx] ^= 0x40;
        }
    }
    return 0;
}


/* ── ask: dual-pane LLM chat (HTTPS via execve curl) ─────
 *
 * Layout:
 *   row 0       title bar
 *   row 1       menu bar
 *   rows 2..N-4 history (alternating you>/ai>, hard-wrap)
 *   row N-3     thin grey separator
 *   row N-2     single-line input (horizontal scroll)
 *   row N-1     status
 *
 * The conversation is sent to an OpenAI-compatible endpoint
 *   POST <endpoint>
 *   Authorization: Bearer <api_key>
 *   { "model": "<model>", "messages": [...] }
 * via fork+execve("curl"). The response goes to /tmp/<APP_NAME>_resp.json;
 * we slurp it back and grep "content":"..." for the assistant's reply.
 */

#define ASK_CONF       APP_NAME ".conf"
#define ASK_REQ_FILE   "/tmp/" APP_NAME "_req.json"
#define ASK_RESP_FILE  "/tmp/" APP_NAME "_resp.json"
#define ASK_INPUT_CAP  4096
#define ASK_MAX_MSGS   64
#define ASK_BUF_CAP    16384
#define ASK_KEY_CAP    256
#define ASK_URL_CAP    256
#define ASK_MODEL_CAP  64
#define ASK_REQ_CAP    20480
#define ASK_RESP_CAP   20480

static char ask_api_key[ASK_KEY_CAP];
static char ask_endpoint[ASK_URL_CAP] =
    "https://api.openai.com/v1/chat/completions";
static char ask_model[ASK_MODEL_CAP] = "gpt-4o-mini";

static char ask_buf[ASK_BUF_CAP];
static int  ask_buf_use;
static int  ask_msg_off[ASK_MAX_MSGS];
static int  ask_msg_len[ASK_MAX_MSGS];
static int  ask_msg_role[ASK_MAX_MSGS];   /* 0=user, 1=assistant */
static int  ask_n_msgs;

static int sapp(char *dst, int at, const char *s) {
    int n = slen(s);
    mcpy(dst + at, s, n);
    return at + n;
}

static void ask_msg_add(int role, const char *text, int tlen) {
    if (tlen > ASK_BUF_CAP - 16) tlen = ASK_BUF_CAP - 16;
    /* drop oldest until it fits */
    while ((ask_buf_use + tlen > ASK_BUF_CAP || ask_n_msgs >= ASK_MAX_MSGS)
            && ask_n_msgs > 0) {
        int dlen = ask_msg_len[0];
        for (int i = 0; i < ask_buf_use - dlen; i++)
            ask_buf[i] = ask_buf[i + dlen];
        ask_buf_use -= dlen;
        for (int i = 1; i < ask_n_msgs; i++) {
            ask_msg_off[i-1]  = ask_msg_off[i] - dlen;
            ask_msg_len[i-1]  = ask_msg_len[i];
            ask_msg_role[i-1] = ask_msg_role[i];
        }
        ask_n_msgs--;
    }
    ask_msg_off[ask_n_msgs]  = ask_buf_use;
    ask_msg_len[ask_n_msgs]  = tlen;
    ask_msg_role[ask_n_msgs] = role;
    mcpy(ask_buf + ask_buf_use, text, tlen);
    ask_buf_use += tlen;
    ask_n_msgs++;
}

/* line-oriented "key=value" lookup. */
static int ask_conf_find(const char *txt, int tn, const char *key,
                         char *out, int cap) {
    int klen = slen(key);
    for (int i = 0; i < tn; i++) {
        if (i != 0 && txt[i-1] != '\n') continue;
        int j = 0;
        while (j < klen && i + j < tn && txt[i+j] == key[j]) j++;
        if (j == klen && i + j < tn && txt[i+j] == '=') {
            int k = i + j + 1, o = 0;
            while (k < tn && txt[k] != '\n' && o < cap - 1) out[o++] = txt[k++];
            out[o] = 0;
            return 1;
        }
    }
    return 0;
}

static void ask_load_conf(void) {
    int fd = (int)op(ASK_CONF, O_RDONLY, 0);
    if (fd < 0) return;
    static char tmp[4096];
    int n = (int)rd(fd, tmp, sizeof tmp - 1);
    cl(fd);
    if (n <= 0) return;
    tmp[n] = 0;
    ask_conf_find(tmp, n, "api_key",  ask_api_key,  sizeof ask_api_key);
    ask_conf_find(tmp, n, "endpoint", ask_endpoint, sizeof ask_endpoint);
    ask_conf_find(tmp, n, "model",    ask_model,    sizeof ask_model);
}

static void ask_save_conf(void) {
    int fd = (int)op(ASK_CONF, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) return;
    static char tmp[ASK_KEY_CAP + ASK_URL_CAP + ASK_MODEL_CAP + 64];
    int n = 0;
    n = sapp(tmp, n, "api_key=");  n = sapp(tmp, n, ask_api_key);
    tmp[n++] = '\n';
    n = sapp(tmp, n, "endpoint="); n = sapp(tmp, n, ask_endpoint);
    tmp[n++] = '\n';
    n = sapp(tmp, n, "model=");    n = sapp(tmp, n, ask_model);
    tmp[n++] = '\n';
    wr(fd, tmp, n);
    cl(fd);
}

static int ask_json_esc(char *out, int at, const char *s, int n) {
    for (int i = 0; i < n; i++) {
        unsigned char c = (unsigned char)s[i];
        if      (c == '"')  { out[at++] = '\\'; out[at++] = '"'; }
        else if (c == '\\') { out[at++] = '\\'; out[at++] = '\\'; }
        else if (c == '\n') { out[at++] = '\\'; out[at++] = 'n'; }
        else if (c == '\r') { out[at++] = '\\'; out[at++] = 'r'; }
        else if (c == '\t') { out[at++] = '\\'; out[at++] = 't'; }
        else if (c < 0x20)  { /* drop */ }
        else                { out[at++] = (char)c; }
    }
    return at;
}

static int ask_build_request(char *out, int cap) {
    (void)cap;
    int at = 0;
    at = sapp(out, at, "{\"model\":\"");
    at = ask_json_esc(out, at, ask_model, slen(ask_model));
    at = sapp(out, at, "\",\"messages\":[");
    for (int i = 0; i < ask_n_msgs; i++) {
        if (i > 0) out[at++] = ',';
        at = sapp(out, at, "{\"role\":\"");
        at = sapp(out, at, ask_msg_role[i] ? "assistant" : "user");
        at = sapp(out, at, "\",\"content\":\"");
        at = ask_json_esc(out, at, ask_buf + ask_msg_off[i], ask_msg_len[i]);
        at = sapp(out, at, "\"}");
    }
    at = sapp(out, at, "]}");
    return at;
}

/* Find first "content":"..." string in JSON, decoding \" \n \t \\ \/ \uXXXX. */
static int ask_extract_content(const char *src, int sn, char *out, int cap) {
    static const char needle[] = "\"content\":";
    int nl = (int)sizeof needle - 1;
    for (int i = 0; i + nl < sn; i++) {
        int j = 0;
        while (j < nl && src[i+j] == needle[j]) j++;
        if (j != nl) continue;
        int k = i + nl;
        while (k < sn && (src[k] == ' ' || src[k] == '\t' || src[k] == '\n')) k++;
        if (k >= sn || src[k] != '"') continue;
        k++;
        int o = 0;
        while (k < sn && o < cap - 1) {
            char c = src[k];
            if (c == '"') { out[o] = 0; return o; }
            if (c == '\\' && k + 1 < sn) {
                char e = src[k+1];
                if      (e == 'n')  { out[o++] = '\n'; k += 2; }
                else if (e == 't')  { out[o++] = '\t'; k += 2; }
                else if (e == 'r')  { k += 2; }
                else if (e == '"')  { out[o++] = '"';  k += 2; }
                else if (e == '\\') { out[o++] = '\\'; k += 2; }
                else if (e == '/')  { out[o++] = '/';  k += 2; }
                else if (e == 'u')  { out[o++] = '?';  k += 6; }
                else                { out[o++] = e;    k += 2; }
            } else {
                out[o++] = c; k++;
            }
        }
        out[o] = 0;
        return o;
    }
    return -1;
}

static int ask_extract_error(const char *src, int sn, char *out, int cap) {
    static const char needle[] = "\"message\":";
    int nl = (int)sizeof needle - 1;
    for (int i = 0; i + nl < sn; i++) {
        int j = 0;
        while (j < nl && src[i+j] == needle[j]) j++;
        if (j != nl) continue;
        int k = i + nl;
        while (k < sn && (src[k] == ' ' || src[k] == '\t' || src[k] == '\n')) k++;
        if (k >= sn || src[k] != '"') continue;
        k++;
        int o = 0;
        while (k < sn && src[k] != '"' && o < cap - 1) {
            if (src[k] == '\\' && k + 1 < sn) k += 2;
            else out[o++] = src[k++];
        }
        out[o] = 0;
        return o;
    }
    return -1;
}

static int ask_call_curl(void) {
    int fd = (int)op(ASK_REQ_FILE, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    if (fd < 0) return -1;
    static char req[ASK_REQ_CAP];
    int rn = ask_build_request(req, sizeof req);
    wr(fd, req, rn);
    cl(fd);

    static char auth[ASK_KEY_CAP + 32];
    int an = 0;
    an = sapp(auth, an, "Authorization: Bearer ");
    an = sapp(auth, an, ask_api_key);
    auth[an] = 0;

    char *argv_[16];
    int ai = 0;
    argv_[ai++] = (char *)"curl";
    argv_[ai++] = (char *)"-sS";
    argv_[ai++] = (char *)"-X"; argv_[ai++] = (char *)"POST";
    argv_[ai++] = (char *)"-H"; argv_[ai++] = (char *)"Content-Type: application/json";
    argv_[ai++] = (char *)"-H"; argv_[ai++] = auth;
    argv_[ai++] = (char *)"--data-binary";
    argv_[ai++] = (char *)"@" ASK_REQ_FILE;
    argv_[ai++] = (char *)"-o"; argv_[ai++] = (char *)ASK_RESP_FILE;
    argv_[ai++] = ask_endpoint;
    argv_[ai++] = 0;

    long pid = forkk();
    if (pid < 0) return -1;
    if (pid == 0) {
        execvee("/usr/bin/curl",       argv_, g_envp);
        execvee("/bin/curl",           argv_, g_envp);
        execvee("/usr/local/bin/curl", argv_, g_envp);
        qu(127);
    }
    int status = 0;
    wait4_(&status);
    return 0;
}

static void ask_render_history(int hist_top, int hist_h) {
    int line_w = SCREEN_W - 4 - 5;     /* width minus role prefix */

    /* count wrapped lines first so we can scroll-pin to bottom */
    int total = 0;
    for (int i = 0; i < ask_n_msgs; i++) {
        int tlen = ask_msg_len[i];
        if (tlen == 0) { total++; continue; }
        int pos = 0;
        while (pos < tlen) {
            int rem = tlen - pos;
            int take = rem < line_w ? rem : line_w;
            int nl = -1;
            for (int k = 0; k < take; k++)
                if (ask_buf[ask_msg_off[i] + pos + k] == '\n') { nl = k; break; }
            if (nl >= 0) take = nl;
            total++;
            pos += take;
            if (nl >= 0) pos++;
        }
    }
    int skip = total > hist_h ? total - hist_h : 0;
    int line = 0, row = 0;

    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    for (int i = 0; i < ask_n_msgs && row < hist_h; i++) {
        const char *prefix = ask_msg_role[i] ? "ai>  " : "you> ";
        int role = ask_msg_role[i];
        int tlen = ask_msg_len[i];
        int first = 1, pos = 0;
        if (tlen == 0) {
            if (line >= skip) {
                cup(2, hist_top + row);
                sgrbgfg(COL_BAR_BG, role ? 24 : COL_BAR_FG);
                fbw(prefix, 5);
                sgrbgfg(COL_BAR_BG, COL_BAR_FG);
                blanks(line_w);
                row++;
            }
            line++;
            continue;
        }
        while (pos < tlen && row < hist_h) {
            int rem = tlen - pos;
            int take = rem < line_w ? rem : line_w;
            int nl = -1;
            for (int k = 0; k < take; k++)
                if (ask_buf[ask_msg_off[i] + pos + k] == '\n') { nl = k; break; }
            if (nl >= 0) take = nl;
            if (line >= skip) {
                cup(2, hist_top + row);
                sgrbgfg(COL_BAR_BG, role ? 24 : COL_BAR_FG);
                if (first) fbw(prefix, 5); else fbw("     ", 5);
                sgrbgfg(COL_BAR_BG, COL_BAR_FG);
                fbw(ask_buf + ask_msg_off[i] + pos, take);
                blanks(line_w - take);
                row++;
            }
            line++;
            pos += take;
            if (nl >= 0) pos++;
            first = 0;
        }
    }
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    while (row < hist_h) {
        cup(2, hist_top + row);
        blanks(SCREEN_W - 4);
        row++;
    }
}

static void ask_settings_modal(void) {
    int sel = 0;
    char *fields[3] = { ask_api_key, ask_endpoint, ask_model };
    int   caps[3]   = { ASK_KEY_CAP, ASK_URL_CAP, ASK_MODEL_CAP };
    static const char *labels[3] = { "API key  ", "Endpoint ", "Model    " };
    int editing = 0;

    while (1) {
        paint_desktop();
        chrome("Ask · Settings");
        body_clear();
        body_at(2, 3, "Edit OpenAI-compatible chat settings.", SCREEN_W - 4);
        body_at(2, 4, "Up/Down select; ENTER edit; ESC save+close.",
                SCREEN_W - 4);
        for (int i = 0; i < 3; i++) {
            cup(2, 6 + i * 2);
            sgrbgfg(COL_BAR_BG, COL_BAR_FG);
            if (i == sel && !editing) sgrbgfg(15, 0);
            if (i == sel &&  editing) sgrbgfg(0, 15);
            fbw(labels[i], slen(labels[i]));
            sgrbgfg(COL_BAR_BG, COL_BAR_FG);
            fbw(": ", 2);
            int sl = slen(fields[i]);
            int max = SCREEN_W - 4 - slen(labels[i]) - 2;
            if (i == 0 && !editing) {
                if (sl > 0) {
                    int show = sl < 6 ? sl : 6;
                    for (int j = 0; j < sl - show; j++) fbw("*", 1);
                    fbw(fields[i] + sl - show, show);
                    blanks(max - sl);
                } else {
                    blanks(max);
                }
            } else if (sl > max) {
                fbw("...", 3);
                fbw(fields[i] + (sl - max + 3), max - 3);
            } else {
                fbw(fields[i], sl);
                blanks(max - sl);
            }
        }
        status(editing ? "type ... ENTER done | ESC cancel"
                       : "UP/DOWN select | ENTER edit | ESC save+close");
        fbflush();

        unsigned char k[16];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        if (!editing) {
            if (k[0] == 0x1b && n == 1) { ask_save_conf(); return; }
            if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
                if (k[2] == 'A' && sel > 0) sel--;
                if (k[2] == 'B' && sel < 2) sel++;
            }
            if (k[0] == '\r' || k[0] == '\n') editing = 1;
        } else {
            if (k[0] == '\r' || k[0] == '\n') { editing = 0; continue; }
            if (k[0] == 0x1b && n == 1)        { editing = 0; continue; }
            if (k[0] == 0x7f || k[0] == 8) {
                int sl = slen(fields[sel]);
                if (sl > 0) fields[sel][sl - 1] = 0;
                continue;
            }
            if (k[0] >= 32 && k[0] < 127) {
                int sl = slen(fields[sel]);
                if (sl < caps[sel] - 1) {
                    fields[sel][sl] = (char)k[0];
                    fields[sel][sl + 1] = 0;
                }
            }
        }
    }
}

static int run_ask(int argc, char **argv) {
    (void)argc; (void)argv;
    current_ms = &ms_ask;
    ask_load_conf();

    static char input[ASK_INPUT_CAP];
    int inlen = 0;
    static char errmsg[256];
    errmsg[0] = 0;

    term_raw();
    int hist_top = 2;
    int hist_h   = SCREEN_H - 5;

    while (1) {
        paint_desktop();
        chrome("Ask");
        body_clear();
        ask_render_history(hist_top, hist_h);

        cup(0, SCREEN_H - 3);
        sgrbgfg(COL_BAR_BG, 8);
        for (int x = 0; x < SCREEN_W; x++) fbs("-");

        cup(0, SCREEN_H - 2);
        sgrbgfg(15, 0);
        fbs(" > ");
        int max_show = SCREEN_W - 4;
        int show_from = inlen > max_show ? inlen - max_show : 0;
        fbw(input + show_from, inlen - show_from);
        blanks(max_show - (inlen - show_from));

        sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        if (errmsg[0]) {
            sgrbgfg(COL_BAR_BG, 88);
            status(errmsg);
            sgrbgfg(COL_BAR_BG, COL_BAR_FG);
            errmsg[0] = 0;
        } else if (!ask_api_key[0]) {
            status("no api_key set — File > Settings (Alt+F)");
        } else {
            status("ENTER send | ^N clear | ^E settings | ^Q quit");
        }
        fbflush();

        unsigned char k[64];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, ami = menu_activation(k, n);
        if (ami >= 0) act = menu_run(&ms_ask, ami);
        if (act == MA_ABOUT)    { show_about("Ask"); continue; }
        if (act == MA_QUIT)     break;
        if (act == MA_NEW)      { ask_n_msgs = 0; ask_buf_use = 0; continue; }
        if (act == MA_SETTINGS) { ask_settings_modal(); continue; }

        if (k[0] == 0x11) break;                                     /* ^Q */
        if (k[0] == 0x0e) { ask_n_msgs = 0; ask_buf_use = 0; continue; } /* ^N */
        if (k[0] == 0x05) { ask_settings_modal(); continue; }            /* ^E */

        if (k[0] == '\r' || k[0] == '\n') {
            if (inlen == 0) continue;
            if (!ask_api_key[0]) {
                int el = sapp(errmsg, 0, "no api_key set — open Settings");
                errmsg[el] = 0;
                continue;
            }
            ask_msg_add(0, input, inlen);
            inlen = 0;
            input[0] = 0;

            paint_desktop();
            chrome("Ask");
            body_clear();
            ask_render_history(hist_top, hist_h);
            cup(0, SCREEN_H - 3);
            sgrbgfg(COL_BAR_BG, 8);
            for (int x = 0; x < SCREEN_W; x++) fbs("-");
            cup(0, SCREEN_H - 2);
            sgrbgfg(15, 0);
            fbs(" > ");
            blanks(SCREEN_W - 3);
            sgrbgfg(COL_BAR_BG, COL_BAR_FG);
            status("sending ...");
            fbflush();

            int rc = ask_call_curl();

            static char resp[ASK_RESP_CAP];
            int rn = -1;
            int fd = (int)op(ASK_RESP_FILE, O_RDONLY, 0);
            if (fd >= 0) {
                rn = (int)rd(fd, resp, sizeof resp - 1);
                cl(fd);
            }
            if (rc < 0 || rn < 0) {
                int el = sapp(errmsg, 0,
                              "curl failed — install curl or check network");
                errmsg[el] = 0;
            } else {
                resp[rn] = 0;
                static char content[ASK_BUF_CAP];
                int cn = ask_extract_content(resp, rn, content, sizeof content);
                if (cn >= 0) {
                    ask_msg_add(1, content, cn);
                } else {
                    static char emsg[256];
                    int en = ask_extract_error(resp, rn, emsg, sizeof emsg);
                    if (en > 0) {
                        int p = sapp(errmsg, 0, "api: ");
                        for (int i = 0; i < en && p < (int)sizeof errmsg - 1; i++)
                            errmsg[p++] = emsg[i];
                        errmsg[p] = 0;
                    } else {
                        int el = sapp(errmsg, 0, "no content in response");
                        errmsg[el] = 0;
                    }
                }
            }
            continue;
        }
        if (k[0] == 0x7f || k[0] == 8) {
            if (inlen > 0) inlen--;
            input[inlen] = 0;
            continue;
        }
        if (k[0] == 0x16) {                  /* ^V paste from suite clipboard */
            int avail = ASK_INPUT_CAP - 1 - inlen;
            int take = cb_n < avail ? cb_n : avail;
            mcpy(input + inlen, cb, take);
            inlen += take;
            input[inlen] = 0;
            continue;
        }
        if (k[0] >= 32 && k[0] < 127 && inlen < ASK_INPUT_CAP - 1) {
            input[inlen++] = (char)k[0];
            input[inlen] = 0;
        }
    }

    term_cooked();
    return 0;
}


/* ── garden: interactive-evolution colour/layout breeder ──
 *
 * 64 Genome instances (1 KB total) shown as an 8x8 grid of
 * thumbnails. The user marks favourites with SPACE and ENTER
 * advances the generation: marked genomes survive, unmarked
 * slots are filled by uniform crossover of two random marked
 * parents, then per-byte mutation. P previews the cursor's
 * genome full-screen with the suite chrome painted in those
 * colours. S saves the population to ./garden.bin (1024 B);
 * the file is auto-loaded on next launch.
 *
 * Layout: default 80x24 packs 8x8 thumbs at 10 cols x 3 rows
 * each, no chrome. If TIOCGWINSZ reports a larger terminal we
 * grow each thumb up to the available cell budget and reserve
 * the spare rows for a top status line + bottom help line.
 */

/* TIOCGWINSZ + struct winsize hoisted to the top of the file (the
 * suite-wide term_init() needs them) — garden's own resize-aware
 * loop still calls io(0, TIOCGWINSZ, ...) below for live resizes. */

#define GARDEN_FILE  "garden.bin"
#define GARDEN_MAGIC 0x47524431u   /* "GRD1" little-endian */

static struct Genome g_pop[64];
static unsigned long long g_marked;     /* 1 bit per slot */
static int g_generation;

static unsigned long long g_rng_state;

static unsigned long long garden_rdtsc(void) {
    unsigned long h, l;
    __asm__ volatile ("rdtsc" : "=d"(h), "=a"(l));
    return ((unsigned long long)h << 32) | l;
}
static void garden_rng_seed_if_unset(void) {
    if (!g_rng_state) g_rng_state = garden_rdtsc() | 1ULL;
}
static unsigned int garden_rng(void) {
    g_rng_state = g_rng_state * 6364136223846793005ULL +
                  1442695040888963407ULL;
    return (unsigned int)(g_rng_state >> 32);
}

static void garden_random_genome(struct Genome *g) {
    /* Pick from a pleasing palette range so initial pop isn't all neon. */
    g->title_bg     = (unsigned char)(garden_rng() & 0xff);
    g->title_fg     = (unsigned char)(garden_rng() & 0xff);
    g->bar_bg       = (unsigned char)(garden_rng() & 0xff);
    g->bar_fg       = (unsigned char)(garden_rng() & 0xff);
    g->desktop      = (unsigned char)(garden_rng() & 0xff);
    g->select_bg    = (unsigned char)(garden_rng() & 0xff);
    g->select_fg    = (unsigned char)(garden_rng() & 0xff);
    g->shadow_bg    = (unsigned char)(garden_rng() & 0xff);
    g->shadow_fg    = (unsigned char)(garden_rng() & 0xff);
    g->accent       = (unsigned char)(garden_rng() & 0xff);
    g->clock_corner = (unsigned char)(garden_rng() & 3);
    g->show_clock   = (unsigned char)(garden_rng() & 1);
    g->border       = (unsigned char)(garden_rng() & 3);
    g->menu_under   = (unsigned char)(garden_rng() & 1);
    g->clock_style  = (unsigned char)(garden_rng() & 7);
    g->reserved     = 0;
}

static void garden_init_pop(void) {
    garden_rng_seed_if_unset();
    for (int i = 0; i < 64; i++) garden_random_genome(&g_pop[i]);
    /* Seed slot 0 with the office6 defaults so the user always has
     * a "boring but recognisable" starting point to breed from. */
    g_pop[0] = (struct Genome){
        21, 15, 7, 0, 30, 15, 0, 0, 8, 21, 1, 0, 0, 1, 1, 0
    };
    g_marked = 0;
    g_generation = 0;
}

static void garden_mutate(struct Genome *g) {
    unsigned char *b = (unsigned char *)g;
    int n = (int)sizeof *g;
    for (int i = 0; i < n; i++) {
        unsigned int r = garden_rng();
        if ((r & 0xff) < 24) {                /* ~9% per byte mutates */
            if (i <= 9) {                     /* colour bytes drift */
                int delta = (int)((r >> 8) & 7) - 3;   /* -3..+3 */
                b[i] = (unsigned char)((int)b[i] + delta);
            } else if (i == 10) {             /* clock_corner 0..3 */
                b[i] = (unsigned char)((r >> 8) & 3);
            } else if (i == 11 || i == 13) {  /* booleans */
                b[i] ^= 1;
            } else if (i == 12) {             /* border 0..3 */
                b[i] = (unsigned char)((r >> 8) & 3);
            } else if (i == 14) {             /* clock_style 0..7 */
                b[i] = (unsigned char)((r >> 8) & 7);
            }
        }
    }
}

static void garden_breed(void) {
    int parents[64], np = 0;
    for (int i = 0; i < 64; i++)
        if ((g_marked >> i) & 1) parents[np++] = i;
    if (np == 0) return;

    struct Genome next[64];
    for (int i = 0; i < 64; i++) {
        if ((g_marked >> i) & 1) {
            next[i] = g_pop[i];               /* survive untouched */
            continue;
        }
        int a = parents[garden_rng() % np];
        int b = parents[garden_rng() % np];
        unsigned char *pa = (unsigned char *)&g_pop[a];
        unsigned char *pb = (unsigned char *)&g_pop[b];
        unsigned char *po = (unsigned char *)&next[i];
        unsigned int mask = garden_rng();
        for (int k = 0; k < (int)sizeof next[i]; k++) {
            po[k] = (mask & 1) ? pa[k] : pb[k];
            mask >>= 1;
            if (k % 32 == 31) mask = garden_rng();
        }
        garden_mutate(&next[i]);
    }
    for (int i = 0; i < 64; i++) g_pop[i] = next[i];
    g_marked = 0;
    g_generation++;
}

static int garden_save(void) {
    int fd = (int)op(GARDEN_FILE, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return -1;
    unsigned int hdr[4];
    hdr[0] = GARDEN_MAGIC;
    hdr[1] = (unsigned int)g_generation;
    hdr[2] = (unsigned int)(g_marked & 0xffffffffu);
    hdr[3] = (unsigned int)(g_marked >> 32);
    wr(fd, hdr, sizeof hdr);
    wr(fd, g_pop, sizeof g_pop);
    cl(fd);
    return 0;
}

static int garden_load(void) {
    int fd = (int)op(GARDEN_FILE, O_RDONLY, 0);
    if (fd < 0) return 0;
    unsigned int hdr[4];
    long n = rd(fd, hdr, sizeof hdr);
    if (n != (long)sizeof hdr || hdr[0] != GARDEN_MAGIC) {
        cl(fd); return 0;
    }
    n = rd(fd, g_pop, sizeof g_pop);
    cl(fd);
    if (n != (long)sizeof g_pop) return 0;
    g_generation = (int)hdr[1];
    g_marked = (unsigned long long)hdr[2] | ((unsigned long long)hdr[3] << 32);
    return 1;
}

static int garden_term_size(int *cols, int *rows) {
    struct winsize ws = { 0, 0, 0, 0 };
    long r = io(0, TIOCGWINSZ, &ws);
    if (r < 0 || ws.ws_col == 0 || ws.ws_row == 0) {
        *cols = 80; *rows = 24; return 0;
    }
    *cols = ws.ws_col; *rows = ws.ws_row;
    return 1;
}

/* Render one thumbnail at screen pos (x,y), w x h cells.
 * w is at least 10, h at least 3. The cursor and marked flags
 * draw distinguishing borders. */
static void garden_render_thumb(int idx, int x, int y, int w, int h,
                                int is_cursor, int is_marked) {
    struct Genome *g = &g_pop[idx];
    static const char border_chars[4] = { '-', '=', '_', '~' };
    char bc = border_chars[g->border & 3];

    /* row 0: title bar */
    cup(x, y);
    sgrbgfg(g->title_bg, g->title_fg);
    fbs(" O7");
    int slots = w - 6;
    for (int i = 0; i < slots; i++) fbw(" ", 1);
    fbs("_X ");

    /* row 1: menu bar — always exactly 1 row */
    cup(x, y + 1);
    sgrbgfg(g->bar_bg, g->bar_fg);
    if (w >= 10) {
        fbs(" F E V H");
        blanks(w - 8);
    } else {
        fbs(" FEVH");
        blanks(w - 5);
    }

    /* rows 2..h-2: desktop body */
    for (int r = 2; r < h - 1; r++) {
        cup(x, y + r);
        sgrbg(g->desktop);
        blanks(w);
    }
    /* clock pip — only in body rows, so hidden in MVP h=3 thumbs */
    if (g->show_clock && h >= 4) {
        int cx = x + ((g->clock_corner & 1) ? w - 6 : 1);
        int cy = y + ((g->clock_corner & 2) ? h - 2 : 2);
        cup(cx, cy);
        sgrbgfg(g->desktop, g->accent);
        fbs("12:00");
    }

    /* status row (last row) — used for marked/cursor indicators */
    cup(x, y + h - 1);
    sgrbgfg(g->bar_bg, g->bar_fg);
    char bcs[2] = { bc, 0 };
    for (int i = 0; i < w; i++) fbs(bcs);

    /* overlay cursor + marked — border highlights drawn last */
    if (is_marked) {
        cup(x, y);
        sgrbgfg(226, 0);                  /* yellow bg, black fg */
        fbs("*");
    }
    if (is_cursor) {
        /* invert title row first cell as a cursor caret */
        cup(x + w - 1, y);
        sgrbgfg(15, 0);
        fbs(">");
        cup(x, y);
        sgrbgfg(15, 0);
        fbs("<");
    }
}

/* Hex mode: every other row of thumbnails is x-shifted by half a
 * thumb width.  Toggled by 'h' in run_garden; persists session-local. */
static int hex_mode;

static void garden_render_grid(int cursor, int cols, int rows) {
    /* Compute thumb size — clip down so 8x8 fits. Reserve at most
     * 2 rows for header/footer when there's spare height.  In hex
     * mode the staggered odd row pushes the rightmost thumb half a
     * width past the regular grid, so 8.5 × thumb_w must fit cols
     * — pick the floor of `cols * 2 / 17`. */
    int chrome_top = 0, chrome_bot = 0;
    int thumb_w = hex_mode ? (cols * 2) / 17 : cols / 8;
    int thumb_h = rows / 8;
    if (thumb_w < 6) thumb_w = 6;
    if (thumb_h < 3) thumb_h = 3;

    if (rows >= 8 * thumb_h + 2) { chrome_top = 1; chrome_bot = 1; }

    /* Optional top chrome */
    if (chrome_top) {
        cup(0, 0);
        sgrbgfg(COL_TITLE_BG, COL_TITLE_FG);
        fbs(" Garden — interactive evolution");
        char buf[32];
        int bn = sapp(buf, 0, "  gen ");
        bn += utoa((unsigned)g_generation, buf + bn);
        bn = sapp(buf, bn, "  ");
        int marks = 0;
        for (int i = 0; i < 64; i++) if ((g_marked >> i) & 1) marks++;
        bn += utoa((unsigned)marks, buf + bn);
        bn = sapp(buf, bn, " marked");
        buf[bn] = 0;
        fbw(buf, bn);
        blanks(cols - 32 - bn);
    }

    int origin_y = chrome_top ? 1 : 0;
    /* In hex mode, the unshifted (even) rows still center at the
     * (cols - 8w)/2 offset; odd rows pick up an extra w/2. */
    int origin_x = (cols - thumb_w * 8) / 2;
    if (hex_mode) origin_x -= thumb_w / 4;        /* nudge left so the
                                                     half-width offset
                                                     of odd rows still
                                                     centres visually */
    if (origin_x < 0) origin_x = 0;

    for (int gy = 0; gy < 8; gy++) {
        int row_x = origin_x + (hex_mode && (gy & 1) ? thumb_w / 2 : 0);
        for (int gx = 0; gx < 8; gx++) {
            int idx = gy * 8 + gx;
            int marked = (int)((g_marked >> idx) & 1);
            int is_cursor = (idx == cursor);
            garden_render_thumb(idx,
                                row_x + gx * thumb_w,
                                origin_y + gy * thumb_h,
                                thumb_w, thumb_h,
                                is_cursor, marked);
        }
    }

    if (chrome_bot) {
        cup(0, rows - 1);
        sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        if (hex_mode) {
            fbs(" hex · w/e/a/d/z/x move | s select | h grid | "
                "ENT breed | V view | Q quit");
            blanks(cols > 70 ? cols - 70 : 0);
        } else {
            fbs(" SPC mark | ENT breed | P preview | V view | "
                "h hex | R random | Q quit");
            blanks(cols > 70 ? cols - 70 : 0);
        }
    }
}

/* Render the preview screen using whatever's in g_genome and wait
 * for one keystroke. Caller is responsible for genome bookkeeping;
 * called both by the in-process fallback (garden_preview) and by
 * the jailed child (run_preview_genome). */
static void garden_preview_render(const char *footer) {
    paint_desktop();
    chrome("Preview");
    body_clear();
    body_at(2, 3, "this is what the suite looks like with this genome.",
            SCREEN_W - 4);
    body_at(2, 5, "  notepad word mail sheet paint hex bfc files",
            SCREEN_W - 4);
    body_at(2, 6, "  find calc mines ask garden", SCREEN_W - 4);
    body_at(2, 8, "  Alt+F / F10 opens the menu — try it.",
            SCREEN_W - 4);
    body_at(2, 9, "  selected items use the genome's select_bg/fg.",
            SCREEN_W - 4);
    body_at(2, 11, "  press any key to return to the garden.",
            SCREEN_W - 4);
    /* draw a fake selected menu title to show the SEL colours */
    cup(0, 1);
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    fbs(" ");
    sgrbgfg(COL_SEL_BG, COL_SEL_FG);
    fbs(" File ");
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    fbs(" Edit  View  Help");
    blanks(SCREEN_W - 24);
    status(footer);
    fbflush();
    unsigned char k[8];
    read_key(k, sizeof k);
}

/* Encode a 16-byte genome into 32 lowercase hex chars + NUL. */
static void garden_genome_hex(const struct Genome *g, char *out33) {
    static const char garden_hx[] = "0123456789abcdef";
    const unsigned char *b = (const unsigned char *)g;
    for (int i = 0; i < (int)sizeof *g; i++) {
        out33[i*2]     = garden_hx[(b[i] >> 4) & 0xf];
        out33[i*2 + 1] = garden_hx[ b[i]       & 0xf];
    }
    out33[32] = 0;
}

/* Spawn the namespace jail launcher with an arbitrary office9
 * subcommand.  Used by both garden_preview_jail and garden_view_jail.
 * Returns 0 on a clean child exit, non-zero if anything broke. */
static int garden_jail_spawn(const char *subcmd, const char *hex) {
    char *jargv[] = { "./jail", "./" APP_NAME,
                      (char *)subcmd, (char *)hex, 0 };
    long pid = forkk();
    if (pid < 0) return -1;
    if (pid == 0) {
        execvee("./jail", jargv, g_envp);
        qu(127);
    }
    int st = 0;
    wait4_(&st);
    return (st & 0x7f) ? -1 : 0;
}

static int garden_preview_jail(int idx) {
    char hex[33];
    garden_genome_hex(&g_pop[idx], hex);
    return garden_jail_spawn("preview-genome", hex);
}

/* Preview the cursor's genome.  Tries the namespace jail first
 * (real isolated child paints the screen); if that fails — jail
 * binary missing, kernel without unprivileged user namespaces, etc.
 * — falls back to the in-process g_genome swap so the feature still
 * works on hardened hosts. */
static void garden_preview(int idx) {
    if (garden_preview_jail(idx) == 0) return;

    struct Genome saved = g_genome;
    g_genome = g_pop[idx];
    garden_preview_render(" PREVIEW · any key returns ");
    g_genome = saved;
}

/* V key — drop the user into the suite shell with the cursor's
 * genome applied, inside a jail.  Files saved during V live inside
 * the jail dir and vanish on exit, so this is non-destructive. */
static int garden_view_jail(int idx) {
    char hex[33];
    garden_genome_hex(&g_pop[idx], hex);
    return garden_jail_spawn("view-genome", hex);
}

static void garden_view(int idx) {
    if (garden_view_jail(idx) == 0) return;
    /* Jail unavailable — degrade to the static preview so the user
     * at least sees the chrome under that genome. */
    garden_preview(idx);
}

/* `office7 preview-genome <32-hex>` — the in-jail entry point.
 * Parses 16 bytes into g_genome and renders the preview screen.
 * The parent already put the tty in raw mode and we inherit its
 * fd 0/1/2, so we don't touch tcsetattr; one read for any key,
 * then exit (the parent regains the terminal automatically). */
static int garden_hexv(int c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}
static int garden_load_genome_hex(const char *h) {
    unsigned char *g = (unsigned char *)&g_genome;
    for (int i = 0; i < (int)sizeof g_genome; i++) {
        int hi = garden_hexv(h[i*2]);
        int lo = garden_hexv(h[i*2 + 1]);
        if (hi < 0 || lo < 0) return -1;
        g[i] = (unsigned char)((hi << 4) | lo);
    }
    return 0;
}

static int run_preview_genome(int argc, char **argv) {
    if (argc < 2) return 2;
    if (garden_load_genome_hex(argv[1]) < 0) return 2;
    garden_preview_render(" PREVIEW · jailed · any key returns ");
    return 0;
}

/* `office9 view-genome <32-hex>` — the in-jail entry point for V.
 * Loads the genome and drops into run_shell, so the user can type
 * `notepad`, `sheet`, etc. and see them with the chosen colours.
 * Pressing Q in the shell tears down the jail and returns to garden. */
static int run_view_genome(int argc, char **argv) {
    if (argc < 2) return 2;
    if (garden_load_genome_hex(argv[1]) < 0) return 2;
    return run_shell(0, 0);
}

static int run_garden(int argc, char **argv) {
    (void)argc; (void)argv;
    current_ms = &ms_garden;

    if (!garden_load()) garden_init_pop();
    garden_rng_seed_if_unset();

    term_raw();
    int cursor = 0;
    int last_msg_ttl = 0;
    static char last_msg[64];
    last_msg[0] = 0;

    while (1) {
        int cols, rows;
        garden_term_size(&cols, &rows);
        cls();
        garden_render_grid(cursor, cols, rows);

        if (last_msg[0] && last_msg_ttl > 0) {
            cup(0, rows - 1);
            sgrbgfg(COL_BAR_BG, 22);
            fbs(" ");
            fbs(last_msg);
            blanks(cols - 1 - slen(last_msg));
            last_msg_ttl--;
            if (last_msg_ttl == 0) last_msg[0] = 0;
        }
        fbflush();

        unsigned char k[16];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, ami = menu_activation(k, n);
        if (ami >= 0) act = menu_run(&ms_garden, ami);
        if (act == MA_ABOUT)   { show_about("Garden"); continue; }
        if (act == MA_QUIT)    break;
        if (act == MA_SAVE)    {
            if (garden_save() == 0) {
                int ml = sapp(last_msg, 0, "saved garden.bin");
                last_msg[ml] = 0; last_msg_ttl = 1;
            }
            continue;
        }
        if (act == MA_RANDOM)  { garden_init_pop(); continue; }
        if (act == MA_BREED)   { garden_breed(); continue; }
        if (act == MA_PREVIEW) { garden_preview(cursor); continue; }
        if (act == MA_VIEW)    { garden_view(cursor); term_raw(); continue; }
        if (act == MA_EXPORT) {
            /* Splice the cursor's gene into a fresh runnable binary
             * so its chrome reflects this thumb when launched. */
            char nm[HX_EXPORT_NAME_LEN + 1];
            hx_make_export_name(nm, gd_export_seq++);
            int rc = gd_splice_export(nm,
                                      (const unsigned char *)&g_pop[cursor]);
            int ml = sapp(last_msg, 0, rc == 0 ? "exported " : "export failed ");
            if (rc == 0) ml = sapp(last_msg, ml, nm);
            last_msg[ml] = 0; last_msg_ttl = 1;
            continue;
        }

        if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
            int gx = cursor % 8, gy = cursor / 8;
            switch (k[2]) {
            case 'A': if (gy > 0) cursor -= 8; break;
            case 'B': if (gy < 7) cursor += 8; break;
            case 'C': if (gx < 7) cursor++;    break;
            case 'D': if (gx > 0) cursor--;    break;
            }
            continue;
        }
        if (k[0] == 'h' || k[0] == 'H') { hex_mode = !hex_mode; continue; }

        /* Hex mode rebinds: w/e/a/d/z/x for hex-aware movement,
         * s = select-self (toggle marked).  Save in hex mode is on
         * the menu (Alt+F → Save) or via ^S. */
        if (hex_mode) {
            char c = k[0];
            if (c >= 'A' && c <= 'Z') c += 32;
            if (c == 's') { g_marked ^= (1ULL << cursor); continue; }
            if (c == 'a' || c == 'd' || c == 'w' || c == 'e' ||
                c == 'z' || c == 'x') {
                int gx = cursor % 8, gy = cursor / 8;
                int odd = gy & 1;
                int ngx = gx, ngy = gy;
                switch (c) {
                case 'a': ngx = gx - 1;                              break;
                case 'd': ngx = gx + 1;                              break;
                case 'w': ngy = gy - 1; ngx = gx + (odd ? 0 : -1);   break;
                case 'e': ngy = gy - 1; ngx = gx + (odd ? 1 : 0);    break;
                case 'z': ngy = gy + 1; ngx = gx + (odd ? 0 : -1);   break;
                case 'x': ngy = gy + 1; ngx = gx + (odd ? 1 : 0);    break;
                }
                if (ngx >= 0 && ngx < 8 && ngy >= 0 && ngy < 8)
                    cursor = ngy * 8 + ngx;
                continue;
            }
        }

        if (k[0] == ' ')              { g_marked ^= (1ULL << cursor); continue; }
        if (k[0] == '\r' || k[0] == '\n') { garden_breed(); continue; }
        if (k[0] == 'p' || k[0] == 'P') { garden_preview(cursor); continue; }
        if (k[0] == 'v' || k[0] == 'V') { garden_view(cursor); term_raw(); continue; }
        if (k[0] == 'r' || k[0] == 'R') { garden_init_pop(); continue; }
        if (k[0] == 's' || k[0] == 'S') {
            if (garden_save() == 0) {
                int ml = sapp(last_msg, 0, "saved garden.bin");
                last_msg[ml] = 0; last_msg_ttl = 1;
            }
            continue;
        }
        if (k[0] == 'l' || k[0] == 'L') {
            if (garden_load()) {
                int ml = sapp(last_msg, 0, "loaded garden.bin");
                last_msg[ml] = 0; last_msg_ttl = 1;
            }
            continue;
        }
        if (k[0] == 'q' || k[0] == 0x11) break;
        /* 'x' / 'X' export shortcut.  Hex mode catches lowercase 'x'
         * earlier as SE movement; an export from hex mode either uses
         * uppercase 'X' (which falls through here) or the Edit→Export
         * menu (MA_EXPORT). */
        if (k[0] == 'X' || (k[0] == 'x' && !hex_mode)) {
            char nm[HX_EXPORT_NAME_LEN + 1];
            hx_make_export_name(nm, gd_export_seq++);
            int rc = gd_splice_export(nm,
                                      (const unsigned char *)&g_pop[cursor]);
            int ml = sapp(last_msg, 0, rc == 0 ? "exported " : "export failed ");
            if (rc == 0) ml = sapp(last_msg, ml, nm);
            last_msg[ml] = 0; last_msg_ttl = 1;
            continue;
        }
    }

    term_cooked();
    return 0;
}


/* ── hxhnt: class-4 hex-CA hunter ────────────────────────────────────
 *
 * Direct port of isolation/artifacts/oneclick_class4/hunter.c, just
 * with libc calls swapped for office's syscall wrappers + framebuffer.
 * Functionality preserved 1:1: same constants, same fitness curve,
 * same GA structure (tournament-2, breed-bottom-half, crossover-cut +
 * 0.5 % point mutation), same winner tournament + write-out.  Self-
 * replication uses *seed files* (./hxhnt.seed, ./hxhnt_winner_N.seed)
 * since the office binary isn't a hunter binary; the on-disk format
 * is the same TAIL bytes the original appended (4 magic + 4 palette +
 * 4096 packed genome).
 */

#define HX_K          4
#define HX_NSIT       16384            /* K^7? actually K^7 = 16384 (4 ^ 7) */
#define HX_GBYTES     4096             /* NSIT * 2 bits / 8                 */
#define HX_PAL_BYTES  4
#define HX_MAGIC_BYTES 4
#define HX_TAIL_MAGIC "HXC4"
#define HX_TAIL_BYTES (HX_MAGIC_BYTES + HX_PAL_BYTES + HX_GBYTES)
#define HX_GRID_W     14
#define HX_GRID_H     14
#define HX_HORIZON    25
#define HX_POP        30
#define HX_GENS       40
#define HX_TSEEDS     3
#define HX_WINNERS    3

/* Static .bss storage — sized at compile time so we don't need malloc.
 * .bss doesn't grow the binary on disk. */
static unsigned char hx_pool[HX_POP][HX_GBYTES];
static unsigned char hx_pals[HX_POP][HX_PAL_BYTES];
static double        hx_fit [HX_POP];
static unsigned char hx_seed_pal[HX_PAL_BYTES];
static unsigned char hx_seed_genome[HX_GBYTES];
static unsigned char hx_grid_a[HX_GRID_W * HX_GRID_H];
static unsigned char hx_grid_b[HX_GRID_W * HX_GRID_H];
static double        hx_last_activity_tail;

/* Hunter has its own LCG state so it doesn't collide with garden's. */
static unsigned long long hx_rng_state;
static unsigned int hx_rand(void) {
    hx_rng_state = hx_rng_state * 6364136223846793005ULL +
                   1442695040888963407ULL;
    return (unsigned int)(hx_rng_state >> 32);
}
#define HX_RAND_MAX 0xffffffffu


/* ── tiny libc-replacements specific to hxhnt ──────────────────────── */

static int mcmp(const void *a, const void *b, size_t n) {
    const unsigned char *aa = (const unsigned char *)a;
    const unsigned char *bb = (const unsigned char *)b;
    for (size_t i = 0; i < n; i++) {
        if (aa[i] != bb[i]) return (int)aa[i] - (int)bb[i];
    }
    return 0;
}

static int atoi_(const char *s) {
    int sign = 1, n = 0;
    while (*s == ' ' || *s == '\t') s++;
    if (*s == '-') { sign = -1; s++; }
    else if (*s == '+') s++;
    while (*s >= '0' && *s <= '9') { n = n * 10 + (*s - '0'); s++; }
    return sign * n;
}

struct hx_timespec { long tv_sec, tv_nsec; };
static void hx_sleep_ms(int ms) {
    struct hx_timespec ts;
    ts.tv_sec  = ms / 1000;
    ts.tv_nsec = (long)(ms % 1000) * 1000000L;
    sys3(SYS_nanosleep, (long)&ts, 0, 0);
}

/* ── packed-genome helpers (verbatim from hunter.c, just renamed) ──── */

static int hx_g_get(const unsigned char *g, int idx) {
    return (g[idx >> 2] >> ((idx & 3) * 2)) & 3;
}
static void hx_g_set(unsigned char *g, int idx, int v) {
    int b = idx >> 2, o = (idx & 3) * 2;
    g[b] = (unsigned char)((g[b] & ~(3 << o)) | ((v & 3) << o));
}
static int hx_sit_idx(int s, const int *n) {
    int i = s;
    for (int k = 0; k < 6; k++) i = i * HX_K + n[k];
    return i;
}


/* ── hex stepping ────────────────────────────────────────────────── */

static const int HX_DY[6]  = { -1, -1,  0,  0,  1,  1 };
static const int HX_DXE[6] = {  0,  1, -1,  1, -1,  0 };
static const int HX_DXO[6] = { -1,  0, -1,  1,  0,  1 };

static void hx_step_grid(const unsigned char *g,
                         const unsigned char *in,
                         unsigned char *out) {
    for (int y = 0; y < HX_GRID_H; y++) {
        const int *dx = (y & 1) ? HX_DXO : HX_DXE;
        for (int x = 0; x < HX_GRID_W; x++) {
            int self = in[y * HX_GRID_W + x];
            int n[6];
            for (int k = 0; k < 6; k++) {
                int yy = y + HX_DY[k];
                int xx = x + dx[k];
                n[k] = (yy >= 0 && yy < HX_GRID_H
                     && xx >= 0 && xx < HX_GRID_W)
                     ? in[yy * HX_GRID_W + xx] : 0;
            }
            out[y * HX_GRID_W + x] = (unsigned char)hx_g_get(g, hx_sit_idx(self, n));
        }
    }
}

/* Park-Miller-ish LCG so seed_grid is deterministic given a uint32_t. */
static unsigned int hx_lcg_state;
static unsigned int hx_lcg(void) {
    hx_lcg_state = hx_lcg_state * 1103515245u + 12345u;
    return hx_lcg_state >> 16;
}
static void hx_seed_grid(unsigned char *grid, unsigned int seed) {
    hx_lcg_state = seed ? seed : 1u;
    for (int i = 0; i < HX_GRID_W * HX_GRID_H; i++)
        grid[i] = (unsigned char)(hx_lcg() & 3);
}


/* ── class-4 fitness ──────────────────────────────────────────────── */

static double hx_fitness(const unsigned char *genome, unsigned int grid_seed) {
    hx_seed_grid(hx_grid_a, grid_seed);
    double act[HX_HORIZON];
    int colour_counts_final[HX_K] = {0, 0, 0, 0};
    for (int t = 0; t < HX_HORIZON; t++) {
        hx_step_grid(genome, hx_grid_a, hx_grid_b);
        int changed = 0;
        for (int i = 0; i < HX_GRID_W * HX_GRID_H; i++)
            if (hx_grid_a[i] != hx_grid_b[i]) changed++;
        act[t] = (double)changed / (HX_GRID_W * HX_GRID_H);
        mcpy(hx_grid_a, hx_grid_b, sizeof hx_grid_a);
    }
    int uniform = 1;
    for (int i = 1; i < HX_GRID_W * HX_GRID_H; i++)
        if (hx_grid_a[i] != hx_grid_a[0]) { uniform = 0; break; }
    for (int i = 0; i < HX_GRID_W * HX_GRID_H; i++)
        colour_counts_final[hx_grid_a[i]]++;
    int diversity = 0;
    for (int c = 0; c < HX_K; c++)
        if (colour_counts_final[c] * 100 >= HX_GRID_W * HX_GRID_H) diversity++;

    int tail_n = HX_HORIZON / 3;
    if (tail_n < 1) tail_n = 1;
    double avg = 0;
    for (int i = HX_HORIZON - tail_n; i < HX_HORIZON; i++) avg += act[i];
    avg /= tail_n;
    hx_last_activity_tail = avg;

    double score = 0;
    if (!uniform) score += 1.0;
    int aperiodic = 0;
    for (int i = HX_HORIZON - tail_n; i < HX_HORIZON; i++)
        if (act[i] > 0.001) { aperiodic = 1; break; }
    if (aperiodic) score += 1.5;
    double activity_reward;
    if (avg <= 0.12) activity_reward = avg / 0.12;
    else             activity_reward = (0.75 - avg) / 0.63;
    if (activity_reward < 0) activity_reward = 0;
    score += 2.0 * activity_reward;
    if (diversity >= 2) score += 0.25 * (diversity < HX_K ? diversity : HX_K);
    return score;
}


/* ── palette + identity-genome bootstrap ───────────────────────────── */

static void hx_invent_palette(unsigned char *pal) {
    for (int i = 0; i < HX_K; ) {
        unsigned int r = hx_rand();
        int c = ((r % 10) < 9) ? (16 + (int)((r >> 8) % 216))
                               : (232 + (int)((r >> 8) % 24));
        int ok = 1;
        for (int j = 0; j < i; j++) if (pal[j] == c) { ok = 0; break; }
        if (ok) pal[i++] = (unsigned char)c;
    }
}
static void hx_identity_genome(unsigned char *g) {
    mset(g + 0 * 1024, 0x00, 1024);
    mset(g + 1 * 1024, 0x55, 1024);
    mset(g + 2 * 1024, 0xAA, 1024);
    mset(g + 3 * 1024, 0xFF, 1024);
}

/* Liveliness-default genome — fully random per-situation lookup.
 * Compared to identity (which freezes the grid one frame in) or to
 * the all-zero "dead" embedded default (which collapses everything
 * to colour 0), a random genome guarantees motion every frame.
 * Usually class-3 (chaotic) — not class-4 — so the user gets
 * something that visibly *moves* until they breed for class-4 with
 * `hxhnt POP GENS`. */
static void hx_random_genome(unsigned char *g) {
    for (int i = 0; i < HX_GBYTES; i++)
        g[i] = (unsigned char)(hx_rand() & 0xff);
}


/* ── GA ops ───────────────────────────────────────────────────────── */

static void hx_mutate(unsigned char *dst, const unsigned char *src,
                      unsigned int rate_q24) {
    /* rate_q24 = mutation probability × 2^24 (so 0.05 ≈ 838860). */
    mcpy(dst, src, HX_GBYTES);
    for (int i = 0; i < HX_NSIT; i++) {
        if ((hx_rand() & 0xffffff) < rate_q24)
            hx_g_set(dst, i, (int)(hx_rand() & 3));
    }
}
static void hx_cross(unsigned char *dst, const unsigned char *a,
                     const unsigned char *b) {
    int cut = 1 + (int)(hx_rand() % (HX_GBYTES - 1));
    mcpy(dst,        a,        cut);
    mcpy(dst + cut, b + cut,  HX_GBYTES - cut);
}
static void hx_palette_inherit(unsigned char *dst, const unsigned char *a,
                               const unsigned char *b) {
    const unsigned char *src = (hx_rand() & 1) ? a : b;
    mcpy(dst, src, HX_PAL_BYTES);
    if ((hx_rand() % 100) < 8) {
        unsigned int r = hx_rand();
        int slot = (int)(r % HX_K);
        int c = ((r % 10) < 9) ? (16 + (int)((r >> 8) % 216))
                               : (232 + (int)((r >> 8) % 24));
        dst[slot] = (unsigned char)c;
    }
}


/* ── seed file I/O ─────────────────────────────────────────────────── */

#define HX_SEED_FILE "hxhnt.seed"

static int hx_read_seed(const char *path, unsigned char *pal,
                        unsigned char *genome) {
    int fd = (int)op(path, O_RDONLY, 0);
    if (fd < 0) return -1;
    char magic[HX_MAGIC_BYTES];
    int ok = (rd(fd, magic,  HX_MAGIC_BYTES) == HX_MAGIC_BYTES)
          && (mcmp(magic, HX_TAIL_MAGIC, HX_MAGIC_BYTES) == 0)
          && (rd(fd, pal,    HX_PAL_BYTES)   == HX_PAL_BYTES)
          && (rd(fd, genome, HX_GBYTES)      == HX_GBYTES);
    cl(fd);
    return ok ? 0 : -1;
}

static int hx_write_seed(const char *path, const unsigned char *pal,
                         const unsigned char *genome) {
    int fd = (int)op(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return -1;
    int ok = (wr(fd, HX_TAIL_MAGIC, HX_MAGIC_BYTES) == HX_MAGIC_BYTES)
          && (wr(fd, pal,            HX_PAL_BYTES)  == HX_PAL_BYTES)
          && (wr(fd, genome,         HX_GBYTES)     == HX_GBYTES);
    cl(fd);
    return ok ? 0 : -1;
}

/* ── embedded ruleset (.hxseed section) ─────────────────────────────
 *
 * Wrapped in a single packed struct so the compiler+linker
 * guarantee field order in the final ELF (separate static arrays in
 * the same section can be reordered by ld — observed: it put the
 * CLOSE marker before the OPEN one).  Layout in source ↔ on disk:
 *
 *   pre [16]               "<<HXSEED-OPEN>>"   (15 chars + NUL)
 *   palette [4]            HX_PAL_BYTES — splice target
 *   genome [4096]          HX_GBYTES    — splice target
 *   post [16]              "<<HXSEED-CLOSE>"   (15 chars + NUL)
 *
 * Total 4132 bytes, in the read-only segment.  The exporter scans
 * /proc/self/exe for the OPEN marker, overwrites the next 4100
 * bytes, sanity-checks the CLOSE marker, writes to dst. */
struct hx_payload {
    unsigned char pre[16];
    unsigned char palette[HX_PAL_BYTES];
    unsigned char genome[HX_GBYTES];
    unsigned char post[16];
} __attribute__((packed));

__attribute__((section(".hxseed"), used, aligned(16)))
static const struct hx_payload hx_embedded = {
    .pre     = "<<HXSEED-OPEN>>",
    /* xterm-256 cube codes whose RGB approximates rock / sand / soil /
     * water — the rpg terrain RGB bases used when no hxhnt.seed has
     * been written yet.  Override by evolving + saving in hxhnt. */
    .palette = { 102, 180, 95, 26 },
    .genome  = { 0 },
    .post    = "<<HXSEED-CLOSE>",
};

/* Convenience aliases so the rest of the code reads naturally. */
#define hx_payload_pre       hx_embedded.pre
#define hx_payload_post      hx_embedded.post
#define hx_embedded_palette  hx_embedded.palette
#define hx_embedded_genome   hx_embedded.genome


/* ── shared bootstrap: populate the active palette + genome ──────
 *
 * Called once at office startup (from main_c), so any app that
 * reads hx_seed_pal / hx_seed_genome — hxhnt for evolving + drawing,
 * rpg for terrain RGBs and the inner CA — sees a sensible value
 * regardless of which app the user opens first.
 *
 * Order of preference:
 *   1. ./hxhnt.seed (explicit user save → palette + genome).
 *   2. The embedded palette (always taken: a fresh build now ships
 *      a sensible water/grass/dirt/lava default).  Genome from
 *      embedded only if it's been spliced (non-zero), else random.
 */
static int hx_active_initialised;
static void hx_active_init(void) {
    if (hx_active_initialised) return;
    hx_active_initialised = 1;

    /* RNG seed, since hx_invent_palette / hx_random_genome consume it. */
    if (!hx_rng_state) {
        unsigned long h, l;
        __asm__ volatile ("rdtsc" : "=d"(h), "=a"(l));
        hx_rng_state = ((unsigned long long)h << 32) | l | 1ULL;
    }

    if (hx_read_seed(HX_SEED_FILE, hx_seed_pal, hx_seed_genome) == 0)
        return;

    mcpy(hx_seed_pal, hx_embedded_palette, HX_PAL_BYTES);
    int embedded_live = 0;
    for (int i = 0; i < HX_GBYTES; i++)
        if (hx_embedded_genome[i] != 0) { embedded_live = 1; break; }
    if (embedded_live) {
        mcpy(hx_seed_genome, hx_embedded_genome, HX_GBYTES);
    } else {
        hx_random_genome(hx_seed_genome);
    }
}


/* ── garden embedded chrome (.gdnseed section) ─────────────────────
 *
 * Parallel to .hxseed but for garden's 16-byte Genome.  Same packed
 * struct trick to fix field order across linker versions.  When
 * spliced, the binary's chrome (title bar / menu / desktop / select /
 * shadow / accent / clock_corner / show_clock / border / menu_under
 * / clock_style) reflects the gene under garden's cursor at export
 * time.  Bootstrap copies gd_embedded.genome → g_genome on launch. */
struct gd_payload {
    unsigned char pre[16];        /* "<<GDNSEED-OPEN>" */
    unsigned char genome[16];     /* sizeof(struct Genome) */
    unsigned char post[16];       /* "<<GDNSEED-CLOSE" */
} __attribute__((packed));

__attribute__((section(".gdnseed"), used, aligned(16)))
static const struct gd_payload gd_embedded = {
    .pre    = "<<GDNSEED-OPEN>",
    .genome = { 21, 15, 7, 0, 30, 15, 0, 0, 8, 21, 1, 0, 0, 1, 1, 0 },
    .post   = "<<GDNSEED-CLOSE",
};


/* Buffer for the splice exporter — sized to comfortably hold any
 * office binary we'd plausibly produce.  Lives in BSS, no on-disk cost. */
static unsigned char hx_export_buf[131072];

static long hx_find_marker(const unsigned char *buf, long len,
                           const unsigned char *marker, long mlen) {
    for (long i = 0; i + mlen <= len; i++)
        if (mcmp(buf + i, marker, (size_t)mlen) == 0) return i;
    return -1;
}

/* Generic splice exporter — both hxhnt and garden funnel through
 * here.  Reads /proc/self/exe, locates `marker_pre`, overwrites the
 * next `payload_len` bytes with `payload`, writes the result to dst.
 * Regions of the binary outside the splice target pass through
 * unchanged, so an export from one app preserves the other app's
 * embedded settings.  Returns 0 on success, -1 on any error
 * (marker missing, file I/O failure, etc.). */
static int office_splice(const char *dst,
                         const unsigned char *marker_pre, long marker_len,
                         const unsigned char *payload,    long payload_len) {
    int fd = (int)op("/proc/self/exe", O_RDONLY, 0);
    if (fd < 0) return -1;
    long total = 0;
    while (total < (long)sizeof hx_export_buf) {
        long n = rd(fd, hx_export_buf + total,
                    sizeof hx_export_buf - total);
        if (n <= 0) break;
        total += n;
    }
    cl(fd);
    if (total <= 0) return -1;

    long off = hx_find_marker(hx_export_buf, total, marker_pre, marker_len);
    if (off < 0) return -1;
    long payload_off = off + marker_len;
    if (payload_off + payload_len > total) return -1;

    mcpy(hx_export_buf + payload_off, payload, (size_t)payload_len);

    int d = (int)op(dst, O_WRONLY | O_CREAT | O_TRUNC, 0755);
    if (d < 0) return -1;
    long off_w = 0;
    while (off_w < total) {
        long w_n = wr(d, hx_export_buf + off_w, total - off_w);
        if (w_n <= 0) { cl(d); return -1; }
        off_w += w_n;
    }
    cl(d);
    sys3(SYS_chmod, (long)dst, 0755, 0);
    return 0;
}

/* Concatenate palette + genome into a stack scratch buffer and call
 * office_splice with the HXSEED marker.  Same call-shape as office18
 * for callers; the actual splice logic lives in office_splice. */
static int hx_splice_export(const char *dst,
                            const unsigned char *pal,
                            const unsigned char *genome) {
    unsigned char buf[HX_PAL_BYTES + HX_GBYTES];
    mcpy(buf,                pal,    HX_PAL_BYTES);
    mcpy(buf + HX_PAL_BYTES, genome, HX_GBYTES);
    return office_splice(dst, hx_payload_pre, sizeof hx_payload_pre,
                         buf, sizeof buf);
}

/* Garden export — splices the cursor's 16-byte Genome into the
 * .gdnseed region.  Same fixed 29-char filename as hxhnt's. */
static int gd_splice_export(const char *dst,
                            const unsigned char *garden_genome) {
    return office_splice(dst, gd_embedded.pre, sizeof gd_embedded.pre,
                         garden_genome, 16);
}

/* gd_export_seq is defined near the run_garden forward-decl block. */

/* Build the fixed-length export filename:
 *
 *     hxh-PPPPPPP-YYYYMMDDHHMMSS-NN
 *
 * Exactly 29 chars + NUL terminator.  Only [a-zA-Z0-9.-].  Every
 * export from the same office process produces the same length name
 * regardless of pid magnitude or sequence number, so the listing
 * sorts by time.  HX_EXPORT_NAME_LEN forward-declared earlier. */

static void hx_pad_uint(char *out, int width, unsigned long u) {
    /* Right-justify u within width, zero-padded.  Caller writes
     * ahead of out. */
    char tmp[20];
    int n = utoa((unsigned)u, tmp);
    /* Truncate from the left if u would overflow width.  In practice
     * pid_max is 7 digits and year fits in 4. */
    int skip = n > width ? n - width : 0;
    int pad  = n < width ? width - n : 0;
    for (int i = 0; i < pad; i++) *out++ = '0';
    for (int i = skip; i < n; i++) *out++ = tmp[i];
}

static void hx_make_export_name(char *out, int seq) {
    long pid = getpid_();
    long t = time_() + g_tz_offset_sec;
    int Y, Mo, D, h, mi, se;
    unix_to_calendar(t, &Y, &Mo, &D, &h, &mi, &se);

    char *p = out;
    *p++ = 'h'; *p++ = 'x'; *p++ = 'h'; *p++ = '-';
    hx_pad_uint(p, 7, (unsigned long)pid); p += 7;
    *p++ = '-';
    hx_pad_uint(p, 4, (unsigned long)Y);   p += 4;
    hx_pad_uint(p, 2, (unsigned long)Mo);  p += 2;
    hx_pad_uint(p, 2, (unsigned long)D);   p += 2;
    hx_pad_uint(p, 2, (unsigned long)h);   p += 2;
    hx_pad_uint(p, 2, (unsigned long)mi);  p += 2;
    hx_pad_uint(p, 2, (unsigned long)se);  p += 2;
    *p++ = '-';
    hx_pad_uint(p, 2, (unsigned long)seq); p += 2;
    *p = 0;
    /* p - out == HX_EXPORT_NAME_LEN by construction. */
}

/* ── render: animate a genome on the office framebuffer ────────────── */

static void hx_render_grid(const unsigned char *grid, const unsigned char *pal,
                           int origin_x, int origin_y) {
    /* Two-cell-wide cells so the grid is visibly square-ish; odd
     * rows offset by one cell for hex appearance.  Same pixel logic
     * as the original hunter's render_grid, just routed through fb. */
    for (int y = 0; y < HX_GRID_H; y++) {
        cup(origin_x + ((y & 1) ? 1 : 0), origin_y + y);
        for (int x = 0; x < HX_GRID_W; x++) {
            sgrbg(pal[grid[y * HX_GRID_W + x]]);
            fbs("  ");
        }
        sgr0();
    }
}

/* Forward decls for the mutation knob — defined further down with
 * the rest of the GA helpers. */
static void hx_mut_nudge(int delta);
static int  hx_mut_format(char *out);

/* Display mode: paint a chrome, then animate the seed continuously
 * until q or ESC.  We're already inside an app — no need to step
 * out after a fixed tick budget.  Switches the tty to VMIN=0/
 * VTIME=2 (200 ms poll) so the loop ticks on its own; restores
 * VMIN=1 before returning so GA-mode read_key calls still block.
 * Returns 'q' = quit, 'g' = run a single GA, 'h' = continuous hunt. */
static int hx_display_seed(unsigned char *genome,
                           unsigned char *pal, unsigned int gseed) {
    hx_seed_grid(hx_grid_a, gseed);
    int gx = 4, gy = 3;
    paint_desktop();
    chrome("hxhnt");
    body_clear();

    /* Polling termios — 200 ms timeout, no minimum byte count. */
    struct ti t = term_orig;
    t.lflag &= ~(ICANON | ECHO);
    t.iflag &= ~(IXON | ICRNL);
    t.cc[6] = 0;     /* VMIN  */
    t.cc[5] = 2;     /* VTIME = 200 ms */
    io(0, TCSETS, &t);

    int flash_ttl = 0;
    char flash_msg[80]; flash_msg[0] = 0;
    int xseq = 1;
    int exit_code = 'q';

    for (long tick = 0; ; tick++) {
        hx_render_grid(hx_grid_a, pal, gx, gy);
        char hint[160]; int p = 0;
        if (flash_ttl > 0) {
            p = sapp(hint, p, flash_msg);
            flash_ttl--;
        } else {
            p = sapp(hint, p, " t=");
            p += utoa((unsigned)tick, hint + p);
            p = sapp(hint, p, " mut=");
            p += hx_mut_format(hint + p);
            p = sapp(hint, p, " g/h/[/] r/d/x/q ");
        }
        hint[p] = 0;
        status(hint);
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n > 0) {
            int c = k[0];
            if (c >= 'A' && c <= 'Z') c += 32;
            if (c == 0x1b || c == 'q') { exit_code = 'q'; break; }
            if (c == 'g')              { exit_code = 'g'; break; }
            if (c == 'h')              { exit_code = 'h'; break; }
            if (c == '[' || c == '{') {
                hx_mut_nudge(-1);
                int q = sapp(flash_msg, 0, " mut down to ");
                q += hx_mut_format(flash_msg + q);
                flash_msg[q] = 0;
                flash_ttl = 8;
            } else if (c == ']' || c == '}') {
                hx_mut_nudge(+1);
                int q = sapp(flash_msg, 0, " mut up to ");
                q += hx_mut_format(flash_msg + q);
                flash_msg[q] = 0;
                flash_ttl = 8;
            } else if (c == 'r') {
                hx_invent_palette(pal);
                int q = sapp(flash_msg, 0, " palette randomised — d to save ");
                flash_msg[q] = 0;
                flash_ttl = 8;
            } else if (c == 'd') {
                int rc = hx_write_seed(HX_SEED_FILE, pal, genome);
                int q;
                if (rc == 0) {
                    q = sapp(flash_msg, 0, " saved ");
                    q = sapp(flash_msg, q, HX_SEED_FILE);
                    q = sapp(flash_msg, q, " — loaded by default next launch ");
                } else {
                    q = sapp(flash_msg, 0, " save failed ");
                }
                flash_msg[q] = 0;
                flash_ttl = 12;
            } else if (c == 'x') {
                char nm[HX_EXPORT_NAME_LEN + 1];
                hx_make_export_name(nm, xseq++);
                int rc = hx_splice_export(nm, pal, genome);
                int q;
                if (rc == 0) {
                    q = sapp(flash_msg, 0, " exported ");
                    q = sapp(flash_msg, q, nm);
                } else {
                    q = sapp(flash_msg, 0, " export failed ");
                }
                flash_msg[q] = 0;
                flash_ttl = 5;
            }
        }

        hx_step_grid(genome, hx_grid_a, hx_grid_b);
        mcpy(hx_grid_a, hx_grid_b, sizeof hx_grid_a);
    }

    /* Restore blocking mode for the rest of run_hxhnt. */
    t.cc[6] = 1;
    t.cc[5] = 2;
    io(0, TCSETS, &t);
    return exit_code;
}


/* ── progress paint during GA ──────────────────────────────────────── */

static void hx_paint_progress(int gen, int gens, double best_fit,
                              double mean_fit, double best_act,
                              const unsigned char *best_pal) {
    paint_desktop();
    chrome("hxhnt · evolving");
    body_clear();
    char buf[120]; int p;

    p = 0; p = sapp(buf, p, "  gen ");
    p += utoa((unsigned)gen, buf + p);
    p = sapp(buf, p, " / ");
    p += utoa((unsigned)gens, buf + p);
    buf[p] = 0;
    body_at(2, 3, buf, SCREEN_W - 4);

    /* best/mean fitness as fixed-point so we don't need printf("%.2f"). */
    long bf = (long)(best_fit * 100.0 + 0.5);
    long mf = (long)(mean_fit * 100.0 + 0.5);
    long ba = (long)(best_act * 1000.0 + 0.5);
    p = 0; p = sapp(buf, p, "  best=");
    p += utoa((unsigned)(bf / 100), buf + p); buf[p++] = '.';
    p += u2((unsigned)(bf % 100), buf + p);
    p = sapp(buf, p, "   mean=");
    p += utoa((unsigned)(mf / 100), buf + p); buf[p++] = '.';
    p += u2((unsigned)(mf % 100), buf + p);
    p = sapp(buf, p, "   activity=");
    p += utoa((unsigned)(ba / 1000), buf + p); buf[p++] = '.';
    p += utoa((unsigned)(ba % 1000), buf + p);
    buf[p] = 0;
    body_at(2, 5, buf, SCREEN_W - 4);

    /* Show the best palette as four colored swatches. */
    cup(2, 7);
    sgrbgfg(COL_BAR_BG, COL_BAR_FG);
    fbs("  best palette: ");
    for (int i = 0; i < HX_K; i++) {
        sgrbg(best_pal[i]);
        fbs("    ");
    }
    sgr0();

    status(" GA running — wait for it ");
    fbflush();
}


/* ── insertion sort by fitness desc, palettes follow genomes ───────── */

static void hx_sort_by_fitness(int n) {
    for (int i = 1; i < n; i++) {
        double fv = hx_fit[i];
        unsigned char tmp_g[HX_GBYTES];
        unsigned char tmp_p[HX_PAL_BYTES];
        mcpy(tmp_g, hx_pool[i], HX_GBYTES);
        mcpy(tmp_p, hx_pals[i], HX_PAL_BYTES);
        int j = i - 1;
        while (j >= 0 && hx_fit[j] < fv) {
            hx_fit[j + 1] = hx_fit[j];
            mcpy(hx_pool[j + 1], hx_pool[j], HX_GBYTES);
            mcpy(hx_pals[j + 1], hx_pals[j], HX_PAL_BYTES);
            j--;
        }
        hx_fit[j + 1] = fv;
        mcpy(hx_pool[j + 1], tmp_g, HX_GBYTES);
        mcpy(hx_pals[j + 1], tmp_p, HX_PAL_BYTES);
    }
}


/* ── parse "POP GENS [SEED]" out of the shell-passed argv[1] ──────── */

static int hx_parse_args(const char *raw, int *pop, int *gens, unsigned *seed) {
    /* raw is everything after "hxhnt " from the shell — possibly empty. */
    if (!raw || !*raw) return 0;
    const char *p = raw;
    while (*p == ' ') p++;
    if (!*p) return 0;
    int n_pop = atoi_(p);
    while (*p && *p != ' ') p++;
    while (*p == ' ') p++;
    if (!*p) return 0;
    int n_gens = atoi_(p);
    while (*p && *p != ' ') p++;
    while (*p == ' ') p++;
    unsigned n_seed = *p ? (unsigned)atoi_(p) : 42u;
    if (n_pop < 2 || n_pop > HX_POP) return -1;
    if (n_gens < 1) return -1;
    *pop = n_pop; *gens = n_gens; *seed = n_seed;
    return 1;
}


/* ── mutation rate knob ─────────────────────────────────────────────
 * Stored as 1/2^24 fixed-point — same scale hx_mutate expects.
 * Defaults to 838860 (≈ 5 %).  Offspring mutation is 1/10 of init, so
 * adjusting one knob coherently scales both. */
static unsigned hx_mut_init = 838860;   /* 5 % default */

/* xterm-256 codes flag where this mut value sits in a fixed ladder. */
static const unsigned hx_mut_ladder[] = {
       8389,    /*  0.05 % */
      83886,    /*  0.5  % */
     167772,    /*  1.0  % */
     335544,    /*  2.0  % */
     503316,    /*  3.0  % */
     838860,    /*  5.0  % */
    1677721,    /* 10.0  % */
    2516582,    /* 15.0  % */
    3355443,    /* 20.0  % */
    5033164,    /* 30.0  % */
};
#define HX_MUT_LADDER_N \
    ((int)(sizeof hx_mut_ladder / sizeof hx_mut_ladder[0]))

static int hx_mut_ladder_idx(void) {
    int best = 0;
    unsigned best_d = 0xffffffffu;
    for (int i = 0; i < HX_MUT_LADDER_N; i++) {
        unsigned d = hx_mut_ladder[i] > hx_mut_init
                   ? hx_mut_ladder[i] - hx_mut_init
                   : hx_mut_init - hx_mut_ladder[i];
        if (d < best_d) { best_d = d; best = i; }
    }
    return best;
}

static void hx_mut_nudge(int delta) {
    int i = hx_mut_ladder_idx() + delta;
    if (i < 0)                  i = 0;
    if (i >= HX_MUT_LADDER_N)   i = HX_MUT_LADDER_N - 1;
    hx_mut_init = hx_mut_ladder[i];
}

/* Append the current mut rate to a buffer as e.g. "5.00%" or "0.05%". */
static int hx_mut_format(char *out) {
    /* hx_mut_init / 2^24 ×100 = percentage.  Use ×10000 for 2 dp,
     * with a +2^23 round-to-nearest. */
    unsigned long pct100 =
        (((unsigned long)hx_mut_init * 10000UL) + (1UL << 23)) >> 24;
    int p = 0;
    p += utoa((unsigned)(pct100 / 100), out + p);
    out[p++] = '.';
    p += u2((unsigned)(pct100 % 100), out + p);
    out[p++] = '%';
    out[p] = 0;
    return p;
}


/* ── one GA session: mutate, score, breed, adopt winner ───────────
 * Returns 1 if the user aborted (q/ESC during a generation), 0 if
 * the session ran to completion.  Caller decides whether to show the
 * winners screen or chain another session. */

static int hx_run_ga_session(int pop, int gens, unsigned rseed) {
    /* Polling termios so each generation advances on its own —
     * VMIN=0, VTIME=2 means read_key returns within ~200 ms whether
     * a key was pressed or not. */
    struct ti t = term_orig;
    t.lflag &= ~(ICANON | ECHO);
    t.iflag &= ~(IXON | ICRNL);
    t.cc[6] = 0;     /* VMIN  */
    t.cc[5] = 2;     /* VTIME = 200 ms */
    io(0, TCSETS, &t);

    int aborted = 0;
    unsigned mut_off = hx_mut_init / 10;
    if (mut_off < 1) mut_off = 1;

    /* Pool[0] = current default; the rest are mutated copies. */
    mcpy(hx_pool[0], hx_seed_genome, HX_GBYTES);
    mcpy(hx_pals[0], hx_seed_pal,    HX_PAL_BYTES);
    for (int i = 1; i < pop; i++) {
        hx_mutate(hx_pool[i], hx_seed_genome, hx_mut_init);
        mcpy(hx_pals[i], hx_seed_pal, HX_PAL_BYTES);
    }

    for (int gen = 0; gen < gens; gen++) {
        for (int i = 0; i < pop; i++)
            hx_fit[i] = hx_fitness(hx_pool[i], rseed);
        hx_sort_by_fitness(pop);

        double sum = 0;
        for (int i = 0; i < pop; i++) sum += hx_fit[i];
        hx_fitness(hx_pool[0], rseed);   /* refresh hx_last_activity_tail */
        hx_paint_progress(gen + 1, gens, hx_fit[0], sum / pop,
                          hx_last_activity_tail, hx_pals[0]);

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n > 0 && (k[0] == 0x1b || k[0] == 'q' || k[0] == 'Q')) {
            aborted = 1;
            break;
        }

        for (int i = pop / 2; i < pop; i++) {
            int pa = (int)(hx_rand() % (pop / 2));
            int pb = (int)(hx_rand() % (pop / 2));
            unsigned char tmp[HX_GBYTES];
            hx_cross(tmp, hx_pool[pa], hx_pool[pb]);
            hx_mutate(hx_pool[i], tmp, mut_off);
            hx_palette_inherit(hx_pals[i], hx_pals[pa], hx_pals[pb]);
        }
    }

    /* Restore blocking termios for whatever the caller does next. */
    t.cc[6] = 1;
    t.cc[5] = 2;
    io(0, TCSETS, &t);

    /* Final tournament. */
    for (int i = 0; i < pop; i++)
        hx_fit[i] = hx_fitness(hx_pool[i], rseed);
    hx_sort_by_fitness(pop);

    /* Adopt winner #1 as the live seed; persist to disk so rpg
     * picks up the new palette + ruleset on its next entry. */
    mcpy(hx_seed_genome, hx_pool[0], HX_GBYTES);
    mcpy(hx_seed_pal,    hx_pals[0], HX_PAL_BYTES);
    hx_write_seed(HX_SEED_FILE, hx_seed_pal, hx_seed_genome);

    return aborted;
}

/* Winners screen — 1/2/3 splice-export, q returns. */
static void hx_show_winners(int pop) {
    int seq = 1;
    char status_msg[80]; status_msg[0] = 0;
    while (1) {
        paint_desktop();
        chrome("hxhnt · winners");
        body_clear();
        body_at(2, 3, "Top winners — 1/2/3 export as binary, q returns:",
                SCREEN_W - 4);
        for (int w = 0; w < HX_WINNERS && w < pop; w++) {
            char line[80]; int p = 0;
            p = sapp(line, p, "  ");
            line[p++] = (char)('1' + w);
            p = sapp(line, p, ")  fit=");
            long ff = (long)(hx_fit[w] * 100.0 + 0.5);
            p += utoa((unsigned)(ff / 100), line + p); line[p++] = '.';
            p += u2((unsigned)(ff % 100), line + p);
            line[p] = 0;
            body_at(2, 5 + w, line, SCREEN_W - 4);
            int sx = SCREEN_W - 10;
            if (sx > 4) {
                cup(sx, 5 + w);
                for (int i = 0; i < HX_K; i++) {
                    sgrbg(hx_pals[w][i]);
                    fbs(" ");
                }
                sgr0();
            }
        }
        body_at(2, 5 + HX_WINNERS + 1,
                "Winner #1 saved as default — rpg will use its palette + ruleset.",
                SCREEN_W - 4);
        if (status_msg[0]) status(status_msg);
        else               status(" 1/2/3 splice export · q returns ");
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;
        if (k[0] == 'q' || k[0] == 'Q' || k[0] == 0x1b) break;
        int w = -1;
        if (k[0] >= '1' && k[0] <= '3') w = k[0] - '1';
        if (w < 0 || w >= pop || w >= HX_WINNERS) continue;

        char export_name[HX_EXPORT_NAME_LEN + 1];
        hx_make_export_name(export_name, seq++);
        int rc = hx_splice_export(export_name, hx_pals[w], hx_pool[w]);
        int p = 0;
        if (rc == 0) {
            p = sapp(status_msg, p, " exported #");
            status_msg[p++] = (char)('1' + w);
            p = sapp(status_msg, p, "  ");
            p = sapp(status_msg, p, export_name);
        } else {
            p = sapp(status_msg, p, " export failed (no .hxseed marker?) ");
        }
        status_msg[p] = 0;
    }
}

/* Single GA session + winners screen — what 'g' or `hxhnt POP GENS`
 * deliver. */
static void hx_run_ga(int pop, int gens, unsigned rseed) {
    hx_run_ga_session(pop, gens, rseed);
    hx_show_winners(pop);
}

/* Continuous hunt — loop short GA sessions, each refining off the
 * previous winner, until the user aborts.  No winners screen between
 * rounds; on exit we just return to display mode showing the latest
 * evolved genome animating. */
static void hx_run_continuous_hunt(void) {
    while (1) {
        unsigned rs = (unsigned)(time_() ^ (long)hx_rand());
        int aborted = hx_run_ga_session(20, 10, rs);
        if (aborted) break;
    }
}


/* ── main entry point ──────────────────────────────────────────────── */

static int run_hxhnt(int argc, char **argv) {
    current_ms = &ms_hxhnt;
    term_raw();

    /* hx_active_init() ran at office startup — defensive-call in case
     * this fork was invoked through an unusual path. */
    hx_active_init();

    /* CLI form: `hxhnt POP GENS [SEED]` runs one GA session and exits. */
    int pop = 0, gens = 0;
    unsigned rseed = 42;
    int mode = (argc > 1) ? hx_parse_args(argv[1], &pop, &gens, &rseed) : 0;
    if (mode > 0) {
        hx_run_ga(pop, gens, rseed);
        term_cooked();
        return 0;
    }

    /* Interactive: display the seed; the user can press 'g' to start
     * a GA at sane defaults, 'r' to randomise the palette, 'd' to
     * persist the current state as the new default.  After a GA the
     * winner becomes the live seed and we loop back into display so
     * the user immediately sees the evolved CA in motion. */
    while (1) {
        int act = hx_display_seed(hx_seed_genome, hx_seed_pal,
                                  (unsigned int)time_());
        if (act == 'g') {
            unsigned int gseed = (unsigned int)(time_() ^ (long)hx_rand());
            hx_run_ga(20, 20, gseed);
            continue;
        }
        if (act == 'h') {
            hx_run_continuous_hunt();
            continue;
        }
        break;
    }

    term_cooked();
    return 0;
}


/* ── rpg: tiny tile explorer driven by the .hxseed ruleset ──────────
 *
 * Treats the embedded 4096-byte CA ruleset as a *terrain generator*:
 * fill a 64×64 hex grid with random 0..3, step it through the rule
 * a handful of times, then drop the player at world (32, 32).  An
 * 8×8 visible window slides around as the player moves so '@' is
 * always at the centre cell.
 *
 * Layout (each cell is 8 chars wide × 3 lines tall):
 *
 *   row 0 of cells (even):  cells_x = origin_x +  0, 8, 16, ...
 *   row 1 of cells (odd):   cells_x = origin_x +  4, 12, 20, ...   (large hex offset)
 *   ...
 *
 * Inside each cell the middle line of three is shifted +2 cols so
 * each cell looks vaguely hex-shaped on its own.  The result is
 * two stages of staggered offset: rows of cells + line-within-cell. */

#define RPG_MAP_W       64       /* one overworld chunk = 64×64 cells */
#define RPG_MAP_H       64
/* office41 — 3×3 mosaic of overworlds.  The world-cell arrays cover
 * RPG_TILE_W × RPG_TILE_H so the player never sees a chunk edge:
 * neighbors are pre-loaded and visible across boundaries.  The mosaic
 * shifts when the player crosses out of the central 64×64 region. */
#define RPG_TILE_W       (3 * RPG_MAP_W)   /* 192 */
#define RPG_TILE_H       (3 * RPG_MAP_H)   /* 192 */
#define RPG_VIS_W        8       /* cells visible across */
#define RPG_VIS_H        8       /* cells visible down   */
#define RPG_CELL_W       8       /* chars per cell, horizontally */
#define RPG_CELL_H       3       /* chars per cell, vertically   */
#define RPG_PLAYER_VX    4       /* player at this cell of visible */
#define RPG_PLAYER_VY    4
#define RPG_GEN_STEPS    5       /* CA ticks before playing */
#define RPG_MID_SHIFT    2       /* per-cell middle-line x shift */

/* office41 — meta-overworld coordinate stack.  rpg_world_pos[0] is
 * the (x, y) of the current overworld within the level-2 meta-grid,
 * rpg_world_pos[1] is the (x, y) of that meta within level-3, and so
 * on up to RPG_WORLD_LEVELS deep.  Walking off an overworld edge
 * advances level 0 with carry into deeper levels at 64-cell wrap.
 * The seed for every overworld is a hash of the full position vector,
 * so identical coords always regenerate the same map. */
#define RPG_WORLD_LEVELS 63
static int rpg_world_pos[RPG_WORLD_LEVELS][2];

static unsigned char rpg_map[RPG_TILE_W * RPG_TILE_H];
static unsigned char rpg_buf[RPG_MAP_W * RPG_MAP_H];     /* one-chunk CA scratch */

/* Per-cell entity layer.  rpg_cat_at[i] = 0 → empty, otherwise the
 * category index (1=plant, 2=building, 3=animal, 4=item) into
 * rpg_cats[].  rpg_idx_at[i] picks one of 64 variants within that
 * category.  rpg_hp_at[i] is only meaningful for animals. */
static unsigned char rpg_cat_at[RPG_TILE_W * RPG_TILE_H];
static unsigned char rpg_idx_at[RPG_TILE_W * RPG_TILE_H];
static unsigned char rpg_hp_at [RPG_TILE_W * RPG_TILE_H];

/* office41 NPC layer.  rpg_npc_at[i] = 0 → no NPC; otherwise the byte
 * encodes a head/body palette pair: high nibble indexes rpg_npc_pal
 * for the head colour, low nibble for the body.  NPCs render as a
 * 1×2 block sprite (same shape as the player) and block movement;
 * bumping prints a greeting. */
static unsigned char rpg_npc_at[RPG_TILE_W * RPG_TILE_H];
static const unsigned char rpg_npc_pal[16] = {
    196, 202, 220, 226, 154, 118,  51,  39,
     33,  93, 201, 198, 252, 245, 240, 232,
};

/* office41 wander layer.  Each animal/NPC has a current step index
 * within a procedural closed-loop path and a path-generation counter
 * that lets us re-seed a fresh loop when the current one completes.
 * The path itself is regenerated from (world_idx, path_id, world_seed)
 * each tick — no per-cell path storage needed. */
#define RPG_PATH_MAX 64
static unsigned char rpg_path_step[RPG_TILE_W * RPG_TILE_H];
static unsigned char rpg_path_id  [RPG_TILE_W * RPG_TILE_H];

/* Inner-CA scratch + per-cell texture cache (office23+).
 * Each overworld cell has its own 64×64 hex CA seeded by hashing
 * its (wx, wy); we run it for 2-4 steps under the parent ruleset,
 * sample 8×3 down to a stripe sized to fit the screen cell, and
 * keep the result + a 4-colour palette in the cache.  ~1 MB BSS for
 * the 192×192 mosaic; zero-init so it doesn't bloat the binary. */
static unsigned char rpg_inner_a[RPG_MAP_W * RPG_MAP_H];
static unsigned char rpg_inner_b[RPG_MAP_W * RPG_MAP_H];
static unsigned char rpg_cell_sample[RPG_TILE_W * RPG_TILE_H * 24]; /* 8×3 */
static unsigned char rpg_cell_pal   [RPG_TILE_W * RPG_TILE_H * 4];
static unsigned char rpg_cell_done  [RPG_TILE_W * RPG_TILE_H];

/* Live-animation state.  When 'l' toggles animation on, each visible
 * cell slot keeps its own 64×64 state grid that we step in-place each
 * frame.  rpg_anim_owner_x/y track which world cell currently owns
 * the slot — when the player moves and the visible window shifts,
 * mismatched slots get re-seeded.  ~256 KB BSS. */
#define RPG_ANIM_SLOTS (RPG_VIS_W * RPG_VIS_H)
static unsigned char rpg_anim_state[RPG_ANIM_SLOTS][RPG_MAP_W * RPG_MAP_H];
static short rpg_anim_owner_x[RPG_ANIM_SLOTS];
static short rpg_anim_owner_y[RPG_ANIM_SLOTS];
static unsigned char rpg_anim_init[RPG_ANIM_SLOTS];
static int rpg_animating;
static long rpg_frame;

/* Per-terrain animation pacing.  Animator runs at ~10 fps; we
 * accumulate `fpm` units per frame and step the terrain whenever
 * the accumulator crosses 600 (one minute's worth of frames).  So
 * 600 fpm = step every frame, 60 fpm = once per second, 1 fpm =
 * once per minute, 0 fpm = stopped (combined with the enabled
 * flag for explicit user shut-off). */
#define RPG_ANIM_FRAMES_PER_MIN 600     /* 10 fps × 60 s */
struct RpgTerrainAnim {
    short fpm;            /* user-adjustable rate, 0..1200 */
    short default_fpm;
    short acc;            /* per-frame accumulator */
    unsigned char enabled;
};
static struct RpgTerrainAnim rpg_terrain_anim[4];
static const char *rpg_terrain_name[4] = {"rock", "sand", "soil", "water"};

static void rpg_terrain_anim_init(void) {
    /* Defaults: rock barely moves, water moves every frame. */
    static const short defs[4] = { 2, 12, 60, 600 };
    for (int i = 0; i < 4; i++) {
        rpg_terrain_anim[i].fpm         = defs[i];
        rpg_terrain_anim[i].default_fpm = defs[i];
        rpg_terrain_anim[i].acc         = 0;
        rpg_terrain_anim[i].enabled     = 1;
    }
}

/* Terrain-type → base RGB.  Inherited from hxhnt's stored palette
 * (hx_seed_pal) by decoding each xterm-256 code back into 24-bit RGB.
 * Refreshed on every entry to run_rpg so changes hxhnt makes during
 * the same session show up immediately. */
struct RpgRGB { unsigned char r, g, b; };
static struct RpgRGB rpg_terrain_rgb[4];

/* xterm-256 → 24-bit RGB.  Cube (16..231) uses 6 non-linear steps:
 * 0 / 95 / 135 / 175 / 215 / 255.  Grayscale (232..255) is a 24-step
 * ramp from 8 to 238.  Codes 0..15 fall back to the standard ANSI
 * 16-colour table. */
static const unsigned char xterm_cube_steps[6] = {0, 95, 135, 175, 215, 255};
static const unsigned char xterm_basic_rgb[16][3] = {
    {  0,   0,   0}, {128,   0,   0}, {  0, 128,   0}, {128, 128,   0},
    {  0,   0, 128}, {128,   0, 128}, {  0, 128, 128}, {192, 192, 192},
    {128, 128, 128}, {255,   0,   0}, {  0, 255,   0}, {255, 255,   0},
    {  0,   0, 255}, {255,   0, 255}, {  0, 255, 255}, {255, 255, 255},
};
static void xterm256_to_rgb(int code, int *r, int *g, int *b) {
    if (code < 0)   code = 0;
    if (code > 255) code = 255;
    if (code < 16) {
        *r = xterm_basic_rgb[code][0];
        *g = xterm_basic_rgb[code][1];
        *b = xterm_basic_rgb[code][2];
    } else if (code < 232) {
        int i = code - 16;
        *r = xterm_cube_steps[i / 36];
        *g = xterm_cube_steps[(i / 6) % 6];
        *b = xterm_cube_steps[i %  6];
    } else {
        int v = 8 + (code - 232) * 10;
        *r = *g = *b = v;
    }
}

/* Recompute rpg_terrain_rgb[] from the active hxhnt palette.  Called
 * at run_rpg startup; cheap (8 table reads). */
static void rpg_terrain_rgb_refresh(const unsigned char *pal) {
    for (int i = 0; i < 4; i++) {
        int r, g, b;
        xterm256_to_rgb(pal[i], &r, &g, &b);
        rpg_terrain_rgb[i].r = (unsigned char)r;
        rpg_terrain_rgb[i].g = (unsigned char)g;
        rpg_terrain_rgb[i].b = (unsigned char)b;
    }
}

/* xterm-256 colour cube: 6×6×6 RGB cube at indices 16..231. */
static int rpg_rgb_to_xterm256(int r, int g, int b) {
    if (r <   0) r =   0;
    if (g <   0) g =   0;
    if (b <   0) b =   0;
    if (r > 255) r = 255;
    if (g > 255) g = 255;
    if (b > 255) b = 255;
    int rr = (r * 5 + 127) / 255;
    int gg = (g * 5 + 127) / 255;
    int bb = (b * 5 + 127) / 255;
    return 16 + 36 * rr + 6 * gg + bb;
}

/* SplitMix64-style mix → cell hash.  Stable across runs so the same
 * (wx, wy) always paints the same texture/palette. */
static unsigned long rpg_lcg_next(unsigned long *s) {
    *s = (*s) * 6364136223846793005UL + 1442695040888963407UL;
    return *s;
}
static unsigned long rpg_cell_hash(int wx, int wy) {
    unsigned long h = ((unsigned long)wx * 0x9E3779B97F4A7C15UL)
                    ^ ((unsigned long)wy * 0xC2B2AE3D27D4EB4FUL);
    h ^= h >> 33;
    h *= 0xFF51AFD7ED558CCDUL;
    h ^= h >> 33;
    h *= 0xC4CEB9FE1A85EC53UL;
    h ^= h >> 33;
    return h | 1UL;
}

/* Forward decl — defined below so the inner-CA reuses the overworld
 * stepper byte-for-byte. */
static void rpg_step_grid(const unsigned char *g,
                          const unsigned char *in,
                          unsigned char *out);

/* Compute (and cache) the inner-CA sample + 4-colour palette for one
 * overworld cell.  Idempotent — repeated calls are no-ops because we
 * key off rpg_cell_done[]. */
/* The default genome can be all zeros (fresh build, no hxhnt evolution
 * yet).  hx_g_get returns 0 for every situation in that case, so one
 * CA step collapses any input grid to uniform 0.  Recheck on every
 * run_rpg launch since the user may have evolved + saved between. */
static int rpg_genome_live_cache = -1;
static int rpg_genome_is_live(void) {
    if (rpg_genome_live_cache == -1) {
        rpg_genome_live_cache = 0;
        for (int i = 0; i < HX_GBYTES; i++)
            if (hx_seed_genome[i]) { rpg_genome_live_cache = 1; break; }
    }
    return rpg_genome_live_cache;
}

static void rpg_compute_cell(int wx, int wy) {
    int idx = wy * RPG_TILE_W + wx;
    if (rpg_cell_done[idx]) return;
    unsigned long s = rpg_cell_hash(wx, wy);
    /* Random 4-colour seed grid via the cell's own LCG.  Use high
     * bits — the low 2 bits of an MCG have period 4, so masking with
     * `& 3` gave a strict 4-cycle pattern (every sub-block had each
     * state exactly 42 times → mode always the same → solid cells). */
    for (int i = 0; i < RPG_MAP_W * RPG_MAP_H; i++)
        rpg_inner_a[i] = (unsigned char)((rpg_lcg_next(&s) >> 30) & 3);
    /* Step the inner CA only when the parent ruleset is non-trivial.
     * On a fresh build the embedded ruleset is all zeros, so even one
     * step would collapse the grid to uniform 0; in that case the
     * random initial grid is itself the "outcome" we sample from. */
    int n_steps = rpg_genome_is_live()
                ? ((int)((rpg_lcg_next(&s) >> 8) % 2) + 1)   /* 1..2 */
                : 0;
    for (int t = 0; t < n_steps; t++) {
        rpg_step_grid(hx_seed_genome, rpg_inner_a, rpg_inner_b);
        mcpy(rpg_inner_a, rpg_inner_b, RPG_MAP_W * RPG_MAP_H);
    }
    /* Aggregate the 64×64 grid into 8×3 blocks (8 cols × {21,22,21}
     * rows = 64×64 covered exactly).  Each output cell is the mode
     * (most-common state) across its sub-block — ~170 cells voting,
     * so two adjacent blocks with subtly different distributions
     * produce different majorities and the cell shows actual grain. */
    static const int band_y[4] = { 0, 21, 43, 64 };
    unsigned char *sample = &rpg_cell_sample[idx * 24];
    for (int r = 0; r < 3; r++) {
        int y0 = band_y[r], y1 = band_y[r + 1];
        for (int c = 0; c < 8; c++) {
            int x0 = c * 8, x1 = x0 + 8;
            unsigned counts[4] = {0, 0, 0, 0};
            for (int y = y0; y < y1; y++)
                for (int x = x0; x < x1; x++)
                    counts[rpg_inner_a[y * RPG_MAP_W + x] & 3]++;
            int best = 0;
            for (int k = 1; k < 4; k++)
                if (counts[k] > counts[best]) best = k;
            sample[r * 8 + c] = (unsigned char)best;
        }
    }
    /* 4-colour palette: terrain base RGB + 4 random offsets. */
    int terrain = rpg_map[idx] & 3;
    int br = rpg_terrain_rgb[terrain].r;
    int bg = rpg_terrain_rgb[terrain].g;
    int bb = rpg_terrain_rgb[terrain].b;
    unsigned char *pal = &rpg_cell_pal[idx * 4];
    for (int k = 0; k < 4; k++) {
        int dr = (int)(rpg_lcg_next(&s) & 0x7f) - 64;
        int dg = (int)(rpg_lcg_next(&s) & 0x7f) - 64;
        int db = (int)(rpg_lcg_next(&s) & 0x7f) - 64;
        pal[k] = (unsigned char)rpg_rgb_to_xterm256(br + dr, bg + dg, bb + db);
    }
    rpg_cell_done[idx] = 1;
}

/* Reset the live-animation cache.  Called when toggling animation
 * on so each slot reseeds from its current owner cleanly. */
static void rpg_anim_reset(void) {
    mset(rpg_anim_init, 0, sizeof rpg_anim_init);
}

/* Aggregate a 64×64 inner grid into the 8×3 sample for an overworld
 * cell.  Same {21,22,21}-row banding rpg_compute_cell uses. */
static void rpg_anim_aggregate(const unsigned char *grid,
                               unsigned char *sample) {
    static const int band_y[4] = { 0, 21, 43, 64 };
    for (int r = 0; r < 3; r++) {
        int y0 = band_y[r], y1 = band_y[r + 1];
        for (int c = 0; c < 8; c++) {
            int x0 = c * 8, x1 = x0 + 8;
            unsigned counts[4] = {0, 0, 0, 0};
            for (int y = y0; y < y1; y++)
                for (int x = x0; x < x1; x++)
                    counts[grid[y * RPG_MAP_W + x] & 3]++;
            int best = 0;
            for (int k = 1; k < 4; k++)
                if (counts[k] > counts[best]) best = k;
            sample[r * 8 + c] = (unsigned char)best;
        }
    }
}

/* Step every visible cell's inner CA one tick under hx_seed_genome,
 * re-aggregate its 8×3 sample — but only those cells whose terrain
 * is "due" this frame.  Per-terrain accumulators advance by their
 * fpm setting each frame; a terrain steps when its accumulator
 * crosses 600 (≈ one minute's worth of frames at 10 fps).  Disabled
 * terrains (enabled=0) skip stepping entirely.
 *
 * When a slot's owner mismatches the world cell currently in that
 * view position (player just moved), re-seed the slot from the
 * cell's deterministic hash.  When the embedded ruleset is empty
 * (would collapse to uniform 0 in one step), re-seed every step
 * instead so the animation churns visibly. */
static void rpg_animate_step(int px, int py, int rows_v) {
    int live = rpg_genome_is_live();
    long frame = rpg_frame;

    /* Tick per-terrain accumulators and decide which step this frame. */
    int step_now[4] = {0, 0, 0, 0};
    for (int t = 0; t < 4; t++) {
        if (!rpg_terrain_anim[t].enabled) continue;
        int a = (int)rpg_terrain_anim[t].acc + (int)rpg_terrain_anim[t].fpm;
        if (a >= RPG_ANIM_FRAMES_PER_MIN) {
            step_now[t] = 1;
            a -= RPG_ANIM_FRAMES_PER_MIN;
        }
        rpg_terrain_anim[t].acc = (short)a;
    }

    for (int vy = 0; vy < rows_v; vy++) {
        for (int vx = 0; vx < RPG_VIS_W; vx++) {
            int slot = vy * RPG_VIS_W + vx;
            int wx = px + vx - RPG_PLAYER_VX;
            int wy = py + vy - RPG_PLAYER_VY;
            if (wx < 0 || wx >= RPG_TILE_W ||
                wy < 0 || wy >= RPG_TILE_H) {
                rpg_anim_init[slot] = 0;
                continue;
            }
            int terrain = rpg_map[wy * RPG_TILE_W + wx] & 3;
            int owner_changed = !rpg_anim_init[slot]
                             || rpg_anim_owner_x[slot] != wx
                             || rpg_anim_owner_y[slot] != wy;

            unsigned char *state = rpg_anim_state[slot];

            if (owner_changed) {
                unsigned long s = rpg_cell_hash(wx, wy)
                                ^ (((unsigned long)frame)
                                   * 0x9E3779B97F4A7C15UL);
                for (int i = 0; i < RPG_MAP_W * RPG_MAP_H; i++)
                    state[i] = (unsigned char)((rpg_lcg_next(&s) >> 30) & 3);
                rpg_anim_owner_x[slot] = (short)wx;
                rpg_anim_owner_y[slot] = (short)wy;
                rpg_anim_init[slot] = 1;
                rpg_anim_aggregate(state,
                    &rpg_cell_sample[(wy * RPG_TILE_W + wx) * 24]);
                rpg_cell_done[wy * RPG_TILE_W + wx] = 1;
            } else if (step_now[terrain]) {
                if (live) {
                    rpg_step_grid(hx_seed_genome, state, rpg_inner_b);
                    mcpy(state, rpg_inner_b, RPG_MAP_W * RPG_MAP_H);
                } else {
                    /* No live ruleset → re-seed for visual churn. */
                    unsigned long s = rpg_cell_hash(wx, wy)
                                    ^ (((unsigned long)frame)
                                       * 0x9E3779B97F4A7C15UL);
                    for (int i = 0; i < RPG_MAP_W * RPG_MAP_H; i++)
                        state[i] = (unsigned char)((rpg_lcg_next(&s) >> 30) & 3);
                }
                rpg_anim_aggregate(state,
                    &rpg_cell_sample[(wy * RPG_TILE_W + wx) * 24]);
                rpg_cell_done[wy * RPG_TILE_W + wx] = 1;
            }
            /* else: terrain not due this frame — sample stays as-is. */
        }
    }
}

/* Each entity kind defines its sprite as a small L-system: axiom +
 * one F-rule + iteration count + 45°-step angle (same alphabet as the
 * lsys app — F forward, +/- turn, [/] push/pop).  At rpg startup we
 * walk the turtle, dump every F-step position into a point cloud,
 * downsample into a (height × 3) grid by counting points per bucket,
 * and threshold the count to one of 4 palette indices.  Same sprite
 * pipeline for plants, buildings, animals, items.
 *
 * The 4-colour palette per kind is derived from a hash of (axiom +
 * rule + iters + angle) — same rules → same palette, mutate the
 * rules and the palette mutates with them.  Category sets the base
 * RGB family. */
/* 4 categories — plant, building, animal, item.  All instances of a
 * category share its category-level behaviour (height, HP, blocking)
 * but every instance gets its own sprite via a 4-archetype L-system
 * library + variant decoder, and its own 4-colour palette derived
 * from a hash of (cat, idx).  256 unique entity variants total. */
enum {
    RC_NONE = 0,
    RC_PLANT = 1,
    RC_BUILDING,
    RC_ANIMAL,
    RC_ITEM,
    RC_N
};

#define RPG_CAT_VARIANTS 64

struct EntityCategory {
    char cat;
    unsigned char height;
    unsigned char hp;          /* base HP for animals; 0 otherwise */
    unsigned char blocking;
    const char *name;
    /* Four L-system archetypes per category.  idx 0..63 picks an
     * archetype via (idx & 3); the upper bits perturb iters / angle
     * / palette so 64 variants spread across 4 archetypes. */
    const char *axioms[4];
    const char *rules[4];
};

static const struct EntityCategory rpg_cats[RC_N] = {
    {0, 0, 0, 0, "none", {"","","",""}, {"","","",""}},
    {'P', 5, 0, 1, "plant",
        {"F", "F", "F", "F"},
        {"FF+[+F-F-F]-[-F+F+F]",
         "F[+F]F[-F]F",
         "F[+F][-F]F[+F][-F]F",
         "F[+F]F[-F]F[+F]"}},
    {'B', 4, 0, 1, "building",
        {"F", "F", "F", "F"},
        {"F+F+F-F-F+F+F",
         "F+F-F-F+F+F+F-F",
         "F+F+F+F",
         "F+F-F+F-F+F"}},
    {'A', 2, 4, 0, "animal",
        {"F", "F", "F", "F"},
        {"F[+F]F[-F]",
         "F+F-F",
         "F-F+F-F",
         "F+F-F+F"}},
    {'I', 1, 0, 0, "item",
        {"F+F+F+F", "F+F+F+F+F+F", "F", "F"},
        {"F", "F", "F[+F][-F]F", "F+F-F+F-F"}},
};

/* Decode the (archetype, iters, angle_steps) tuple from a variant
 * idx in 0..63.  Five bits go into geometry (4 arch × 4 iters × 2
 * angle), the top bit perturbs only the palette via the hash. */
static void rpg_variant_decode(int idx,
                               int *arch, int *iters, int *angle) {
    *arch  = idx & 3;                  /* 0..3 */
    *iters = 1 + ((idx >> 2) & 3);     /* 1..4 */
    *angle = 1 + ((idx >> 4) & 1);     /* 1..2 */
}

/* Per-(cat, variant) sprite cache: rasterised+downsampled into a
 * height×3 grid of palette indices + 4-colour palette derived from
 * the rule hash.  Built lazily on first encounter. */
#define RPG_SPRITE_W 3
#define RPG_SPRITE_H_MAX 5
static unsigned char rpg_sprite[RC_N][RPG_CAT_VARIANTS]
                                [RPG_SPRITE_H_MAX * RPG_SPRITE_W];
static unsigned char rpg_sprite_pal[RC_N][RPG_CAT_VARIANTS][4];
static unsigned char rpg_sprite_done[RC_N][RPG_CAT_VARIANTS];

/* Player state.  inv[idx] counts of item-variant idx (only items
 * track here); inv_count is the running total for status-bar
 * display.  bend_skill tracks the player's mastery of each terrain
 * (0..9), levelling up with every successful bend. */
struct RpgPlayer {
    int hp, max_hp;
    int mp, max_mp;
    unsigned char inv[RPG_CAT_VARIANTS];
    int inv_count;
    unsigned char bend_skill[4];     /* per-terrain skill (0..9) */
    unsigned char cat_bend  [4];     /* per-category bend counter (palette salt) */
};
static struct RpgPlayer rpg_player;


/* ── L-system sprite pipeline ────────────────────────────────────
 *
 * Each entity kind's L-system is expanded once at startup into a
 * point cloud (one Pt per F-step), the cloud is bbox-fit into a
 * (height × 3) grid of buckets, hits per bucket are counted, and
 * the count is thresholded to a palette index 0..3.  The palette
 * itself comes from a hash of the rule string (so mutations move
 * the palette in lock-step) blended with the category's base RGB.
 *
 * Buffers are static — the sprite build is one-shot and tiny. */

#define RPG_SPRITE_PT_MAX 4096
static short rpg_sp_xs[RPG_SPRITE_PT_MAX];
static short rpg_sp_ys[RPG_SPRITE_PT_MAX];
static int   rpg_sp_n;

static void rpg_sprite_walk(const char *cmds, int len, int angle_steps) {
    static const int DX[8] = { 0,  1,  1,  1,  0, -1, -1, -1};
    static const int DY[8] = {-1, -1,  0,  1,  1,  1,  0, -1};
    struct { short x, y; unsigned char dir; } stk[64];
    int sp = 0;
    int x = 0, y = 0;
    unsigned char dir = 0;       /* facing up */
    rpg_sp_n = 0;
    if (rpg_sp_n < RPG_SPRITE_PT_MAX) {
        rpg_sp_xs[rpg_sp_n] = (short)x;
        rpg_sp_ys[rpg_sp_n] = (short)y;
        rpg_sp_n++;
    }
    for (int i = 0; i < len; i++) {
        char c = cmds[i];
        if (c == 'F') {
            x += DX[dir]; y += DY[dir];
            if (rpg_sp_n < RPG_SPRITE_PT_MAX) {
                rpg_sp_xs[rpg_sp_n] = (short)x;
                rpg_sp_ys[rpg_sp_n] = (short)y;
                rpg_sp_n++;
            }
        } else if (c == '+') {
            int nd = (int)dir + angle_steps;
            dir = (unsigned char)(((nd % 8) + 8) % 8);
        } else if (c == '-') {
            int nd = (int)dir - angle_steps;
            dir = (unsigned char)(((nd % 8) + 8) % 8);
        } else if (c == '[') {
            if (sp < 64) {
                stk[sp].x = (short)x; stk[sp].y = (short)y;
                stk[sp].dir = dir; sp++;
            }
        } else if (c == ']') {
            if (sp > 0) {
                sp--;
                x = stk[sp].x; y = stk[sp].y; dir = stk[sp].dir;
            }
        }
    }
}

/* Local expansion buffers — separate from the lsys app's buffers
 * because those are defined further down the file (file-scope static
 * means no forward visibility before their definition).  Used once
 * per kind at startup; ~32 KB BSS, zero file-size impact. */
#define RPG_LSYS_BUF_BYTES 8192
static char rpg_lsys_buf_a[RPG_LSYS_BUF_BYTES];
static char rpg_lsys_buf_b[RPG_LSYS_BUF_BYTES];

/* Walk axiom → rule N times into the ping-pong buffers; returns the
 * pointer to whichever buf holds the final string and writes its
 * length to *out_len.  Truncates if the rule blows the buf. */
static const char *lsys_expand_simple(const char *axiom, const char *rule,
                                      int iters, int *out_len) {
    int alen = slen(axiom);
    if (alen >= RPG_LSYS_BUF_BYTES - 1) alen = RPG_LSYS_BUF_BYTES - 1;
    mcpy(rpg_lsys_buf_a, axiom, alen);
    rpg_lsys_buf_a[alen] = 0;
    char *src = rpg_lsys_buf_a;
    char *dst = rpg_lsys_buf_b;
    int cur = alen;
    int rule_len = slen(rule);
    for (int it = 0; it < iters; it++) {
        int dn = 0; int overflow = 0;
        for (int i = 0; i < cur; i++) {
            char c = src[i];
            if (c == 'F') {
                if (dn + rule_len >= RPG_LSYS_BUF_BYTES - 1) { overflow = 1; break; }
                mcpy(dst + dn, rule, rule_len);
                dn += rule_len;
            } else {
                if (dn + 1 >= RPG_LSYS_BUF_BYTES - 1) { overflow = 1; break; }
                dst[dn++] = c;
            }
        }
        dst[dn] = 0;
        cur = dn;
        char *t = src; src = dst; dst = t;
        if (overflow) break;
    }
    *out_len = cur;
    return src;
}

/* FNV-1a string hash. */
static unsigned long rpg_str_hash(unsigned long h, const char *s) {
    while (*s) {
        h ^= (unsigned char)*s++;
        h *= 0x100000001b3UL;
    }
    return h;
}

/* Category base RGB — the palette is intensity variations of this. */
struct RpgCatBase { unsigned char r, g, b; };
static const struct RpgCatBase rpg_cat_base_table[] = {
    {0,   0,   0},   /* unused */
    { 30, 130,  50},   /* P plant   — green */
    {180, 150, 110},   /* B building — tan   */
    {200,  90,  60},   /* A animal   — warm  */
    {220, 200,  80},   /* I item     — gold  */
};
static int rpg_cat_index(char cat) {
    if (cat == 'P') return 1;
    if (cat == 'B') return 2;
    if (cat == 'A') return 3;
    if (cat == 'I') return 4;
    return 1;
}

static int clamp255(int v) { return v < 0 ? 0 : (v > 255 ? 255 : v); }

/* Build the rasterised sprite + palette for one (cat, idx) variant.
 * Lazy: idempotent — sprite_done flag short-circuits repeat calls. */
static void rpg_sprite_build(int cat, int idx) {
    if (cat <= 0 || cat >= RC_N) return;
    if (idx < 0 || idx >= RPG_CAT_VARIANTS) return;
    if (rpg_sprite_done[cat][idx]) return;

    const struct EntityCategory *ec = &rpg_cats[cat];
    int arch, iters, angle;
    rpg_variant_decode(idx, &arch, &iters, &angle);
    const char *axiom = ec->axioms[arch];
    const char *rule  = ec->rules [arch];
    if (!axiom || !*axiom) { rpg_sprite_done[cat][idx] = 1; return; }

    int len = 0;
    const char *cmds = lsys_expand_simple(axiom, rule && *rule ? rule : "F",
                                          iters, &len);
    rpg_sprite_walk(cmds, len, angle);

    int h = ec->height;
    if (h < 1) h = 1;
    if (h > RPG_SPRITE_H_MAX) h = RPG_SPRITE_H_MAX;

    /* Bbox of the point cloud. */
    int minx = rpg_sp_xs[0], maxx = rpg_sp_xs[0];
    int miny = rpg_sp_ys[0], maxy = rpg_sp_ys[0];
    for (int i = 1; i < rpg_sp_n; i++) {
        if (rpg_sp_xs[i] < minx) minx = rpg_sp_xs[i];
        if (rpg_sp_xs[i] > maxx) maxx = rpg_sp_xs[i];
        if (rpg_sp_ys[i] < miny) miny = rpg_sp_ys[i];
        if (rpg_sp_ys[i] > maxy) maxy = rpg_sp_ys[i];
    }
    int bw = maxx - minx + 1, bh = maxy - miny + 1;
    if (bw < 1) bw = 1; if (bh < 1) bh = 1;

    unsigned counts[RPG_SPRITE_W * RPG_SPRITE_H_MAX] = {0};
    for (int i = 0; i < rpg_sp_n; i++) {
        int x = rpg_sp_xs[i] - minx;
        int y = rpg_sp_ys[i] - miny;
        int bx = (x * RPG_SPRITE_W) / bw;
        int by = (y * h) / bh;
        if (bx >= RPG_SPRITE_W) bx = RPG_SPRITE_W - 1;
        if (by >= h)            by = h - 1;
        counts[by * RPG_SPRITE_W + bx]++;
    }
    unsigned max_hits = 1;
    for (int i = 0; i < RPG_SPRITE_W * h; i++)
        if (counts[i] > max_hits) max_hits = counts[i];
    unsigned char *out = rpg_sprite[cat][idx];
    for (int i = 0; i < RPG_SPRITE_W * RPG_SPRITE_H_MAX; i++) out[i] = 0;
    for (int i = 0; i < RPG_SPRITE_W * h; i++) {
        unsigned c = counts[i];
        int p;
        if (c == 0)                     p = 0;
        else if (c * 3 <= max_hits)     p = 1;
        else if (c * 3 <= 2 * max_hits) p = 2;
        else                            p = 3;
        out[i] = (unsigned char)p;
    }

    /* Hash (cat, idx, archetype) → palette perturbation.  Variants
     * 32..63 (top bit set) give a *different palette* over the same
     * geometry — they're the colour-only mutations. */
    unsigned long hh = 0xcbf29ce484222325UL;
    hh = rpg_str_hash(hh, axiom);
    hh = rpg_str_hash(hh, rule);
    hh ^= ((unsigned long)cat * 0x9e3779b97f4a7c15UL);
    hh ^= ((unsigned long)idx * 0xc2b2ae3d27d4eb4fUL);
    /* Per-category bend counter — bumped by an entity bender, mixed
     * in as a salt so the affected category recolours on next render. */
    if (cat >= RC_PLANT && cat < RC_N)
        hh ^= (unsigned long)rpg_player.cat_bend[cat - RC_PLANT]
            * 0xff51afd7ed558ccdUL;
    int dr = (int)((hh      ) & 0x3f) - 32;
    int dg = (int)((hh >>  8) & 0x3f) - 32;
    int db = (int)((hh >> 16) & 0x3f) - 32;
    const struct RpgCatBase *cb = &rpg_cat_base_table[rpg_cat_index(ec->cat)];
    int br = (int)cb->r + dr;
    int bg = (int)cb->g + dg;
    int bb = (int)cb->b + db;
    unsigned char *pal = rpg_sprite_pal[cat][idx];
    pal[0] = 0;
    pal[1] = (unsigned char)rpg_rgb_to_xterm256(
        clamp255(br + (255 - br) * 55 / 100),
        clamp255(bg + (255 - bg) * 55 / 100),
        clamp255(bb + (255 - bb) * 55 / 100));
    pal[2] = (unsigned char)rpg_rgb_to_xterm256(
        clamp255(br), clamp255(bg), clamp255(bb));
    pal[3] = (unsigned char)rpg_rgb_to_xterm256(
        clamp255(br * 45 / 100),
        clamp255(bg * 45 / 100),
        clamp255(bb * 45 / 100));
    rpg_sprite_done[cat][idx] = 1;
}

static void rpg_sprites_init(void) {
    /* No eager build — sprites build on first encounter, which keeps
     * startup snappy and only spends cycles on what the player sees. */
    mset(rpg_sprite_done, 0, sizeof rpg_sprite_done);
}


/* 64×64 hex stepper, mirroring hx_step_grid but sized for the
 * world map.  Reuses HX_DY/DXE/DXO + hx_g_get + hx_sit_idx so the
 * generated terrain matches what hxhnt would produce on a bigger
 * canvas. */
static void rpg_step_grid(const unsigned char *g,
                          const unsigned char *in,
                          unsigned char *out) {
    for (int y = 0; y < RPG_MAP_H; y++) {
        const int *dx = (y & 1) ? HX_DXO : HX_DXE;
        for (int x = 0; x < RPG_MAP_W; x++) {
            int self = in[y * RPG_MAP_W + x];
            int n[6];
            for (int k = 0; k < 6; k++) {
                int yy = y + HX_DY[k];
                int xx = x + dx[k];
                n[k] = (yy >= 0 && yy < RPG_MAP_H
                     && xx >= 0 && xx < RPG_MAP_W)
                     ? in[yy * RPG_MAP_W + xx] : 0;
            }
            out[y * RPG_MAP_W + x] = (unsigned char)
                hx_g_get(g, hx_sit_idx(self, n));
        }
    }
}

/* Hash the full level-stack of world coordinates into a deterministic
 * RNG seed.  Identical coords always rehydrate the same overworld. */
static unsigned long rpg_world_seed(void) {
    unsigned long h = 0xcbf29ce484222325UL;
    for (int i = 0; i < RPG_WORLD_LEVELS; i++) {
        h ^= (unsigned long)(unsigned int)rpg_world_pos[i][0];
        h *= 0x100000001b3UL;
        h ^= (unsigned long)(unsigned int)rpg_world_pos[i][1];
        h *= 0x100000001b3UL;
    }
    return h | 1ULL;
}

/* Bubble (dx, dy) up the position stack with carry on 64-cell wrap.
 * dx, dy are typically -1, 0, or +1 (one overworld cell at a time). */
static void rpg_world_advance(int dx, int dy) {
    int cx = dx, cy = dy;
    for (int level = 0; level < RPG_WORLD_LEVELS && (cx || cy); level++) {
        rpg_world_pos[level][0] += cx;
        rpg_world_pos[level][1] += cy;
        cx = cy = 0;
        if (rpg_world_pos[level][0] < 0)   { rpg_world_pos[level][0] += 64; cx = -1; }
        if (rpg_world_pos[level][0] >= 64) { rpg_world_pos[level][0] -= 64; cx =  1; }
        if (rpg_world_pos[level][1] < 0)   { rpg_world_pos[level][1] += 64; cy = -1; }
        if (rpg_world_pos[level][1] >= 64) { rpg_world_pos[level][1] -= 64; cy =  1; }
    }
}

/* Compute the world seed of a neighboring overworld at (dx, dy)
 * relative to the player's current overworld.  Carries up the
 * world-position stack temporarily and restores it. */
static unsigned long rpg_neighbor_seed(int dx, int dy) {
    int snap[RPG_WORLD_LEVELS][2];
    mcpy((unsigned char *)snap, (unsigned char *)rpg_world_pos, sizeof snap);
    rpg_world_advance(dx, dy);
    unsigned long s = rpg_world_seed();
    mcpy((unsigned char *)rpg_world_pos, (unsigned char *)snap, sizeof snap);
    return s;
}

static void rpg_init_map(const unsigned char *ruleset) {
    /* office41 — populate the 192×192 mosaic by running 9 independent
     * 64×64 sub-overworld CAs.  Each sub uses its own world seed
     * (current ± neighbor offset) so neighbors are deterministic
     * across re-loads.  rpg_buf and rpg_inner_a are clobbered as
     * ping-pong scratch; both are re-initialised on first frame. */
    if (!hx_rng_state) {
        unsigned long h, l;
        __asm__ volatile ("rdtsc" : "=d"(h), "=a"(l));
        hx_rng_state = ((unsigned long long)h << 32) | l | 1ULL;
    }
    for (int cy = -1; cy <= 1; cy++) {
        for (int cx = -1; cx <= 1; cx++) {
            hx_rng_state = rpg_neighbor_seed(cx, cy);
            for (int i = 0; i < RPG_MAP_W * RPG_MAP_H; i++)
                rpg_buf[i] = (unsigned char)(hx_rand() & 3);
            for (int t = 0; t < RPG_GEN_STEPS; t++) {
                rpg_step_grid(ruleset, rpg_buf, rpg_inner_a);
                mcpy(rpg_buf, rpg_inner_a, RPG_MAP_W * RPG_MAP_H);
            }
            int sub_x = (cx + 1) * RPG_MAP_W;
            int sub_y = (cy + 1) * RPG_MAP_H;
            for (int y = 0; y < RPG_MAP_H; y++) {
                mcpy(&rpg_map[(sub_y + y) * RPG_TILE_W + sub_x],
                     &rpg_buf[y * RPG_MAP_W],
                     RPG_MAP_W);
            }
        }
    }
}

/* Pick an entity category for a cell, biased by its terrain type.
 * Returns RC_NONE..RC_ITEM.  Terrain meanings:
 *   0 rock   buildings + items, no plants
 *   1 sand   plants + animals
 *   2 soil   all kinds
 *   3 water  just animals */
static int rpg_cat_for(int colour, unsigned r) {
    switch (colour & 3) {
    case 0:
        if (r <  10) return RC_BUILDING;
        if (r <  18) return RC_BUILDING;
        if (r <  22) return RC_ITEM;
        if (r <  28) return RC_ITEM;
        return RC_NONE;
    case 1:
        if (r <  15) return RC_PLANT;
        if (r <  30) return RC_PLANT;
        if (r <  38) return RC_ANIMAL;
        if (r <  43) return RC_ANIMAL;
        return RC_NONE;
    case 2:
        if (r <  12) return RC_PLANT;
        if (r <  22) return RC_PLANT;
        if (r <  28) return RC_BUILDING;
        if (r <  32) return RC_BUILDING;
        if (r <  40) return RC_ANIMAL;
        if (r <  46) return RC_ANIMAL;
        if (r <  50) return RC_ITEM;
        return RC_NONE;
    case 3:
        if (r <  12) return RC_ANIMAL;
        return RC_NONE;
    }
    return RC_NONE;
}

static void rpg_init_entities(int spawn_x, int spawn_y) {
    mset(rpg_cat_at, 0, sizeof rpg_cat_at);
    mset(rpg_idx_at, 0, sizeof rpg_idx_at);
    mset(rpg_hp_at,  0, sizeof rpg_hp_at);
    mset(rpg_npc_at, 0, sizeof rpg_npc_at);
    mset(rpg_path_step, 0, sizeof rpg_path_step);
    mset(rpg_path_id,   0, sizeof rpg_path_id);
    /* office41 — seed entities per-sub-overworld so each chunk's
     * crowd is deterministic and stable across reloads. */
    for (int cy = -1; cy <= 1; cy++) {
        for (int cx = -1; cx <= 1; cx++) {
            hx_rng_state = rpg_neighbor_seed(cx, cy)
                         ^ 0xa5a5a5a5a5a5a5a5UL;
            int sub_x = (cx + 1) * RPG_MAP_W;
            int sub_y = (cy + 1) * RPG_MAP_H;
            for (int yy = 0; yy < RPG_MAP_H; yy++) {
                for (int xx = 0; xx < RPG_MAP_W; xx++) {
                    int gidx = (sub_y + yy) * RPG_TILE_W + (sub_x + xx);
                    int c = rpg_map[gidx];
                    unsigned r = hx_rand() & 0xff;
                    int cat = rpg_cat_for(c, r);
                    rpg_cat_at[gidx] = (unsigned char)cat;
                    if (cat) {
                        int idx = (int)(hx_rand() & (RPG_CAT_VARIANTS - 1));
                        rpg_idx_at[gidx] = (unsigned char)idx;
                        if (rpg_cats[cat].cat == 'A') rpg_hp_at[gidx] = rpg_cats[cat].hp;
                    }
                    if (!cat && (c == 1 || c == 2)) {
                        unsigned q = hx_rand();
                        if ((q & 31) == 0) {
                            unsigned char b = (unsigned char)((q >> 8) & 0xff);
                            if (!b) b = 0xa5;
                            rpg_npc_at[gidx] = b;
                        }
                    }
                }
            }
        }
    }
    /* Clear a 3×3 around spawn so the player isn't boxed in. */
    for (int dy = -1; dy <= 1; dy++) for (int dx = -1; dx <= 1; dx++) {
        int nx = spawn_x + dx, ny = spawn_y + dy;
        if (nx >= 0 && nx < RPG_TILE_W && ny >= 0 && ny < RPG_TILE_H) {
            rpg_cat_at[ny * RPG_TILE_W + nx] = 0;
            rpg_npc_at[ny * RPG_TILE_W + nx] = 0;
        }
    }
}

static void rpg_player_init(void) {
    rpg_player.max_hp = 20;
    rpg_player.hp     = 20;
    rpg_player.max_mp = 30;       /* enough for a few bends out of the gate */
    rpg_player.mp     = 30;
    mset(rpg_player.inv, 0, sizeof rpg_player.inv);
    rpg_player.inv_count = 0;
    mset(rpg_player.bend_skill, 0, sizeof rpg_player.bend_skill);
    mset(rpg_player.cat_bend,   0, sizeof rpg_player.cat_bend);
}

/* Re-seed the RNG from the world coord stack and regenerate the
 * 3×3 mosaic + entities.  spawn (x, y) is in mosaic coords (0..192)
 * and determines the 3×3 clear-zone around the player's entry point. */
static void rpg_load_overworld(int spawn_x, int spawn_y) {
    rpg_init_map(hx_seed_genome);
    rpg_init_entities(spawn_x, spawn_y);
    rpg_genome_live_cache = -1;
    mset(rpg_cell_done, 0, sizeof rpg_cell_done);
    rpg_anim_reset();
}

/* Shift the loaded mosaic by (dx, dy) ∈ {-1, 0, 1}² so the player's
 * sub-overworld becomes the central one again.  After the shift,
 * the player's own (x, y) stays where they walked to; only the
 * world-pos stack and the underlying mosaic content advance. */
static void rpg_shift_mosaic(int dx, int dy, int spawn_x, int spawn_y) {
    if (dx == 0 && dy == 0) return;
    rpg_world_advance(dx, dy);
    rpg_load_overworld(spawn_x, spawn_y);
}

/* office41 — generate a procedural closed-loop path of hex directions.
 * Pick three counts a, b, c in [0..10]; emit a copies of E paired with
 * a of W, b of NE with b of SW, c of NW with c of SE; Fisher-Yates
 * shuffle the resulting 2*(a+b+c) entries.  Opposite-pair balance
 * guarantees closure regardless of shuffle.  Returns the path length. */
static int rpg_path_build(unsigned long seed, unsigned char *out) {
    unsigned long s = seed | 1ULL;
    s = s * 6364136223846793005UL + 1442695040888963407UL;
    int a = (int)((s >> 33) % 11);
    s = s * 6364136223846793005UL + 1442695040888963407UL;
    int b = (int)((s >> 33) % 11);
    s = s * 6364136223846793005UL + 1442695040888963407UL;
    int c = (int)((s >> 33) % 11);
    int n = 2 * (a + b + c);
    if (n > RPG_PATH_MAX) n = RPG_PATH_MAX;
    int p = 0;
    for (int i = 0; i < a && p < n; i++) out[p++] = 0;   /* E  */
    for (int i = 0; i < a && p < n; i++) out[p++] = 3;   /* W  */
    for (int i = 0; i < b && p < n; i++) out[p++] = 1;   /* NE */
    for (int i = 0; i < b && p < n; i++) out[p++] = 4;   /* SW */
    for (int i = 0; i < c && p < n; i++) out[p++] = 2;   /* NW */
    for (int i = 0; i < c && p < n; i++) out[p++] = 5;   /* SE */
    n = p;
    for (int i = n - 1; i > 0; i--) {
        s = s * 6364136223846793005UL + 1442695040888963407UL;
        int j = (int)((s >> 33) % (unsigned)(i + 1));
        unsigned char t = out[i]; out[i] = out[j]; out[j] = t;
    }
    return n;
}

/* Hex direction 0..5 → (dx, dy) in offset coords.  Mirrors the
 * 'd e w a z x' player keys: 0=E, 1=NE, 2=NW, 3=W, 4=SW, 5=SE. */
static void rpg_path_dxdy(int dir, int y, int *dx, int *dy) {
    int odd = y & 1;
    *dx = 0; *dy = 0;
    switch (dir) {
    case 0: *dx =  1;                     break;
    case 1: *dx = odd ?  1 :  0; *dy = -1; break;
    case 2: *dx = odd ?  0 : -1; *dy = -1; break;
    case 3: *dx = -1;                     break;
    case 4: *dx = odd ?  0 : -1; *dy =  1; break;
    case 5: *dx = odd ?  1 :  0; *dy =  1; break;
    }
}

/* Advance every animal/NPC by one path step.  Stalls (does not
 * advance the step counter) if the destination is blocked; that
 * preserves loop closure across temporary obstructions.  Iterates
 * with a "moved this tick" bitmap so an entity can't be processed
 * twice when it walks into a yet-unvisited cell. */
static void rpg_path_tick(int player_x, int player_y) {
    static unsigned char moved[RPG_TILE_W * RPG_TILE_H];
    mset(moved, 0, sizeof moved);
    unsigned long wseed = rpg_world_seed();
    for (int y = 0; y < RPG_TILE_H; y++) {
        for (int x = 0; x < RPG_TILE_W; x++) {
            int idx = y * RPG_TILE_W + x;
            if (moved[idx]) continue;
            int has_npc    = rpg_npc_at[idx] != 0;
            int has_animal = rpg_cat_at[idx] == RC_ANIMAL;
            if (!has_npc && !has_animal) continue;
            unsigned long pseed = wseed
                ^ ((unsigned long)idx           * 0x9e3779b97f4a7c15UL)
                ^ ((unsigned long)rpg_path_id[idx] * 0xbf58476d1ce4e5b9UL);
            unsigned char path[RPG_PATH_MAX];
            int n = rpg_path_build(pseed, path);
            if (n == 0) {
                rpg_path_id[idx]++;
                continue;
            }
            int step = rpg_path_step[idx] % n;
            int dx, dy;
            rpg_path_dxdy(path[step], y, &dx, &dy);
            int nx = x + dx, ny = y + dy;
            if (nx < 0 || nx >= RPG_TILE_W || ny < 0 || ny >= RPG_TILE_H) continue;
            int nidx = ny * RPG_TILE_W + nx;
            if (nx == player_x && ny == player_y) continue;
            if (rpg_cat_at[nidx] || rpg_npc_at[nidx]) continue;
            if (has_npc) {
                rpg_npc_at[nidx] = rpg_npc_at[idx];
                rpg_npc_at[idx] = 0;
            } else {
                rpg_cat_at[nidx] = rpg_cat_at[idx];
                rpg_idx_at[nidx] = rpg_idx_at[idx];
                rpg_hp_at [nidx] = rpg_hp_at [idx];
                rpg_cat_at[idx] = 0;
                rpg_idx_at[idx] = 0;
                rpg_hp_at [idx] = 0;
            }
            int nstep = (step + 1) % n;
            unsigned char npid = rpg_path_id[idx];
            if (nstep == 0) npid++;
            rpg_path_step[idx] = 0;
            rpg_path_id  [idx] = 0;
            rpg_path_step[nidx] = (unsigned char)nstep;
            rpg_path_id  [nidx] = npid;
            moved[nidx] = 1;
        }
    }
}

/* Render the 8×8 window in two passes:
 *   1. terrain — each cell paints its own 8×3 inner-CA sample with a
 *      per-cell 4-colour palette diverged from the terrain base RGB.
 *   2. entities — north→south so a tall plant or tower in row vy can
 *      paint upward into already-drawn rows vy-1, vy-2 (occlusion).
 *      Sprites are 3 cols wide × height rows tall, ' ' is transparent.
 * The player is drawn dead-last so nothing covers them. */
static void rpg_render_view(int px, int py) {
    int origin_y = 1;
    int origin_x = (SCREEN_W - (RPG_VIS_W * RPG_CELL_W + RPG_CELL_W / 2)) / 2;
    if (origin_x < 0) origin_x = 0;
    int max_rows = (SCREEN_H - origin_y) / RPG_CELL_H;
    int rows_v = max_rows < RPG_VIS_H ? max_rows : RPG_VIS_H;

    /* Paint the cell-region pure black before laying cells.  Without
     * this, paint_desktop's teal showed through the staggered hex
     * gaps (the 2-col x-shift on each cell's middle line, the dead
     * col on odd rows' left edge, etc.) and clashed with off-map
     * cells which paint black — at map edges that mix looked
     * garbled.  Now gaps + off-map both read as void. */
    sgrbg(0);
    for (int r = origin_y; r < origin_y + rows_v * RPG_CELL_H; r++) {
        cup(0, r);
        blanks(SCREEN_W);
    }

    /* Pass 1: terrain — per-cell inner-CA sample + per-cell palette. */
    for (int vy = 0; vy < rows_v; vy++) {
        int row_offset = (vy & 1) ? (RPG_CELL_W / 2) : 0;
        for (int vx = 0; vx < RPG_VIS_W; vx++) {
            int wx = px + vx - RPG_PLAYER_VX;
            int wy = py + vy - RPG_PLAYER_VY;
            int in_map = (wx >= 0 && wx < RPG_TILE_W &&
                          wy >= 0 && wy < RPG_TILE_H);
            int base_x = origin_x + row_offset + vx * RPG_CELL_W;
            int base_y = origin_y + vy * RPG_CELL_H;
            if (in_map) {
                int idx = wy * RPG_TILE_W + wx;
                rpg_compute_cell(wx, wy);
                unsigned char *sample = &rpg_cell_sample[idx * 24];
                unsigned char *cpal   = &rpg_cell_pal   [idx * 4];
                for (int line = 0; line < RPG_CELL_H; line++) {
                    int line_x = base_x + (line == 1 ? RPG_MID_SHIFT : 0);
                    cup(line_x, base_y + line);
                    for (int col = 0; col < RPG_CELL_W; col++) {
                        unsigned char c = sample[line * RPG_CELL_W + col] & 3;
                        sgrbg(cpal[c]);
                        fbs(" ");
                    }
                }
            } else {
                for (int line = 0; line < RPG_CELL_H; line++) {
                    int line_x = base_x + (line == 1 ? RPG_MID_SHIFT : 0);
                    cup(line_x, base_y + line);
                    sgrbg(0);
                    blanks(RPG_CELL_W);
                }
            }
        }
    }

    /* Pass 2: entity sprites — L-system rasterised + downsampled into
     * a (height × 3) grid of palette indices.  index 0 is transparent
     * (terrain shows through), 1/2/3 paint as full-cell coloured bg
     * blocks.  Iteration order is north→south so southern (closer)
     * entities paint over northern (farther) ones. */
    for (int vy = 0; vy < rows_v; vy++) {
        int row_offset = (vy & 1) ? (RPG_CELL_W / 2) : 0;
        for (int vx = 0; vx < RPG_VIS_W; vx++) {
            int wx = px + vx - RPG_PLAYER_VX;
            int wy = py + vy - RPG_PLAYER_VY;
            if (wx < 0 || wx >= RPG_TILE_W || wy < 0 || wy >= RPG_TILE_H) continue;
            int idx = wy * RPG_TILE_W + wx;
            int cat = rpg_cat_at[idx];
            if (!cat) continue;
            int vidx = rpg_idx_at[idx];
            rpg_sprite_build(cat, vidx);
            const struct EntityCategory *ec = &rpg_cats[cat];
            const unsigned char *sprite = rpg_sprite[cat][vidx];
            const unsigned char *spal   = rpg_sprite_pal[cat][vidx];
            int base_x = origin_x + row_offset + vx * RPG_CELL_W;
            int base_y = origin_y + vy * RPG_CELL_H;
            int art_x = base_x + (RPG_CELL_W - RPG_SPRITE_W) / 2;
            int h = ec->height;
            for (int li = 0; li < h; li++) {
                int art_row = h - 1 - li;       /* sprite row 0 = top */
                int sy = base_y + 2 - li;
                if (sy < origin_y || sy >= origin_y + rows_v * RPG_CELL_H) continue;
                for (int col = 0; col < RPG_SPRITE_W; col++) {
                    unsigned char pidx = sprite[art_row * RPG_SPRITE_W + col];
                    if (pidx == 0) continue;     /* transparent */
                    int sx = art_x + col;
                    if (sx < 0 || sx >= SCREEN_W) continue;
                    cup(sx, sy);
                    sgrbg(spal[pidx]);
                    fbs(" ");
                }
            }
        }
    }

    /* Pass 3: NPCs — same 1×2 head/body shape as the player, with
     * per-NPC colour pulled from rpg_npc_pal via the encoded byte's
     * nibbles.  Painted after L-system entities so a tall plant in
     * the same row doesn't bury them, and before the player so the
     * player always wins z-order on the player's own cell. */
    for (int vy = 0; vy < rows_v; vy++) {
        int row_offset_n = (vy & 1) ? (RPG_CELL_W / 2) : 0;
        for (int vx = 0; vx < RPG_VIS_W; vx++) {
            int wx = px + vx - RPG_PLAYER_VX;
            int wy = py + vy - RPG_PLAYER_VY;
            if (wx < 0 || wx >= RPG_TILE_W || wy < 0 || wy >= RPG_TILE_H) continue;
            int idx = wy * RPG_TILE_W + wx;
            unsigned char b = rpg_npc_at[idx];
            if (!b) continue;
            int sx = origin_x + row_offset_n + vx * RPG_CELL_W + RPG_CELL_W / 2;
            int sy_top = origin_y + vy * RPG_CELL_H;
            int head = rpg_npc_pal[(b >> 4) & 0xf];
            int body = rpg_npc_pal[ b       & 0xf];
            cup(sx, sy_top);
            sgrbg(head);
            fbs(" ");
            cup(sx, sy_top + 1);
            sgrbg(body);
            fbs(" ");
        }
    }

    /* 1×2 player sprite: head row + body row in distinct colours
     * deliberately outside the terrain RGB families (water/grass/
     * dirt/lava all have G < ~245 and either low R or low B), so the
     * sprite reads as a tiny figure standing on whatever the cell
     * texture happens to be.  Bright yellow (226) head over bright
     * magenta (201) body — neither colour appears in any per-cell
     * palette regardless of how the random RGB offsets land. */
    int row_offset = (RPG_PLAYER_VY & 1) ? (RPG_CELL_W / 2) : 0;
    int sprite_x = origin_x + row_offset + RPG_PLAYER_VX * RPG_CELL_W
                 + RPG_CELL_W / 2;
    int sprite_y = origin_y + RPG_PLAYER_VY * RPG_CELL_H;   /* top of cell */
    cup(sprite_x, sprite_y);
    sgrbg(226);
    fbs(" ");
    cup(sprite_x, sprite_y + 1);
    sgrbg(201);
    fbs(" ");
    sgr0();
}

/* Hex-aware player move with entity interactions.
 *
 *   • item     →  pick up; entity removed from map; player advances.
 *   • animal   →  melee.  Player rolls d4 vs animal HP; animal hits
 *                 back for d3 unless dropped.  Player stays put.
 *   • building →  blocked.
 *   • plant    →  blocked unless small bush (height ≤ 2).
 *
 * Returns 1 if the player actually moved, 0 otherwise.  Writes a
 * one-line action message into *msg (caller-sized). */
static int rpg_move(int *px, int *py, char c, char *msg) {
    int x = *px, y = *py, odd = y & 1;
    int nx = x, ny = y;
    switch (c) {
    case 'a': nx = x - 1;                              break;
    case 'd': nx = x + 1;                              break;
    case 'w': ny = y - 1; nx = x + (odd ? 0 : -1);     break;
    case 'e': ny = y - 1; nx = x + (odd ? 1 : 0);      break;
    case 'z': ny = y + 1; nx = x + (odd ? 0 : -1);     break;
    case 'x':                                                      /* canonical SE, matches garden */
    case 'c': ny = y + 1; nx = x + (odd ? 1 : 0);      break;      /* 'c' kept as legacy alias */
    default:  return 0;
    }
    if (nx < 0 || nx >= RPG_TILE_W || ny < 0 || ny >= RPG_TILE_H) {
        return 0;   /* shouldn't happen — mosaic re-centers before edge */
    }
    int idx = ny * RPG_TILE_W + nx;
    if (rpg_npc_at[idx]) {
        msg[sapp(msg, 0, "npc: hello, traveller")] = 0;
        return 0;
    }
    int cat = rpg_cat_at[idx];
    if (cat) {
        const struct EntityCategory *ec = &rpg_cats[cat];
        int vidx = rpg_idx_at[idx];
        if (ec->cat == 'I') {
            rpg_player.inv[vidx]++;
            rpg_player.inv_count++;
            rpg_cat_at[idx] = 0;
            int n = sapp(msg, 0, "picked up ");
            n = sapp(msg, n, ec->name);
            msg[n] = 0;
            *px = nx; *py = ny;
            return 1;
        }
        if (ec->cat == 'A') {
            int dmg_e = (int)(hx_rand() % 4) + 1;
            int dmg_p = (int)(hx_rand() % 3) + 1;
            int hp = rpg_hp_at[idx];
            hp = (hp > dmg_e) ? hp - dmg_e : 0;
            rpg_hp_at[idx] = (unsigned char)hp;
            int n = sapp(msg, 0, "hit ");
            n = sapp(msg, n, ec->name);
            n = sapp(msg, n, " for ");
            n += utoa((unsigned)dmg_e, msg + n);
            if (hp == 0) {
                rpg_cat_at[idx] = 0;
                n = sapp(msg, n, "; killed!");
            } else {
                rpg_player.hp -= dmg_p;
                if (rpg_player.hp < 0) rpg_player.hp = 0;
                n = sapp(msg, n, "; took ");
                n += utoa((unsigned)dmg_p, msg + n);
            }
            msg[n] = 0;
            return 0;
        }
        if (ec->blocking) {
            int n = sapp(msg, 0, "blocked by ");
            n = sapp(msg, n, ec->name);
            msg[n] = 0;
            return 0;
        }
    }
    *px = nx; *py = ny;
    return 1;
}

/* Cast the zap spell: nearest animal in 3-hex Manhattan range eats
 * 6 damage for 3 MP.  Manhattan in offset coords is a cheap proxy —
 * good enough for an out-of-range filter. */
static int rpg_cast_zap(int px, int py, char *msg) {
    if (rpg_player.mp < 3) {
        int n = sapp(msg, 0, "not enough mana");
        msg[n] = 0;
        return 0;
    }
    int best_idx = -1, best_d = 999;
    for (int dy = -3; dy <= 3; dy++) for (int dx = -3; dx <= 3; dx++) {
        int nx = px + dx, ny = py + dy;
        if (nx < 0 || nx >= RPG_TILE_W) continue;
        if (ny < 0 || ny >= RPG_TILE_H) continue;
        int idx = ny * RPG_TILE_W + nx;
        if (rpg_cat_at[idx] != RC_ANIMAL) continue;
        int adx = dx < 0 ? -dx : dx;
        int ady = dy < 0 ? -dy : dy;
        int d = adx + ady;
        if (d < best_d) { best_d = d; best_idx = idx; }
    }
    if (best_idx < 0) {
        int n = sapp(msg, 0, "no target in range");
        msg[n] = 0;
        return 0;
    }
    rpg_player.mp -= 3;
    int hp = rpg_hp_at[best_idx];
    int dmg = 6;
    hp = (hp > dmg) ? hp - dmg : 0;
    rpg_hp_at[best_idx] = (unsigned char)hp;
    int n = sapp(msg, 0, "zap! animal takes 6");
    if (hp == 0) {
        rpg_cat_at[best_idx] = 0;
        n = sapp(msg, n, "; killed!");
    }
    msg[n] = 0;
    return 1;
}

/* Bend terrain `t` (0..3 = rock/sand/soil/water).  Costs (5 - skill[t])
 * mana per generation, runs as many gens as the player can afford up
 * to a 10-gen cap.  The inline GA replaces the global ruleset +
 * palette with its winner; rpg's terrain-RGB derivation and inner-CA
 * caches re-key off the new state so the world repaints in the
 * evolved colours.  Each successful bend levels the skill up to 9. */
static int rpg_bend(int t, char *msg) {
    if (t < 0 || t > 3) return 0;
    int cost = 5 - (int)rpg_player.bend_skill[t];
    if (cost < 1) cost = 1;
    int gens = rpg_player.mp / cost;
    if (gens < 1) {
        msg[sapp(msg, 0, "low mana")] = 0;
        return 0;
    }
    if (gens > 10) gens = 10;
    int spend = gens * cost;
    rpg_player.mp -= spend;

    /* Inline GA — hands the screen over to hxhnt's progress paint
     * for ~gens × ~200 ms, then we resume rpg.  hx_seed_genome and
     * hx_seed_pal are updated to the winner before return. */
    unsigned int rseed = (unsigned int)(time_() ^ (long)hx_rand());
    hx_run_ga_session(20, gens, rseed);

    /* Rebuild rpg state to reflect the evolved CA. */
    rpg_terrain_rgb_refresh(hx_seed_pal);
    rpg_genome_live_cache = -1;
    mset(rpg_cell_done, 0, sizeof rpg_cell_done);
    rpg_anim_reset();

    /* Skill up. */
    if (rpg_player.bend_skill[t] < 9) rpg_player.bend_skill[t]++;

    msg[sapp(msg, 0, "bent")] = 0;
    return 1;
}

/* Entity-category benders are inlined into run_rpg's dispatch; bumping
 * cat_bend salts the sprite-palette hash so all instances of the
 * affected category recolour on next render. */

/* Inventory popup: paints a centred panel listing item kinds with
 * their counts.  Caller already drew the world view; the popup
 * overlays it.  Returns when any key is pressed. */
static void rpg_show_inventory(void) {
    int bw = 30, bh = 12;
    int bx = (SCREEN_W - bw) / 2;
    int by = (SCREEN_H - bh) / 2;
    sgrbgfg(COL_TITLE_BG, COL_TITLE_FG);
    cup(bx, by); blanks(bw);
    cup(bx + 1, by); fbs(" Inventory ");
    sgrbgfg(15, 0);
    for (int li = 1; li < bh; li++) {
        cup(bx, by + li);
        blanks(bw);
    }
    int line = 0;
    for (int k = 0; k < RPG_CAT_VARIANTS; k++) {
        if (!rpg_player.inv[k]) continue;
        if (line >= bh - 4) break;
        cup(bx + 2, by + 2 + line);
        char buf[32]; int n = 0;
        n = sapp(buf, n, "item #");
        n += utoa((unsigned)k, buf + n);
        n = sapp(buf, n, "  x");
        n += utoa((unsigned)rpg_player.inv[k], buf + n);
        buf[n] = 0;
        fbs(buf);
        line++;
    }
    if (line == 0) {
        cup(bx + 2, by + 2);
        fbs("(empty)");
    }
    cup(bx + 2, by + bh - 2);
    sgrbgfg(15, 8);
    fbs("(any key to close)");
    sgr0();
    fbflush();
    unsigned char k[8];
    read_key(k, sizeof k);
}

/* Adjust an fpm value with non-linear steps so the user can sweep
 * 1..1200 in a manageable number of presses.  delta = +1 or -1. */
static void rpg_anim_fpm_nudge(short *fpm, int delta) {
    int f = *fpm;
    if (delta > 0) {
        if      (f <    5) f += 1;
        else if (f <   30) f += 5;
        else if (f <  120) f += 10;
        else if (f <  600) f += 50;
        else if (f < 1200) f += 100;
    } else {
        if      (f >  600) f -= 100;
        else if (f >  120) f -= 50;
        else if (f >   30) f -= 10;
        else if (f >    5) f -= 5;
        else if (f >    0) f -= 1;
    }
    if (f < 0)    f = 0;
    if (f > 1200) f = 1200;
    *fpm = (short)f;
}

/* Animation-speed settings panel.  Up/down to navigate, space to
 * toggle a terrain on/off, +/- to nudge its fpm, 0 resets to its
 * default, q/k closes.  Painted directly over whatever was on
 * screen — we don't bother repainting underneath since rpg's main
 * loop will refresh on return. */
static void rpg_show_anim_settings(void) {
    int bw = 44, bh = 12;
    int bx = (SCREEN_W - bw) / 2;
    int by = (SCREEN_H - bh) / 2;
    int sel = 0;
    /* Make sure reads in here block — caller may have polling on. */
    struct ti rt = term_orig;
    rt.lflag &= ~(ICANON | ECHO);
    rt.iflag &= ~(IXON | ICRNL);
    rt.cc[6] = 1; rt.cc[5] = 0;
    io(0, TCSETS, &rt);

    while (1) {
        /* Title bar. */
        sgrbgfg(COL_TITLE_BG, COL_TITLE_FG);
        cup(bx, by); blanks(bw);
        cup(bx + 1, by); fbs(" Animation Speed (frames per minute) ");
        /* Body. */
        sgrbgfg(15, 0);
        for (int li = 1; li < bh; li++) {
            cup(bx, by + li);
            blanks(bw);
        }
        for (int t = 0; t < 4; t++) {
            int row = by + 2 + t;
            cup(bx + 2, row);
            if (t == sel) sgrbgfg(33, 15); else sgrbgfg(15, 0);
            char buf[64]; int p = 0;
            buf[p++] = (t == sel) ? '>' : ' ';
            buf[p++] = ' ';
            p = sapp(buf, p, rpg_terrain_name[t]);
            while (p < 10) buf[p++] = ' ';
            p = sapp(buf, p, rpg_terrain_anim[t].enabled ? "[on ]" : "[off]");
            buf[p++] = ' ';
            buf[p++] = ' ';
            int f = rpg_terrain_anim[t].fpm;
            /* Right-align the number to 4 cols. */
            char nb[8]; int nn = utoa((unsigned)f, nb);
            for (int s = 0; s < 4 - nn; s++) buf[p++] = ' ';
            for (int s = 0; s < nn; s++) buf[p++] = nb[s];
            p = sapp(buf, p, " fpm");
            buf[p] = 0;
            fbs(buf);
            sgrbgfg(15, 0);
            cup(bx + bw - 1, row);
            fbs(" ");
        }
        cup(bx + 2, by + bh - 3);
        sgrbgfg(15, 8);
        fbs("up/down: select   space: on/off");
        cup(bx + 2, by + bh - 2);
        fbs("+/-: rate   0: reset   q: close");
        sgr0();
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;
        if (k[0] == 'q' || k[0] == 'Q' || k[0] == 'k' || k[0] == 'K') break;
        if (k[0] == 0x1b && n == 1) break;
        if (k[0] == 0x1b && n >= 3 && k[1] == '[') {
            if (k[2] == 'A') sel = (sel + 3) & 3;          /* up */
            if (k[2] == 'B') sel = (sel + 1) & 3;          /* down */
            continue;
        }
        if (k[0] == ' ') {
            rpg_terrain_anim[sel].enabled ^= 1;
        } else if (k[0] == '+' || k[0] == '=') {
            rpg_anim_fpm_nudge(&rpg_terrain_anim[sel].fpm, +1);
        } else if (k[0] == '-' || k[0] == '_') {
            rpg_anim_fpm_nudge(&rpg_terrain_anim[sel].fpm, -1);
        } else if (k[0] == '0') {
            rpg_terrain_anim[sel].fpm =
                rpg_terrain_anim[sel].default_fpm;
        }
    }
}

static int run_rpg(int argc, char **argv) {
    (void)argc; (void)argv;
    /* Inherit the active hxhnt ruleset + palette.  hx_active_init()
     * already populated these at office startup; refresh terrain RGBs
     * + invalidate the per-cell cache here so any palette change the
     * user made in hxhnt during this session takes effect now. */
    hx_active_init();
    rpg_terrain_rgb_refresh(hx_seed_pal);
    rpg_sprites_init();
    /* Reset the level-stack to the origin overworld each rpg launch.
     * Sessions don't persist coords yet — a future fork can save the
     * stack to a .rpg file alongside hxhnt.seed so re-entry resumes
     * where the player left off. */
    mset(rpg_world_pos, 0, sizeof rpg_world_pos);

    int px = RPG_TILE_W / 2;       /* spawn at the centre of the mosaic */
    int py = RPG_TILE_H / 2;

    rpg_load_overworld(px, py);
    rpg_player_init();

    char action[80]; action[0] = 0;
    int idle_ticks = 0;
    int rows_v_cached = RPG_VIS_H;
    rpg_animating = 0;
    rpg_frame = 0;
    rpg_terrain_anim_init();

    /* Set up termios manually so we can switch between blocking and
     * polling on the 'l' toggle.  Initial state: blocking. */
    struct ti rt = term_orig;
    rt.lflag &= ~(ICANON | ECHO);
    rt.iflag &= ~(IXON | ICRNL);
    rt.cc[6] = 1; rt.cc[5] = 0;     /* VMIN=1 (blocking), VTIME=0 */
    io(0, TCSETS, &rt);
    while (1) {
        if (rpg_animating) {
            rpg_animate_step(px, py, rows_v_cached);
            rpg_frame++;
        }

        paint_desktop();
        chrome("rpg");
        rpg_render_view(px, py);

        char hint[160]; int hl = 0;
        hl = sapp(hint, hl, " HP ");
        hl += utoa((unsigned)rpg_player.hp, hint + hl); hint[hl++] = '/';
        hl += utoa((unsigned)rpg_player.max_hp, hint + hl);
        hl = sapp(hint, hl, "  MP ");
        hl += utoa((unsigned)rpg_player.mp, hint + hl); hint[hl++] = '/';
        hl += utoa((unsigned)rpg_player.max_mp, hint + hl);
        hl = sapp(hint, hl, "  inv ");
        hl += utoa((unsigned)rpg_player.inv_count, hint + hl);
        hl = sapp(hint, hl, "  | ");
        if (rpg_animating) {
            hl = sapp(hint, hl, "[live] ");
        }
        if (action[0]) {
            hl = sapp(hint, hl, action);
            hl = sapp(hint, hl, " · ");
        }
        hl = sapp(hint, hl, "wadezx=move i=inv m=zap l=live k=speeds 0-7=bend q ");
        hint[hl] = 0;
        status(hint);
        fbflush();

        if (rpg_player.hp <= 0) {
            cup(2, 0);
            sgrbgfg(196, 15);
            fbs(" YOU DIED — press any key ");
            sgr0();
            fbflush();
            unsigned char k[4]; read_key(k, sizeof k);
            break;
        }

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;
        if (k[0] == 'q' || k[0] == 'Q' || k[0] == 0x1b) break;
        if (k[0] == 'i' || k[0] == 'I') { rpg_show_inventory(); continue; }
        if (k[0] == 'm' || k[0] == 'M') {
            rpg_cast_zap(px, py, action);
            idle_ticks = 0;
            continue;
        }
        if (k[0] == 'l' || k[0] == 'L') {
            rpg_animating = !rpg_animating;
            if (rpg_animating) {
                rpg_anim_reset();
                rt.cc[6] = 0; rt.cc[5] = 1;   /* poll: 100 ms */
            } else {
                rt.cc[6] = 1; rt.cc[5] = 0;   /* block */
                /* Force per-cell-cache rebuild so static view returns
                 * to its baseline 1-or-2-step CA outcome. */
                mset(rpg_cell_done, 0, sizeof rpg_cell_done);
            }
            io(0, TCSETS, &rt);
            continue;
        }
        if (k[0] == 'k' || k[0] == 'K') {
            rpg_show_anim_settings();
            /* Settings panel set blocking termios; restore whatever
             * the rpg loop had. */
            rt.cc[6] = rpg_animating ? 0 : 1;
            rt.cc[5] = rpg_animating ? 1 : 0;
            io(0, TCSETS, &rt);
            continue;
        }
        if (k[0] >= '0' && k[0] <= '3') {
            int t = k[0] - '0';
            action[0] = 0;
            rpg_bend(t, action);
            rt.cc[6] = rpg_animating ? 0 : 1;
            rt.cc[5] = rpg_animating ? 1 : 0;
            io(0, TCSETS, &rt);
            idle_ticks = 0;
            continue;
        }
        if (k[0] >= '4' && k[0] <= '7') {
            int slot = k[0] - '4';
            action[0] = 0;
            if (rpg_player.mp < 3) {
                action[sapp(action, 0, "low mana")] = 0;
            } else {
                rpg_player.mp -= 3;
                rpg_player.cat_bend[slot]++;
                mset(rpg_sprite_done[RC_PLANT + slot], 0, RPG_CAT_VARIANTS);
                action[sapp(action, 0, "bent")] = 0;
            }
            idle_ticks = 0;
            continue;
        }
        char c = k[0];
        if (c >= 'A' && c <= 'Z') c += 32;
        if (c == 's') continue;   /* reserved */
        action[0] = 0;
        rpg_move(&px, &py, c, action);
        rpg_path_tick(px, py);
        /* Mosaic shift — if the player has stepped out of the central
         * 64×64 sub-region of the 192×192 mosaic, advance the world
         * stack and regenerate so they're back in the centre.  This
         * guarantees the player never sees an unloaded edge. */
        {
            int mdx = 0, mdy = 0;
            if (px <  RPG_MAP_W)         mdx = -1;
            else if (px >= 2 * RPG_MAP_W)mdx =  1;
            if (py <  RPG_MAP_H)         mdy = -1;
            else if (py >= 2 * RPG_MAP_H)mdy =  1;
            if (mdx || mdy) {
                px -= mdx * RPG_MAP_W;
                py -= mdy * RPG_MAP_H;
                rpg_shift_mosaic(mdx, mdy, px, py);
            }
        }
        /* Slow regen: every 4 actions, +1 HP/MP. */
        idle_ticks++;
        if (idle_ticks >= 4) {
            idle_ticks = 0;
            if (rpg_player.hp < rpg_player.max_hp) rpg_player.hp++;
            if (rpg_player.mp < rpg_player.max_mp) rpg_player.mp++;
        }
    }
    term_cooked();
    return 0;
}


/* ── lsys: character-mode L-system viewer ────────────────
 * Six tiny grammars; each has an axiom + a single F-rule.  The
 * expander walks src→dst buffers, copying non-F chars verbatim and
 * replacing every F with the rule body, repeated `iterations` times.
 *
 * Same alphabet the Velour lsystem app uses:
 *   F     forward one step (draw)
 *   + -   turn  (angle_steps × 45° per token)
 *   [ ]   push / pop turtle state (64-deep stack)
 *
 * 4 categories cycle with TAB.  Same string, four glyph+colour
 * interpretations — plant '*' green, building '#' tan, creature '@'
 * red, item '+' gold.  The framework is the Django app's structure
 * (axiom + rules + iterations + angle); the rendering is block-mode
 * because the office suite paints into an 80×25 framebuffer. */
#define LSYS_BUF_BYTES   16384
#define LSYS_STACK_DEPTH 64

struct LSystem {
    const char *name;
    const char *axiom;
    const char *rule;     /* body that replaces every F each iteration */
    int iterations;
    int angle_steps;      /* 1 → 45°, 2 → 90°, etc. */
};

static const struct LSystem lsys_lib[] = {
    {"Pine",    "F", "FF+[+F-F-F]-[-F+F+F]", 3, 1},
    {"Bush",    "F", "F[+F]F[-F]F",          3, 1},
    {"Tower",   "F", "F+F-F-F+F",            3, 2},
    {"Coral",   "F", "F[+F][-F]F[+F][-F]F",  3, 1},
    {"Snake",   "F", "F+F-F",                4, 1},
    {"Crystal", "F", "F[+F][-F]F",           3, 2},
};
#define LSYS_N ((int)(sizeof lsys_lib / sizeof lsys_lib[0]))

enum { LC_PLANT = 0, LC_BUILDING, LC_CREATURE, LC_ITEM, LC_COUNT };
static const char         *lsys_cat_name [LC_COUNT] =
    {"plant", "building", "creature", "item"};
static const char          lsys_cat_glyph[LC_COUNT] =
    {'*', '#', '@', '+'};
static const unsigned char lsys_cat_col  [LC_COUNT] =
    {  46,  138,  196,  220};   /* xterm-256: green, tan, red, gold */

static char lsys_buf_a[LSYS_BUF_BYTES];
static char lsys_buf_b[LSYS_BUF_BYTES];

/* Returns pointer to the buffer holding the final string + writes
 * its length to *out_len.  Stops appending if the buf is about to
 * overflow (the truncated string is still self-consistent). */
static const char *lsys_expand(const struct LSystem *L, int *out_len) {
    int alen = slen(L->axiom);
    if (alen >= LSYS_BUF_BYTES - 1) alen = LSYS_BUF_BYTES - 1;
    mcpy(lsys_buf_a, L->axiom, alen);
    lsys_buf_a[alen] = 0;
    char *src = lsys_buf_a;
    char *dst = lsys_buf_b;
    int cur = alen;
    int rule_len = slen(L->rule);
    for (int it = 0; it < L->iterations; it++) {
        int dn = 0;
        int overflow = 0;
        for (int i = 0; i < cur; i++) {
            char c = src[i];
            if (c == 'F') {
                if (dn + rule_len >= LSYS_BUF_BYTES - 1) { overflow = 1; break; }
                mcpy(dst + dn, L->rule, rule_len);
                dn += rule_len;
            } else {
                if (dn + 1 >= LSYS_BUF_BYTES - 1) { overflow = 1; break; }
                dst[dn++] = c;
            }
        }
        dst[dn] = 0;
        cur = dn;
        char *t = src; src = dst; dst = t;
        if (overflow) break;
    }
    *out_len = cur;
    return src;
}

/* Globals shared between the bbox pass and the draw pass. */
static const int LSYS_DX[8] = { 0,  1,  1,  1,  0, -1, -1, -1};
static const int LSYS_DY[8] = {-1, -1,  0,  1,  1,  1,  0, -1};
static int g_lsys_min_x, g_lsys_min_y, g_lsys_max_x, g_lsys_max_y;
static int g_lsys_ox, g_lsys_oy;
static unsigned char g_lsys_glyph;
static unsigned char g_lsys_col;

struct LSysState { short x, y; unsigned char dir; };

/* mode 0: measure bbox into g_lsys_{min,max}_{x,y}.
 * mode 1: paint glyphs at (g_lsys_ox + x, g_lsys_oy + y), clipped to
 *         rows 2..SCREEN_H-2 (chrome + status are reserved). */
static void lsys_walk(const char *cmds, int len, int angle_steps, int mode) {
    struct LSysState stk[LSYS_STACK_DEPTH];
    int sp = 0;
    int x = 0, y = 0;
    unsigned char dir = 0;          /* facing N */
    if (mode == 0) {
        g_lsys_min_x = g_lsys_max_x = 0;
        g_lsys_min_y = g_lsys_max_y = 0;
    }
    /* Helper: process the current (x,y) for the active mode. */
#define LSYS_VISIT() do {                                            \
        if (mode == 0) {                                             \
            if (x < g_lsys_min_x) g_lsys_min_x = x;                  \
            if (x > g_lsys_max_x) g_lsys_max_x = x;                  \
            if (y < g_lsys_min_y) g_lsys_min_y = y;                  \
            if (y > g_lsys_max_y) g_lsys_max_y = y;                  \
        } else {                                                     \
            int sx = x + g_lsys_ox;                                  \
            int sy = y + g_lsys_oy;                                  \
            if (sx >= 0 && sx < SCREEN_W &&                          \
                sy >= 2 && sy < SCREEN_H - 1) {                      \
                cup(sx, sy);                                         \
                sgrbgfg(COL_DESKTOP, g_lsys_col);                    \
                char ch = (char)g_lsys_glyph;                        \
                fbw(&ch, 1);                                         \
            }                                                        \
        }                                                            \
    } while (0)
    LSYS_VISIT();
    for (int i = 0; i < len; i++) {
        char c = cmds[i];
        if (c == 'F') {
            x += LSYS_DX[dir];
            y += LSYS_DY[dir];
            LSYS_VISIT();
        } else if (c == '+') {
            int nd = (int)dir + angle_steps;
            dir = (unsigned char)(((nd % 8) + 8) % 8);
        } else if (c == '-') {
            int nd = (int)dir - angle_steps;
            dir = (unsigned char)(((nd % 8) + 8) % 8);
        } else if (c == '[') {
            if (sp < LSYS_STACK_DEPTH) {
                stk[sp].x = (short)x; stk[sp].y = (short)y;
                stk[sp].dir = dir; sp++;
            }
        } else if (c == ']') {
            if (sp > 0) {
                sp--;
                x = stk[sp].x; y = stk[sp].y; dir = stk[sp].dir;
            }
        }
    }
#undef LSYS_VISIT
}

static int run_lsys(int argc, char **argv) {
    (void)argc; (void)argv;
    int sel = 0;            /* current grammar */
    int cat = LC_PLANT;     /* current interpretation */
    term_raw();
    while (1) {
        paint_desktop();
        chrome("lsys");

        const struct LSystem *L = &lsys_lib[sel];
        int len = 0;
        const char *cmds = lsys_expand(L, &len);
        g_lsys_glyph = lsys_cat_glyph[cat];
        g_lsys_col   = lsys_cat_col  [cat];

        lsys_walk(cmds, len, L->angle_steps, 0);
        int bw = g_lsys_max_x - g_lsys_min_x + 1;
        int bh = g_lsys_max_y - g_lsys_min_y + 1;
        g_lsys_ox = (SCREEN_W - bw) / 2 - g_lsys_min_x;
        int avail_h = SCREEN_H - 4;
        int top = 2 + (avail_h - bh) / 2;
        if (top < 2) top = 2;
        g_lsys_oy = top - g_lsys_min_y;

        lsys_walk(cmds, len, L->angle_steps, 1);
        sgr0();

        /* Info line just under the title bar. */
        cup(2, 1);
        sgrbgfg(COL_TITLE_BG, COL_TITLE_FG);
        char info[96]; int ip = 0;
        info[ip++] = ' ';
        info[ip++] = (char)('1' + sel);
        info[ip++] = ' ';
        ip = sapp(info, ip, L->name);
        ip = sapp(info, ip, "  cat=");
        ip = sapp(info, ip, lsys_cat_name[cat]);
        ip = sapp(info, ip, " '");
        info[ip++] = lsys_cat_glyph[cat];
        info[ip++] = '\'';
        ip = sapp(info, ip, "  iter=");
        ip += utoa((unsigned)L->iterations, info + ip);
        ip = sapp(info, ip, "  cmds=");
        ip += utoa((unsigned)len, info + ip);
        info[ip++] = ' ';
        info[ip] = 0;
        fbs(info);
        sgr0();

        status(" 1-6 grammar · TAB category · q quit ");
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;
        if (k[0] == 'q' || k[0] == 'Q' || k[0] == 0x1b) break;
        if (k[0] >= '1' && k[0] <= '0' + LSYS_N) sel = k[0] - '1';
        else if (k[0] == '\t') cat = (cat + 1) % LC_COUNT;
    }
    term_cooked();
    return 0;
}


/* ── bytebeat: tiny PCM synth (office41) ─────────────────
 * "Bytebeat" is the practice of generating audio by evaluating an
 * expression on a sample counter t once per sample.  We pick u8 mono
 * at 8000 Hz so each sample is a single byte and the math fits in a
 * 32-bit accumulator.  PCM is generated into /tmp/<APP>_bb.raw and
 * piped to aplay (alsa-utils) via fork+execve, mirroring run_ask's
 * curl pattern.  Five preset formulas; pick one with 1..5, q quits.
 *
 * Safe and simple:
 *   – integer arithmetic on a counter, no input parsing
 *   – one-way write to disk + aplay invocation, no network
 *   – aplay is ubiquitous on linux desktops; if missing, we surface
 *     the failure in the status line and return cleanly. */

#define BB_RATE      8000
#define BB_SECS      4
#define BB_LEN       (BB_RATE * BB_SECS)
#define BB_PRESETS   5
#define BB_RAW_FILE  "/tmp/" APP_NAME "_bb.raw"

static unsigned char bb_eval(int preset, unsigned long t) {
    unsigned long v = 0;
    switch (preset) {
    case 0: v = t * (t >> 8 & t >> 16); break;                  /* Crowd */
    case 1: v = (t * (t >> 5 | t >> 8)) >> (t >> 16);  break;   /* 42 Melody */
    case 2: v = t & t >> 8; break;                              /* Three Note */
    case 3: v = (t * 5 & t >> 7) | (t * 3 & t >> 10); break;    /* Skyline */
    case 4: v = (t | (t >> 9 | t >> 7)) * t & (t >> 11 | t >> 9); break; /* Phaser */
    }
    return (unsigned char)(v & 0xff);
}

static const char *bb_name[BB_PRESETS] = {
    "Crowd",
    "42 Melody",
    "Three Note",
    "Skyline",
    "Phaser",
};
static const char *bb_formula[BB_PRESETS] = {
    "t * (t>>8 & t>>16)",
    "(t * (t>>5 | t>>8)) >> (t>>16)",
    "t & t>>8",
    "t*5 & t>>7  |  t*3 & t>>10",
    "(t|(t>>9|t>>7)) * t & (t>>11|t>>9)",
};

static int bb_render_and_play(int preset, char *err) {
    static unsigned char buf[BB_LEN];
    for (unsigned long t = 0; t < BB_LEN; t++)
        buf[t] = bb_eval(preset, t);
    int fd = (int)op(BB_RAW_FILE, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) { err[sapp(err, 0, "open /tmp failed")] = 0; return -1; }
    long w = wr(fd, buf, BB_LEN);
    cl(fd);
    if (w != BB_LEN) { err[sapp(err, 0, "write short")] = 0; return -1; }

    /* Three player candidates, tried in order in the child.  execvee
     * only returns on failure, so if aplay isn't installed we fall
     * through to paplay, then ffplay; first one that takes wins. */
    char *aplay_av[8] = {
        (char *)"aplay", (char *)"-q",
        (char *)"-f", (char *)"U8",
        (char *)"-r", (char *)"8000",
        (char *)BB_RAW_FILE, 0,
    };
    char *paplay_av[8] = {
        (char *)"paplay", (char *)"--raw",
        (char *)"--format=u8", (char *)"--rate=8000",
        (char *)"--channels=1",
        (char *)BB_RAW_FILE, 0,
    };
    char *ffplay_av[12] = {
        (char *)"ffplay", (char *)"-nodisp", (char *)"-autoexit",
        (char *)"-loglevel", (char *)"quiet",
        (char *)"-f", (char *)"u8",
        (char *)"-ar", (char *)"8000",
        (char *)"-ac", (char *)"1",
        (char *)BB_RAW_FILE,
    };

    long pid = forkk();
    if (pid < 0) { err[sapp(err, 0, "fork failed")] = 0; return -1; }
    if (pid == 0) {
        execvee("/usr/bin/aplay",       aplay_av,  g_envp);
        execvee("/bin/aplay",           aplay_av,  g_envp);
        execvee("/usr/bin/paplay",      paplay_av, g_envp);
        execvee("/bin/paplay",          paplay_av, g_envp);
        execvee("/usr/bin/ffplay",      ffplay_av, g_envp);
        execvee("/usr/local/bin/ffplay",ffplay_av, g_envp);
        qu(127);
    }
    int status = 0;
    wait4_(&status);
    if (status) { err[sapp(err, 0, "no audio player (aplay/paplay/ffplay)")] = 0; return -1; }
    return 0;
}

static int run_bytebeat(int argc, char **argv) {
    (void)argc; (void)argv;
    int sel = 0;
    char msg[64]; msg[0] = 0;
    for (;;) {
        paint_desktop();
        chrome("bytebeat");
        body_clear();
        body_at(2, 3, "Tiny PCM synth — 8000 Hz u8 mono, 4 s per play.",
                SCREEN_W - 4);
        for (int i = 0; i < BB_PRESETS; i++) {
            char line[96]; int p = 0;
            line[p++] = ' ';
            line[p++] = (char)('1' + i);
            line[p++] = ' ';
            line[p++] = (i == sel) ? '>' : ' ';
            line[p++] = ' ';
            p = sapp(line, p, bb_name[i]);
            for (; p < 16; p++) line[p] = ' ';
            line[p++] = ' ';
            p = sapp(line, p, bb_formula[i]);
            line[p] = 0;
            body_at(2, 5 + i, line, SCREEN_W - 4);
        }
        body_at(2, 5 + BB_PRESETS + 1,
                "1-5 select | ENTER play | q back", SCREEN_W - 4);
        if (msg[0]) body_at(2, 5 + BB_PRESETS + 3, msg, SCREEN_W - 4);
        status(" 1-5 select  ENTER play  q back ");
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;
        if (k[0] == 'q' || k[0] == 'Q' || k[0] == 0x1b) break;
        if (k[0] >= '1' && k[0] <= '0' + BB_PRESETS) sel = k[0] - '1';
        else if (k[0] == '\r' || k[0] == '\n' || k[0] == ' ') {
            msg[0] = 0;
            int n2 = sapp(msg, 0, "playing ");
            n2 = sapp(msg, n2, bb_name[sel]);
            msg[n2] = 0;
            status(msg);
            fbflush();
            char err[64]; err[0] = 0;
            int rc = bb_render_and_play(sel, err);
            msg[0] = 0;
            if (rc) {
                int n3 = sapp(msg, 0, "error: ");
                n3 = sapp(msg, n3, err);
                msg[n3] = 0;
            } else {
                int n3 = sapp(msg, 0, "done — ");
                n3 = sapp(msg, n3, bb_name[sel]);
                msg[n3] = 0;
            }
        }
    }
    return 0;
}


/* ── dispatch ─────────────────────────────────────────── */
static const char *basename_(const char *p) {
    const char *b = p;
    for (const char *q = p; *q; q++) if (*q == '/') b = q + 1;
    return b;
}

int main_c(int argc, char **argv, char **envp) {
    g_envp = envp;
    term_init();
    tz_init_from_envp(envp);
    /* Bootstrap the active hxhnt palette + genome before any app
     * touches them.  hxhnt evolves these; rpg derives terrain RGBs
     * from the palette and uses the genome for its CA stepping. */
    hx_active_init();
    /* Suite-wide chrome lives in the .gdnseed embedded region.  A
     * fresh build's gd_embedded matches the office6 default (so the
     * blue/grey Win95 look survives); a spliced binary's region was
     * overwritten by garden's export with the user's chosen gene. */
    mcpy(&g_genome, gd_embedded.genome, sizeof g_genome);
    const char *cmd = (argc > 0) ? basename_(argv[0]) : "office";
    int sub_argc = argc;
    char **sub_argv = argv;
    if ((scmp(cmd, "office")  == 0 ||
         scmp(cmd, "office2") == 0 ||
         scmp(cmd, "office3") == 0 ||
         scmp(cmd, "office4") == 0 ||
         scmp(cmd, "office5") == 0 ||
         scmp(cmd, "office6") == 0 ||
         scmp(cmd, "office7") == 0 ||
         scmp(cmd, "office8") == 0 ||
         scmp(cmd, "office9") == 0 ||
         scmp(cmd, "office10") == 0 ||
         scmp(cmd, "office11") == 0 ||
         scmp(cmd, "office12") == 0 ||
         scmp(cmd, "office13") == 0 ||
         scmp(cmd, "office14") == 0 ||
         scmp(cmd, "office15") == 0 ||
         scmp(cmd, "office16") == 0 ||
         scmp(cmd, "office17") == 0 ||
         scmp(cmd, "office18") == 0 ||
         scmp(cmd, "office19") == 0 ||
         scmp(cmd, "office20") == 0 ||
         scmp(cmd, "office21") == 0 ||
         scmp(cmd, "office22") == 0 ||
         scmp(cmd, "office23") == 0 ||
         scmp(cmd, "office24") == 0 ||
         scmp(cmd, "office25") == 0 ||
         scmp(cmd, "office26") == 0 ||
         scmp(cmd, "office27") == 0 ||
         scmp(cmd, "office28") == 0 ||
         scmp(cmd, "office29") == 0 ||
         scmp(cmd, "office30") == 0 ||
         scmp(cmd, "office31") == 0 ||
         scmp(cmd, "office32") == 0 ||
         scmp(cmd, "office33") == 0 ||
         scmp(cmd, "office34") == 0 ||
         scmp(cmd, "office35") == 0 ||
         scmp(cmd, "office36") == 0 ||
         scmp(cmd, "office37") == 0 ||
         scmp(cmd, "office38") == 0 ||
         scmp(cmd, "office39") == 0 ||
         scmp(cmd, "office40") == 0 ||
         scmp(cmd, "office41") == 0) && argc > 1) {
        cmd = argv[1];
        sub_argv = argv + 1;
        sub_argc = argc - 1;
    }
    if (scmp(cmd, "notepad") == 0) return run_notepad(sub_argc, sub_argv);
    if (scmp(cmd, "word")    == 0) return run_word   (sub_argc, sub_argv);
    if (scmp(cmd, "mail")    == 0) return run_mail   (sub_argc, sub_argv);
    if (scmp(cmd, "sheet")   == 0) return run_sheet  (sub_argc, sub_argv);
    if (scmp(cmd, "paint")   == 0) return run_paint  (sub_argc, sub_argv);
    if (scmp(cmd, "hex")     == 0) return run_hex    (sub_argc, sub_argv);
    if (scmp(cmd, "bfc")     == 0) return run_bfc    (sub_argc, sub_argv);
    if (scmp(cmd, "files")   == 0) return run_files  (sub_argc, sub_argv);
    if (scmp(cmd, "find")    == 0) return run_find   (sub_argc, sub_argv);
    if (scmp(cmd, "calc")    == 0) return run_calc   (sub_argc, sub_argv);
    if (scmp(cmd, "mines")   == 0) return run_mines  (sub_argc, sub_argv);
    if (scmp(cmd, "ask")     == 0) return run_ask    (sub_argc, sub_argv);
    if (scmp(cmd, "garden")  == 0) return run_garden (sub_argc, sub_argv);
    if (scmp(cmd, "hxhnt")   == 0) return run_hxhnt  (sub_argc, sub_argv);
    if (scmp(cmd, "rpg")     == 0) return run_rpg    (sub_argc, sub_argv);
    if (scmp(cmd, "lsys")    == 0) return run_lsys   (sub_argc, sub_argv);
    if (scmp(cmd, "bytebeat") == 0 || scmp(cmd, "bb") == 0)
        return run_bytebeat(sub_argc, sub_argv);
    if (scmp(cmd, "preview-genome") == 0) return run_preview_genome(sub_argc, sub_argv);
    if (scmp(cmd, "view-genome")    == 0) return run_view_genome   (sub_argc, sub_argv);
    /* An exported hxh-* binary launched by name lands here.  Default
     * to display-mode hxhnt so the embedded tail's genome animates,
     * matching the original hunter's launch behaviour. */
    if (cmd[0] == 'h' && cmd[1] == 'x' && cmd[2] == 'h')
        return run_hxhnt(sub_argc, sub_argv);
    return run_shell(sub_argc, sub_argv);
}


/* ── _start: read argc/argv/envp from rsp, dispatch, exit ─
 * Stack at entry: argc, argv[0..argc-1], NULL, envp[0..], NULL, ...
 * envp starts at rsp + 16 + argc*8. */
__asm__ (
    ".global _start\n"
    "_start:\n"
    "    movq (%rsp), %rdi\n"
    "    leaq 8(%rsp), %rsi\n"
    "    leaq 16(%rsp,%rdi,8), %rdx\n"
    "    andq $-16, %rsp\n"
    "    call main_c\n"
    "    movl %eax, %edi\n"
    "    movl $231, %eax\n"
    "    syscall\n"
);
