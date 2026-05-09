/* office59.c -- Win95-style 11-app suite. Linux x86_64. No libc.
 *
 *   shell  notepad  sheet  hex  files  calc
 *   ask   garden  hxhnt  rpg  lsys  saver
 *
 * office59 — 64-bit math in calc + sheet evaluator.
 *
 * office58's expression evaluator was 32-bit `int` end-to-end, so
 * `2^32` overflowed silently to 0 — and any matrix multiply whose
 * dot-product climbed past INT_MAX would wrap.  This fork widens
 * the whole feval_* chain to `long long` (64-bit signed):
 * feval_expr / _term / _pow / _atom / _cell / range_reduce /
 * parse_int_literal all return `long long`; binlog / ipow_ / isqrt_
 * operate on `long long`; sheet matrix-multiply (M, K) and its dot-
 * product accumulator are also widened.  New helper `litoa_` writes
 * a 64-bit signed value into a buffer (up to 20 digits + sign), and
 * `lutoa_` is its unsigned twin built on the existing string-reverse
 * pattern from `utoa`.
 *
 * Calc's result buffer + sheet's shown-formula buffer grow from 16
 * to 24 bytes; the on-screen sheet still clips to CELL_W = 9 chars
 * (so very large numbers visually truncate) but all arithmetic and
 * stored-back values are full-precision.  Cell text storage
 * (cell[3][12][8][16]) is unchanged — formulas are short text and
 * the only path that writes a numeric result back into a cell is
 * matrix multiply (sheet_put_int), which now uses a wider tmp
 * buffer and clips to the 15-byte cell limit.
 *
 * Sheet UX fix: in office58 a cell containing `=A1+B2` could only
 * be edited by pressing `e`, which positioned the cursor at the
 * end of the existing formula — so typing `42` produced
 * `=A1+B242` rather than replacing the formula.  office59 adds
 * Excel-style overwrite: typing any printable character on a
 * selected cell that isn't a reserved hotkey (q/s/e/m/M/k/K/1/2/3)
 * starts a fresh edit with that character as the first input.
 * `e` still opens the existing content for in-place fixes.  Hint
 * row updated to advertise it.
 *
 * Carried forward from office58: scientific calc + 16 binary logic ops in sheet.
 *
 * The shared expression evaluator (feval_expr / feval_term /
 * feval_atom) was missing two operators and the full set of binary
 * boolean functions.  In office57 typing `2^3` in calc returned 2
 * because `^` simply terminated parsing at the first operand —
 * "false answer" with no error.  This fork rebuilds the operator
 * stack and adds 16 named logic functions usable from sheet cells.
 *
 *   1. New operators.  feval_expr now layers expr → term → pow →
 *      atom.  `^` is right-associative (2^3^2 = 2^9 = 512), `%`
 *      lives at term level next to `*` and `/`, and `-` works as
 *      both subtraction and unary negation.  Calc accepts the lot,
 *      and any cell whose value starts with `=` does too.
 *
 *   2. Scientific helpers.  ABS, SQR (a²), SQRT (integer
 *      Newton-Raphson — 6 digits of precision is plenty for the
 *      8×12 sheet), SIGN, MIN2/MAX2 (binary, distinct from the
 *      range-reducing MIN/MAX over A1:A8).  All command-line
 *      parseable: calc echoes `SQRT(81) = 9`.
 *
 *   3. 16 binary logic functions.  AND, OR, XOR, NAND, NOR, XNOR,
 *      IDA, IDB, NOTA, NOTB, IMP, CIMP, NIA, NIB, FAL, TRU — the
 *      full set of two-input boolean operators.  Each takes two
 *      32-bit ints and applies its truth table bitwise via a
 *      single `binlog(a, b, tt)` helper.  In sheet a cell can read
 *      `=XOR(A1, B1)` or `=NAND(2, 3)`; the helper makes the
 *      16-row dispatch table fit in ~64 bytes plus the tiny names.
 *      Cell values that recurse into other formulas inherit the
 *      existing depth-limit guard (16 deep), so an infinite
 *      reference chain bottoms out gracefully at 0.
 *
 * Carried forward from office57: sheet save fix.  In office56 and earlier, pressing
 * `s` in sheet was effectively a no-op when the user launched
 * sheet from the shell (no argv arg): `fname` was empty and
 * `save_file("")` silently failed, with no status output either
 * way.  office57 always saves to a fresh timestamped filename per
 * active tab:
 *
 *     sheet<X>_<YYYY><mon><DD>-<HHMM>-<SS>.csv
 *
 * with X = A/B/C and the local-time date built via the existing
 * unix_to_calendar + g_tz_offset_sec.  Each `s` press creates a
 * NEW file (the timestamp guarantees uniqueness at second
 * granularity), so there's a save history without overwriting
 * earlier snapshots.  Status banner at row 1 reports either
 * "saved -> <name> (NNN B)" on success or "ERR: save failed" if
 * the syscall returned negative — same persistent banner the
 * matrix-mul ops use.
 *
 * Carried forward from office56: sheet has two combine ops that
 * never error on dimension mismatch — M (zero-pad multiply) and
 * K (Kronecker product).  Both write to sheet C and switch focus
 * there; status banner shows the dims used + any padding/clipping.
 *
 * M (zero-pad multiply): A is interpreted as m×n with zeros past
 * A.cols, B as n×q with zeros past B.rows, where n = max(A.cols,
 * B.rows).  Result is m×q.  Empty cells already evaluate to 0, so
 * "missing" entries on the inner axis just zero out their term in
 * the dot-product sum.  When ac != br the banner says "pad" so the
 * silent extension is visible.  Replaces office55's strict-multiply
 * variant, which errored on mismatch — zero-pad is the closest
 * well-defined operation that keeps the M-hotkey ergonomic for any
 * pair of sheets the user happens to fill.
 *
 * K (Kronecker product A⊗B): always defined for any A and B.  A
 * (m×n) ⊗ B (p×q) produces an (m·p)×(n·q) block matrix where each
 * block (i, j) is A[i][j]·B.  Useful for tensoring small matrices
 * to grow them.  C truncates to the 12×8 sheet cap when the full
 * result is bigger; banner reports clipped vs. full dims so the
 * user knows when to choose smaller inputs.
 *
 * Tabs (A · B · C) carry over from office55: cell store is
 * cell[3][12][8][16], `cur_sheet` int picks which is on screen,
 * Tab/1/2/3 cycle.  Cell values that start with '=' are evaluated
 * through the existing feval_expr so formulas work as matrix
 * entries.  Save/open scoped to the active sheet; CSV format
 * unchanged from earlier forks.
 *
 * Carried forward from office54: drop the bytebeat module to slim
 * the suite back under the 64 KB cap.  Removing it strips the
 * bb_eval / bb_render_and_play / run_bytebeat trio, the BB_*
 * constants, the static 32 KB render buffer (.bss only, no file
 * impact), the forward decl, two menu strings, and two dispatch
 * entries.  Apps list goes 12 → 11.
 *
 * Carried forward from office53: silent terrain bends in rpg.
 * hx_run_ga_session takes a `silent` flag: when set, it skips the
 * polling-termios switch, the per-generation hx_paint_progress +
 * read_key, and the abort-on-q check.  The GA still runs the same
 * number of generations and still adopts the winner; rpg_bend
 * invalidates the cell cache + refreshes palettes as before, so the
 * world repopulates with the evolved CA on the very next render —
 * the player just sees a brief pause, then the overworld shifts
 * colour and pattern under their feet.  The existing hxhnt callers
 * (run_continuous_hunt, hx_run_ga) pass silent=0 so their
 * interactive view is unchanged.
 *
 * Carried forward from office52: bracket every fbflush() with DECSET 2026 (synchronized
 * output) so the terminal holds rendering until the full buffered
 * frame has arrived.  Eliminates the mid-frame flicker that was
 * visible in rpg every refresh: paint_desktop emits cls + 80×24 of
 * teal, chrome paints the title row, rpg_render_view paints a black
 * rectangle into the cell region, then 64 cells × ~24 chars paint
 * on top — each step a separate sequence the terminal would render
 * before the next arrived.  With \033[?2026h ... \033[?2026l around
 * the whole flush, supporting terminals (Windows Terminal, kitty,
 * wezterm, alacritty 0.13+, foot, ghostty, VTE 0.65+) draw nothing
 * until the end marker, so the user only sees the completed frame.
 * Terminals that don't recognise the DECSET ignore it cleanly.
 *
 * Carried forward from office51: three changes in rpg's mosaic-shift
 * path so the player never sees an "edge of the world" loading event.
 * Pushes the binary over the 64 KB cap (~67 KB) — a follow-up fork
 * can trim or split if the size matters more than the smoothness.
 *
 *   1. World-stable cell hash.  In office50 each cell's 8×3 sample
 *      texture and 4-colour palette derived from rpg_cell_hash(wx,
 *      wy) keyed by *mosaic* coords.  When the player crossed a
 *      sub-overworld boundary the mosaic shifted, every visible
 *      cell ended up at a new mosaic coord, and every texture
 *      blinked to a new pattern — the same world cell looked
 *      different before vs. after the cross.  Now textures key off
 *      the cell's *world* coord (panel seed + local x, y), so a
 *      world cell looks identical regardless of which mosaic slot
 *      it currently occupies.  Cross-overs are visually invisible.
 *
 *   2. Partial-regen shift.  rpg_shift_mosaic in office50 always
 *      regenerated all 9 panels (~75 ms of CA stepping + entity
 *      seeding) on every cross.  Now the 6 reused panels (4 for
 *      diagonal crosses) memmove into their new mosaic slots and
 *      only the 3 (or 5) new-edge panels regenerate, ~3× faster.
 *
 *   3. Pre-load at 2-cell margin.  When the player walks within 2
 *      cells of any central-panel boundary, the new edge panels
 *      that *would* be needed if they crossed are computed into a
 *      shadow buffer, one panel per game tick.  By the time the
 *      cross fires, the shadow is ready and rpg_shift_mosaic just
 *      memcpys the staged content into place — zero compute on the
 *      critical path.  If the player crosses faster than the
 *      shadow can keep up (or jumps a direction), shift falls back
 *      to synchronous regen of any unstaged panels.
 *
 * Carried forward from office50: per-overworld base palette in rpg
 * (each of the 9 sub-overworlds derives its own 4-colour palette
 * from the world seed) and Ask max_tokens=1024 cap.
 *
 * Carried forward from office49: 12-app suite with mail/find/paint/
 * word/mines/bfc removed (~6900 B trim back under 64 KB cap).
 *
 * Carried forward from office48: grabber pulls the model name
 * from the same table row as the chosen key.  Each row in the
 * alistaitsacle README is `| `<key>` | <model> | <status> | …`, so
 * after we lock in the key cell we walk the rest of the line, skip
 * the cell separator, and copy the second cell into ask_model.
 * Without this, the grabber leaves ask_model at whatever the user
 * had set — which causes "this token does not have access to model
 * X" errors when the picked key is provisioned for a different
 * model than the user happened to type.
 *
 * Carried forward from office47: grabber overrides ask_endpoint to
 * the pekpik proxy URL. keys from
 * alistaitsacle/free-llm-api-keys aren't valid OpenAI keys, they're
 * issued for the upstream's pekpik proxy.  Sending them straight to
 * api.openai.com returns "Incorrect API key provided".  When the
 * grabber succeeds we now also overwrite ask_endpoint with the
 * proxy URL (https://aiapiv2.pekpik.com/v1/chat/completions) and
 * default the model to gpt-4o-mini, so the very next message
 * actually authenticates.  The user can still hand-edit endpoint or
 * model afterwards if they have a real key for a different host.
 *
 * Carried forward from office46: provider-aware grabber + Anthropic
 * aware parser pointed at https://github.com/alistaitsacle/free-
 * llm-api-keys (README.md, refreshed 3-5x daily by the upstream
 * cron).  The README has `### <Provider>` markdown sections, each
 * holding a table of `` `<key>` `` cells.  The grabber:
 *   1. Detects which provider Ask is currently configured for
 *      (OpenAI / Anthropic / Gemini, via endpoint hostname).
 *   2. Walks the downloaded README, tracking the current `### `
 *      section name.
 *   3. Reservoir-samples one backtick-quoted token from the
 *      section that matches the provider — "GPT" for OpenAI,
 *      "Claude" or "Anthropic" for Anthropic, "Gemini" for Gemini.
 *   4. Falls back to the first token in any section if no match.
 * Keys can be sk-…, AIza…, anthropic_..., etc; the parser just
 * accepts alphanumeric/underscore/dash strings of ≥20 chars.
 *
 * Office42's dan1471 grabber is replaced (single-source repo, plain
 * sk- tokens only — superseded by alistaitsacle's multi-provider
 * format).
 *
 * Carried forward from office45: Anthropic + Gemini wire formats.  Endpoint hostname
 * picks the wire format:
 *
 *   – api.openai.com (or anything else)  → OpenAI Chat Completions
 *     (Authorization: Bearer KEY; messages[].content; reply in
 *     "content":"…")
 *   – api.anthropic.com                  → Anthropic Messages
 *     (x-api-key + anthropic-version: 2023-06-01; max_tokens
 *     required; reply in "text":"…" inside content[])
 *   – generativelanguage.googleapis.com  → Google Gemini
 *     (x-goog-api-key; contents[].parts[].text; "model" role
 *     instead of "assistant"; reply in "text":"…" inside parts[])
 *
 * The settings modal still has just three fields (api_key, endpoint,
 * model) — paste the right URL and key for each provider.  Defaults
 * stay on OpenAI so existing configs don't break.
 *
 * Carried forward from office44: shell home-screen menu lists.  run_shell prints its
 * OWN built-in-commands list separate from show_about's, and that
 * list never got updated when bytebeat (office39) and saver
 * (office43) shipped — so users couldn't see those names in the
 * default Welcome screen.  Now both lists agree.
 *
 * Carried forward from office43: screensaver app. launch `saver` and the rpg world
 * auto-plays in fullscreen — no title bar, no status bar, just the
 * cell mosaic with a wandering player picking a random hex direction
 * every ~250 ms.  Animals and NPCs continue their closed-loop wander
 * paths each tick; the 3×3 mosaic shifts as the player crosses
 * sub-overworlds.  Any keypress exits.  rpg_render_view gained a
 * `g_rpg_fullscreen` flag that drops origin_y to 0 so the cell grid
 * extends to the top row, leaving no chrome strip.
 *
 * Carried forward from office42: Ask paste fix + 'r' key preseeds
 *   – Paste fix.  The text-edit handler used to consume only k[0]
 *     of each read_key call, so a 50-character API-key paste was
 *     truncated to a single character.  Now it loops over every
 *     printable byte in the read, and the read buffer is enlarged
 *     to 256 bytes so terminal pastes don't get split.
 *   – `r` key in settings — fetch a random API key from the
 *     dan1471/FREE-openai-api-keys README via fork+execve curl
 *     into /tmp/office50_keys.txt, scan for "sk-" tokens, and
 *     drop one into the API-key field.  Saves typing for the
 *     toy/dev workflow the user uses against open OpenAI proxies.
 *
 * Carried forward from office41: seamless 3×3 overworld mosaic.  The world-cell arrays
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
#define APP_NAME    "office66"
#define APP_VERSION "43"


/* ── selective build (office66+) ────────────────────────
 * Each app's dispatch entry is wrapped in `#if OFFICE_FEATURE_<NAME>`,
 * and each feature defaults ON (1) unless the build overrides with
 * `-DOFFICE_FEATURE_<NAME>=0`.  The function bodies themselves stay
 * compiled regardless — `-ffunction-sections` + `--gc-sections` (in
 * Makefile) drop any function whose only callers were excluded
 * dispatch lines, so disabling `OFFICE_FEATURE_RPG=0` actually shrinks
 * the binary by ~13 KB even though run_rpg's source still appears.
 *
 * The Velour `officeforge` app (queued as a follow-up) drives this
 * with a checkbox UI + live byte budget, but the same flags work
 * directly on the cc command line, e.g.:
 *
 *   cc -DOFFICE_FEATURE_RPG=0 -DOFFICE_FEATURE_HXHNT=0 \\
 *      -DOFFICE_FEATURE_ASK=0 -DOFFICE_FEATURE_FTP=0 ...
 *
 * to produce a sub-64-KB lite build of office. */

/* officerpg v0.1 — fork of office66 with everything but RPG +
 * HXHNT (the CA engine RPG depends on) hard-disabled.  HXHNT's
 * dispatch entry stays out of the shell; only RPG is reachable as
 * a launchable app, and the binary auto-execs RPG on startup so
 * the user never sees the bare shell. */
#define OFFICE_FEATURE_NOTEPAD     0
#define OFFICE_FEATURE_SHEET       0
#define OFFICE_FEATURE_HEX         0
#define OFFICE_FEATURE_FILES       0
#define OFFICE_FEATURE_CALC        0
#define OFFICE_FEATURE_ASK         0
#define OFFICE_FEATURE_GARDEN      0
#define OFFICE_FEATURE_HXHNT       1
#define OFFICE_FEATURE_RPG         1
#define OFFICE_FEATURE_LSYS        0
#define OFFICE_FEATURE_SCREENSAVER 0
#define OFFICE_FEATURE_NET         0
#define OFFICE_FEATURE_HTTP        0
#define OFFICE_FEATURE_ECHO        0
#define OFFICE_FEATURE_FINGER      0
#define OFFICE_FEATURE_GOPHER      0
#define OFFICE_FEATURE_PROBE       0
#define OFFICE_FEATURE_DNS         0
#define OFFICE_FEATURE_FTP         0
#define OFFICE_FEATURE_SSHTEL      0
/* Sheet macros only make sense when sheet itself is in. */
#if !OFFICE_FEATURE_SHEET
#undef  OFFICE_FEATURE_SHEET_MACROS
#define OFFICE_FEATURE_SHEET_MACROS 0
#endif
#ifndef OFFICE_FEATURE_SHEET_MACROS
#define OFFICE_FEATURE_SHEET_MACROS 1
#endif


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
/* office61: setsockopt needs 5 args (fd, level, opt, val, len). */
static long sys5(long n, long a, long b, long c, long d, long e) {
    long r;
    register long r10 __asm__("r10") = d;
    register long r8  __asm__("r8")  = e;
    __asm__ volatile ("syscall" : "=a"(r)
                      : "0"(n), "D"(a), "S"(b), "d"(c), "r"(r10), "r"(r8)
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
#define SYS_uname  63
#define SYS_readlink 89
#define SYS_socket    41
#define SYS_accept    43
#define SYS_bind      49
#define SYS_listen    50
#define SYS_setsockopt 54
#define SYS_connect    42
#define SYS_sendto     44
#define SYS_recvfrom   45
#define SYS_time   201
#define SYS_getdents64 217
#define SYS_exit_group 231

#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT  64
#define O_TRUNC  512

/* v0.3: defined here so the file builds without -include stddef.h.
 * Older forks compiled by accident (`NULL` was unused in the lite
 * build); the v0.2 shot-bundle port at line 10771 added a real call. */
#define NULL ((void*)0)

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
/* office52 — wrap each frame in DECSET 2026 (synchronized output).
 * Terminals that recognise it (Windows Terminal, kitty, wezterm,
 * alacritty 0.13+, foot, ghostty, VTE 0.65+) hold rendering until
 * they see the close, so the user never sees a half-painted cls +
 * paint_desktop + chrome + cell-region pre-paint mid-flicker.
 * Terminals that don't know the sequence ignore it. */
static void fbflush(void) {
    static const char beg[] = "\033[?2026h";
    static const char end[] = "\033[?2026l";
    wr(1, beg, sizeof beg - 1);
    wr(1, fb, fbn);
    wr(1, end, sizeof end - 1);
    fbn = 0;
}


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
static const MI mE_full[]   = {{"Cut     ^X", MA_CUT},
                               {"Copy    ^C", MA_COPY},
                               {"Paste   ^V", MA_PASTE}};
static const MI mE_paste[]  = {{"Paste   ^V", MA_PASTE}};
static const MI mV_hex[]    = {{"Hex/ASC Tab", MA_HEXTOG}};
static const MI mH_about[]  = {{"About...  ", MA_ABOUT}};

#define NA(a) ((int)(sizeof(a)/sizeof((a)[0])))

static const MS ms_notepad = { mF_full, NA(mF_full), mE_full, NA(mE_full),
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_sheet   = { mF_save, NA(mF_save), mE_full, NA(mE_full),
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_hex     = { mF_save, NA(mF_save), mE_full, NA(mE_full),
                               mV_hex, NA(mV_hex), mH_about, NA(mH_about) };
static const MS ms_calc    = { mF_quit, NA(mF_quit), mE_paste, NA(mE_paste),
                               0, 0, mH_about, NA(mH_about) };
static const MS ms_files   = { mF_quit, NA(mF_quit), 0, 0,
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
    body_at(2, 5, "  notepad sheet hex files calc", SCREEN_W - 4);
    body_at(2, 6, "  ask garden hxhnt rpg lsys saver", SCREEN_W - 4);
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
static int run_sheet(int, char**);
static int run_hex(int, char**);
static int run_files(int, char**);
static int run_calc(int, char**);
static int run_ask(int, char**);
static int run_garden(int, char**);
static int run_lsys  (int, char**);
static int run_hxhnt(int, char**);
static int run_rpg(int, char**);
static int run_screensaver(int, char**);
static int run_net(int, char**);
static int run_http(int, char**);
static int run_echo(int, char**);
static int run_finger(int, char**);
static int run_gopher(int, char**);
static int run_probe(int, char**);
static int run_dns(int, char**);
static int run_ftp(int, char**);
static int run_sshtel(int, char**);

/* Per-instance identity that survives PID-namespace flattening.
 * jail.c injects `--instance=<8hex>` into argv before execve so this
 * office process can identify itself even when getpid() always returns
 * 1.  Outside the jail the field stays empty and the home/net panels
 * fall back to the bare host pid. */
static char g_instance_token[24];

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
            /* If jail.c injected a per-instance token, surface it
             * alongside the pid so identity survives PID-namespace
             * flattening (every jailed office is pid 1). */
            if (g_instance_token[0]) {
                /* UTF-8 middle dot (0xC2 0xB7) emitted byte-by-byte;
                 * a `'·'` char literal is a 2-byte multi-char constant
                 * that gets truncated to 0xB7 alone, which isn't valid
                 * UTF-8 so terminals render it as garbage. */
                buf[p++] = ' ';
                buf[p++] = (char)0xC2; buf[p++] = (char)0xB7;
                buf[p++] = ' ';
                int tn = 0;
                while (g_instance_token[tn] && tn < 16) {
                    buf[p++] = g_instance_token[tn++];
                }
            }
            buf[p] = 0;
            cup(2, 2);
            sgrbgfg(COL_BAR_BG, g_genome.accent);
            fbw(buf, p);
            sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        }
        body_at(2, 3, "Welcome to Office. Built-in commands:", SCREEN_W - 4);
        body_at(2, 4, "  notepad  sheet  hex  files  calc",
                SCREEN_W - 4);
        body_at(2, 5, "  ask  garden  hxhnt  rpg  lsys",
                SCREEN_W - 4);
        body_at(2, 6, "  saver  net  http  echo  finger  gopher  probe",
                SCREEN_W - 4);
        body_at(2, 7, "  dns  ftp  sshtel  exit",
                SCREEN_W - 4);
        body_at(2, 8, "  (Alt+F / F10 opens menus in every app)", SCREEN_W - 4);
        if (msg[0]) {
            sgrbgfg(COL_BAR_BG, msg_kind == 2 ? 88 : 22);
            body_at(2, 9, msg, SCREEN_W - 4);
            sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        }
        cup(2, cur_y + 7);
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

            /* office66: each match is independent + #if-gated.  When
             * a feature's flag is 0 the line drops out, the function
             * is unreferenced, and --gc-sections strips its bytes. */
            int rc = -1;
            int matched = 0;
#if OFFICE_FEATURE_NOTEPAD
            if (!matched && scmp(cmd, "notepad") == 0) { rc = run_notepad(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_SHEET
            if (!matched && scmp(cmd, "sheet") == 0)   { rc = run_sheet(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_HEX
            if (!matched && scmp(cmd, "hex") == 0)     { rc = run_hex(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_FILES
            if (!matched && scmp(cmd, "files") == 0)   { rc = run_files(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_CALC
            if (!matched && scmp(cmd, "calc") == 0)    { rc = run_calc(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_ASK
            if (!matched && scmp(cmd, "ask") == 0)     { rc = run_ask(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_GARDEN
            if (!matched && scmp(cmd, "garden") == 0)  { rc = run_garden(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_HXHNT
            if (!matched && scmp(cmd, "hxhnt") == 0)   { rc = run_hxhnt(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_RPG
            if (!matched && scmp(cmd, "rpg") == 0)     { rc = run_rpg(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_LSYS
            if (!matched && scmp(cmd, "lsys") == 0)    { rc = run_lsys(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_SCREENSAVER
            if (!matched && (scmp(cmd, "saver") == 0 || scmp(cmd, "screensaver") == 0))
                                                       { rc = run_screensaver(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_NET
            if (!matched && scmp(cmd, "net") == 0)     { rc = run_net(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_HTTP
            if (!matched && scmp(cmd, "http") == 0)    { rc = run_http(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_ECHO
            if (!matched && scmp(cmd, "echo") == 0)    { rc = run_echo(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_FINGER
            if (!matched && scmp(cmd, "finger") == 0)  { rc = run_finger(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_GOPHER
            if (!matched && scmp(cmd, "gopher") == 0)  { rc = run_gopher(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_PROBE
            if (!matched && scmp(cmd, "probe") == 0)   { rc = run_probe(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_DNS
            if (!matched && scmp(cmd, "dns") == 0)     { rc = run_dns(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_FTP
            if (!matched && scmp(cmd, "ftp") == 0)     { rc = run_ftp(sub_argc, sub_argv); matched = 1; }
#endif
#if OFFICE_FEATURE_SSHTEL
            if (!matched && scmp(cmd, "sshtel") == 0)  { rc = run_sshtel(sub_argc, sub_argv); matched = 1; }
#endif
            if (!matched) { mcpy(msg, "unknown command", 16); msg_kind = 2; }

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

static void notepad_draw(const char *title) {
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
                while (o < blen && buf[o] != '\n') o++;
                break;
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
    if (cur_sx < 0) {
        cur_sx = 2;
        cur_sy = y < SCREEN_H - 1 ? y : SCREEN_H - 2;
    }
    if (cur_sy >= SCREEN_H - 1) cur_sy = SCREEN_H - 2;
    status("  arrows | enter | bksp | ^S save | ^Q quit");
    cup(cur_sx, cur_sy);
    fbs(ESC "[?25h");
    fbflush();
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

static int notepad_loop(const char *title) {
    term_raw();
    while (1) {
        adjust_btop(SCREEN_H - 4);
        notepad_draw(title);
        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        int act = -1, mi = menu_activation(k, n);
        if (mi >= 0) act = menu_run(&ms_notepad, mi);
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
    return notepad_loop("Notepad");
}


/* ── sheet: CSV view + arrow-key navigation, single-cell edit ── */
#define SHEET_COLS 8
#define SHEET_ROWS 12
#define CELL_W     9
#define NSHEETS    3                  /* office55: A · B · C */

static char  cell[NSHEETS][SHEET_ROWS][SHEET_COLS][16];
static int   cellrow, cellcol;
static int   cur_sheet;               /* 0 = A, 1 = B, 2 = C */
static char  sheet_msg[64];           /* status line for matrix-multiply */

/* office65: cell macros — sparse table of "after this cell's value
 * changes, write these other cells" rules.  Macro slot 0xFF in the
 * sheet byte means unused.  16 slots is more than enough for the 8×12
 * grid; macros are deliberately rare ("special wiring"). */
#define MAX_MACROS 16
#define MACRO_LEN  40
static unsigned char macro_loc[MAX_MACROS][3];   /* sheet, row, col */
static char          macro_text[MAX_MACROS][MACRO_LEN];
static long long     macro_prev[MAX_MACROS];
/* Self coords for the running macro — feval atoms read these when the
 * `self` keyword appears in EXPR. */
static int macro_self_row, macro_self_col;
/* Pending writes accumulated within one macro firing — applied as a
 * single batch at the end so two statements `D5=self; E5=self*2`
 * see the same `self`, not the half-updated state. */
struct macro_write { unsigned char sheet, row, col; char text[16]; };
static struct macro_write macro_pending[8];
static int macro_pending_n;

/* tiny formula evaluator: =EXPR with + - * / % ^, parens, cell refs A1..H12.
 * 64-bit math (long long) so 2^32, big matrix products etc. stay precise. */
static const char *fp;
static long long feval_expr(int depth);

static void fskip_ws(void) { while (*fp == ' ' || *fp == '\t') fp++; }

static long long parse_int_literal(const char *s) {
    long long v = 0; int neg = 0;
    if (*s == '-') { neg = 1; s++; }
    while (*s >= '0' && *s <= '9') { v = v * 10 + (*s - '0'); s++; }
    return neg ? -v : v;
}

static long long feval_cell(int row, int col, int depth) {
    if (row < 0 || row >= SHEET_ROWS || col < 0 || col >= SHEET_COLS) return 0;
    if (depth <= 0) return 0;
    const char *t = cell[cur_sheet][row][col];
    if (t[0] == '=') {
        const char *save = fp;
        fp = t + 1;
        long long v = feval_expr(depth - 1);
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

/* Reduce a SUM/AVG/MIN/MAX range to a single value. kind: 0 sum, 1 avg, 2 min, 3 max */
static long long range_reduce(int kind, int depth) {
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
    long long acc = 0;
    int       count = 0;
    long long best = 0; int has = 0;
    for (int r = r1; r <= r2; r++) {
        for (int c = c1; c <= c2; c++) {
            long long v = feval_cell(r, c, depth);
            acc += v; count++;
            if (!has) { best = v; has = 1; }
            else if (kind == 2 && v < best) best = v;
            else if (kind == 3 && v > best) best = v;
        }
    }
    if (kind == 0) return acc;
    if (kind == 1) return count ? (acc / count) : 0;
    return best;
}

/* Binary logic dispatch. tt is the 4-bit truth table indexed by
 * (a,b): bit 0 → (0,0), bit 1 → (0,1), bit 2 → (1,0), bit 3 → (1,1).
 * Applied bitwise across all 64 bits of a and b. */
static long long binlog(long long a, long long b, int tt) {
    long long r = 0;
    if (tt & 1) r |= ~a & ~b;
    if (tt & 2) r |= ~a & b;
    if (tt & 4) r |= a & ~b;
    if (tt & 8) r |= a & b;
    return r;
}

static const struct { const char *name; unsigned char tt; } LOG_OPS[16] = {
    {"FAL", 0},  {"NOR", 1},  {"NIA", 2},  {"NOTA", 3},
    {"NIB", 4},  {"NOTB", 5}, {"XOR", 6},  {"NAND", 7},
    {"AND", 8},  {"XNOR", 9}, {"IDB", 10}, {"IMP", 11},
    {"IDA", 12}, {"CIMP", 13},{"OR", 14},  {"TRU", 15},
};

static long long ipow_(long long base, long long exp) {
    if (exp < 0) return 0;
    long long r = 1;
    while (exp > 0) {
        if (exp & 1) r *= base;
        base *= base;
        exp >>= 1;
    }
    return r;
}

static long long isqrt_(long long n) {
    if (n < 2) return n < 0 ? 0 : n;
    long long x = n, y = (x + 1) / 2;
    while (y < x) { x = y; y = (x + n / x) / 2; }
    return x;
}

static long long feval_pow(int depth);

static long long feval_atom(int depth) {
    fskip_ws();
    if (*fp == '(') {
        fp++;
        long long v = feval_expr(depth);
        fskip_ws();
        if (*fp == ')') fp++;
        return v;
    }
    if (*fp == '-') { fp++; return -feval_atom(depth); }
    if (*fp == '+') { fp++; return  feval_atom(depth); }
    if (*fp >= '0' && *fp <= '9') {
        long long v = 0;
        while (*fp >= '0' && *fp <= '9') { v = v * 10 + (*fp - '0'); fp++; }
        return v;
    }
    if (match_func("SUM")) return range_reduce(0, depth);
    if (match_func("AVG")) return range_reduce(1, depth);
    if (match_func("MIN")) return range_reduce(2, depth);
    if (match_func("MAX")) return range_reduce(3, depth);
    if (match_func("ABS")) {
        long long a = feval_expr(depth);
        fskip_ws(); if (*fp == ')') fp++;
        return a < 0 ? -a : a;
    }
    if (match_func("SQRT")) {
        long long a = feval_expr(depth);
        fskip_ws(); if (*fp == ')') fp++;
        return isqrt_(a);
    }
    if (match_func("SQR")) {
        long long a = feval_expr(depth);
        fskip_ws(); if (*fp == ')') fp++;
        return a * a;
    }
    if (match_func("SIGN")) {
        long long a = feval_expr(depth);
        fskip_ws(); if (*fp == ')') fp++;
        return a > 0 ? 1 : (a < 0 ? -1 : 0);
    }
    if (match_func("MIN2")) {
        long long a = feval_expr(depth);
        fskip_ws(); if (*fp == ',') fp++;
        long long b = feval_expr(depth);
        fskip_ws(); if (*fp == ')') fp++;
        return a < b ? a : b;
    }
    if (match_func("MAX2")) {
        long long a = feval_expr(depth);
        fskip_ws(); if (*fp == ',') fp++;
        long long b = feval_expr(depth);
        fskip_ws(); if (*fp == ')') fp++;
        return a > b ? a : b;
    }
    for (int i = 0; i < 16; i++) {
        if (match_func(LOG_OPS[i].name)) {
            long long a = feval_expr(depth);
            fskip_ws(); if (*fp == ',') fp++;
            long long b = feval_expr(depth);
            fskip_ws(); if (*fp == ')') fp++;
            return binlog(a, b, LOG_OPS[i].tt);
        }
    }
    /* office65: VALUE(REF) — synonym for the bare cell ref, useful in
     * macros where the user wants explicit "this is a value lookup".
     * `value(A1)` and `A1` evaluate identically. */
    if (match_func("VALUE")) {
        int r, c;
        long long v = 0;
        if (try_cellref(&r, &c)) v = feval_cell(r, c, depth);
        fskip_ws();
        if (*fp == ')') fp++;
        return v;
    }
    /* office65: `self` keyword — the cell on which the running macro
     * is attached.  macro_self_row/col are set by macro_run_one before
     * this evaluator is invoked.  Outside the macro path the keyword
     * still parses but reads the current selection, which is harmless
     * (formulas can use `self` too if anyone wants). */
    if ((fp[0] == 's' || fp[0] == 'S') &&
        (fp[1] == 'e' || fp[1] == 'E') &&
        (fp[2] == 'l' || fp[2] == 'L') &&
        (fp[3] == 'f' || fp[3] == 'F') &&
        !((fp[4] >= 'a' && fp[4] <= 'z') ||
          (fp[4] >= 'A' && fp[4] <= 'Z') ||
          (fp[4] >= '0' && fp[4] <= '9'))) {
        fp += 4;
        return feval_cell(macro_self_row, macro_self_col, depth);
    }
    int row, col;
    if (try_cellref(&row, &col)) return feval_cell(row, col, depth);
    return 0;
}

static long long feval_pow(int depth) {
    long long v = feval_atom(depth);
    fskip_ws();
    if (*fp == '^') {
        fp++;
        long long e = feval_pow(depth);
        return ipow_(v, e);
    }
    return v;
}

static long long feval_term(int depth) {
    long long v = feval_pow(depth);
    while (1) {
        fskip_ws();
        if (*fp == '*') { fp++; v *= feval_pow(depth); }
        else if (*fp == '/') { fp++; long long d = feval_pow(depth); v = d ? v / d : 0; }
        else if (*fp == '%') { fp++; long long d = feval_pow(depth); v = d ? v % d : 0; }
        else break;
    }
    return v;
}

static long long feval_expr(int depth) {
    long long v = feval_term(depth);
    while (1) {
        fskip_ws();
        if (*fp == '+') { fp++; v += feval_term(depth); }
        else if (*fp == '-') { fp++; v -= feval_term(depth); }
        else break;
    }
    return v;
}

static long long sheet_eval(const char *formula) {
    fp = formula + 1;
    return feval_expr(8);
}


/* Forward decl — litoa_ is defined further down (in the matrix-multiply
 * helper block) but the macro engine here needs it to format result
 * values into pending writes. */
static int litoa_(long long v, char *out);


/* ── office65: cell-macro engine ──────────────────────────
 * After every user commit (Enter on edit, paste, cut, Excel-overwrite
 * commit), macro_pass walks the 16-slot sparse macro table, fires
 * each macro whose source cell's evaluated value has actually changed
 * since the last pass, then re-snapshots prev values so cascades
 * caused by macro writes don't trigger another firing.
 *
 * DSL: `DST = EXPR ; DST = EXPR ; ...`
 *   DST  = cell ref like A1, H12 (current sheet only)
 *   EXPR = literal | cell-ref | self | VALUE(ref) | EXPR ± * / % ^ EXPR
 *          (whatever feval_expr already understands, plus self/VALUE)
 * Statements separated by ';' or newline.  Up to 8 pending writes per
 * firing — sufficient for the dashboard use case of "one source feeds
 * a handful of derived cells". */

static long long macro_eval_at(int s, int r, int c) {
    int saved = cur_sheet;
    cur_sheet = s;
    long long v;
    const char *t = cell[s][r][c];
    if (t[0] == '=') v = sheet_eval(t);
    else              v = parse_int_literal(t);
    cur_sheet = saved;
    return v;
}

static int macro_find(int s, int r, int c) {
    for (int i = 0; i < MAX_MACROS; i++) {
        if (macro_loc[i][0] == (unsigned char)s &&
            macro_loc[i][1] == (unsigned char)r &&
            macro_loc[i][2] == (unsigned char)c &&
            macro_loc[i][0] != 0xFF) return i;
    }
    return -1;
}

static int macro_alloc(int s, int r, int c) {
    int i = macro_find(s, r, c);
    if (i >= 0) return i;
    for (int j = 0; j < MAX_MACROS; j++) {
        if (macro_loc[j][0] == 0xFF) {
            macro_loc[j][0] = (unsigned char)s;
            macro_loc[j][1] = (unsigned char)r;
            macro_loc[j][2] = (unsigned char)c;
            macro_text[j][0] = 0;
            macro_prev[j] = macro_eval_at(s, r, c);
            return j;
        }
    }
    return -1;
}

static void macro_clear_slot(int idx) {
    macro_loc[idx][0] = 0xFF;
    macro_text[idx][0] = 0;
    macro_prev[idx] = 0;
}

static void macros_init(void) {
    for (int i = 0; i < MAX_MACROS; i++) {
        macro_loc[i][0] = 0xFF;
        macro_text[i][0] = 0;
        macro_prev[i] = 0;
    }
}

/* Parse a DST cell-ref at *p, advance past it.  Returns 1 on success. */
static int macro_parse_dst(const char **p, int *row, int *col) {
    const char *s = *p;
    while (*s == ' ' || *s == '\t') s++;
    int c = -1;
    if (*s >= 'A' && *s <= 'H') c = *s - 'A';
    else if (*s >= 'a' && *s <= 'h') c = *s - 'a';
    if (c < 0) return 0;
    s++;
    if (*s < '0' || *s > '9') return 0;
    int r = 0;
    while (*s >= '0' && *s <= '9') { r = r * 10 + (*s - '0'); s++; }
    if (r < 1 || r > SHEET_ROWS) return 0;
    *row = r - 1;
    *col = c;
    *p = s;
    return 1;
}

/* Run one macro: parse the DSL, buffer writes, apply atomically. */
static void macro_run_one(int slot) {
    int s = macro_loc[slot][0];
    macro_self_row = macro_loc[slot][1];
    macro_self_col = macro_loc[slot][2];
    int saved_sheet = cur_sheet;
    cur_sheet = s;
    macro_pending_n = 0;

    const char *p = macro_text[slot];
    while (*p) {
        while (*p == ' ' || *p == '\t' || *p == ';' || *p == '\n') p++;
        if (!*p) break;
        int dst_row, dst_col;
        if (!macro_parse_dst(&p, &dst_row, &dst_col)) {
            while (*p && *p != ';' && *p != '\n') p++;
            continue;
        }
        while (*p == ' ' || *p == '\t') p++;
        if (*p != '=') {
            while (*p && *p != ';' && *p != '\n') p++;
            continue;
        }
        p++;
        while (*p == ' ' || *p == '\t') p++;
        /* feval_expr advances `fp` until it can't continue; pass it
         * into the rest-of-statement and read fp back to know where
         * to resume. */
        fp = p;
        long long v = feval_expr(8);
        p = fp;
        if (macro_pending_n < 8) {
            macro_pending[macro_pending_n].sheet = (unsigned char)s;
            macro_pending[macro_pending_n].row   = (unsigned char)dst_row;
            macro_pending[macro_pending_n].col   = (unsigned char)dst_col;
            int n = litoa_(v, macro_pending[macro_pending_n].text);
            if (n > 15) n = 15;
            macro_pending[macro_pending_n].text[n] = 0;
            macro_pending_n++;
        }
        while (*p && *p != ';' && *p != '\n') p++;
    }

    /* Apply pending writes atomically. */
    for (int i = 0; i < macro_pending_n; i++) {
        int ws = macro_pending[i].sheet;
        int wr = macro_pending[i].row;
        int wc = macro_pending[i].col;
        int n = slen(macro_pending[i].text);
        if (n > 15) n = 15;
        for (int j = 0; j < n; j++) cell[ws][wr][wc][j] = macro_pending[i].text[j];
        cell[ws][wr][wc][n] = 0;
    }
    cur_sheet = saved_sheet;
}

/* One-pass macro engine — call after any user commit.  Decides which
 * macros to fire based on source-cell value diff vs. last pass, fires
 * them in slot order, then re-snapshots prev_val so cells that were
 * mutated by macro writes don't trigger their own macros next pass. */
static void macro_pass(void) {
    long long cur_vals[MAX_MACROS];
    int       fire[MAX_MACROS];
    for (int i = 0; i < MAX_MACROS; i++) {
        fire[i] = 0;
        cur_vals[i] = 0;
        if (macro_loc[i][0] == 0xFF) continue;
        cur_vals[i] = macro_eval_at(
            macro_loc[i][0], macro_loc[i][1], macro_loc[i][2]);
        if (cur_vals[i] != macro_prev[i]) fire[i] = 1;
    }
    for (int i = 0; i < MAX_MACROS; i++) {
        if (fire[i]) macro_run_one(i);
    }
    /* Re-snapshot prev values *after* writes — this is what kills
     * cascading.  If macro A wrote to cell D and D has its own macro,
     * D's prev gets updated to its new (post-write) value, so on the
     * next user commit it won't spuriously fire. */
    for (int i = 0; i < MAX_MACROS; i++) {
        if (macro_loc[i][0] == 0xFF) continue;
        macro_prev[i] = macro_eval_at(
            macro_loc[i][0], macro_loc[i][1], macro_loc[i][2]);
    }
}

/* 64-bit signed → string.  Buffer should hold at least 21 bytes
 * ("-9223372036854775808" + NUL).  Returns digits written. */
static int litoa_(long long v, char *out) {
    int n = 0;
    unsigned long long u;
    if (v < 0) {
        out[n++] = '-';
        u = (unsigned long long)(-(v + 1)) + 1ULL; /* handles LLONG_MIN */
    } else {
        u = (unsigned long long)v;
    }
    char t[24]; int tn = 0;
    if (!u) t[tn++] = '0';
    while (u) { t[tn++] = (char)('0' + (int)(u % 10)); u /= 10; }
    for (int i = 0; i < tn; i++) out[n + i] = t[tn - 1 - i];
    return n + tn;
}

static int itoa_(int v, char *out) {
    return litoa_((long long)v, out);
}

static void sheet_load_csv(void) {
    /* Wipe only the active sheet — A/B/C survive each other's loads.
     * Also clear macros for this sheet so an empty MACROS section in
     * the file means "no macros", not "keep the in-memory ones". */
    mset(cell[cur_sheet], 0, sizeof cell[cur_sheet]);
    for (int i = 0; i < MAX_MACROS; i++) {
        if (macro_loc[i][0] == (unsigned char)cur_sheet)
            macro_clear_slot(i);
    }
    /* Locate optional MACROS: section so the cell loader stops before
     * it and the macro loader knows where to start. */
    int macros_pos = -1;
    for (int o = 0; o < blen - 7; o++) {
        if ((o == 0 || buf[o - 1] == '\n') &&
            buf[o] == 'M' && buf[o+1] == 'A' && buf[o+2] == 'C' &&
            buf[o+3] == 'R' && buf[o+4] == 'O' && buf[o+5] == 'S' &&
            buf[o+6] == ':') {
            macros_pos = o;
            break;
        }
    }
    int cell_end = macros_pos < 0 ? blen : macros_pos;
    int r = 0, c = 0, i = 0;
    for (int o = 0; o < cell_end && r < SHEET_ROWS; o++) {
        char ch = buf[o];
        if (ch == ',') {
            cell[cur_sheet][r][c][i] = 0;
            if (c < SHEET_COLS - 1) c++;
            i = 0;
        } else if (ch == '\n') {
            cell[cur_sheet][r][c][i] = 0;
            r++; c = 0; i = 0;
        } else if (i < 15) {
            cell[cur_sheet][r][c][i++] = ch;
        }
    }
    if (macros_pos < 0) return;
    /* Parse "<col><row>=><text>\n" lines after the MACROS: header. */
    int o = macros_pos + 7;
    while (o < blen && buf[o] != '\n') o++;
    if (o < blen) o++;
    while (o < blen) {
        if (!(buf[o] >= 'A' && buf[o] <= 'H')) break;
        int mc = buf[o] - 'A'; o++;
        int mr = 0;
        while (o < blen && buf[o] >= '0' && buf[o] <= '9') {
            mr = mr * 10 + (buf[o] - '0'); o++;
        }
        if (mr < 1 || mr > SHEET_ROWS) {
            while (o < blen && buf[o] != '\n') o++;
            if (o < blen) o++;
            continue;
        }
        mr--;
        if (o + 1 >= blen || buf[o] != '=' || buf[o + 1] != '>') {
            while (o < blen && buf[o] != '\n') o++;
            if (o < blen) o++;
            continue;
        }
        o += 2;
        int slot = macro_alloc(cur_sheet, mr, mc);
        int ti = 0;
        while (o < blen && buf[o] != '\n' && ti < MACRO_LEN - 1) {
            if (slot >= 0) macro_text[slot][ti] = buf[o];
            ti++; o++;
        }
        if (slot >= 0) {
            macro_text[slot][ti] = 0;
            macro_prev[slot] = macro_eval_at(cur_sheet, mr, mc);
        }
        if (o < blen) o++;
    }
}

/* Forward decl — sapp + sheet_app_int are defined later (sapp in
 * the suite-wide helper block, sheet_app_int as part of the matrix-
 * multiply helper block).  sheet_save_csv + sheet_make_save_fname
 * use both. */
static int sapp(char *dst, int at, const char *s);
static int sheet_app_int(char *dst, int at, int v);
/* Build "sheet<X>_<YYYY><mon><DD>-<HHMM>-<SS>.csv" into out.
 * <X> = 'A' + cur_sheet, date in local time via g_tz_offset_sec. */
static const char SHEET_MON_NAME[12][4] = {
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec"
};
static int sheet_make_save_fname(char *out) {
    long t = time_() + g_tz_offset_sec;
    int Y, Mo, D, h, mi, se;
    unix_to_calendar(t, &Y, &Mo, &D, &h, &mi, &se);
    int n = sapp(out, 0, "sheet");
    out[n++] = (char)('A' + cur_sheet);
    out[n++] = '_';
    n += utoa((unsigned)Y, out + n);
    n = sapp(out, n, SHEET_MON_NAME[(Mo - 1) & 0xf]);
    n += u2((unsigned)D, out + n);
    out[n++] = '-';
    n += u2((unsigned)h, out + n);
    n += u2((unsigned)mi, out + n);
    out[n++] = '-';
    n += u2((unsigned)se, out + n);
    n = sapp(out, n, ".csv");
    out[n] = 0;
    return n;
}
static void sheet_save_csv(void) {
    char savefn[64];
    sheet_make_save_fname(savefn);
    blen = 0;
    for (int r = 0; r < SHEET_ROWS; r++) {
        for (int c = 0; c < SHEET_COLS; c++) {
            int n = slen(cell[cur_sheet][r][c]);
            for (int i = 0; i < n && blen < BUF_CAP - 2; i++) buf[blen++] = cell[cur_sheet][r][c][i];
            if (c < SHEET_COLS - 1 && blen < BUF_CAP - 1) buf[blen++] = ',';
        }
        if (blen < BUF_CAP - 1) buf[blen++] = '\n';
    }
    /* office65: append a MACROS: section if the active sheet has any.
     * Format: one line per macro, "<col><row>=><dsl-text>", e.g.
     * `A1=>D5=self;E5=self*2`.  sheet_load_csv detects the header and
     * parses these into the sparse macro table. */
    int header_written = 0;
    for (int i = 0; i < MAX_MACROS; i++) {
        if (macro_loc[i][0] != (unsigned char)cur_sheet) continue;
        if (!macro_text[i][0]) continue;
        if (!header_written) {
            const char *hdr = "MACROS:\n";
            for (int j = 0; hdr[j] && blen < BUF_CAP - 1; j++)
                buf[blen++] = hdr[j];
            header_written = 1;
        }
        if (blen < BUF_CAP - 4) buf[blen++] = (char)('A' + macro_loc[i][2]);
        blen += utoa((unsigned)(macro_loc[i][1] + 1), buf + blen);
        if (blen < BUF_CAP - 2) { buf[blen++] = '='; buf[blen++] = '>'; }
        for (int j = 0; macro_text[i][j] && blen < BUF_CAP - 2; j++)
            buf[blen++] = macro_text[i][j];
        if (blen < BUF_CAP - 1) buf[blen++] = '\n';
    }
    int rc = save_file(savefn);
    int n = 0;
    sheet_msg[0] = 0;
    if (rc < 0) {
        n = sapp(sheet_msg, 0, " ERR: save failed");
    } else {
        n = sapp(sheet_msg, 0, " saved -> ");
        n = sapp(sheet_msg, n, savefn);
        n = sapp(sheet_msg, n, " (");
        n = sheet_app_int(sheet_msg, n, blen);
        n = sapp(sheet_msg, n, " B)");
    }
    sheet_msg[n] = 0;
}

/* office55 matrix-multiply helpers — auto-detect each sheet's
 * filled rectangle and compute A·B → C with int values, evaluating
 * formula cells through the existing feval_expr path.  `sapp` is
 * the string-append helper defined later; forward-decl + a small
 * append-int helper keep the multiply code tight. */
static int sapp(char *dst, int at, const char *s);
static int sheet_app_int(char *dst, int at, int v) {
    char tmp[12];
    int  tn = itoa_(v, tmp);
    mcpy(dst + at, tmp, tn);
    return at + tn;
}
static void sheet_dims(int s, int *rows, int *cols) {
    int mr = -1, mc = -1;
    for (int r = 0; r < SHEET_ROWS; r++) {
        for (int c = 0; c < SHEET_COLS; c++) {
            if (cell[s][r][c][0]) {
                if (r > mr) mr = r;
                if (c > mc) mc = c;
            }
        }
    }
    *rows = mr + 1;
    *cols = mc + 1;
}
static long long read_int_in_sheet(int s, int r, int c) {
    int saved = cur_sheet;
    cur_sheet = s;
    const char *t = cell[s][r][c];
    long long v = (t[0] == '=') ? sheet_eval(t) : parse_int_literal(t);
    cur_sheet = saved;
    return v;
}
/* Common: write a 64-bit int into cell[2][r][c] truncated to 15 chars. */
static void sheet_put_int(int r, int c, long long v) {
    char tmp[24];
    int  tn = litoa_(v, tmp);
    if (tn > 15) tn = 15;
    mcpy(cell[2][r][c], tmp, tn);
    cell[2][r][c][tn] = 0;
}

/* Zero-pad multiply (M).  inner = max(A.cols, B.rows); A treated as
 * m×inner with zeros past A.cols, B as inner×q with zeros past
 * B.rows.  Result is m×q, never errors on dim mismatch. */
static void sheet_multiply(void) {
    int ar, ac, br, bc;
    sheet_dims(0, &ar, &ac);
    sheet_dims(1, &br, &bc);
    int n = 0;
    sheet_msg[0] = 0;
    if (ar == 0 || ac == 0) { sheet_msg[sapp(sheet_msg, 0, " A empty")] = 0; return; }
    if (br == 0 || bc == 0) { sheet_msg[sapp(sheet_msg, 0, " B empty")] = 0; return; }
    int inner = (ac > br) ? ac : br;
    mset(cell[2], 0, sizeof cell[2]);
    for (int i = 0; i < ar; i++) {
        for (int j = 0; j < bc; j++) {
            long long acc = 0;
            for (int k = 0; k < inner; k++) {
                long long aV = (k < ac) ? read_int_in_sheet(0, i, k) : 0;
                long long bV = (k < br) ? read_int_in_sheet(1, k, j) : 0;
                acc += aV * bV;
            }
            sheet_put_int(i, j, acc);
        }
    }
    n = sapp(sheet_msg, 0, " C=A.B ");
    n = sheet_app_int(sheet_msg, n, ar);
    sheet_msg[n++] = 'x';
    n = sheet_app_int(sheet_msg, n, ac);
    sheet_msg[n++] = ' ';
    n = sheet_app_int(sheet_msg, n, br);
    sheet_msg[n++] = 'x';
    n = sheet_app_int(sheet_msg, n, bc);
    n = sapp(sheet_msg, n, " -> ");
    n = sheet_app_int(sheet_msg, n, ar);
    sheet_msg[n++] = 'x';
    n = sheet_app_int(sheet_msg, n, bc);
    if (ac != br) n = sapp(sheet_msg, n, " pad");
    sheet_msg[n] = 0;
    cur_sheet = 2;
    cellrow = 0; cellcol = 0;
}

/* Kronecker product (K).  C = A⊗B.  C is (ar*br) × (ac*bc); each
 * block (i, j) is A[i][j]·B.  Truncated to fit the 12×8 sheet cap. */
static void sheet_kronecker(void) {
    int ar, ac, br, bc;
    sheet_dims(0, &ar, &ac);
    sheet_dims(1, &br, &bc);
    int n = 0;
    sheet_msg[0] = 0;
    if (ar == 0 || ac == 0) { sheet_msg[sapp(sheet_msg, 0, " A empty")] = 0; return; }
    if (br == 0 || bc == 0) { sheet_msg[sapp(sheet_msg, 0, " B empty")] = 0; return; }
    int outR = ar * br, outC = ac * bc;
    int useR = (outR > SHEET_ROWS) ? SHEET_ROWS : outR;
    int useC = (outC > SHEET_COLS) ? SHEET_COLS : outC;
    mset(cell[2], 0, sizeof cell[2]);
    for (int i = 0; i < ar; i++) {
        for (int j = 0; j < ac; j++) {
            long long aV = read_int_in_sheet(0, i, j);
            for (int p = 0; p < br; p++) {
                int rr = i * br + p;
                if (rr >= useR) break;
                for (int q = 0; q < bc; q++) {
                    int cc = j * bc + q;
                    if (cc >= useC) break;
                    long long bV = read_int_in_sheet(1, p, q);
                    sheet_put_int(rr, cc, aV * bV);
                }
            }
        }
    }
    n = sapp(sheet_msg, 0, " C=AxB(k) ");
    n = sheet_app_int(sheet_msg, n, ar);
    sheet_msg[n++] = 'x';
    n = sheet_app_int(sheet_msg, n, ac);
    sheet_msg[n++] = ' ';
    n = sheet_app_int(sheet_msg, n, br);
    sheet_msg[n++] = 'x';
    n = sheet_app_int(sheet_msg, n, bc);
    n = sapp(sheet_msg, n, " -> ");
    n = sheet_app_int(sheet_msg, n, useR);
    sheet_msg[n++] = 'x';
    n = sheet_app_int(sheet_msg, n, useC);
    if (outR > useR || outC > useC) n = sapp(sheet_msg, n, " clip");
    sheet_msg[n] = 0;
    cur_sheet = 2;
    cellrow = 0; cellcol = 0;
}

static int run_sheet(int argc, char **argv) {
    current_ms = &ms_sheet;
    cur_sheet = 0;
    sheet_msg[0] = 0;
    macros_init();
    if (argc > 1 && argv[1][0]) {
        load_file(argv[1]);
        sheet_load_csv();
    } else {
        /* Wipe all 3 sheets so a fresh launch starts clean. */
        mset(cell, 0, sizeof cell);
        fname[0] = 0;
    }
    cellrow = 0; cellcol = 0;
    term_raw();

    int editing = 0;
    int editing_macro = 0;
    int eidx = 0;
    /* Macro edit buffer — separate from the cell text since macros
     * are 40 chars vs cells' 16 chars and we don't want to clobber
     * cell data while the user is composing a macro. */
    static char macro_edit_buf[MACRO_LEN];

    while (1) {
        paint_desktop();
        chrome("Sheet");
        body_clear();
        /* Tab strip at row 1 — `[A] B  C`-style with active inverted. */
        cup(2, 1);
        for (int s = 0; s < NSHEETS; s++) {
            if (s == cur_sheet) sgrbgfg(15, 0);
            else                sgrbgfg(7, 0);
            fbw(" ", 1);
            fbw(s == cur_sheet ? "[" : " ", 1);
            char ch = (char)('A' + s);
            fbw(&ch, 1);
            fbw(s == cur_sheet ? "]" : " ", 1);
            fbw(" ", 1);
        }
        sgrbgfg(7, 8);
        if (sheet_msg[0]) fbs(sheet_msg);
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
                char shown[24];
                int  len;
                int  is_formula = (cell[cur_sheet][r][c][0] == '=');
                if (is_formula && !(editing && sel)) {
                    long long v = sheet_eval(cell[cur_sheet][r][c]);
                    len = litoa_(v, shown);
                    if (len > CELL_W - 1) len = CELL_W - 1;
                    sgrbgfg(sel ? 15 : 7, sel ? 0 : 21);   /* blue fg = formula */
                    fbw(shown, len);
                } else {
                    len = slen(cell[cur_sheet][r][c]);
                    if (len > CELL_W - 1) len = CELL_W - 1;
                    fbw(cell[cur_sheet][r][c], len);
                }
                sgrbgfg(sel ? 15 : 7, 0);
                blanks(CELL_W - len);
            }
        }
        char hint[140] = { 0 };
        int hn = 0;
        const char *h;
        if (editing_macro) {
            /* Show the macro-edit buffer live in the status line so
             * the user can see what they're typing — the cell grid
             * doesn't have room for a 40-char DSL string. */
            hint[hn++] = ' '; hint[hn++] = ' ';
            const char *lab = "macro> ";
            for (int i = 0; lab[i] && hn < (int)sizeof hint - 2; i++)
                hint[hn++] = lab[i];
            for (int i = 0; macro_edit_buf[i] && hn < (int)sizeof hint - 2; i++)
                hint[hn++] = macro_edit_buf[i];
            hint[hn++] = '_';                /* cursor hint */
            h = "";
        } else if (editing) {
            h = "  editing — enter commits, esc cancels  (=A1+B2 for formulas)";
        } else {
            /* If the selected cell has a macro attached, surface it
             * in the status line so the user remembers it's wired. */
            int mi = macro_find(cur_sheet, cellrow, cellcol);
            if (mi >= 0 && macro_text[mi][0]) {
                hint[hn++] = ' '; hint[hn++] = ' ';
                hint[hn++] = 'm'; hint[hn++] = 'a'; hint[hn++] = 'c';
                hint[hn++] = 'r'; hint[hn++] = 'o'; hint[hn++] = ':';
                hint[hn++] = ' ';
                int mt = 0;
                while (macro_text[mi][mt] && hn < (int)sizeof hint - 2)
                    hint[hn++] = macro_text[mi][mt++];
                h = "";
            } else {
                h = "  arrows|e edit|a macro|tab/1-3|M A.B|K A(x)B|s save|q back";
            }
        }
        while (h[hn]) { hint[hn] = h[hn]; hn++; }
        status(hint);
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        if (editing_macro) {
            if (k[0] == '\r' || k[0] == '\n') {
                macro_edit_buf[eidx] = 0;
                if (eidx == 0) {
                    int mi = macro_find(cur_sheet, cellrow, cellcol);
                    if (mi >= 0) macro_clear_slot(mi);
                } else {
                    int mi = macro_alloc(cur_sheet, cellrow, cellcol);
                    if (mi >= 0) {
                        for (int i = 0; i < eidx; i++)
                            macro_text[mi][i] = macro_edit_buf[i];
                        macro_text[mi][eidx] = 0;
                        macro_prev[mi] = macro_eval_at(
                            cur_sheet, cellrow, cellcol);
                    }
                }
                editing_macro = 0;
                /* Don't fire macros here — attaching is not a value
                 * change, just wiring.  Future value changes trigger. */
                continue;
            }
            if (k[0] == 0x1b && n == 1) { editing_macro = 0; continue; }
            if (k[0] == 0x7f || k[0] == 8) {
                if (eidx > 0) macro_edit_buf[--eidx] = 0;
                continue;
            }
            if (k[0] >= 32 && k[0] < 127 && eidx < MACRO_LEN - 1) {
                macro_edit_buf[eidx++] = (char)k[0];
                macro_edit_buf[eidx] = 0;
            }
            continue;
        }

        if (editing) {
            if (k[0] == '\r' || k[0] == '\n') {
                cell[cur_sheet][cellrow][cellcol][eidx] = 0;
                editing = 0;
                macro_pass();
                continue;
            }
            if (k[0] == 0x1b && n == 1) {
                editing = 0;
                continue;
            }
            if (k[0] == 0x7f || k[0] == 8) {
                if (eidx > 0) cell[cur_sheet][cellrow][cellcol][--eidx] = 0;
                continue;
            }
            if (k[0] == 0x16) {                          /* ^V paste in edit */
                for (int i = 0; i < cb_n && eidx < 15; i++) {
                    if (cb[i] >= 32 && cb[i] < 127)
                        cell[cur_sheet][cellrow][cellcol][eidx++] = cb[i];
                }
                cell[cur_sheet][cellrow][cellcol][eidx] = 0;
                continue;
            }
            if (k[0] >= 32 && k[0] < 127 && eidx < 15) {
                cell[cur_sheet][cellrow][cellcol][eidx++] = (char)k[0];
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
            eidx = slen(cell[cur_sheet][cellrow][cellcol]);
        }
        /* office65: 'a' attaches/edits a macro on the selected cell. */
        if (k[0] == 'a') {
            int mi = macro_find(cur_sheet, cellrow, cellcol);
            if (mi >= 0) {
                int t = 0;
                while (macro_text[mi][t] && t < MACRO_LEN - 1) {
                    macro_edit_buf[t] = macro_text[mi][t]; t++;
                }
                macro_edit_buf[t] = 0;
                eidx = t;
            } else {
                macro_edit_buf[0] = 0;
                eidx = 0;
            }
            editing_macro = 1;
            continue;
        }
        /* office55 — tab cycle + 1/2/3 jump + M multiply.  Clear any
         * stale matrix-multiply message on every nav action so the
         * banner doesn't linger after the user moves on. */
        if (k[0] == '\t') {
            cur_sheet = (cur_sheet + 1) % NSHEETS;
            cellrow = 0; cellcol = 0;
            sheet_msg[0] = 0;
            continue;
        }
        if (k[0] >= '1' && k[0] <= ('0' + NSHEETS)) {
            cur_sheet = k[0] - '1';
            cellrow = 0; cellcol = 0;
            sheet_msg[0] = 0;
            continue;
        }
        if (k[0] == 'M' || k[0] == 'm') {
            sheet_multiply();
            continue;
        }
        if (k[0] == 'K' || k[0] == 'k') {
            sheet_kronecker();
            continue;
        }
        if (k[0] == 0x03 || k[0] == 0x18) {              /* copy / cut cell */
            cb_set(cell[cur_sheet][cellrow][cellcol],
                   slen(cell[cur_sheet][cellrow][cellcol]));
            if (k[0] == 0x18) {
                cell[cur_sheet][cellrow][cellcol][0] = 0;
                macro_pass();
            }
        }
        if (k[0] == 0x16) {                              /* paste cell */
            int put = cb_n; if (put > 15) put = 15;
            int j = 0;
            for (int i = 0; i < put; i++) {
                if (cb[i] >= 32 && cb[i] < 127) cell[cur_sheet][cellrow][cellcol][j++] = cb[i];
            }
            cell[cur_sheet][cellrow][cellcol][j] = 0;
            macro_pass();
        }
        if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
            switch (k[2]) {
            case 'A': if (cellrow > 0) cellrow--; break;
            case 'B': if (cellrow < SHEET_ROWS - 1) cellrow++; break;
            case 'C': if (cellcol < SHEET_COLS - 1) cellcol++; break;
            case 'D': if (cellcol > 0) cellcol--; break;
            }
        }
        /* Excel-style overwrite: any printable char that isn't a
         * reserved hotkey starts a fresh edit, replacing whatever
         * was in the cell.  Lets the user type "42" over "=A1+B2"
         * without first backspacing through the formula. */
        if (!editing && k[0] >= 32 && k[0] < 127 &&
            k[0] != 'q' && k[0] != 's' && k[0] != 'e' && k[0] != 'a' &&
            k[0] != 'm' && k[0] != 'M' && k[0] != 'k' && k[0] != 'K' &&
            !(k[0] >= '1' && k[0] <= '3')) {
            cell[cur_sheet][cellrow][cellcol][0] = (char)k[0];
            cell[cur_sheet][cellrow][cellcol][1] = 0;
            eidx = 1;
            editing = 1;
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


/* ── calc: single-line expression input ────────────────── */
static int run_calc(int argc, char **argv) {
    current_ms = &ms_calc;
    (void)argc; (void)argv;
    term_raw();
    char line[80]; int llen = 0;
    int has_result = 0; long long result = 0;
    /* Calc reuses the sheet's formula engine, which references
     * `cell[cur_sheet][][]`. Pin cur_sheet to A and zero-init that
     * sheet so cell refs evaluate to 0; sheets B and C are left
     * untouched in case the user is mid-matrix-prep. */
    cur_sheet = 0;
    mset(cell[0], 0, sizeof cell[0]);
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
            char r[24]; int rn = litoa_(result, r);
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
 * Three providers are auto-detected from the endpoint hostname
 * (office50+):
 *
 *   – api.openai.com (or anything else)  → OpenAI Chat Completions
 *     (Authorization: Bearer; messages[].content; reply in
 *     "content":"…" string at top level of choices[])
 *   – api.anthropic.com                  → Anthropic Messages
 *     (x-api-key + anthropic-version: 2023-06-01; messages with
 *     max_tokens=4096; reply in nested "text":"…" inside content[])
 *   – generativelanguage.googleapis.com  → Google Gemini
 *     (x-goog-api-key; contents[].parts[].text format with "model"
 *     role; reply in nested "text":"…" inside parts[])
 *
 * All three go through fork+execve("curl"); response lands in
 * /tmp/<APP_NAME>_resp.json and we grep content/text for the reply. */

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

/* Provider auto-detected from the endpoint hostname — picks the
 * wire format, auth header, and response parser for ask_call_curl. */
enum { ASK_PROV_OPENAI = 0, ASK_PROV_ANTHROPIC = 1, ASK_PROV_GEMINI = 2 };

static int ask_str_contains(const char *hay, const char *needle) {
    int hl = slen(hay), nl = slen(needle);
    if (nl == 0 || nl > hl) return 0;
    for (int i = 0; i + nl <= hl; i++) {
        int j = 0;
        while (j < nl && hay[i+j] == needle[j]) j++;
        if (j == nl) return 1;
    }
    return 0;
}

static int ask_provider(void) {
    if (ask_str_contains(ask_endpoint, "anthropic.com"))         return ASK_PROV_ANTHROPIC;
    if (ask_str_contains(ask_endpoint, "generativelanguage"))    return ASK_PROV_GEMINI;
    if (ask_str_contains(ask_endpoint, "googleapis.com"))        return ASK_PROV_GEMINI;
    return ASK_PROV_OPENAI;
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
    int prov = ask_provider();
    if (prov == ASK_PROV_GEMINI) {
        /* Gemini: {"contents":[{"role":"user|model","parts":[{"text":"…"}]}]} */
        at = sapp(out, at, "{\"contents\":[");
        for (int i = 0; i < ask_n_msgs; i++) {
            if (i > 0) out[at++] = ',';
            at = sapp(out, at, "{\"role\":\"");
            at = sapp(out, at, ask_msg_role[i] ? "model" : "user");
            at = sapp(out, at, "\",\"parts\":[{\"text\":\"");
            at = ask_json_esc(out, at, ask_buf + ask_msg_off[i], ask_msg_len[i]);
            at = sapp(out, at, "\"}]}");
        }
        at = sapp(out, at, "]}");
        return at;
    }
    /* OpenAI + Anthropic both use messages[].  Anthropic also needs
     * a top-level max_tokens field, and rejects model strings it
     * doesn't recognise — but the user supplies the model, so we
     * just pass it through. */
    at = sapp(out, at, "{\"model\":\"");
    at = ask_json_esc(out, at, ask_model, slen(ask_model));
    /* office50 — always cap max_tokens.  Anthropic *requires* it; for
     * OpenAI / proxies it's optional, but the pekpik proxy was
     * applying a very large default per call against GPT-5.5 keys
     * (eating the whole rate-limit budget on every message). */
    at = sapp(out, at, "\",\"max_tokens\":1024,\"messages\":[");
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

/* Find first "<key>":"..." string in JSON, decoding \" \n \t \\ \/ \uXXXX.
 * Skips any "<key>":[...] / "<key>":{...} occurrences (Anthropic's
 * outer "content" is an array; Gemini's outer "content" is an
 * object — in both cases we want the inner "text" string). */
static int ask_extract_string(const char *src, int sn, const char *key,
                              char *out, int cap) {
    int kl = slen(key);
    for (int i = 0; i + kl + 3 < sn; i++) {
        if (src[i] != '"') continue;
        int j = 0;
        while (j < kl && src[i+1+j] == key[j]) j++;
        if (j != kl) continue;
        if (src[i+1+kl] != '"' || src[i+2+kl] != ':') continue;
        int k = i + 3 + kl;
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

/* Provider-aware response parser.  OpenAI puts the assistant reply
 * in "content":"…"; Anthropic + Gemini both nest a "text":"…" string
 * inside their respective array structures.  We try OpenAI's key
 * first, then fall back to "text". */
static int ask_extract_content(const char *src, int sn, char *out, int cap) {
    int n = ask_extract_string(src, sn, "content", out, cap);
    if (n >= 0) return n;
    return ask_extract_string(src, sn, "text", out, cap);
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

    int prov = ask_provider();
    static char auth[ASK_KEY_CAP + 32];
    int an = 0;
    if (prov == ASK_PROV_ANTHROPIC) {
        an = sapp(auth, an, "x-api-key: ");
    } else if (prov == ASK_PROV_GEMINI) {
        an = sapp(auth, an, "x-goog-api-key: ");
    } else {
        an = sapp(auth, an, "Authorization: Bearer ");
    }
    an = sapp(auth, an, ask_api_key);
    auth[an] = 0;

    char *argv_[20];
    int ai = 0;
    argv_[ai++] = (char *)"curl";
    argv_[ai++] = (char *)"-sS";
    argv_[ai++] = (char *)"-X"; argv_[ai++] = (char *)"POST";
    argv_[ai++] = (char *)"-H"; argv_[ai++] = (char *)"Content-Type: application/json";
    argv_[ai++] = (char *)"-H"; argv_[ai++] = auth;
    if (prov == ASK_PROV_ANTHROPIC) {
        argv_[ai++] = (char *)"-H";
        argv_[ai++] = (char *)"anthropic-version: 2023-06-01";
    }
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

/* office50 — provider-aware key grabber.  Pulls the constantly-
 * refreshed README.md from alistaitsacle/free-llm-api-keys, which
 * is organised as `### <Provider>` sections, each holding a markdown
 * table of `` `<key>` `` cells.  We track the current section, and
 * only sample from the section that matches the Ask app's currently
 * configured provider (OpenAI → "GPT" or "OpenAI"; Anthropic →
 * "Claude" or "Anthropic"; Gemini → "Gemini").  If no matching
 * section is found, fall back to any backtick-token in the file. */
#define ASK_KEYS_FILE  "/tmp/" APP_NAME "_keys.md"
#define ASK_KEYS_URL   "https://raw.githubusercontent.com/alistaitsacle/free-llm-api-keys/main/README.md"
#define ASK_KEYS_BUF   262144
static char ask_keys_buf[ASK_KEYS_BUF];

static int ask_section_matches(const char *line, int n, int prov) {
    /* The header line starts with "### " followed by a provider
     * label.  Match on substrings — the label often has a date or
     * timestamp suffix in backticks, e.g. "### Gemini `05-07 08:52`". */
    static const char *openai_tags[]    = { "GPT", "OpenAI", "ChatGPT", "OAI", 0 };
    static const char *anthropic_tags[] = { "Claude", "Anthropic", 0 };
    static const char *gemini_tags[]    = { "Gemini", "Google", 0 };
    const char **tags = openai_tags;
    if (prov == ASK_PROV_ANTHROPIC) tags = anthropic_tags;
    else if (prov == ASK_PROV_GEMINI) tags = gemini_tags;
    for (int t = 0; tags[t]; t++) {
        int tl = slen(tags[t]);
        for (int i = 0; i + tl <= n; i++) {
            int j = 0;
            while (j < tl && line[i+j] == tags[t][j]) j++;
            if (j == tl) return 1;
        }
    }
    return 0;
}

static void ask_fetch_random_key(void) {
    char *argv_[6];
    int ai = 0;
    argv_[ai++] = (char *)"curl";
    argv_[ai++] = (char *)"-fsSL";
    argv_[ai++] = (char *)"-o"; argv_[ai++] = (char *)ASK_KEYS_FILE;
    argv_[ai++] = (char *)ASK_KEYS_URL;
    argv_[ai++] = 0;

    long pid = forkk();
    if (pid < 0) return;
    if (pid == 0) {
        execvee("/usr/bin/curl",       argv_, g_envp);
        execvee("/bin/curl",           argv_, g_envp);
        execvee("/usr/local/bin/curl", argv_, g_envp);
        qu(127);
    }
    int status = 0;
    wait4_(&status);
    if (status) return;

    int fd = (int)op(ASK_KEYS_FILE, O_RDONLY, 0);
    if (fd < 0) return;
    long m = rd(fd, ask_keys_buf, ASK_KEYS_BUF - 1);
    cl(fd);
    if (m <= 0) return;
    ask_keys_buf[m] = 0;

    int prov = ask_provider();
    int chosen_off = -1, chosen_len = 0, count = 0;
    int fallback_off = -1, fallback_len = 0, fallback_count = 0;
    /* Remember each candidate's full line offsets too — after
     * sampling we re-walk the line to extract the model column. */
    long chosen_line_start = -1, chosen_line_end = -1;
    long fallback_line_start = -1, fallback_line_end = -1;
    long chosen_key_end = -1, fallback_key_end = -1;
    int in_section = 0;
    unsigned long s;
    {
        unsigned long h, l;
        __asm__ volatile ("rdtsc" : "=d"(h), "=a"(l));
        s = (h << 32) | l | 1ULL;
    }

    /* Walk line-by-line.  Section state tracks whether the current
     * lines belong to a provider-matching `### …` block. */
    long i = 0;
    while (i < m) {
        long line_start = i;
        while (i < m && ask_keys_buf[i] != '\n') i++;
        long line_end = i;
        if (i < m) i++;
        long ln = line_end - line_start;
        if (ln >= 4 && ask_keys_buf[line_start] == '#'
                    && ask_keys_buf[line_start+1] == '#'
                    && ask_keys_buf[line_start+2] == '#'
                    && ask_keys_buf[line_start+3] == ' ') {
            in_section = ask_section_matches(
                &ask_keys_buf[line_start + 4],
                (int)(ln - 4), prov);
            continue;
        }
        /* Walk this line for `…` backtick-token cells. */
        for (long j = line_start; j < line_end; j++) {
            if (ask_keys_buf[j] != '`') continue;
            long k = j + 1;
            while (k < line_end) {
                char ch = ask_keys_buf[k];
                int ok = (ch >= 'a' && ch <= 'z') ||
                         (ch >= 'A' && ch <= 'Z') ||
                         (ch >= '0' && ch <= '9') ||
                         ch == '-' || ch == '_' || ch == '.';
                if (!ok) break;
                k++;
            }
            int tok_len = (int)(k - (j + 1));
            if (tok_len >= 20 && tok_len < ASK_KEY_CAP
                              && k < line_end && ask_keys_buf[k] == '`') {
                if (in_section) {
                    count++;
                    s = s * 6364136223846793005UL + 1442695040888963407UL;
                    if ((s >> 33) % (unsigned)count == 0) {
                        chosen_off = (int)(j + 1);
                        chosen_len = tok_len;
                        chosen_line_start = line_start;
                        chosen_line_end   = line_end;
                        chosen_key_end    = k + 1;   /* past closing ` */
                    }
                } else {
                    fallback_count++;
                    s = s * 6364136223846793005UL + 1442695040888963407UL;
                    if ((s >> 33) % (unsigned)fallback_count == 0) {
                        fallback_off = (int)(j + 1);
                        fallback_len = tok_len;
                        fallback_line_start = line_start;
                        fallback_line_end   = line_end;
                        fallback_key_end    = k + 1;
                    }
                }
                j = k;   /* advance past closing backtick */
            }
        }
    }
    if (chosen_off < 0) {
        chosen_off       = fallback_off;
        chosen_len       = fallback_len;
        chosen_line_start = fallback_line_start;
        chosen_line_end   = fallback_line_end;
        chosen_key_end    = fallback_key_end;
    }
    if (chosen_off < 0) return;
    for (int k = 0; k < chosen_len; k++)
        ask_api_key[k] = ask_keys_buf[chosen_off + k];
    ask_api_key[chosen_len] = 0;

    /* office50 — pull the model name from the same row.  The README
     * format is `| `<key>` | <model> | …`, so we start just past the
     * closing backtick of the key cell, skip whitespace + the `|`
     * separator + more whitespace, and copy chars until the next `|`
     * or end-of-line.  Trim trailing whitespace before terminating.
     * If anything looks off we leave ask_model as-is. */
    if (chosen_key_end > 0 && chosen_line_end > chosen_key_end) {
        long p = chosen_key_end;
        while (p < chosen_line_end &&
               (ask_keys_buf[p] == ' ' || ask_keys_buf[p] == '\t')) p++;
        if (p < chosen_line_end && ask_keys_buf[p] == '|') {
            p++;
            while (p < chosen_line_end &&
                   (ask_keys_buf[p] == ' ' || ask_keys_buf[p] == '\t')) p++;
            long mstart = p;
            while (p < chosen_line_end && ask_keys_buf[p] != '|') p++;
            long mend = p;
            while (mend > mstart &&
                   (ask_keys_buf[mend-1] == ' '
                 || ask_keys_buf[mend-1] == '\t'
                 || ask_keys_buf[mend-1] == '`')) mend--;
            while (mstart < mend && ask_keys_buf[mstart] == '`') mstart++;
            int mlen = (int)(mend - mstart);
            if (mlen > 0 && mlen < ASK_MODEL_CAP) {
                for (int k = 0; k < mlen; k++)
                    ask_model[k] = ask_keys_buf[mstart + k];
                ask_model[mlen] = 0;
            }
        }
    }

    /* office47 — these keys aren't real OpenAI keys; they're issued
     * for the upstream's OpenAI-compatible proxy.  Force the endpoint
     * to the proxy URL so the next message authenticates.  All keys
     * (including the ones in the Gemini/Claude sections) speak OpenAI
     * Chat Completions over this proxy.  User can edit endpoint
     * manually afterwards if they have a real key for a real host. */
    static const char proxy_url[] =
        "https://aiapiv2.pekpik.com/v1/chat/completions";
    int pul = (int)sizeof proxy_url - 1;
    if (pul < ASK_URL_CAP) {
        for (int k = 0; k <= pul; k++) ask_endpoint[k] = proxy_url[k];
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
        body_at(2, 3, "Edit chat settings.  Endpoint hostname picks the provider.",
                SCREEN_W - 4);
        {
            int prov = ask_provider();
            const char *pn = (prov == ASK_PROV_ANTHROPIC) ? "Anthropic Messages"
                           : (prov == ASK_PROV_GEMINI)    ? "Google Gemini"
                                                          : "OpenAI Chat Completions";
            char hint[80]; int hp = 0;
            hp = sapp(hint, hp, "Provider: ");
            hp = sapp(hint, hp, pn);
            hint[hp] = 0;
            body_at(2, 4, hint, SCREEN_W - 4);
        }
        body_at(2, 5, "Up/Down select; ENTER edit; r=random key; ESC save+close.",
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

        /* Larger buffer so a paste of an API key (~50 chars) arrives
         * in one read instead of being split across multiple reads. */
        unsigned char k[256];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        if (!editing) {
            if (k[0] == 0x1b && n == 1) { ask_save_conf(); return; }
            if (n >= 3 && k[0] == 0x1b && k[1] == '[') {
                if (k[2] == 'A' && sel > 0) sel--;
                if (k[2] == 'B' && sel < 2) sel++;
            }
            if (k[0] == '\r' || k[0] == '\n') editing = 1;
            if (k[0] == 'r' || k[0] == 'R') {
                ask_fetch_random_key();
            }
        } else {
            if (k[0] == '\r' || k[0] == '\n') { editing = 0; continue; }
            if (k[0] == 0x1b && n == 1)        { editing = 0; continue; }
            if (k[0] == 0x7f || k[0] == 8) {
                int sl = slen(fields[sel]);
                if (sl > 0) fields[sel][sl - 1] = 0;
                continue;
            }
            /* Paste fix: process every printable byte in the read,
             * not just k[0].  Terminal-mediated pastes deliver many
             * bytes in one read; pre-office50 only the first was
             * consumed, truncating long API keys to a single char. */
            for (int i = 0; i < n; i++) {
                unsigned char ch = k[i];
                if (ch < 32 || ch >= 127) continue;
                int sl = slen(fields[sel]);
                if (sl < caps[sel] - 1) {
                    fields[sel][sl] = (char)ch;
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

/* office53 — `silent` mode for invisible bends in rpg.  When silent
 * is non-zero we skip the polling-termios switch, the per-generation
 * hx_paint_progress + read_key, and the abort-on-q check.  The GA
 * still runs the full number of generations and still adopts the
 * winner; the caller (rpg_bend) sees a brief pause, then renders the
 * overworld with the evolved CA — no view takeover. */
static int hx_run_ga_session(int pop, int gens, unsigned rseed, int silent) {
    /* Polling termios so each generation advances on its own —
     * VMIN=0, VTIME=2 means read_key returns within ~200 ms whether
     * a key was pressed or not.  Skipped in silent mode (no per-gen
     * paint, so no need to wait between generations). */
    struct ti t = term_orig;
    if (!silent) {
        t.lflag &= ~(ICANON | ECHO);
        t.iflag &= ~(IXON | ICRNL);
        t.cc[6] = 0;     /* VMIN  */
        t.cc[5] = 2;     /* VTIME = 200 ms */
        io(0, TCSETS, &t);
    }

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

        if (!silent) {
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

    /* Restore blocking termios for whatever the caller does next.
     * Skipped in silent mode since we never switched off blocking. */
    if (!silent) {
        t.cc[6] = 1;
        t.cc[5] = 2;
        io(0, TCSETS, &t);
    }

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
    hx_run_ga_session(pop, gens, rseed, /*silent=*/0);
    hx_show_winners(pop);
}

/* Continuous hunt — loop short GA sessions, each refining off the
 * previous winner, until the user aborts.  No winners screen between
 * rounds; on exit we just return to display mode showing the latest
 * evolved genome animating. */
static void hx_run_continuous_hunt(void) {
    while (1) {
        unsigned rs = (unsigned)(time_() ^ (long)hx_rand());
        int aborted = hx_run_ga_session(20, 10, rs, /*silent=*/0);
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
/* office50 — 3×3 mosaic of overworlds.  The world-cell arrays cover
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
/* office51 — distance from a central-panel boundary at which we start
 * pre-loading the new edge panels off-screen.  At margin=2 the player
 * has 2 ticks of warning before the cross fires; at 1-2 panels per
 * tick of preload that's enough to cover a cardinal cross (3 new
 * panels) and most of a diagonal (5).  Anything still unstaged when
 * cross fires falls back to synchronous regen. */
#define RPG_PRELOAD_MARGIN 2

/* office50 — meta-overworld coordinate stack.  rpg_world_pos[0] is
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

/* office50 NPC layer.  rpg_npc_at[i] = 0 → no NPC; otherwise the byte
 * encodes a head/body palette pair: high nibble indexes rpg_npc_pal
 * for the head colour, low nibble for the body.  NPCs render as a
 * 1×2 block sprite (same shape as the player) and block movement;
 * bumping prints a greeting. */
static unsigned char rpg_npc_at[RPG_TILE_W * RPG_TILE_H];
static const unsigned char rpg_npc_pal[16] = {
    196, 202, 220, 226, 154, 118,  51,  39,
     33,  93, 201, 198, 252, 245, 240, 232,
};

/* v0.2: animal-action-anim — bss arrays declared up front so they
 * see the same TILE_W/H as the rest of the entity layers.  The
 * AA_* enum + helper functions live below the RC_* enum (where
 * RC_ANIMAL / RC_PLANT become visible). */
static unsigned char rpg_animal_action[RPG_TILE_W * RPG_TILE_H];
static unsigned char rpg_animal_action_ttl[RPG_TILE_W * RPG_TILE_H];

/* office50 wander layer.  Each animal/NPC has a current step index
 * within a procedural closed-loop path and a path-generation counter
 * that lets us re-seed a fresh loop when the current one completes.
 * The path itself is regenerated from (world_idx, path_id, world_seed)
 * each tick — no per-cell path storage needed. */
#define RPG_PATH_MAX 64
static unsigned char rpg_path_step[RPG_TILE_W * RPG_TILE_H];
static unsigned char rpg_path_id  [RPG_TILE_W * RPG_TILE_H];

/* office51 — shadow buffer holding the new edge panels for the
 * projected post-shift mosaic, computed off-screen while the player
 * is still ≤ RPG_PRELOAD_MARGIN cells from the central-panel
 * boundary.  Exactly 9 slots so each panel is keyed by its target
 * mosaic position; only NEW slots (those that lie outside the old
 * mosaic after the projected shift) are filled.  ~180 KB BSS.
 * path_step / path_id are not shadowed — NPCs always start at step 0
 * in a freshly entered panel. */
struct RpgPanelShadow {
    unsigned char map      [RPG_MAP_W * RPG_MAP_H];
    unsigned char cat_at   [RPG_MAP_W * RPG_MAP_H];
    unsigned char idx_at   [RPG_MAP_W * RPG_MAP_H];
    unsigned char hp_at    [RPG_MAP_W * RPG_MAP_H];
    unsigned char npc_at   [RPG_MAP_W * RPG_MAP_H];
};
static struct RpgPanelShadow rpg_preload_panel[9];
static unsigned char rpg_preload_done[9];     /* 1 = filled this dir */
static int rpg_preload_mdx;                   /* projected shift dx ∈ {-1,0,+1} */
static int rpg_preload_mdy;                   /* projected shift dy */

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
/* office50 — when set, rpg_render_view drops origin_y to 0 and uses
 * the entire screen height for cells (no chrome strip on top).  The
 * screensaver app sets this; regular rpg leaves it at 0. */
static int g_rpg_fullscreen;

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
/* office50 — one 4-colour terrain palette per sub-overworld in the
 * 3×3 mosaic.  rpg_terrain_rgb[s][i] is the RGB for terrain `i`
 * (0=rock, 1=sand, 2=soil, 3=water) in sub-chunk `s` (0..8, row-major
 * within the mosaic).  Refreshed every time the mosaic loads/shifts. */
static struct RpgRGB rpg_terrain_rgb[9][4];

/* office51 — cached world seed for each of the 9 mosaic sub-panels.
 * Refreshed every time the mosaic loads or shifts.  Used by the
 * world-stable cell hash so per-cell texture/palette derive from the
 * cell's world coord (panel seed + local x, y) rather than mosaic
 * coord — same world cell looks identical no matter which mosaic
 * slot it occupies, so cross-overs don't blink visible textures. */
static unsigned long rpg_panel_seed[9];

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

static unsigned long rpg_neighbor_seed(int dx, int dy);

/* Derive a 4-colour palette for one overworld from its seed.  Each
 * terrain class anchors on a recognisable archetype (rock/sand/soil/
 * water) and drifts ~±32 per channel based on the seed, so different
 * overworlds visibly differ but rock is still rocky and water blue. */
static void rpg_palette_for_seed(unsigned long s, struct RpgRGB out[4]) {
    static const struct RpgRGB anchor[4] = {
        {  90,  90,  92 },   /* rock  — neutral grey */
        { 220, 200, 140 },   /* sand  — warm tan */
        {  90, 130,  60 },   /* soil  — moss green */
        {  30,  80, 180 },   /* water — deep blue */
    };
    s |= 1ULL;
    for (int i = 0; i < 4; i++) {
        s = s * 6364136223846793005UL + 1442695040888963407UL;
        int dr = (int)((s >> 33) & 0x3f) - 32;
        s = s * 6364136223846793005UL + 1442695040888963407UL;
        int dg = (int)((s >> 33) & 0x3f) - 32;
        s = s * 6364136223846793005UL + 1442695040888963407UL;
        int db = (int)((s >> 33) & 0x3f) - 32;
        int r = (int)anchor[i].r + dr;
        int g = (int)anchor[i].g + dg;
        int b = (int)anchor[i].b + db;
        if (r < 0) r = 0; if (r > 255) r = 255;
        if (g < 0) g = 0; if (g > 255) g = 255;
        if (b < 0) b = 0; if (b > 255) b = 255;
        out[i].r = (unsigned char)r;
        out[i].g = (unsigned char)g;
        out[i].b = (unsigned char)b;
    }
}

/* Refresh all 9 sub-overworld palettes from their per-neighbour
 * world seeds.  Called whenever the mosaic loads or shifts.  Also
 * refreshes office51's rpg_panel_seed[] cache (same per-neighbour
 * seeds, used by rpg_cell_world_hash for stable per-cell textures). */
static void rpg_palettes_refresh(void) {
    for (int cy = -1; cy <= 1; cy++) {
        for (int cx = -1; cx <= 1; cx++) {
            int slot = (cy + 1) * 3 + (cx + 1);
            unsigned long ns = rpg_neighbor_seed(cx, cy);
            rpg_panel_seed[slot] = ns;
            rpg_palette_for_seed(ns, rpg_terrain_rgb[slot]);
        }
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

static unsigned long rpg_lcg_next(unsigned long *s) {
    *s = (*s) * 6364136223846793005UL + 1442695040888963407UL;
    return *s;
}

/* office51 — world-stable cell hash.  Combines the panel's cached
 * world seed with the cell's local position inside that panel, so the
 * same world cell returns the same hash regardless of which mosaic
 * slot it's currently rendered in.  Drives texture + palette in
 * rpg_compute_cell so cross-overs don't shimmer.  Replaces office50's
 * rpg_cell_hash(wx, wy) which keyed off mosaic coords and so changed
 * per-cell appearance whenever the mosaic shifted. */
static unsigned long rpg_cell_world_hash(int wx, int wy) {
    int sub_x = wx / RPG_MAP_W;
    int sub_y = wy / RPG_MAP_H;
    if (sub_x < 0) sub_x = 0; else if (sub_x > 2) sub_x = 2;
    if (sub_y < 0) sub_y = 0; else if (sub_y > 2) sub_y = 2;
    int local_x = wx - sub_x * RPG_MAP_W;
    int local_y = wy - sub_y * RPG_MAP_H;
    unsigned long h = rpg_panel_seed[sub_y * 3 + sub_x]
                    ^ ((unsigned long)local_x * 0x9E3779B97F4A7C15UL)
                    ^ ((unsigned long)local_y * 0xC2B2AE3D27D4EB4FUL);
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

/* ── v0.5: per-cell rule pool (port of JS ev52) ──────────────────
 *
 * `u` toggles a 256-slot pool of mother-relative ruleset mutations;
 * each rendered cell picks its slot from a stable hash of (panel
 * seed, world_x, world_y), so neighbouring cells get coherent
 * variations on the same theme rather than random noise.  Shift+U
 * discards the pool so the next ensure call rebuilds against the
 * current mother (useful after load-bundle swaps the genome).
 *
 * Slot 0 mirrors the mother — covers cells whose hash lands on 0,
 * keeping a baseline familiar.  Slots 1..N-1: hx_mutate at ~10%
 * per-situation flip rate (matches JS RULE_POOL_MUTATION).
 *
 * RAM cost: 256 × HX_GBYTES = 256 × 4096 = 1 MB.  Allocated lazily
 * on first toggle so the binary baseline stays unchanged for users
 * who never enable it. */
#define RPG_RULE_POOL_SIZE     256
#define RPG_RULE_POOL_MUT_Q24  1677721   /* 0.10 × 2^24 */

static unsigned char rpg_rule_pool[RPG_RULE_POOL_SIZE][HX_GBYTES];
static int rpg_rule_pool_built = 0;
static int rpg_per_cell_rules_on = 0;

static void rpg_ensure_rule_pool(void) {
    if (rpg_rule_pool_built) return;
    mcpy(rpg_rule_pool[0], hx_seed_genome, HX_GBYTES);
    for (int i = 1; i < RPG_RULE_POOL_SIZE; i++)
        hx_mutate(rpg_rule_pool[i], hx_seed_genome, RPG_RULE_POOL_MUT_Q24);
    rpg_rule_pool_built = 1;
}

static void rpg_reseed_rule_pool(void) {
    rpg_rule_pool_built = 0;
    if (rpg_per_cell_rules_on) rpg_ensure_rule_pool();
    mset(rpg_cell_done, 0, sizeof rpg_cell_done);
}

/* Stable per-world-coord pool index.  rpg_cell_world_hash forces
 * bit 0 to 1 (returns h | 1UL), so shift past the low byte before
 * masking — otherwise only 128 of 256 slots would ever be picked. */
static const unsigned char *rpg_get_cell_ruleset(int wx, int wy) {
    if (!rpg_per_cell_rules_on) return hx_seed_genome;
    rpg_ensure_rule_pool();
    unsigned long h = rpg_cell_world_hash(wx, wy);
    int idx = (int)((h >> 8) & 0xff);
    return rpg_rule_pool[idx];
}

/* ── v0.6: pool GA (port of JS ev54) ─────────────────────────────
 *
 * Tournament-2 over the rule pool every RPG_POOL_GA_PERIOD frames.
 * Score = Shannon entropy of the rule's output distribution
 * (rules with uniform output across {0,1,2,3} are "interesting";
 * rules that mostly output one state are stale).  Loser is
 * replaced with a child of the winner — usually crossover with
 * another random slot followed by mild mutation, sometimes
 * mutation only.  Slot 0 (mother mirror) is protected so the
 * baseline rule stays available even after long evolution.
 *
 * Cell cache is wiped on each GA round so the next render shows
 * the freshly-evolved rule(s).  Only fires when per-cell rules
 * are enabled AND the main loop is animating; if the user isn't
 * watching the world evolve, neither is the GA. */
#define RPG_POOL_GA_PERIOD       60          /* frames between rounds */
#define RPG_POOL_GA_MUT_CO_Q24   335544      /* ≈0.02 × 2^24 */
#define RPG_POOL_GA_MUT_MO_Q24   838860      /* ≈0.05 × 2^24 */
#define RPG_POOL_GA_CROSS_PCT    70          /* % of rounds that crossover */

static long rpg_pool_ga_last_frame = -1;
static long rpg_pool_ga_rounds     = 0;

/* Integer-only entropy proxy.  Real Shannon entropy needs ln, but
 * for ranking two rules we only need a monotonic surrogate.  Use
 * Σ counts·(N − counts) — maximised when the distribution is
 * uniform (each count = N/K), zero when one bucket holds all of
 * N.  Same monotonic ordering as Shannon for K=4 buckets. */
static unsigned long rpg_pool_fitness(const unsigned char *rs) {
    unsigned long counts[4] = { 0, 0, 0, 0 };
    for (int i = 0; i < HX_NSIT; i++)
        counts[hx_g_get(rs, i) & 3]++;
    unsigned long fit = 0;
    for (int k = 0; k < 4; k++)
        fit += counts[k] * (HX_NSIT - counts[k]);
    return fit;
}

/* Fast LCG-driven coin flip: `pct` % of the time returns 1. */
static int rpg_pool_coin(unsigned long *s, int pct) {
    *s = (*s) * 6364136223846793005UL + 1442695040888963407UL;
    return ((int)((*s >> 33) % 100) < pct);
}

static void rpg_pool_ga_tick(long frame) {
    if (!rpg_per_cell_rules_on || !rpg_rule_pool_built) return;
    if (rpg_pool_ga_last_frame >= 0
     && frame - rpg_pool_ga_last_frame < RPG_POOL_GA_PERIOD) return;
    rpg_pool_ga_last_frame = frame;

    /* Tournament-2.  Slots 1..N-1 only; slot 0 (mother) protected. */
    static unsigned long s = 0x12345678abcdefUL;
    s = s * 6364136223846793005UL + 1442695040888963407UL;
    int a = 1 + (int)((s >> 33) % (RPG_RULE_POOL_SIZE - 1));
    s = s * 6364136223846793005UL + 1442695040888963407UL;
    int b = 1 + (int)((s >> 33) % (RPG_RULE_POOL_SIZE - 1));
    if (a == b) b = (b % (RPG_RULE_POOL_SIZE - 1)) + 1;

    unsigned long fa = rpg_pool_fitness(rpg_rule_pool[a]);
    unsigned long fb = rpg_pool_fitness(rpg_rule_pool[b]);
    int win  = (fa >= fb) ? a : b;
    int lose = (fa >= fb) ? b : a;

    if (rpg_pool_coin(&s, RPG_POOL_GA_CROSS_PCT)) {
        s = s * 6364136223846793005UL + 1442695040888963407UL;
        int c = (int)((s >> 33) % RPG_RULE_POOL_SIZE);
        if (c == lose) c = (c + 1) % RPG_RULE_POOL_SIZE;
        unsigned char tmp[HX_GBYTES];
        hx_cross(tmp, rpg_rule_pool[win], rpg_rule_pool[c]);
        hx_mutate(rpg_rule_pool[lose], tmp, RPG_POOL_GA_MUT_CO_Q24);
    } else {
        hx_mutate(rpg_rule_pool[lose],
                  rpg_rule_pool[win],
                  RPG_POOL_GA_MUT_MO_Q24);
    }
    rpg_pool_ga_rounds++;
    /* Cells whose hash resolves to `lose` now look stale.  We don't
     * track the inverse map (would cost ~144 KB), so wipe wholesale.
     * Lazy rebuild means cost is paid only on visible cells. */
    mset(rpg_cell_done, 0, sizeof rpg_cell_done);
}

static void rpg_compute_cell(int wx, int wy) {
    int idx = wy * RPG_TILE_W + wx;
    if (rpg_cell_done[idx]) return;
    /* office51 — world-stable hash so this cell looks identical
     * regardless of which mosaic slot it currently occupies. */
    unsigned long s = rpg_cell_world_hash(wx, wy);
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
    /* v0.5: when per-cell rules are on, fetch this cell's pool slot
     * once and step under that instead of the mother. */
    const unsigned char *cell_rs = rpg_get_cell_ruleset(wx, wy);
    for (int t = 0; t < n_steps; t++) {
        rpg_step_grid(cell_rs, rpg_inner_a, rpg_inner_b);
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
    /* 4-colour palette: terrain base RGB + 4 random offsets.  office50:
     * pick the sub-overworld this cell sits in (3×3 mosaic, 64-cell
     * wide) so each sub-world gets its own colour scheme. */
    int terrain = rpg_map[idx] & 3;
    int sub = (wy / RPG_MAP_W) * 3 + (wx / RPG_MAP_W);
    if (sub < 0 || sub > 8) sub = 4;
    int br = rpg_terrain_rgb[sub][terrain].r;
    int bg = rpg_terrain_rgb[sub][terrain].g;
    int bb = rpg_terrain_rgb[sub][terrain].b;
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
                unsigned long s = rpg_cell_world_hash(wx, wy)
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
                    /* v0.5: per-cell rule pool also gates the
                     * live-step path so animal-anim cells stay
                     * coherent with rpg_compute_cell. */
                    rpg_step_grid(rpg_get_cell_ruleset(wx, wy),
                                  state, rpg_inner_b);
                    mcpy(state, rpg_inner_b, RPG_MAP_W * RPG_MAP_H);
                } else {
                    /* No live ruleset → re-seed for visual churn. */
                    unsigned long s = rpg_cell_world_hash(wx, wy)
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

/* v0.2: animal-action-anim port (JS ev61).  Per-cell action state
 * + ticking TTL gives each animal a transient "what they're doing
 * right now" badge.  Bound to the renderer as a single-cell
 * coloured halo above each animal — terminal resolution can't
 * carry the JS version's full 10-map × personal-CA tint, but the
 * action signal still reads at a glance.
 *
 * AA_WALK is the default (no halo); ATTACK is set when the player
 * hits the animal; FLEE is set on every same-variant hex-neighbour
 * of that hit; EAT is set in path_tick when an animal walks
 * adjacent to a plant cell.  TTL is in render-frames (~30 by
 * default), decrements once per render, and at 0 the cell reverts
 * to AA_WALK. */
enum {
    AA_WALK   = 0,
    AA_ATTACK = 1,
    AA_FLEE   = 2,
    AA_EAT    = 3,
};
#define AA_TTL_DEFAULT  30
/* v0.2 / port of ev67: master toggle for the animation subsystem.
 * Default OFF — the per-render-frame tick + halo paint run on
 * every visible animal even when no action is active, and the
 * L-system sprite + 1×2 colour block already convey "this is an
 * animal" without the halo.  `h` toggles it on inside run_rpg. */
static int rpg_animal_anim_on = 0;

/* xterm-256 indices for each action's halo glyph. */
static const unsigned char rpg_animal_action_color[4] = {
    0,     /* AA_WALK   — no halo */
    196,   /* AA_ATTACK — red    */
    220,   /* AA_FLEE   — yellow */
     46,   /* AA_EAT    — green  */
};

static void rpg_animal_action_tick(void) {
    /* Cheap linear sweep over 36864 bytes; once-per-render so
     * negligible against the cell-paint cost.  Cells whose timer
     * expires fall back to AA_WALK and the halo stops drawing. */
    for (int i = 0; i < RPG_TILE_W * RPG_TILE_H; i++) {
        if (rpg_animal_action_ttl[i] == 0) continue;
        if (--rpg_animal_action_ttl[i] == 0)
            rpg_animal_action[i] = AA_WALK;
    }
}

/* Hex-neighbour offsets for offset-r layout — the same six
 * directions the move-step switch in rpg_move uses, broken out so
 * kin-spook + eat-detection can share. */
static void rpg_hex_neighbour(int x, int y, int dir,
                              int *nx_out, int *ny_out) {
    int odd = y & 1;
    int nx = x, ny = y;
    switch (dir) {
    case 0: nx = x + 1;                            break;   /* E  */
    case 1: nx = x + (odd ? 1 :  0); ny = y - 1;   break;   /* NE */
    case 2: nx = x + (odd ? 0 : -1); ny = y - 1;   break;   /* NW */
    case 3: nx = x - 1;                            break;   /* W  */
    case 4: nx = x + (odd ? 0 : -1); ny = y + 1;   break;   /* SW */
    case 5: nx = x + (odd ? 1 :  0); ny = y + 1;   break;   /* SE */
    }
    *nx_out = nx; *ny_out = ny;
}

static void rpg_animal_spook_kin(int x, int y, int variant) {
    for (int k = 0; k < 6; k++) {
        int nx, ny;
        rpg_hex_neighbour(x, y, k, &nx, &ny);
        if (nx < 0 || nx >= RPG_TILE_W || ny < 0 || ny >= RPG_TILE_H)
            continue;
        int ni = ny * RPG_TILE_W + nx;
        if (rpg_cat_at[ni] != RC_ANIMAL) continue;
        if (rpg_idx_at[ni] != (unsigned char)variant) continue;
        rpg_animal_action    [ni] = AA_FLEE;
        rpg_animal_action_ttl[ni] = AA_TTL_DEFAULT;
    }
}

static int rpg_animal_near_plant(int x, int y) {
    for (int k = 0; k < 6; k++) {
        int nx, ny;
        rpg_hex_neighbour(x, y, k, &nx, &ny);
        if (nx < 0 || nx >= RPG_TILE_W || ny < 0 || ny >= RPG_TILE_H)
            continue;
        if (rpg_cat_at[ny * RPG_TILE_W + nx] == RC_PLANT) return 1;
    }
    return 0;
}

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

/* ── v1.2: lsystem-genome (port of JS ev15) ──────────────────────
 *
 * Each EntityCategory ships 4 archetype rule strings as rodata
 * (rpg_cats[cat].rules[arch]).  v1.2 adds a parallel mutable
 * buffer that can override any (cat, arch) slot with an evolved
 * rule.  Background tournament-2 GA runs every RPG_LSYS_GA_PERIOD
 * frames while the animation loop is live AND 'G' is toggled on.
 *
 * Within-category tournaments only — animals stay animal-shaped
 * even after long evolution.  Crossover may pull from a different
 * category to inject novelty, but the result is always installed
 * into the loser's slot inside the original category.
 *
 * Fitness = points-from-turtle-walk + bbox area (geometric
 * complexity + spatial spread).  Trivial rules (only F or only
 * brackets) score near zero.  Sprite cache is invalidated for
 * every variant idx whose (idx & 3) matches the replaced arch.
 *
 * RAM cost: 5 cats × 4 arch × 64 chars = 1280 B for the evolved
 * buffer + 20 B for the set-flags. */
#define RPG_LSYS_RULE_MAX  64
#define RPG_LSYS_GA_PERIOD 120          /* frames between rounds */

static char rpg_lsys_evolved[RC_N][4][RPG_LSYS_RULE_MAX];
static unsigned char rpg_lsys_evolved_set[RC_N][4];
static int  rpg_lsys_ga_on = 0;
static long rpg_lsys_ga_last_frame = -1;
static long rpg_lsys_ga_rounds = 0;

static unsigned long rpg_lsys_rng = 0xc0ffee5UL;
static unsigned int rpg_lsys_rand(void) {
    rpg_lsys_rng = rpg_lsys_rng * 6364136223846793005UL
                 + 1442695040888963407UL;
    return (unsigned int)(rpg_lsys_rng >> 32);
}

static const char *rpg_lsys_rule(int cat, int arch) {
    if (cat > 0 && cat < RC_N && arch >= 0 && arch < 4
     && rpg_lsys_evolved_set[cat][arch])
        return rpg_lsys_evolved[cat][arch];
    return rpg_cats[cat].rules[arch];
}

/* Score = points + bbox area after expand+walk at fixed iters/angle
 * so all rules evaluate on the same scale.  Reuses the existing
 * sprite turtle (rpg_sp_xs/ys + rpg_sp_n). */
static int rpg_lsys_fitness(int cat, int arch) {
    if (cat <= 0 || cat >= RC_N) return 0;
    const char *axiom = rpg_cats[cat].axioms[arch];
    const char *rule  = rpg_lsys_rule(cat, arch);
    if (!axiom || !*axiom || !rule || !*rule) return 0;
    int len = 0;
    const char *cmds = lsys_expand_simple(axiom, rule, 3, &len);
    rpg_sprite_walk(cmds, len, 1);
    int pts = rpg_sp_n;
    if (pts <= 1) return 0;
    int minx = rpg_sp_xs[0], maxx = rpg_sp_xs[0];
    int miny = rpg_sp_ys[0], maxy = rpg_sp_ys[0];
    for (int i = 1; i < pts; i++) {
        if (rpg_sp_xs[i] < minx) minx = rpg_sp_xs[i];
        if (rpg_sp_xs[i] > maxx) maxx = rpg_sp_xs[i];
        if (rpg_sp_ys[i] < miny) miny = rpg_sp_ys[i];
        if (rpg_sp_ys[i] > maxy) maxy = rpg_sp_ys[i];
    }
    int area = (maxx - minx + 1) * (maxy - miny + 1);
    return pts + area;
}

/* Mutate src into dst: 1-3 random char replacements from the
 * L-system alphabet.  Imbalanced brackets are tolerated by the
 * turtle walker, so no balancing logic needed. */
static void rpg_lsys_mutate(char *dst, const char *src) {
    static const char alpha[5] = { 'F', '+', '-', '[', ']' };
    int n = slen(src);
    if (n >= RPG_LSYS_RULE_MAX) n = RPG_LSYS_RULE_MAX - 1;
    mcpy(dst, src, n); dst[n] = 0;
    if (n == 0) return;
    int flips = 1 + (int)(rpg_lsys_rand() % 3);
    for (int f = 0; f < flips; f++) {
        int idx = (int)(rpg_lsys_rand() % n);
        dst[idx] = alpha[rpg_lsys_rand() % 5];
    }
}

/* Single-point crossover: prefix of A up to cut_a, then suffix of B
 * from cut_b.  Result length capped at RPG_LSYS_RULE_MAX-1. */
static void rpg_lsys_cross(char *dst, const char *a, const char *b) {
    int la = slen(a), lb = slen(b);
    if (la >= RPG_LSYS_RULE_MAX) la = RPG_LSYS_RULE_MAX - 1;
    if (lb >= RPG_LSYS_RULE_MAX) lb = RPG_LSYS_RULE_MAX - 1;
    if (la < 1 && lb < 1) { dst[0] = 0; return; }
    if (la < 1) { mcpy(dst, b, lb); dst[lb] = 0; return; }
    if (lb < 1) { mcpy(dst, a, la); dst[la] = 0; return; }
    int cut_a = (int)(rpg_lsys_rand() % la);
    int cut_b = (int)(rpg_lsys_rand() % lb);
    int copy_a = cut_a;
    int copy_b = lb - cut_b;
    if (copy_a + copy_b >= RPG_LSYS_RULE_MAX)
        copy_b = RPG_LSYS_RULE_MAX - 1 - copy_a;
    if (copy_b < 0) copy_b = 0;
    mcpy(dst, a, copy_a);
    if (copy_b > 0) mcpy(dst + copy_a, b + cut_b, copy_b);
    dst[copy_a + copy_b] = 0;
}

static void rpg_lsys_ga_tick(long frame) {
    if (!rpg_lsys_ga_on) return;
    if (rpg_lsys_ga_last_frame >= 0
     && frame - rpg_lsys_ga_last_frame < RPG_LSYS_GA_PERIOD) return;
    rpg_lsys_ga_last_frame = frame;
    int cat = 1 + (int)(rpg_lsys_rand() % (RC_N - 1));
    int aA = (int)(rpg_lsys_rand() % 4);
    int aB = (int)(rpg_lsys_rand() % 4);
    if (aA == aB) aB = (aB + 1) & 3;
    int fA = rpg_lsys_fitness(cat, aA);
    int fB = rpg_lsys_fitness(cat, aB);
    int win  = (fA >= fB) ? aA : aB;
    int lose = (fA >= fB) ? aB : aA;
    char child[RPG_LSYS_RULE_MAX];
    if ((rpg_lsys_rand() % 100) < 70) {
        int cat2 = 1 + (int)(rpg_lsys_rand() % (RC_N - 1));
        int a2   = (int)(rpg_lsys_rand() % 4);
        char tmp[RPG_LSYS_RULE_MAX];
        rpg_lsys_cross(tmp,
                       rpg_lsys_rule(cat,  win),
                       rpg_lsys_rule(cat2, a2));
        rpg_lsys_mutate(child, tmp);
    } else {
        rpg_lsys_mutate(child, rpg_lsys_rule(cat, win));
    }
    int n = slen(child);
    if (n >= RPG_LSYS_RULE_MAX) n = RPG_LSYS_RULE_MAX - 1;
    mcpy(rpg_lsys_evolved[cat][lose], child, n);
    rpg_lsys_evolved[cat][lose][n] = 0;
    rpg_lsys_evolved_set[cat][lose] = 1;
    /* Variants whose archetype matches the replaced slot now have
     * stale sprite caches.  Clear those so the next render rebuilds
     * with the evolved rule. */
    for (int idx = 0; idx < RPG_CAT_VARIANTS; idx++)
        if ((idx & 3) == lose) rpg_sprite_done[cat][idx] = 0;
    rpg_lsys_ga_rounds++;
}

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
    /* v1.2: pull from the evolved buffer if the GA has touched
     * this slot, else from the const archetype. */
    const char *rule  = rpg_lsys_rule(cat, arch);
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

/* v0.2: hex meta-shift — offset-r topology.  Mirrors JS hexMetaShift
 * from ev56.  In odd meta-rows, NE/SE shift +1 in mx and NW/SW shift
 * 0; in even rows the opposite (-1 / 0).  E/W are parity-invariant. */
static void rpg_hex_meta_shift(char move, int my,
                               int *out_dx, int *out_dy) {
    int odd = (my & 1) == 1;
    switch (move) {
    case 'a': *out_dx = -1;            *out_dy =  0; return;
    case 'd': *out_dx = +1;            *out_dy =  0; return;
    case 'w': *out_dx = odd ?  0 : -1; *out_dy = -1; return;
    case 'e': *out_dx = odd ? +1 :  0; *out_dy = -1; return;
    case 'z': *out_dx = odd ?  0 : -1; *out_dy = +1; return;
    case 'x': *out_dx = odd ? +1 :  0; *out_dy = +1; return;
    }
    *out_dx = 0; *out_dy = 0;
}

/* Bubble (dx, dy) up the position stack with carry on 64-cell wrap.
 * dx, dy are typically -1, 0, or +1 (one overworld cell at a time).
 *
 * v0.2: when `hex_move` is non-zero, every cascade re-resolves the
 * move using the upper level's my parity — so an NW step at level 0
 * cascades up as the same NW step at level 1, but with level 1's
 * parity applied to figure out whether that NW lands at (mx, my-1)
 * or (mx-1, my-1).  hex_move=0 keeps the legacy rectangular cascade
 * (used by rpg_neighbor_seed and any caller that doesn't have a
 * specific move character). */
static void rpg_world_advance(int dx, int dy, char hex_move) {
    int cx = dx, cy = dy;
    for (int level = 0; level < RPG_WORLD_LEVELS && (cx || cy); level++) {
        rpg_world_pos[level][0] += cx;
        rpg_world_pos[level][1] += cy;
        int x_over = 0, y_over = 0;
        if (rpg_world_pos[level][0] < 0)   { rpg_world_pos[level][0] += 64; x_over = -1; }
        if (rpg_world_pos[level][0] >= 64) { rpg_world_pos[level][0] -= 64; x_over =  1; }
        if (rpg_world_pos[level][1] < 0)   { rpg_world_pos[level][1] += 64; y_over = -1; }
        if (rpg_world_pos[level][1] >= 64) { rpg_world_pos[level][1] -= 64; y_over =  1; }
        if (!x_over && !y_over) { cx = 0; cy = 0; break; }
        if (hex_move && y_over != 0 && level + 1 < RPG_WORLD_LEVELS) {
            int upper_my = rpg_world_pos[level + 1][1];
            int hdx = 0, hdy = 0;
            rpg_hex_meta_shift(hex_move, upper_my, &hdx, &hdy);
            cx = hdx; cy = hdy;
        } else {
            cx = x_over; cy = y_over;
        }
    }
}

/* Compute the world seed of a neighboring overworld at (dx, dy)
 * relative to the player's current overworld.  Carries up the
 * world-position stack temporarily and restores it. */
static unsigned long rpg_neighbor_seed(int dx, int dy) {
    int snap[RPG_WORLD_LEVELS][2];
    mcpy((unsigned char *)snap, (unsigned char *)rpg_world_pos, sizeof snap);
    rpg_world_advance(dx, dy, 0);
    unsigned long s = rpg_world_seed();
    mcpy((unsigned char *)rpg_world_pos, (unsigned char *)snap, sizeof snap);
    return s;
}

static void rpg_init_map(const unsigned char *ruleset) {
    /* office50 — populate the 192×192 mosaic by running 9 independent
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
    /* office50 — seed entities per-sub-overworld so each chunk's
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

/* office51 — generate one panel's terrain CA + entities into a set
 * of 5 panel-flat (64×64) buffers.  Same recipe as the 9-panel loops
 * in rpg_init_map / rpg_init_entities, but for one panel.  Used by
 * rpg_preload_panel_compute to fill the off-screen shadow.  Marked
 * noinline so the compiler doesn't bloat callers (the entity loop
 * is heavy; inlined it wedged ~300 B into rpg_preload_advance_one). */
__attribute__((noinline))
static void rpg_panel_regen_into(unsigned long ws,
                                 unsigned char *out_map,
                                 unsigned char *out_cat,
                                 unsigned char *out_idx,
                                 unsigned char *out_hp,
                                 unsigned char *out_npc) {
    /* Terrain CA — match rpg_init_map's per-panel pass. */
    hx_rng_state = ws;
    for (int i = 0; i < RPG_MAP_W * RPG_MAP_H; i++)
        rpg_buf[i] = (unsigned char)(hx_rand() & 3);
    for (int t = 0; t < RPG_GEN_STEPS; t++) {
        rpg_step_grid(hx_seed_genome, rpg_buf, rpg_inner_a);
        mcpy(rpg_buf, rpg_inner_a, RPG_MAP_W * RPG_MAP_H);
    }
    mcpy(out_map, rpg_buf, RPG_MAP_W * RPG_MAP_H);
    /* Entities — match rpg_init_entities' per-panel pass. */
    hx_rng_state = ws ^ 0xa5a5a5a5a5a5a5a5UL;
    for (int yy = 0; yy < RPG_MAP_H; yy++) {
        for (int xx = 0; xx < RPG_MAP_W; xx++) {
            int idx = yy * RPG_MAP_W + xx;
            int c = out_map[idx];
            unsigned rr = hx_rand() & 0xff;
            int cat = rpg_cat_for(c, rr);
            out_cat[idx] = (unsigned char)cat;
            out_idx[idx] = 0;
            out_hp [idx] = 0;
            out_npc[idx] = 0;
            if (cat) {
                int vidx = (int)(hx_rand() & (RPG_CAT_VARIANTS - 1));
                out_idx[idx] = (unsigned char)vidx;
                if (rpg_cats[cat].cat == 'A')
                    out_hp[idx] = rpg_cats[cat].hp;
            }
            if (!cat && (c == 1 || c == 2)) {
                unsigned q = hx_rand();
                if ((q & 31) == 0) {
                    unsigned char b = (unsigned char)((q >> 8) & 0xff);
                    if (!b) b = 0xa5;
                    out_npc[idx] = b;
                }
            }
        }
    }
}

/* Splat one panel-flat (64×64) buffer set into mosaic slot (sx, sy).
 * Resets path state since a freshly entered panel restarts NPC loops.
 * noinline keeps rpg_shift_mosaic compact (caller's loop would
 * otherwise inline 7×64 mcpys ≈ 200 B per call site). */
__attribute__((noinline))
static void rpg_panel_splat(int sx, int sy,
                            const unsigned char *m, const unsigned char *c,
                            const unsigned char *i, const unsigned char *h,
                            const unsigned char *n) {
    int sub_x = sx * RPG_MAP_W;
    int sub_y = sy * RPG_MAP_H;
    for (int y = 0; y < RPG_MAP_H; y++) {
        int di = (sub_y + y) * RPG_TILE_W + sub_x;
        int si = y * RPG_MAP_W;
        mcpy(&rpg_map      [di], &m[si], RPG_MAP_W);
        mcpy(&rpg_cat_at   [di], &c[si], RPG_MAP_W);
        mcpy(&rpg_idx_at   [di], &i[si], RPG_MAP_W);
        mcpy(&rpg_hp_at    [di], &h[si], RPG_MAP_W);
        mcpy(&rpg_npc_at   [di], &n[si], RPG_MAP_W);
        mset(&rpg_path_step[di], 0, RPG_MAP_W);
        mset(&rpg_path_id  [di], 0, RPG_MAP_W);
    }
}

/* Copy one panel's data within the live mosaic from (src_sx, src_sy)
 * to (dst_sx, dst_sy).  Source and destination 64×64 regions are
 * disjoint (different sub coords ⇒ no overlap); iteration order
 * across multiple panels matters when chains exist (e.g. mdx=-1
 * threads old0→new1→new2), so rpg_shift_mosaic schedules calls so
 * each src is read before its slot is overwritten.  noinline. */
__attribute__((noinline))
static void rpg_panel_copy_live(int dst_sx, int dst_sy,
                                int src_sx, int src_sy) {
    int dst_x = dst_sx * RPG_MAP_W;
    int dst_y = dst_sy * RPG_MAP_H;
    int src_x = src_sx * RPG_MAP_W;
    int src_y = src_sy * RPG_MAP_H;
    for (int y = 0; y < RPG_MAP_H; y++) {
        int di = (dst_y + y) * RPG_TILE_W + dst_x;
        int si = (src_y + y) * RPG_TILE_W + src_x;
        mcpy(&rpg_map      [di], &rpg_map      [si], RPG_MAP_W);
        mcpy(&rpg_cat_at   [di], &rpg_cat_at   [si], RPG_MAP_W);
        mcpy(&rpg_idx_at   [di], &rpg_idx_at   [si], RPG_MAP_W);
        mcpy(&rpg_hp_at    [di], &rpg_hp_at    [si], RPG_MAP_W);
        mcpy(&rpg_npc_at   [di], &rpg_npc_at   [si], RPG_MAP_W);
        mcpy(&rpg_path_step[di], &rpg_path_step[si], RPG_MAP_W);
        mcpy(&rpg_path_id  [di], &rpg_path_id  [si], RPG_MAP_W);
    }
}

static void rpg_preload_invalidate(void) {
    mset(rpg_preload_done, 0, sizeof rpg_preload_done);
    rpg_preload_mdx = 0;
    rpg_preload_mdy = 0;
}

/* Compute one shadow panel for the projected post-shift mosaic at
 * slot (sx, sy).  Idempotent — does nothing if already filled. */
static void rpg_preload_panel_compute(int sx, int sy) {
    int slot = sy * 3 + sx;
    if (rpg_preload_done[slot]) return;
    /* World offset relative to *current* world center for this
     * future slot:  current_post_shift = current + (mdx, mdy);
     * future slot world = current_post_shift + (sx-1, sy-1).
     * → relative to current: (mdx + sx - 1, mdy + sy - 1). */
    int dx = rpg_preload_mdx + (sx - 1);
    int dy = rpg_preload_mdy + (sy - 1);
    unsigned long ws = rpg_neighbor_seed(dx, dy);
    struct RpgPanelShadow *p = &rpg_preload_panel[slot];
    rpg_panel_regen_into(ws, p->map, p->cat_at, p->idx_at,
                         p->hp_at, p->npc_at);
    rpg_preload_done[slot] = 1;
}

/* Called once per player tick.  If the player is within
 * RPG_PRELOAD_MARGIN of any central-panel boundary, ensure the
 * shadow is targeting that direction and advance it by one panel. */
static void rpg_preload_advance_one(int px, int py) {
    int pdx = 0, pdy = 0;
    if (px <  (int)RPG_MAP_W + RPG_PRELOAD_MARGIN)        pdx = -1;
    else if (px >= 2 * (int)RPG_MAP_W - RPG_PRELOAD_MARGIN) pdx = +1;
    if (py <  (int)RPG_MAP_H + RPG_PRELOAD_MARGIN)        pdy = -1;
    else if (py >= 2 * (int)RPG_MAP_H - RPG_PRELOAD_MARGIN) pdy = +1;
    if (!pdx && !pdy) return;     /* not in margin */
    if (pdx != rpg_preload_mdx || pdy != rpg_preload_mdy) {
        /* Direction changed (e.g. corner switch, backtrack) — start
         * a fresh shadow for the new projection. */
        rpg_preload_mdx = pdx;
        rpg_preload_mdy = pdy;
        mset(rpg_preload_done, 0, sizeof rpg_preload_done);
    }
    /* Find the first unfilled NEW slot and compute it.  NEW = source
     * lies outside the old mosaic for this projected direction. */
    for (int sy = 0; sy < 3; sy++) {
        for (int sx = 0; sx < 3; sx++) {
            int old_sx = sx + pdx;
            int old_sy = sy + pdy;
            int is_new = (old_sx < 0 || old_sx > 2 ||
                          old_sy < 0 || old_sy > 2);
            if (is_new && !rpg_preload_done[sy * 3 + sx]) {
                rpg_preload_panel_compute(sx, sy);
                return;
            }
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

/* v0.2: pc-speaker port — the C-only audio counterpart to the JS
 * Web Audio score.  KIOCSOUND on /dev/tty1 is the only portable
 * way to drive the actual PC speaker from userland; it requires a
 * privileged seat at the console (root or membership in the tty
 * group, plus a host that has a real PC speaker).
 *
 * v0.3: the v0.2 comment claimed WSL would fail the open and fall
 * through to BEL.  False on WSL2 — /dev/tty1 exists, the open
 * succeeds, and the subsequent KIOCSOUND ioctl wedges WSL2's
 * virtualised vt console driver hard enough to require a Windows
 * reboot.  So now runtime-detect WSL via /proc/sys/kernel/osrelease
 * and short-circuit to BEL before touching /dev/tty1.
 *
 * Plays a four-note A-major arpeggio (A4, C♯5, E5, A5) — the same
 * "the action succeeded" flavour Web Audio uses for waltz down-
 * beats — with hx_sleep_ms between ioctl calls so the notes
 * separate audibly.  Always emits the stop ioctl on the way out,
 * otherwise the speaker holds the last tone until the next reboot. */
#define KIOCSOUND 0x4B2F
static int rpg_is_wsl(void) {
    char buf[256];
    int fd = (int)op("/proc/sys/kernel/osrelease", O_RDONLY, 0);
    if (fd < 0) return 0;
    long n = rd(fd, buf, sizeof buf - 1);
    cl(fd);
    if (n <= 0) return 0;
    buf[n] = 0;
    for (long i = 0; i + 8 < n; i++) {
        if ((buf[i]=='m'||buf[i]=='M') && (buf[i+1]=='i'||buf[i+1]=='I')
         && (buf[i+2]=='c'||buf[i+2]=='C') && (buf[i+3]=='r'||buf[i+3]=='R')
         && (buf[i+4]=='o'||buf[i+4]=='O') && (buf[i+5]=='s'||buf[i+5]=='S')
         && (buf[i+6]=='o'||buf[i+6]=='O') && (buf[i+7]=='f'||buf[i+7]=='F')
         && (buf[i+8]=='t'||buf[i+8]=='T')) return 1;
        if (buf[i]=='W' && buf[i+1]=='S' && buf[i+2]=='L') return 1;
    }
    return 0;
}
static int rpg_pc_speaker_chime(void) {
    /* v0.3: KIOCSOUND on WSL wedges LXSS — BEL only on WSL hosts. */
    if (rpg_is_wsl()) {
        wr(1, "\a", 1);
        return -1;
    }
    int fd = (int)op("/dev/tty1", O_WRONLY, 0);
    if (fd < 0) {
        wr(1, "\a", 1);
        return -1;
    }
    static const short notes_hz[4] = { 440, 554, 659, 880 };
    for (int i = 0; i < 4; i++) {
        long period = 1193180L / notes_hz[i];   /* PIT divisor */
        io(fd, KIOCSOUND, period);
        hx_sleep_ms(140);
    }
    io(fd, KIOCSOUND, 0);
    cl(fd);
    return 0;
}

/* ── v1.1: music-mood (port of JS ev42, monophonic pc-speaker) ─────
 *
 * 'M' (Shift+M) toggles a continuous mood-modulated melody on the
 * PC speaker.  Mechanics:
 *   - persistent fd to /dev/tty1, kept open while music is on
 *     (re-opening every note would thrash inode locks)
 *   - per-frame note picker: every N animating frames, KIOCSOUND
 *     a new period.  Tone holds between picks (square wave at the
 *     scale freq), so the speaker plays continuously instead of
 *     clicking
 *   - mood = hp ratio: ≥ half-HP picks A-major pentatonic; below
 *     picks A-minor pentatonic.  Tempo follows: high mood = 6-frame
 *     period, low mood = 12-frame (the world feels "slower" when
 *     wounded)
 *   - bytebeat formula `t·5 + (t>>3)` picks scale degree + octave,
 *     so the line walks the scale with occasional jumps, no
 *     repeating loop short enough to perceive
 *
 * WSL: same v0.3 guard as rpg_pc_speaker_chime — never touches
 * /dev/tty1, music is silently a no-op.  Other terminals open the
 * device but require a privileged seat (root or `tty` group); the
 * open fails gracefully → silent no-op.
 *
 * Closing the world (q/ESC, screensaver exit, terminal restore)
 * MUST call rpg_music_close so KIOCSOUND(0) clears the tone —
 * otherwise the speaker holds the last frequency until reboot. */
static int rpg_music_on = 0;
static int rpg_music_fd = -1;
static long rpg_music_next_frame = 0;
static unsigned long rpg_music_t = 0;

/* A-pentatonic scales · degrees in Hz, base octave (A3=220).
 * rpg_music_tick may shift up an octave for variety. */
static const short rpg_music_scale_major[5] = { 220, 247, 277, 330, 370 };
static const short rpg_music_scale_minor[5] = { 220, 247, 262, 330, 392 };

static void rpg_music_close(void) {
    if (rpg_music_fd >= 0) {
        io(rpg_music_fd, KIOCSOUND, 0);
        cl(rpg_music_fd);
        rpg_music_fd = -1;
    }
    rpg_music_on = 0;
}

static int rpg_music_open(void) {
    if (rpg_is_wsl()) return -1;
    if (rpg_music_fd >= 0) return 0;
    rpg_music_fd = (int)op("/dev/tty1", O_WRONLY, 0);
    return rpg_music_fd >= 0 ? 0 : -1;
}

static void rpg_music_tick(long frame) {
    if (!rpg_music_on || rpg_music_fd < 0) return;
    if (frame < rpg_music_next_frame) return;
    int hp_x16 = (rpg_player.max_hp > 0)
               ? (rpg_player.hp * 16) / rpg_player.max_hp : 8;
    const short *scale = (hp_x16 >= 8)
                       ? rpg_music_scale_major
                       : rpg_music_scale_minor;
    unsigned long t = rpg_music_t;
    unsigned long b = t * 5UL + (t >> 3);
    int idx     = (int)(b % 5);
    int oct_up  = (int)((b >> 4) & 1);
    long freq   = scale[idx] * (1 + oct_up);
    long period = 1193180L / freq;
    io(rpg_music_fd, KIOCSOUND, period);
    rpg_music_t = t + 1;
    rpg_music_next_frame = frame + (hp_x16 >= 8 ? 6 : 12);
}

/* v0.2: shot-bundle-full port — write the complete world state
 * (mosaic + every entity layer + active ruleset + world-coord
 * stack + player state) to a fixed file in cwd, mirroring the JS
 * `s` hotkey from ev57.  No image is bundled (the C build renders
 * to ANSI cells, not pixels); everything else needed to reproduce
 * the world deterministically goes in.  Format is a magic+version
 * header followed by the in-memory arrays back-to-back so reload
 * is a straight read-into-place. */
#define RPG_BUNDLE_FILE     "officerpg-state.bin"
#define RPG_BUNDLE_MAGIC    0x52504731u   /* "RPG1" little-endian */
#define RPG_BUNDLE_VERSION  1

static int rpg_save_bundle(char *action) {
    int fd = (int)op(RPG_BUNDLE_FILE,
                     O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) {
        if (action) action[sapp(action, 0, "save: open failed")] = 0;
        return -1;
    }
    /* Header: magic, version, world coord stack flat. */
    unsigned int hdr[2 + RPG_WORLD_LEVELS * 2];
    hdr[0] = RPG_BUNDLE_MAGIC;
    hdr[1] = RPG_BUNDLE_VERSION;
    for (int i = 0; i < RPG_WORLD_LEVELS; i++) {
        hdr[2 + i * 2    ] = (unsigned int)rpg_world_pos[i][0];
        hdr[2 + i * 2 + 1] = (unsigned int)rpg_world_pos[i][1];
    }
    wr(fd, hdr, sizeof hdr);
    /* Mosaic + entity layers (192*192 each = 36864 B). */
    wr(fd, rpg_map,        sizeof rpg_map);
    wr(fd, rpg_cat_at,     sizeof rpg_cat_at);
    wr(fd, rpg_npc_at,     sizeof rpg_npc_at);
    wr(fd, rpg_idx_at,     sizeof rpg_idx_at);
    wr(fd, rpg_hp_at,      sizeof rpg_hp_at);
    /* Active hex CA ruleset (4096 B in this layout). */
    wr(fd, hx_seed_genome, sizeof hx_seed_genome);
    /* Player snapshot — hp/mp/inv/skill/bend caps. */
    wr(fd, &rpg_player,    sizeof rpg_player);
    cl(fd);
    if (action)
        action[sapp(action, 0, "saved bundle → officerpg-state.bin")] = 0;
    return 0;
}

/* v0.2: shot-export port — write the next render's frame buffer
 * to officerpg-shot.ans.  cat'ing the file in a same-sized
 * terminal replays the rendering exactly (the file is just the
 * ANSI escape sequence the terminal would have received).  The
 * pending flag is checked by run_rpg's render loop just before
 * fbflush — that timing means the file holds the SAME frame the
 * user sees, with its status row's "shot →" confirmation included.
 *
 * Lowercase 'e' is the NE move so the export hotkey is uppercase
 * 'E'; lowercase 's' is reserved (legacy) and shift+S is bundle-
 * save, so this slot is the natural fit for an ANSI screenshot. */
#define RPG_SHOT_FILE "officerpg-shot.ans"
static int rpg_shot_pending = 0;

static int rpg_save_shot_to_file(void) {
    int fd = (int)op(RPG_SHOT_FILE,
                     O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return -1;
    static const char clr[] = "\033[2J\033[H";
    wr(fd, clr, sizeof clr - 1);
    wr(fd, fb, fbn);
    cl(fd);
    return 0;
}

/* v0.2: load bundle counterpart — Shift+L reads the file written
 * by Shift+S back into memory.  Validates the magic + version
 * before touching any in-memory state, so a stale or alien file
 * leaves the live world untouched.  Caches that depend on world
 * coords (cell-done, anim) get reset after the load so the next
 * render rebuilds from the freshly-restored layers. */
static int rpg_load_bundle(char *action) {
    int fd = (int)op(RPG_BUNDLE_FILE, O_RDONLY, 0);
    if (fd < 0) {
        if (action) action[sapp(action, 0, "load: no bundle file")] = 0;
        return -1;
    }
    unsigned int hdr[2 + RPG_WORLD_LEVELS * 2];
    long n = rd(fd, hdr, sizeof hdr);
    if (n != (long)sizeof hdr ||
        hdr[0] != RPG_BUNDLE_MAGIC ||
        hdr[1] != RPG_BUNDLE_VERSION) {
        cl(fd);
        if (action) action[sapp(action, 0, "load: bad header")] = 0;
        return -1;
    }
    /* Stage into scratch first so a partial read doesn't corrupt
     * the live world.  rpg_buf is the existing CA scratch ring
     * which is already 192×192 = same size as one mosaic layer. */
    int ok = 1;
    ok &= rd(fd, rpg_map,        sizeof rpg_map)        == (long)sizeof rpg_map;
    ok &= rd(fd, rpg_cat_at,     sizeof rpg_cat_at)     == (long)sizeof rpg_cat_at;
    ok &= rd(fd, rpg_npc_at,     sizeof rpg_npc_at)     == (long)sizeof rpg_npc_at;
    ok &= rd(fd, rpg_idx_at,     sizeof rpg_idx_at)     == (long)sizeof rpg_idx_at;
    ok &= rd(fd, rpg_hp_at,      sizeof rpg_hp_at)      == (long)sizeof rpg_hp_at;
    ok &= rd(fd, hx_seed_genome, sizeof hx_seed_genome) == (long)sizeof hx_seed_genome;
    ok &= rd(fd, &rpg_player,    sizeof rpg_player)     == (long)sizeof rpg_player;
    cl(fd);
    if (!ok) {
        if (action) action[sapp(action, 0, "load: short read")] = 0;
        return -1;
    }
    for (int i = 0; i < RPG_WORLD_LEVELS; i++) {
        rpg_world_pos[i][0] = (int)hdr[2 + i * 2    ];
        rpg_world_pos[i][1] = (int)hdr[2 + i * 2 + 1];
    }
    /* Cell-derived caches are stale now; the next render will
     * lazy-rebuild them on demand. */
    mset(rpg_cell_done, 0, sizeof rpg_cell_done);
    rpg_genome_live_cache = -1;
    rpg_palettes_refresh();
    rpg_preload_invalidate();
    if (action)
        action[sapp(action, 0, "loaded bundle ← officerpg-state.bin")] = 0;
    return 0;
}

/* Re-seed the RNG from the world coord stack and regenerate the
 * 3×3 mosaic + entities.  spawn (x, y) is in mosaic coords (0..192)
 * and determines the 3×3 clear-zone around the player's entry point.
 * office51 — refreshes palettes + panel-seed cache up front so the
 * world-stable cell hash returns valid results from the very first
 * lazy rpg_compute_cell after the load. */
static void rpg_load_overworld(int spawn_x, int spawn_y) {
    rpg_palettes_refresh();
    rpg_init_map(hx_seed_genome);
    rpg_init_entities(spawn_x, spawn_y);
    rpg_genome_live_cache = -1;
    mset(rpg_cell_done, 0, sizeof rpg_cell_done);
    /* v0.2: animals just regenerated — drop any stale action
     * state from the prior overworld so new spawns start in
     * AA_WALK with no ghost timers. */
    mset(rpg_animal_action,     0, sizeof rpg_animal_action);
    mset(rpg_animal_action_ttl, 0, sizeof rpg_animal_action_ttl);
    rpg_anim_reset();
}

/* office51 — shift the 3×3 mosaic by (dx, dy) ∈ {-1,0,+1}².  Fast
 * path (when the shadow has every NEW panel for this direction):
 * memmove the 4-6 reused panels into their new slots and splat the
 * pre-computed shadow into the 3-5 new slots — pure memcpy, no CA
 * stepping, imperceptible.  Slow fallback (shadow incomplete or
 * direction mismatch): full 9-panel regen, same as office50. */
static void rpg_shift_mosaic(int dx, int dy, int spawn_x, int spawn_y,
                             char hex_move) {
    if (dx == 0 && dy == 0) return;
    rpg_world_advance(dx, dy, hex_move);

    int shadow_ok = (rpg_preload_mdx == dx && rpg_preload_mdy == dy);
    if (shadow_ok) {
        for (int sy = 0; sy < 3 && shadow_ok; sy++) {
            for (int sx = 0; sx < 3 && shadow_ok; sx++) {
                int old_sx = sx + dx, old_sy = sy + dy;
                int is_new = (old_sx < 0 || old_sx > 2 ||
                              old_sy < 0 || old_sy > 2);
                if (is_new && !rpg_preload_done[sy * 3 + sx])
                    shadow_ok = 0;
            }
        }
    }

    if (shadow_ok) {
        /* Pass 1 — memmove REUSED panels.  Iteration order matters:
         * each chain (mdx=-1 → new1←old0, new2←old1) must process
         * the higher-index slot first so its source isn't overwritten
         * before being read. */
        int sxs = (dx <= 0) ? 2 : 0, sxe = (dx <= 0) ? -1 : 3;
        int sxd = (dx <= 0) ? -1 : 1;
        int sys = (dy <= 0) ? 2 : 0, sye = (dy <= 0) ? -1 : 3;
        int syd = (dy <= 0) ? -1 : 1;
        for (int sy = sys; sy != sye; sy += syd) {
            for (int sx = sxs; sx != sxe; sx += sxd) {
                int old_sx = sx + dx, old_sy = sy + dy;
                int reused = (old_sx >= 0 && old_sx <= 2 &&
                              old_sy >= 0 && old_sy <= 2);
                if (reused && (sx != old_sx || sy != old_sy))
                    rpg_panel_copy_live(sx, sy, old_sx, old_sy);
            }
        }
        /* Pass 2 — install shadow into the NEW slots. */
        for (int sy = 0; sy < 3; sy++) {
            for (int sx = 0; sx < 3; sx++) {
                int old_sx = sx + dx, old_sy = sy + dy;
                int is_new = (old_sx < 0 || old_sx > 2 ||
                              old_sy < 0 || old_sy > 2);
                if (is_new) {
                    struct RpgPanelShadow *p =
                        &rpg_preload_panel[sy * 3 + sx];
                    rpg_panel_splat(sx, sy, p->map, p->cat_at,
                                    p->idx_at, p->hp_at, p->npc_at);
                }
            }
        }
    } else {
        /* Slow fallback — full 9-panel regen.  Hits when player
         * crosses faster than preload could fill the shadow or
         * changes direction on the cusp. */
        rpg_load_overworld(spawn_x, spawn_y);
        rpg_preload_invalidate();
        return;
    }

    /* Refresh per-panel palettes + the panel-seed cache the
     * world-stable cell hash reads. */
    rpg_palettes_refresh();

    /* Clear a 3×3 around the spawn so the player isn't boxed in. */
    for (int dy2 = -1; dy2 <= 1; dy2++) {
        for (int dx2 = -1; dx2 <= 1; dx2++) {
            int nx = spawn_x + dx2, ny = spawn_y + dy2;
            if (nx >= 0 && nx < RPG_TILE_W &&
                ny >= 0 && ny < RPG_TILE_H) {
                rpg_cat_at[ny * RPG_TILE_W + nx] = 0;
                rpg_npc_at[ny * RPG_TILE_W + nx] = 0;
            }
        }
    }

    /* Cell sample/pal cache is keyed by mosaic position; same world
     * cell now lives at a different mosaic slot, so invalidate.  With
     * world-stable hashes the recomputed values match prior ones —
     * cross-overs visually identical, just lazy-recomputed. */
    mset(rpg_cell_done, 0, sizeof rpg_cell_done);
    rpg_anim_reset();
    rpg_preload_invalidate();
}

/* office50 — generate a procedural closed-loop path of hex directions.
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
                /* v0.2: carry the action + TTL with the moving
                 * animal, then bump to EAT briefly if it just
                 * walked next to a plant cell.  Skipped when
                 * the halo subsystem is off so path-tick stays
                 * at its pre-anim cost — the rpg_animal_near_
                 * plant call alone is six neighbour reads × N
                 * walking animals every tick. */
                if (rpg_animal_anim_on) {
                    unsigned char a   = rpg_animal_action    [idx];
                    unsigned char ttl = rpg_animal_action_ttl[idx];
                    rpg_animal_action    [idx] = 0;
                    rpg_animal_action_ttl[idx] = 0;
                    if (rpg_animal_near_plant(nx, ny)) {
                        rpg_animal_action    [nidx] = AA_EAT;
                        rpg_animal_action_ttl[nidx] = AA_TTL_DEFAULT;
                    } else {
                        rpg_animal_action    [nidx] = a;
                        rpg_animal_action_ttl[nidx] = ttl;
                    }
                }
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
    /* v0.2 / ev67-port: drop per-cell action TTLs once per
     * render so halos fade back to walk after their window.
     * Skipped entirely when the halo subsystem is off (the
     * default) so the linear 36864-cell sweep doesn't run
     * when the feature is disengaged. */
    if (rpg_animal_anim_on) rpg_animal_action_tick();
    int origin_y = g_rpg_fullscreen ? 0 : 1;
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
            /* v0.2 / ev67-port: action-anim halo — paint a
             * 1-cell coloured patch one row above the sprite
             * top when the animal has a non-WALK action active.
             * Gated on rpg_animal_anim_on so the visible-cell
             * loop runs at pre-anim cost when off (the action
             * arrays are also kept at zero in that mode, so the
             * `act != AA_WALK` test would always fail anyway —
             * the explicit gate is one cmp per animal cell). */
            if (rpg_animal_anim_on && cat == RC_ANIMAL) {
                unsigned char act = rpg_animal_action[idx];
                if (act != AA_WALK) {
                    int sy = base_y + 2 - h;
                    if (sy >= origin_y &&
                        sy < origin_y + rows_v * RPG_CELL_H) {
                        int sx = art_x + RPG_SPRITE_W / 2;
                        if (sx >= 0 && sx < SCREEN_W) {
                            cup(sx, sy);
                            sgrbg(rpg_animal_action_color[act & 3]);
                            fbs(" ");
                        }
                    }
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
            int variant_hit = rpg_idx_at[idx];
            hp = (hp > dmg_e) ? hp - dmg_e : 0;
            rpg_hp_at[idx] = (unsigned char)hp;
            int n = sapp(msg, 0, "hit ");
            n = sapp(msg, n, ec->name);
            n = sapp(msg, n, " for ");
            n += utoa((unsigned)dmg_e, msg + n);
            /* v0.2 animal-action-anim: hit animal flips to ATTACK
             * halo + every same-variant hex-neighbour to FLEE so
             * the swing reads visibly as it happens.  Gated on
             * rpg_animal_anim_on (ev67 port) — when off, the
             * action arrays stay zero and no bookkeeping runs. */
            if (rpg_animal_anim_on) {
                rpg_animal_action    [idx] = AA_ATTACK;
                rpg_animal_action_ttl[idx] = AA_TTL_DEFAULT;
                rpg_animal_spook_kin(nx, ny, variant_hit);
            }
            if (hp == 0) {
                rpg_cat_at[idx] = 0;
                if (rpg_animal_anim_on) {
                    rpg_animal_action    [idx] = AA_WALK;
                    rpg_animal_action_ttl[idx] = 0;
                }
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

    /* office53 — silent GA so the player stays on the overworld.
     * The GA still runs `gens` generations and adopts the winner;
     * after the brief pause we invalidate the cell cache + refresh
     * palettes and the next render shows the world repopulating
     * with the evolved CA + colours. */
    unsigned int rseed = (unsigned int)(time_() ^ (long)hx_rand());
    hx_run_ga_session(20, gens, rseed, /*silent=*/1);

    /* Rebuild rpg state to reflect the evolved CA. */
    rpg_palettes_refresh();
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
     * already populated these at office startup; rpg_load_overworld
     * refreshes terrain RGBs + the panel-seed cache itself so any
     * palette change the user made in hxhnt this session takes
     * effect on the next mosaic generation. */
    hx_active_init();
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
    rpg_preload_invalidate();      /* fresh shadow each launch */

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
            /* v0.6: pool GA runs only when per-cell rules are on
             * (fast no-op gate inside).  Tied to rpg_animating so
             * dormant worlds don't drift unobserved. */
            rpg_pool_ga_tick(rpg_frame);
            /* v1.1: music note-picker.  Internal gate handles "off"
             * fast path; tied to rpg_animating so notes only fire
             * while the world is moving. */
            rpg_music_tick(rpg_frame);
            /* v1.2: L-system GA — drift the sprite library over
             * time when toggled on (G).  Slow cadence (every
             * RPG_LSYS_GA_PERIOD frames) so changes are noticeable
             * but not jarring. */
            rpg_lsys_ga_tick(rpg_frame);
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
        hl = sapp(hint, hl, "wadezx=move i=inv m=zap l=live k=speeds 0-7=bend "
                            "S=save L=load E=shot b=beep h=halos q ");
        hint[hl] = 0;
        status(hint);
        /* v0.2: if a shot was requested by the previous key-handler
         * (E pressed), capture the just-built frame buffer to disk
         * BEFORE fbflush wipes it.  The file contains the exact
         * ANSI sequence the terminal sees, so cat'ing it back
         * replays the snapshot. */
        if (rpg_shot_pending) {
            rpg_save_shot_to_file();
            rpg_shot_pending = 0;
        }
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
        /* v0.2: uppercase 'L' loads the saved bundle (port of
         * JS shot-bundle-full reload).  Lowercase 'l' keeps its
         * legacy live-anim-toggle role; they were aliased before
         * this fork so we tighten the match here. */
        if (k[0] == 'L') {
            action[0] = 0;
            rpg_load_bundle(action);
            idle_ticks = 0;
            continue;
        }
        if (k[0] == 'l') {
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
        char raw = k[0];
        char c = raw;
        if (c >= 'A' && c <= 'Z') c += 32;
        /* v0.2: 'S' (shift+s) writes the full world state to disk —
         * port of JS shot-bundle-full.  Lowercase 's' stays reserved
         * for future use as it has been since office50. */
        if (raw == 'S') {
            action[0] = 0;
            rpg_save_bundle(action);
            idle_ticks = 0;
            continue;
        }
        /* v0.2: 'E' (shift+e) — port of JS shot-export.  Sets the
         * pending flag; the render loop captures fb to disk on the
         * next frame so the file content matches the on-screen
         * frame including this command's "shot →" confirmation. */
        if (raw == 'E') {
            rpg_shot_pending = 1;
            action[sapp(action, 0, "shot → officerpg-shot.ans")] = 0;
            idle_ticks = 0;
            continue;
        }
        /* v0.2 / ev67-port: 'h' toggles the animal halo subsystem.
         * Off by default — the per-frame tick + halo paint slow
         * the render under live + journey, and the L-system
         * sprite already conveys "this is an animal" without
         * the halo.  Engaging clears any in-flight TTLs so a
         * fresh re-engage starts from a clean state. */
        if (c == 'h') {
            rpg_animal_anim_on = !rpg_animal_anim_on;
            if (!rpg_animal_anim_on) {
                mset(rpg_animal_action,     0, sizeof rpg_animal_action);
                mset(rpg_animal_action_ttl, 0, sizeof rpg_animal_action_ttl);
            }
            action[0] = 0;
            action[sapp(action, 0,
                rpg_animal_anim_on ? "animal halos ON"
                                   : "animal halos OFF")] = 0;
            idle_ticks = 0;
            continue;
        }
        /* v0.5: 'u' toggles the per-cell rule pool (port of JS
         * ev52); Shift+U ('U') discards the pool so the next
         * ensure rebuilds it against the current mother — useful
         * after Shift+L loads a different bundle. */
        if (c == 'u') {
            action[0] = 0;
            if (raw == 'U') {
                rpg_reseed_rule_pool();
                action[sapp(action, 0,
                    "rule pool reseeded from mother")] = 0;
            } else {
                if (!rpg_per_cell_rules_on) {
                    rpg_ensure_rule_pool();
                    rpg_per_cell_rules_on = 1;
                    rpg_pool_ga_last_frame = -1;   /* fire on next frame */
                    action[sapp(action, 0,
                        "per-cell rules ON · 256-slot pool · GA breeding")] = 0;
                } else {
                    rpg_per_cell_rules_on = 0;
                    action[sapp(action, 0,
                        "per-cell rules OFF · mother only")] = 0;
                }
                mset(rpg_cell_done, 0, sizeof rpg_cell_done);
            }
            idle_ticks = 0;
            continue;
        }
        /* v1.2: 'G' (Shift+G) toggles the L-system GA.  When ON,
         * sprite rule strings drift via tournament-2 within each
         * category — animals stay animal-shaped but their exact
         * silhouettes evolve.  Sprite caches invalidate per-slot
         * so changes are visible on the next render of an entity
         * using that archetype. */
        if (raw == 'G') {
            rpg_lsys_ga_on = !rpg_lsys_ga_on;
            if (rpg_lsys_ga_on) rpg_lsys_ga_last_frame = -1;
            action[0] = 0;
            action[sapp(action, 0,
                rpg_lsys_ga_on
                  ? "L-system GA ON · sprites drift over time"
                  : "L-system GA OFF")] = 0;
            idle_ticks = 0;
            continue;
        }
        /* v1.1: 'M' (Shift+M) toggles mood-modulated music — port
         * of JS ev42 onto pc-speaker.  Lowercase 'm' is "cast zap"
         * since v0.1 so the toggle is uppercase only. */
        if (raw == 'M') {
            action[0] = 0;
            if (rpg_music_on) {
                rpg_music_close();
                action[sapp(action, 0, "♪ music OFF")] = 0;
            } else {
                if (rpg_music_open() == 0) {
                    rpg_music_on = 1;
                    rpg_music_next_frame = 0;
                    action[sapp(action, 0,
                        "♪ music ON · pc-speaker pentatonic")] = 0;
                } else {
                    action[sapp(action, 0,
                        "♪ music unavailable (WSL or no /dev/tty1)")] = 0;
                }
            }
            idle_ticks = 0;
            continue;
        }
        /* v0.2: 'B' (beep) — pc-speaker chime port.  Tries KIOCSOUND
         * on /dev/tty1; if that's not accessible, rings the BEL.
         * Audible feedback you can trigger anywhere in the world. */
        if (c == 'b') {
            action[0] = 0;
            int rc = rpg_pc_speaker_chime();
            action[sapp(action, 0,
                rc == 0 ? "♪ pc speaker"
                        : "♪ bell (no pc speaker)")] = 0;
            idle_ticks = 0;
            continue;
        }
        if (c == 's') continue;   /* reserved */
        action[0] = 0;
        rpg_move(&px, &py, c, action);
        rpg_path_tick(px, py);
        /* office51 — pre-load the projected new edge panels into the
         * shadow buffer one panel per tick whenever the player is
         * within RPG_PRELOAD_MARGIN cells of a central-panel boundary.
         * By the time the cross fires below, most/all of the work is
         * already done off-screen. */
        rpg_preload_advance_one(px, py);
        /* Mosaic shift — if the player has stepped out of the central
         * 64×64 sub-region of the 192×192 mosaic, advance the world
         * stack and regenerate so they're back in the centre.  This
         * guarantees the player never sees an unloaded edge.
         *
         * v0.2: pixel transform stays rectangular so the player ends
         * up centred in the new mosaic regardless of hex offset, but
         * the world advance is hex-resolved — an NW move out of an
         * even my-row bumps mx by -1 in addition to my by -1, which
         * the rectangular mdx/mdy alone wouldn't capture. */
        {
            int mdx = 0, mdy = 0;
            if (px <  RPG_MAP_W)         mdx = -1;
            else if (px >= 2 * RPG_MAP_W)mdx =  1;
            if (py <  RPG_MAP_H)         mdy = -1;
            else if (py >= 2 * RPG_MAP_H)mdy =  1;
            if (mdx || mdy) {
                px -= mdx * RPG_MAP_W;
                py -= mdy * RPG_MAP_H;
                int meta_dx = mdx, meta_dy = mdy;
                int hdx = 0, hdy = 0;
                rpg_hex_meta_shift(c, rpg_world_pos[0][1], &hdx, &hdy);
                if (hdx || hdy) { meta_dx = hdx; meta_dy = hdy; }
                rpg_shift_mosaic(meta_dx, meta_dy, px, py, c);
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
    /* v1.1: silence + close pc-speaker fd before yielding the
     * terminal — otherwise KIOCSOUND holds the last tone past exit. */
    rpg_music_close();
    term_cooked();
    return 0;
}


/* ── saver: rpg screensaver (office50) ────────────────────
 * Auto-plays the rpg world in fullscreen — clears the screen black,
 * sets g_rpg_fullscreen so render_view drops origin_y to 0, and
 * loops a directed hex move every ~300 ms.  Animals + NPCs keep
 * wandering on their closed-loop paths each tick; the 3×3 mosaic
 * shifts as the player crosses sub-overworlds.  Any keypress exits
 * cleanly.  No chrome, no status bar — just the world.
 *
 * v0.2: simplified port of the JS autoplay-journey planner.  Picks
 * a hex heading on engage and forward-projects each candidate move
 * onto it — so the player walks in a real direction instead of
 * drifting randomly, while still reading as exploratory.  6 recent
 * positions kept in a ring to detect oscillation; on hit, switch
 * to a chaos burst (uniform-random over legal cells) for a few
 * ticks before resuming the heading.  Heading drifts ±1 slot
 * every ~30 steps so the run still wanders new territory. */

/* Hex unit vectors scaled ×2 so a/d (horizontal) and w/e/z/x
 * (vertical-with-half-tile-x) sit on integer coordinates and the
 * dot product is a clean projection scalar. */
static const signed char rpg_hex_ddx[6] = { -2, +2, -1, +1, -1, +1 };
static const signed char rpg_hex_ddy[6] = {  0,  0, -2, -2, +2, +2 };
static const char        rpg_hex_dirs[6] = { 'a', 'd', 'w', 'e', 'z', 'x' };

/* Same simulate-move-without-applying as JS autoplaySimMove.  Used
 * by the journey planner to score candidate moves before commit. */
static void rpg_sim_move(int x, int y, char dir, int *nx, int *ny) {
    int odd = y & 1;
    *nx = x; *ny = y;
    switch (dir) {
    case 'a': *nx = x - 1; break;
    case 'd': *nx = x + 1; break;
    case 'w': *ny = y - 1; *nx = x + (odd ? 0 : -1); break;
    case 'e': *ny = y - 1; *nx = x + (odd ? 1 : 0); break;
    case 'z': *ny = y + 1; *nx = x + (odd ? 0 : -1); break;
    case 'x': *ny = y + 1; *nx = x + (odd ? 1 : 0); break;
    }
}

#define RPG_JOURNEY_RING 6

/* Pick the next move for the screensaver / autoplay planner.
 * `heading` is one of 0..5 indexing into rpg_hex_ddx/ddy.
 * `chaos`   non-zero → random walk (oscillation-break), uses rng
 *           only for tie-breaking and ignores heading projection.
 * `ring`    last RPG_JOURNEY_RING (x, y) cells; revisits get a
 *           small penalty so the planner doesn't bounce.
 * Returns the chosen direction character. */
static char rpg_journey_pick(int px, int py, int heading,
                             int chaos, unsigned long *rng,
                             const short ring[][2], int ring_n) {
    int hdx = rpg_hex_ddx[heading & 5];
    int hdy = rpg_hex_ddy[heading & 5];
    int best_score = -1000000;
    int best_i     = 0;
    /* Step the rng once up front so noise is stable across the loop. */
    *rng = *rng * 6364136223846793005UL + 1442695040888963407UL;
    unsigned long noise = *rng >> 32;
    for (int i = 0; i < 6; i++) {
        int nx, ny;
        rpg_sim_move(px, py, rpg_hex_dirs[i], &nx, &ny);
        if (nx < 0 || nx >= RPG_TILE_W ||
            ny < 0 || ny >= RPG_TILE_H) continue;
        int idx = ny * RPG_TILE_W + nx;
        int pen = 0;
        /* Hard penalties: water, NPC, plant, building.  Same set
         * the JS version treats as blocking / costly. */
        if ((rpg_map[idx] & 3) == 3) pen += 100;
        if (rpg_npc_at[idx])         pen += 100;
        unsigned char cat = rpg_cat_at[idx];
        if (cat == RC_PLANT || cat == RC_BUILDING) pen += 100;
        /* Anti-revisit: any cell in the ring gets +1, more for
         * fresher entries.  Subtle on its own; in chaos mode the
         * caller raises the weight by passing a high heading slot. */
        for (int r = 0; r < ring_n; r++) {
            if (ring[r][0] == nx && ring[r][1] == ny) {
                pen += 2 + (ring_n - r);
                break;
            }
        }
        int score;
        if (chaos) {
            /* Random walk: legal moves all roughly tied, jitter
             * picks among them.  Penalties still dominate so we
             * don't bury into water during the burst. */
            score = -pen + (int)((noise >> (i * 4)) & 0xf);
        } else {
            /* Forward projection in the heading's direction. */
            int ddx = nx - px, ddy = ny - py;
            int proj = ddx * hdx + ddy * hdy;
            score = proj * 4 - pen + (int)((noise >> (i * 4)) & 0x3);
        }
        if (score > best_score) { best_score = score; best_i = i; }
    }
    return rpg_hex_dirs[best_i];
}
static int run_screensaver(int argc, char **argv) {
    (void)argc; (void)argv;
    hx_active_init();
    rpg_sprites_init();
    mset(rpg_world_pos, 0, sizeof rpg_world_pos);
    int px = RPG_TILE_W / 2;
    int py = RPG_TILE_H / 2;
    rpg_load_overworld(px, py);
    rpg_player_init();
    rpg_preload_invalidate();
    rpg_terrain_anim_init();
    rpg_animating = 0;
    rpg_frame = 0;
    g_rpg_fullscreen = 1;

    /* Polling termios — VTIME ~250 ms is the move/render cadence,
     * VMIN=0 so any keypress unblocks read_key immediately. */
    struct ti rt = term_orig;
    rt.lflag &= ~(ICANON | ECHO);
    rt.iflag &= ~(IXON | ICRNL);
    rt.cc[6] = 0;     /* VMIN  */
    rt.cc[5] = 3;     /* VTIME = 300 ms */
    io(0, TCSETS, &rt);

    /* Fresh black canvas. */
    sgr0();
    sgrbg(0);
    fbs("\033[2J");
    fbflush();

    unsigned long s;
    {
        unsigned long h, l;
        __asm__ volatile ("rdtsc" : "=d"(h), "=a"(l));
        s = (h << 32) | l | 1ULL;
    }
    char action[80]; action[0] = 0;

    /* Journey-planner state.  Heading is rotated through the 6 hex
     * slots; ring tracks the last few visited cells for oscillation
     * detection; chaos counter forces N random-walk ticks after we
     * spot a position repeat 3+ times in the ring.
     *
     * autoplay-stuck (ev45 escalation ladder): each successive
     * chaos trigger within RPG_JOURNEY_RESTUCK ticks of the previous
     * one bumps `chaos_level` up — bigger heading kick on exit and
     * longer random-walk burst.  A clean run (no restuck for
     * RPG_JOURNEY_CALM ticks) resets the level back to 1. */
    int journey_heading      = (int)((s >> 17) % 6);
    int journey_steps        = 0;        /* since last drift     */
    int journey_total_steps  = 0;        /* since session start  */
    int journey_chaos        = 0;        /* random-walk counter  */
    int journey_chaos_level  = 1;        /* L1..L3 escalation    */
    int journey_last_chaos   = -1000;    /* tick of last burst   */
    short journey_ring[RPG_JOURNEY_RING][2];
    for (int i = 0; i < RPG_JOURNEY_RING; i++) {
        journey_ring[i][0] = -1; journey_ring[i][1] = -1;
    }
    int journey_ring_n = 0;

    static const signed char rpg_chaos_ticks[4] = { 8, 8, 16, 24 };

    for (;;) {
        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n > 0) break;

        journey_total_steps++;

        /* Oscillation detection — count how many ring entries match
         * the player's current cell.  3+ hits in a 6-cell ring is a
         * clear A↔B bounce or U-turn, so trigger a chaos burst. */
        int chaos_will_start = 0;
        if (journey_chaos == 0) {
            int hits = 0;
            for (int i = 0; i < journey_ring_n; i++)
                if (journey_ring[i][0] == px && journey_ring[i][1] == py)
                    hits++;
            if (hits >= 3) chaos_will_start = 1;
        }
        if (chaos_will_start) {
            int delta = journey_total_steps - journey_last_chaos;
            if (delta < 60 && journey_chaos_level < 3)
                journey_chaos_level++;
            else if (delta >= 200)
                journey_chaos_level = 1;
            journey_chaos       = rpg_chaos_ticks[journey_chaos_level];
            journey_last_chaos  = journey_total_steps;
        }

        int prev_chaos = journey_chaos;
        if (journey_chaos > 0) journey_chaos--;

        /* Heading drift — every ~30 steps, rotate ±1 slot so the run
         * doesn't pin to one azimuth indefinitely.  At chaos exit we
         * kick by chaos_level slots so the resume direction isn't
         * the same one that got stuck — bigger kick at higher
         * escalation. */
        journey_steps++;
        if (prev_chaos > 0 && journey_chaos == 0) {
            s = s * 6364136223846793005UL + 1442695040888963407UL;
            int kick = journey_chaos_level;
            int sign = ((s >> 33) & 1) ? 1 : -1;
            journey_heading = ((journey_heading + sign * kick) % 6 + 6) % 6;
        }
        if (journey_steps >= 30) {
            journey_steps = 0;
            s = s * 6364136223846793005UL + 1442695040888963407UL;
            journey_heading = (journey_heading + 5 + (int)((s >> 33) & 3)) % 6;
        }

        char c = rpg_journey_pick(px, py, journey_heading,
                                  journey_chaos > 0, &s,
                                  journey_ring, journey_ring_n);

        /* Push current cell onto the ring (FIFO of the last N). */
        for (int i = RPG_JOURNEY_RING - 1; i > 0; i--) {
            journey_ring[i][0] = journey_ring[i - 1][0];
            journey_ring[i][1] = journey_ring[i - 1][1];
        }
        journey_ring[0][0] = (short)px;
        journey_ring[0][1] = (short)py;
        if (journey_ring_n < RPG_JOURNEY_RING) journey_ring_n++;

        action[0] = 0;
        rpg_move(&px, &py, c, action);
        rpg_path_tick(px, py);
        rpg_preload_advance_one(px, py);

        int mdx = 0, mdy = 0;
        if (px <  RPG_MAP_W)         mdx = -1;
        else if (px >= 2 * RPG_MAP_W)mdx =  1;
        if (py <  RPG_MAP_H)         mdy = -1;
        else if (py >= 2 * RPG_MAP_H)mdy =  1;
        if (mdx || mdy) {
            px -= mdx * RPG_MAP_W;
            py -= mdy * RPG_MAP_H;
            int meta_dx = mdx, meta_dy = mdy;
            int hdx = 0, hdy = 0;
            rpg_hex_meta_shift(c, rpg_world_pos[0][1], &hdx, &hdy);
            if (hdx || hdy) { meta_dx = hdx; meta_dy = hdy; }
            rpg_shift_mosaic(meta_dx, meta_dy, px, py, c);
        }
        /* v0.4: ev43 death-respawn port — rpg_move can knock hp to 0
         * via animal contact; in interactive run_rpg the player sees a
         * modal and presses any key to restart, but journey mode runs
         * unattended.  Render the death banner briefly, reset the
         * player (HP/MP/inv), re-seed the journey planner with a
         * fresh heading + empty ring so the resume doesn't immediately
         * re-stuck against whatever killed us, and keep going.  Check
         * fires BEFORE the per-tick heal — otherwise hp would tick
         * back to 1 each loop and death would never register. */
        if (rpg_player.hp <= 0) {
            cup(2, 0);
            sgrbgfg(196, 15);
            fbs(" YOU DIED — journey respawn ");
            sgr0();
            fbflush();
            hx_sleep_ms(1500);
            rpg_player_init();
            s = s * 6364136223846793005UL + 1442695040888963407UL;
            journey_heading      = (int)((s >> 17) % 6);
            journey_steps        = 0;
            journey_chaos        = 0;
            journey_chaos_level  = 1;
            journey_last_chaos   = -1000;
            for (int i = 0; i < RPG_JOURNEY_RING; i++) {
                journey_ring[i][0] = -1; journey_ring[i][1] = -1;
            }
            journey_ring_n = 0;
        }
        if (rpg_player.hp < rpg_player.max_hp) rpg_player.hp++;
        if (rpg_player.mp < rpg_player.max_mp) rpg_player.mp++;

        rpg_render_view(px, py);
        fbflush();
    }

    g_rpg_fullscreen = 0;
    rt.cc[6] = 1;
    rt.cc[5] = 0;
    io(0, TCSETS, &rt);
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

/* ── net diagnostics panel ─────────────────────────────
 * Tier-1 introspection for jailed office instances.  Inside the
 * `garden` jail every office process is PID 1 in its own pid-ns,
 * so getpid() collapses identity.  jail.c (sibling tool) compensates
 * by injecting `--instance=<8hex>` into argv before execve and
 * sethostname()-ing a unique UTS hostname; this panel surfaces both
 * along with a "am I jailed?" verdict, namespace-inode fingerprints,
 * uid_map mapping, and any listening tcp4 ports parsed from
 * /proc/net/tcp.  No syscalls beyond what seccomp_full already
 * permits (open/read/close + uname + readlink), so it works inside
 * the existing seccomp filter without widening.  Tiers 2-4 will hang
 * server loops + outbound probes off the same panel. */

static int net_read_file(const char *path, char *out, int max) {
    int fd = (int)op(path, O_RDONLY, 0);
    if (fd < 0) { out[0] = 0; return -1; }
    long n = rd(fd, out, max - 1);
    cl(fd);
    if (n < 0) n = 0;
    out[n] = 0;
    return (int)n;
}

static int net_readlink(const char *path, char *out, int max) {
    long n = sys4(SYS_readlink, (long)path, (long)out, (long)(max - 1), 0);
    if (n < 0) { out[0] = 0; return -1; }
    out[n] = 0;
    return (int)n;
}

static unsigned net_hex_to_u(const char *p, const char *e) {
    unsigned v = 0;
    while (p < e) {
        char c = *p++;
        int d = (c >= '0' && c <= '9') ? c - '0'
              : (c >= 'a' && c <= 'f') ? c - 'a' + 10
              : (c >= 'A' && c <= 'F') ? c - 'A' + 10 : 0;
        v = v * 16 + d;
    }
    return v;
}

static int run_net(int argc, char **argv) {
    (void)argc; (void)argv;
    current_ms = &ms_shell;
    term_raw_polling();

    char hostname[80];
    char ns_user[64], ns_pid[64], ns_net[64], ns_mnt[64], ns_uts[64];
    char uid_map[256], tcp4[4096];
    char buf[256];

    int redraw = 1;
    int running = 1;
    while (running) {
        if (redraw) {
            /* utsname is 6 × 65-byte fields; nodename is the 2nd. */
            char uts[6 * 65];
            mset(uts, 0, sizeof uts);
            sys3(SYS_uname, (long)uts, 0, 0);
            int hi = 0;
            while (hi < 64 && uts[65 + hi]) { hostname[hi] = uts[65 + hi]; hi++; }
            hostname[hi] = 0;

            net_readlink("/proc/self/ns/user", ns_user, sizeof ns_user);
            net_readlink("/proc/self/ns/pid",  ns_pid,  sizeof ns_pid);
            net_readlink("/proc/self/ns/net",  ns_net,  sizeof ns_net);
            net_readlink("/proc/self/ns/mnt",  ns_mnt,  sizeof ns_mnt);
            net_readlink("/proc/self/ns/uts",  ns_uts,  sizeof ns_uts);
            net_read_file("/proc/self/uid_map", uid_map, sizeof uid_map);
            net_read_file("/proc/net/tcp",      tcp4,    sizeof tcp4);

            long my_pid = getpid_();
            /* Heuristic: a userns places "0 <huid> 1" in uid_map, while
             * the init userns shows "0 0 4294967295".  Combine with
             * pid==1 for confidence. */
            int jailed_userns = 0;
            {
                const char *q = uid_map;
                while (*q == ' ') q++;
                while (*q && *q != ' ' && *q != '\n') q++;
                while (*q == ' ') q++;
                while (*q && *q != ' ' && *q != '\n') q++;
                while (*q == ' ') q++;
                if (q[0] == '1' && (q[1] == '\n' || q[1] == 0))
                    jailed_userns = 1;
            }
            int pid_one = (my_pid == 1);

            paint_desktop();
            chrome("Net — instance & isolation");
            body_clear();
            int p, y = 2;

            /* identity row */
            p = 0;
            p = sapp(buf, p, "instance: ");
            p = sapp(buf, p, g_instance_token[0] ? g_instance_token : "(host)");
            p = sapp(buf, p, "   pid: ");
            p += utoa((unsigned)my_pid, buf + p);
            p = sapp(buf, p, "   host: ");
            p = sapp(buf, p, hostname[0] ? hostname : "(unknown)");
            buf[p] = 0;
            body_at(2, y++, buf, SCREEN_W - 4);
            y++;

            /* jailed verdict */
            p = 0;
            p = sapp(buf, p, "jailed: ");
            if (pid_one && jailed_userns)
                p = sapp(buf, p, "yes — pid-ns + user-ns active");
            else if (jailed_userns)
                p = sapp(buf, p, "user-ns mapped (no pid-ns)");
            else if (pid_one)
                p = sapp(buf, p, "pid 1 (suspect — init or jail without userns)");
            else
                p = sapp(buf, p, "no — looks like a host process");
            buf[p] = 0;
            body_at(2, y++, buf, SCREEN_W - 4);
            y++;

            /* namespace inodes */
            body_at(2, y++, "namespace inodes:", SCREEN_W - 4);
            const char *labels[5] = { "  user ", "  pid  ", "  net  ",
                                       "  mnt  ", "  uts  " };
            char *vals[5] = { ns_user, ns_pid, ns_net, ns_mnt, ns_uts };
            for (int i = 0; i < 5; i++) {
                p = 0;
                p = sapp(buf, p, labels[i]);
                p = sapp(buf, p, vals[i][0] ? vals[i] : "(unreadable)");
                buf[p] = 0;
                body_at(2, y++, buf, SCREEN_W - 4);
            }
            y++;

            /* uid_map first line */
            body_at(2, y++, "uid_map (first line):", SCREEN_W - 4);
            int ul = 0;
            while (uid_map[ul] && uid_map[ul] != '\n' && ul < 100) ul++;
            p = 0; p = sapp(buf, p, "  ");
            mcpy(buf + p, uid_map, ul); p += ul;
            buf[p] = 0;
            body_at(2, y++, buf, SCREEN_W - 4);
            y++;

            /* listening tcp4 */
            body_at(2, y++, "listening tcp4 (port hex → dec):", SCREEN_W - 4);
            const char *t = tcp4;
            while (*t && *t != '\n') t++;       /* skip header */
            if (*t == '\n') t++;
            int found = 0;
            while (*t && y < SCREEN_H - 2) {
                while (*t == ' ') t++;
                while (*t && *t != ' ' && *t != '\n') t++;     /* sl */
                while (*t == ' ') t++;
                const char *la = t;
                while (*t && *t != ':' && *t != '\n') t++;
                if (*t != ':') {
                    while (*t && *t != '\n') t++;
                    if (*t == '\n') t++;
                    continue;
                }
                t++;
                const char *port_hex = t;
                while (*t && *t != ' ' && *t != '\n') t++;
                const char *port_end = t;
                while (*t == ' ') t++;
                while (*t && *t != ' ' && *t != '\n') t++;     /* rem */
                while (*t == ' ') t++;
                int listening = (t[0] == '0' && (t[1] == 'A' || t[1] == 'a'));
                while (*t && *t != '\n') t++;
                if (*t == '\n') t++;
                if (listening) {
                    unsigned port = net_hex_to_u(port_hex, port_end);
                    p = 0;
                    p = sapp(buf, p, "  ");
                    int la_len = (int)(port_hex - 1 - la);
                    if (la_len > 8) la_len = 8;
                    mcpy(buf + p, la, la_len); p += la_len;
                    buf[p++] = ':';
                    int ph_len = (int)(port_end - port_hex);
                    mcpy(buf + p, port_hex, ph_len); p += ph_len;
                    p = sapp(buf, p, "  → port ");
                    p += utoa(port, buf + p);
                    buf[p] = 0;
                    body_at(2, y++, buf, SCREEN_W - 4);
                    found = 1;
                }
            }
            if (!found)
                body_at(2, y++, "  (none — net-ns isolated, no listeners yet)",
                        SCREEN_W - 4);

            status(" r refresh · q quit ");
            fbflush();
            redraw = 0;
        }

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;
        int act = -1, ami = menu_activation(k, n);
        if (ami >= 0) act = menu_run(&ms_shell, ami);
        if (act == MA_ABOUT) { show_about("Net Panel"); redraw = 1; continue; }
        if (act == MA_QUIT) break;
        if (k[0] == 'q' || k[0] == 'Q' || k[0] == 0x1b) break;
        if (k[0] == 'r' || k[0] == 'R') redraw = 1;
    }
    term_cooked();
    return 0;
}


/* ── http server (Tier 2) ──────────────────────────────
 * One-port plain-text HTTP/1.0 responder.  Each request gets a fresh
 * accept(), is read in one shot (≤1 KB), parsed for "METHOD /path",
 * dispatched to one of four handlers, response written + connection
 * closed.  No keep-alive, no chunked, no thread pool — this is a
 * diagnostic surface for jailed office instances, not a real server.
 *
 * Routes:
 *   /         tiny index linking the diag endpoints
 *   /id       instance token + pid + hostname (one line each)
 *   /status   identity + namespace inodes + uid_map (richer dump)
 *   /ports    listening tcp4 ports parsed from /proc/net/tcp
 *
 * The listening fd is created with SOCK_NONBLOCK so accept() returns
 * -EAGAIN immediately when no client is queued — that lets the same
 * loop poll the keyboard at term_raw_polling's VTIME cadence.  Inside
 * the jail this only sees the loopback in the (mostly-empty) net-ns;
 * Tier 4 will add veth or UNIX-socket port proxying for real reach. */

#define AF_INET        2
#define SOCK_STREAM    1
#define SOCK_NONBLOCK  0x800
#define SOL_SOCKET     1
#define SO_REUSEADDR   2

struct http_sin {
    unsigned short sin_family;
    unsigned short sin_port;
    unsigned int   sin_addr;
    unsigned char  sin_zero[8];
};

static char http_log_lines[8][80];      /* circular */
static int  http_log_idx = 0;
static int  http_log_n   = 0;

static unsigned short htons16_(unsigned short x) {
    return (unsigned short)((x << 8) | (x >> 8));
}

static int http_start(int port) {
    long fd = sys3(SYS_socket, AF_INET, SOCK_STREAM | SOCK_NONBLOCK, 0);
    if (fd < 0) return (int)fd;
    int one = 1;
    sys5(SYS_setsockopt, fd, SOL_SOCKET, SO_REUSEADDR, (long)&one, 4);
    struct http_sin a;
    mset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port   = htons16_((unsigned short)port);
    a.sin_addr   = 0;                   /* INADDR_ANY */
    if (sys3(SYS_bind, fd, (long)&a, sizeof a) < 0) { cl((int)fd); return -1; }
    if (sys3(SYS_listen, fd, 8, 0) < 0)             { cl((int)fd); return -1; }
    return (int)fd;
}

static void http_log(const char *method, const char *path, int code) {
    char *line = http_log_lines[http_log_idx];
    int p = 0, sl = slen(method);
    if (sl > 6) sl = 6;
    mcpy(line + p, method, sl); p += sl;
    line[p++] = ' ';
    int pl = slen(path);
    if (pl > 40) pl = 40;
    mcpy(line + p, path, pl); p += pl;
    line[p++] = ' ';
    p += utoa((unsigned)code, line + p);
    line[p] = 0;
    http_log_idx = (http_log_idx + 1) & 7;
    if (http_log_n < 8) http_log_n++;
}

static int http_write_all(int fd, const char *s, int n) {
    int o = 0;
    while (o < n) {
        long k = wr(fd, s + o, n - o);
        if (k <= 0) return -1;
        o += (int)k;
    }
    return 0;
}

static int http_send(int fd, int code, const char *body, int blen) {
    char hdr[200];
    int p = 0;
    p = sapp(hdr, p, "HTTP/1.0 ");
    p += utoa((unsigned)code, hdr + p);
    p = sapp(hdr, p, code == 200 ? " OK" : code == 404 ? " Not Found" : " Error");
    p = sapp(hdr, p, "\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: ");
    p += utoa((unsigned)blen, hdr + p);
    p = sapp(hdr, p, "\r\nConnection: close\r\n\r\n");
    if (http_write_all(fd, hdr, p) < 0) return -1;
    if (blen > 0) http_write_all(fd, body, blen);
    return 0;
}

/* Pull port-hex out of /proc/net/tcp lines; same parser the net panel
 * uses, condensed into a body builder. */
static int http_build_ports(char *body, int max) {
    int b = 0;
    b = sapp(body, b, "listening tcp4 (local_addr:port_hex → port_dec)\n");
    char tcp4[4096];
    int n2 = net_read_file("/proc/net/tcp", tcp4, sizeof tcp4);
    if (n2 <= 0) { b = sapp(body, b, "(unreadable)\n"); return b; }
    const char *t = tcp4;
    while (*t && *t != '\n') t++;
    if (*t == '\n') t++;
    while (*t && b < max - 80) {
        while (*t == ' ') t++;
        while (*t && *t != ' ' && *t != '\n') t++;
        while (*t == ' ') t++;
        const char *la = t;
        while (*t && *t != ':' && *t != '\n') t++;
        if (*t != ':') { while (*t && *t != '\n') t++; if (*t == '\n') t++; continue; }
        t++;
        const char *ph = t;
        while (*t && *t != ' ' && *t != '\n') t++;
        const char *pe = t;
        while (*t == ' ') t++;
        while (*t && *t != ' ' && *t != '\n') t++;
        while (*t == ' ') t++;
        int listening = (t[0] == '0' && (t[1] == 'A' || t[1] == 'a'));
        while (*t && *t != '\n') t++;
        if (*t == '\n') t++;
        if (listening) {
            unsigned port = net_hex_to_u(ph, pe);
            int la_len = (int)(ph - 1 - la);
            if (la_len > 8) la_len = 8;
            mcpy(body + b, la, la_len); b += la_len;
            body[b++] = ':';
            int phlen = (int)(pe - ph);
            mcpy(body + b, ph, phlen); b += phlen;
            b = sapp(body, b, " → ");
            b += utoa(port, body + b);
            body[b++] = '\n';
        }
    }
    return b;
}

static int http_handle(int cfd) {
    char req[1024];
    long n = rd(cfd, req, sizeof req - 1);
    if (n <= 0) { cl(cfd); return -1; }
    req[n] = 0;
    char method[8] = {0};
    char path[64]  = {0};
    int i = 0, j = 0;
    while (i < n && req[i] != ' ' && j < (int)sizeof method - 1) method[j++] = req[i++];
    while (i < n && req[i] == ' ') i++;
    j = 0;
    while (i < n && req[i] != ' ' && req[i] != '\r' && req[i] != '\n' &&
           j < (int)sizeof path - 1) path[j++] = req[i++];
    if (path[0] == 0) { path[0] = '/'; path[1] = 0; }

    char body[2048];
    int b = 0;
    int code = 200;

    if (scmp(path, "/id") == 0) {
        b = sapp(body, b, "instance: ");
        b = sapp(body, b, g_instance_token[0] ? g_instance_token : "(host)");
        b = sapp(body, b, "\npid: ");
        b += utoa((unsigned)getpid_(), body + b);
        char uts[6 * 65]; mset(uts, 0, sizeof uts);
        if (sys3(SYS_uname, (long)uts, 0, 0) == 0) {
            b = sapp(body, b, "\nhost: ");
            int hi = 0;
            while (hi < 64 && uts[65 + hi] && b < (int)sizeof body - 2)
                body[b++] = uts[65 + hi++];
        }
        body[b++] = '\n';
    } else if (scmp(path, "/ports") == 0) {
        b = http_build_ports(body, (int)sizeof body);
    } else if (scmp(path, "/status") == 0) {
        b = sapp(body, b, "office61 status\ninstance: ");
        b = sapp(body, b, g_instance_token[0] ? g_instance_token : "(host)");
        b = sapp(body, b, "\npid: ");
        b += utoa((unsigned)getpid_(), body + b);
        b = sapp(body, b, "\n\nnamespace inodes:\n");
        const char *paths[5] = {
            "/proc/self/ns/user", "/proc/self/ns/pid", "/proc/self/ns/net",
            "/proc/self/ns/mnt", "/proc/self/ns/uts" };
        const char *labels[5] = { "  user ", "  pid  ", "  net  ", "  mnt  ", "  uts  " };
        char nsb[80];
        for (int z = 0; z < 5; z++) {
            net_readlink(paths[z], nsb, sizeof nsb);
            b = sapp(body, b, labels[z]);
            b = sapp(body, b, nsb[0] ? nsb : "(unreadable)");
            body[b++] = '\n';
        }
        char umap[256];
        if (net_read_file("/proc/self/uid_map", umap, sizeof umap) > 0) {
            b = sapp(body, b, "\nuid_map: ");
            int z = 0;
            while (umap[z] && umap[z] != '\n' && b < (int)sizeof body - 1)
                body[b++] = umap[z++];
            body[b++] = '\n';
        }
    } else if (scmp(path, "/") == 0) {
        b = sapp(body, b, "office61 — tier-2 http server\n\n");
        b = sapp(body, b, "  /id       instance + pid + hostname\n");
        b = sapp(body, b, "  /status   full identity + namespaces + uid_map\n");
        b = sapp(body, b, "  /ports    listening tcp4 from /proc/net/tcp\n");
    } else {
        code = 404;
        b = sapp(body, b, "404 — try /  /id  /status  /ports\n");
    }

    http_send(cfd, code, body, b);
    http_log(method, path, code);
    cl(cfd);
    return 0;
}

static int run_http(int argc, char **argv) {
    int port = 8080;
    if (argc > 1 && argv[1] && argv[1][0]) {
        int v = 0, ok = 1;
        for (int z = 0; argv[1][z]; z++) {
            if (argv[1][z] < '0' || argv[1][z] > '9') { ok = 0; break; }
            v = v * 10 + (argv[1][z] - '0');
        }
        if (ok && v > 0 && v < 65536) port = v;
    }

    int lfd = http_start(port);
    if (lfd < 0) {
        term_cooked();
        char m[80]; int p = 0;
        p = sapp(m, p, "http: cannot bind port ");
        p += utoa((unsigned)port, m + p);
        m[p++] = '\n'; m[p] = 0;
        wr(2, m, p);
        return 1;
    }

    current_ms = &ms_shell;
    term_raw_polling();

    int hits = 0;
    int redraw = 1;
    int running = 1;
    while (running) {
        if (redraw) {
            paint_desktop();
            chrome("HTTP — minimal server (Tier 2)");
            body_clear();
            char buf[160];
            int p, y = 2;
            p = 0;
            p = sapp(buf, p, "listening on 0.0.0.0:");
            p += utoa((unsigned)port, buf + p);
            p = sapp(buf, p, "   instance ");
            p = sapp(buf, p, g_instance_token[0] ? g_instance_token : "(host)");
            p = sapp(buf, p, "   pid ");
            p += utoa((unsigned)getpid_(), buf + p);
            buf[p] = 0;
            body_at(2, y++, buf, SCREEN_W - 4);
            y++;

            p = 0;
            p = sapp(buf, p, "routes: /  /id  /status  /ports     hits: ");
            p += utoa((unsigned)hits, buf + p);
            buf[p] = 0;
            body_at(2, y++, buf, SCREEN_W - 4);
            y++;

            body_at(2, y++, "request log (oldest first):", SCREEN_W - 4);
            int nl = http_log_n;
            int start = (http_log_idx - nl + 8) & 7;
            for (int z = 0; z < nl && y < SCREEN_H - 2; z++) {
                int ix = (start + z) & 7;
                p = 0;
                p = sapp(buf, p, "  ");
                p = sapp(buf, p, http_log_lines[ix]);
                buf[p] = 0;
                body_at(2, y++, buf, SCREEN_W - 4);
            }

            status(" q quit · try: curl http://127.0.0.1:<port>/status ");
            fbflush();
            redraw = 0;
        }

        unsigned char k[8];
        int kn = read_key(k, sizeof k);
        if (kn > 0) {
            int act = -1, ami = menu_activation(k, kn);
            if (ami >= 0) act = menu_run(&ms_shell, ami);
            if (act == MA_ABOUT) { show_about("HTTP server"); redraw = 1; continue; }
            if (act == MA_QUIT) { running = 0; break; }
            if (k[0] == 'q' || k[0] == 'Q' || k[0] == 0x1b) { running = 0; break; }
        }

        /* Non-blocking accept; fd < 0 with -EAGAIN/-EWOULDBLOCK = no
         * pending connection.  On hit, handle synchronously then redraw. */
        long cfd = sys3(SYS_accept, lfd, 0, 0);
        if (cfd >= 0) {
            http_handle((int)cfd);
            hits++;
            redraw = 1;
        }
    }

    cl(lfd);
    term_cooked();
    return 0;
}


/* ── tier-3 servers + outbound probe ───────────────────
 * Three more single-port responders (echo, finger, gopher) and one
 * outbound TCP probe.  Each server reuses http_start() for the
 * non-blocking listen socket and http_log() for the request log,
 * then gets a per-protocol handler.  They share a tiny accept-loop
 * harness (srv_run) so the panel + key-poll logic isn't repeated
 * three times. */

typedef int (*srv_handler_fn)(int cfd, char *log_path_out, int max);

/* gopher needs to know its own port to embed in menu lines.
 * Set by run_gopher() before srv_run() invokes srv_handle_gopher. */
static int g_gopher_port;

static int srv_handle_echo(int cfd, char *log, int max) {
    char buf[512];
    long n = rd(cfd, buf, sizeof buf);
    if (n > 0) wr(cfd, buf, n);
    /* Log shows up to 24 bytes of the echoed payload (escape to dots). */
    int p = 0;
    p = sapp(log, p, "echo ");
    int show = (n > 24) ? 24 : (int)n;
    for (int i = 0; i < show && p < max - 1; i++) {
        char c = buf[i];
        log[p++] = (c >= 32 && c < 127) ? c : '.';
    }
    log[p] = 0;
    cl(cfd);
    return 0;
}

static int srv_handle_finger(int cfd, char *log, int max) {
    char req[128];
    long n = rd(cfd, req, sizeof req - 1);
    if (n < 0) n = 0;
    req[n] = 0;
    /* RFC 1288: "user[\r\n]" or just "[\r\n]".  We don't actually have
     * users, so reply with system identity regardless of the query. */
    char body[512];
    int b = 0;
    b = sapp(body, b, "office62 finger\r\n");
    b = sapp(body, b, "instance: ");
    b = sapp(body, b, g_instance_token[0] ? g_instance_token : "(host)");
    b = sapp(body, b, "\r\npid: ");
    b += utoa((unsigned)getpid_(), body + b);
    char uts[6 * 65]; mset(uts, 0, sizeof uts);
    if (sys3(SYS_uname, (long)uts, 0, 0) == 0) {
        b = sapp(body, b, "\r\nhost: ");
        int hi = 0;
        while (hi < 64 && uts[65 + hi] && b < (int)sizeof body - 4)
            body[b++] = uts[65 + hi++];
    }
    b = sapp(body, b, "\r\n");
    wr(cfd, body, b);
    /* Trim CR/LF off the query for the log. */
    int q = 0;
    while (q < (int)n && req[q] != '\r' && req[q] != '\n') q++;
    req[q] = 0;
    int p = 0;
    p = sapp(log, p, "finger '");
    int slen_q = q < 24 ? q : 24;
    for (int i = 0; i < slen_q && p < max - 4; i++) log[p++] = req[i];
    log[p++] = '\'';
    log[p] = 0;
    cl(cfd);
    return 0;
}

static int srv_handle_gopher(int cfd, char *log, int max) {
    char req[128];
    long n = rd(cfd, req, sizeof req - 1);
    if (n < 0) n = 0;
    req[n] = 0;
    int q = 0;
    while (q < (int)n && req[q] != '\r' && req[q] != '\n') q++;
    req[q] = 0;
    /* Build a gopher menu.  Item type 1 = directory, 0 = text, i = info.
     * Each line: type display_name TAB selector TAB host TAB port CRLF.
     * We keep host = "127.0.0.1" port = the listener's port (passed via
     * the gopher_port global).  Selector "i*" maps to plain info lines. */
    char body[1024];
    int b = 0;
    if (q == 0 || (q == 1 && req[0] == '/')) {
        b = sapp(body, b, "iWelcome to office62 gopher\tfake\t(NULL)\t0\r\n");
        b = sapp(body, b, "i\tfake\t(NULL)\t0\r\n");
        b = sapp(body, b, "0instance + pid + host\t/id\t127.0.0.1\t");
        b += utoa((unsigned)g_gopher_port, body + b);
        b = sapp(body, b, "\r\n");
        b = sapp(body, b, "0listening tcp4 ports\t/ports\t127.0.0.1\t");
        b += utoa((unsigned)g_gopher_port, body + b);
        b = sapp(body, b, "\r\n");
        b = sapp(body, b, ".\r\n");
    } else if (req[0] == '/' && req[1] == 'i' && req[2] == 'd') {
        b = sapp(body, b, "instance: ");
        b = sapp(body, b, g_instance_token[0] ? g_instance_token : "(host)");
        b = sapp(body, b, "\r\npid: ");
        b += utoa((unsigned)getpid_(), body + b);
        char uts[6 * 65]; mset(uts, 0, sizeof uts);
        if (sys3(SYS_uname, (long)uts, 0, 0) == 0) {
            b = sapp(body, b, "\r\nhost: ");
            int hi = 0;
            while (hi < 64 && uts[65 + hi] && b < (int)sizeof body - 4)
                body[b++] = uts[65 + hi++];
        }
        b = sapp(body, b, "\r\n.\r\n");
    } else if (req[0] == '/' && req[1] == 'p') {
        b = http_build_ports(body, (int)sizeof body - 8);
        b = sapp(body, b, ".\r\n");
    } else {
        b = sapp(body, b, "3not found: ");
        int sl = q < 40 ? q : 40;
        mcpy(body + b, req, sl); b += sl;
        b = sapp(body, b, "\r\n.\r\n");
    }
    wr(cfd, body, b);
    int p = 0;
    p = sapp(log, p, "gopher ");
    int gl = q < 40 ? q : 40;
    for (int i = 0; i < gl && p < max - 1; i++) log[p++] = req[i];
    log[p] = 0;
    cl(cfd);
    return 0;
}

/* Generic accept-loop runner shared by echo / finger / gopher. */
static int srv_run(const char *name, int port, srv_handler_fn handler) {
    int lfd = http_start(port);
    if (lfd < 0) {
        char m[80]; int p = 0;
        p = sapp(m, p, name);
        p = sapp(m, p, ": cannot bind port ");
        p += utoa((unsigned)port, m + p);
        m[p++] = '\n'; m[p] = 0;
        wr(2, m, p);
        return 1;
    }
    current_ms = &ms_shell;
    term_raw_polling();

    int hits = 0, redraw = 1, running = 1;
    while (running) {
        if (redraw) {
            paint_desktop();
            char title[40]; int t = 0;
            t = sapp(title, t, name);
            t = sapp(title, t, " — tier-3 listener");
            title[t] = 0;
            chrome(title);
            body_clear();
            char buf[160];
            int p, y = 2;
            p = 0;
            p = sapp(buf, p, "listening on 0.0.0.0:");
            p += utoa((unsigned)port, buf + p);
            p = sapp(buf, p, "   instance ");
            p = sapp(buf, p, g_instance_token[0] ? g_instance_token : "(host)");
            p = sapp(buf, p, "   hits: ");
            p += utoa((unsigned)hits, buf + p);
            buf[p] = 0;
            body_at(2, y++, buf, SCREEN_W - 4);
            y++;

            body_at(2, y++, "request log (oldest first):", SCREEN_W - 4);
            int nl = http_log_n;
            int start = (http_log_idx - nl + 8) & 7;
            for (int z = 0; z < nl && y < SCREEN_H - 2; z++) {
                int ix = (start + z) & 7;
                p = 0;
                p = sapp(buf, p, "  ");
                p = sapp(buf, p, http_log_lines[ix]);
                buf[p] = 0;
                body_at(2, y++, buf, SCREEN_W - 4);
            }

            status(" q quit ");
            fbflush();
            redraw = 0;
        }

        unsigned char k[8];
        int kn = read_key(k, sizeof k);
        if (kn > 0) {
            int act = -1, ami = menu_activation(k, kn);
            if (ami >= 0) act = menu_run(&ms_shell, ami);
            if (act == MA_ABOUT) { show_about(name); redraw = 1; continue; }
            if (act == MA_QUIT) { running = 0; break; }
            if (k[0] == 'q' || k[0] == 'Q' || k[0] == 0x1b) { running = 0; break; }
        }
        long cfd = sys3(SYS_accept, lfd, 0, 0);
        if (cfd >= 0) {
            char line[80]; line[0] = 0;
            handler((int)cfd, line, sizeof line);
            /* Splice into the http log buffer (shared circular). */
            char *dst = http_log_lines[http_log_idx];
            int q = 0;
            while (line[q] && q < 79) { dst[q] = line[q]; q++; }
            dst[q] = 0;
            http_log_idx = (http_log_idx + 1) & 7;
            if (http_log_n < 8) http_log_n++;
            hits++;
            redraw = 1;
        }
    }
    cl(lfd);
    term_cooked();
    return 0;
}

static int srv_parse_port(int argc, char **argv, int dflt) {
    if (argc > 1 && argv[1] && argv[1][0]) {
        int v = 0, ok = 1;
        for (int z = 0; argv[1][z]; z++) {
            if (argv[1][z] < '0' || argv[1][z] > '9') { ok = 0; break; }
            v = v * 10 + (argv[1][z] - '0');
        }
        if (ok && v > 0 && v < 65536) return v;
    }
    return dflt;
}

static int run_echo(int argc, char **argv) {
    return srv_run("echo", srv_parse_port(argc, argv, 7007), srv_handle_echo);
}
static int run_finger(int argc, char **argv) {
    return srv_run("finger", srv_parse_port(argc, argv, 7079), srv_handle_finger);
}
static int run_gopher(int argc, char **argv) {
    int port = srv_parse_port(argc, argv, 7070);
    g_gopher_port = port;
    return srv_run("gopher", port, srv_handle_gopher);
}


/* ── outbound TCP probe ─────────────────────────────────
 * `probe HOST PORT [SEND]` opens a TCP connection (with a 2-second
 * timeout via SO_RCVTIMEO + SO_SNDTIMEO), optionally sends SEND
 * followed by CRLF, then reads up to 4 KB and renders the first 24
 * lines.  Useful from inside the jail to confirm whether the net-ns
 * has any reachable endpoints — Tier 4's port-rerouting work hangs
 * off this same diagnostic. */

#define SO_RCVTIMEO 20
#define SO_SNDTIMEO 21
struct probe_tv { long tv_sec, tv_usec; };

static unsigned probe_parse_ipv4(const char *s) {
    unsigned a = 0, b = 0, c = 0, d = 0;
    int o = 0;
    int parts[4] = {0, 0, 0, 0};
    int pi = 0, val = 0, has = 0;
    while (s[o]) {
        if (s[o] >= '0' && s[o] <= '9') { val = val * 10 + (s[o] - '0'); has = 1; }
        else if (s[o] == '.') {
            if (pi < 4) parts[pi++] = val;
            val = 0; has = 0;
        } else break;
        o++;
    }
    if (has && pi < 4) parts[pi++] = val;
    if (pi != 4) return 0;
    a = parts[0]; b = parts[1]; c = parts[2]; d = parts[3];
    /* Network byte order: a.b.c.d → bytes {a, b, c, d} → on x86
     * a little-endian uint32 reads as (d<<24)|(c<<16)|(b<<8)|a. */
    return (d << 24) | (c << 16) | (b << 8) | a;
}

static int run_probe(int argc, char **argv) {
    /* Home shell only tokenises on the first space, so a typed
     * "probe HOST PORT [SEND]" arrives as argc=2 with argv[1] holding
     * the whole rest of the line.  Split internally on spaces into
     * up to 3 fields so both call paths (shell + main dispatch) work. */
    static char host_buf[64], port_buf[16], send_buf[128];
    const char *host = 0, *send = 0;
    int port = 0;
    int have_host = 0, have_port = 0;

    if (argc >= 3) {
        host = argv[1];
        if (argc >= 4) send = argv[3];
        int v = 0, ok = 1;
        for (int z = 0; argv[2][z]; z++) {
            if (argv[2][z] < '0' || argv[2][z] > '9') { ok = 0; break; }
            v = v * 10 + (argv[2][z] - '0');
        }
        if (ok && v > 0 && v < 65536) { port = v; have_host = 1; have_port = 1; }
    } else if (argc == 2 && argv[1] && argv[1][0]) {
        const char *s = argv[1];
        int o = 0, hi = 0;
        while (s[o] && s[o] != ' ' && hi < (int)sizeof host_buf - 1)
            host_buf[hi++] = s[o++];
        host_buf[hi] = 0;
        host = host_buf;
        while (s[o] == ' ') o++;
        int pi = 0;
        while (s[o] && s[o] != ' ' && pi < (int)sizeof port_buf - 1)
            port_buf[pi++] = s[o++];
        port_buf[pi] = 0;
        while (s[o] == ' ') o++;
        if (s[o]) {
            int si = 0;
            while (s[o] && si < (int)sizeof send_buf - 1) send_buf[si++] = s[o++];
            send_buf[si] = 0;
            send = send_buf;
        }
        int v = 0, ok = pi > 0;
        for (int z = 0; port_buf[z]; z++) {
            if (port_buf[z] < '0' || port_buf[z] > '9') { ok = 0; break; }
            v = v * 10 + (port_buf[z] - '0');
        }
        if (ok && v > 0 && v < 65536 && hi > 0) {
            port = v; have_host = 1; have_port = 1;
        }
    }

    if (!have_host || !have_port) {
        wr(2, "probe: usage: probe HOST PORT [SEND_STRING]\n", 44);
        return 2;
    }

    unsigned ip = probe_parse_ipv4(host);
    if (ip == 0) {
        wr(2, "probe: HOST must be dotted-quad ipv4 (DNS comes in tier 4)\n", 60);
        return 2;
    }

    long fd = sys3(SYS_socket, AF_INET, SOCK_STREAM, 0);
    if (fd < 0) { wr(2, "probe: socket failed\n", 21); return 1; }

    /* 2-second send + recv timeout so a black-hole port doesn't hang. */
    struct probe_tv tv = { 2, 0 };
    sys5(SYS_setsockopt, fd, SOL_SOCKET, SO_RCVTIMEO, (long)&tv, (long)sizeof tv);
    sys5(SYS_setsockopt, fd, SOL_SOCKET, SO_SNDTIMEO, (long)&tv, (long)sizeof tv);

    struct http_sin a;
    mset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port   = htons16_((unsigned short)port);
    a.sin_addr   = ip;

    paint_desktop();
    chrome("Probe — outbound TCP test");
    body_clear();
    char buf[256];
    int p, y = 2;
    p = 0;
    p = sapp(buf, p, "connect ");
    p = sapp(buf, p, host);
    buf[p++] = ':';
    p += utoa((unsigned)port, buf + p);
    if (send) { p = sapp(buf, p, "  send='"); p = sapp(buf, p, send); buf[p++] = '\''; }
    buf[p] = 0;
    body_at(2, y++, buf, SCREEN_W - 4); y++;

    long rc = sys3(SYS_connect, fd, (long)&a, sizeof a);
    if (rc < 0) {
        p = 0; p = sapp(buf, p, "connect failed: errno=");
        p += utoa((unsigned)(-rc), buf + p);
        buf[p] = 0;
        body_at(2, y++, buf, SCREEN_W - 4);
    } else {
        body_at(2, y++, "connected.", SCREEN_W - 4); y++;
        if (send) {
            int sl = slen(send);
            wr((int)fd, send, sl);
            wr((int)fd, "\r\n", 2);
        }
        char rbuf[4096];
        long n = rd((int)fd, rbuf, sizeof rbuf - 1);
        if (n < 0) {
            p = 0; p = sapp(buf, p, "read failed: errno=");
            p += utoa((unsigned)(-n), buf + p);
            buf[p] = 0;
            body_at(2, y++, buf, SCREEN_W - 4);
        } else {
            rbuf[n] = 0;
            p = 0; p = sapp(buf, p, "read ");
            p += utoa((unsigned)n, buf + p);
            p = sapp(buf, p, " bytes:");
            buf[p] = 0;
            body_at(2, y++, buf, SCREEN_W - 4);
            /* Render up to 24 lines, max SCREEN_W-4 cols each. */
            const char *t = rbuf;
            int rows = 0;
            while (*t && rows < 24 && y < SCREEN_H - 2) {
                const char *e = t;
                while (*e && *e != '\n' && (e - t) < SCREEN_W - 6) e++;
                int len = (int)(e - t);
                p = 0;
                p = sapp(buf, p, "  ");
                int copy = len < (int)sizeof buf - 4 ? len : (int)sizeof buf - 4;
                for (int i = 0; i < copy; i++) {
                    char c = t[i];
                    buf[p++] = (c >= 32 && c < 127) ? c : '.';
                }
                buf[p] = 0;
                body_at(2, y++, buf, SCREEN_W - 4);
                t = e;
                while (*t == '\n') t++;
                rows++;
            }
        }
    }
    cl((int)fd);
    status(" any key returns ");
    fbflush();
    term_raw_polling();
    unsigned char k[4];
    read_key(k, sizeof k);
    term_cooked();
    return 0;
}


/* ── tier-4 DNS resolver ───────────────────────────────
 * Minimal stub resolver for A records.  Reads /etc/resolv.conf for
 * the first nameserver IP, builds a DNS query packet by hand, sends
 * via UDP, parses the first A record from the answer.  No EDNS, no
 * TCP fallback, no caching, no retries — diagnostic only.  Inside
 * the jail this fails when /etc/resolv.conf is absent (chrooted FS
 * has only /office63), which is itself a useful signal that DNS
 * isn't reachable from the netns. */

#define SOCK_DGRAM 2

static int dns_first_nameserver(char *out, int max) {
    char buf[2048];
    int n = net_read_file("/etc/resolv.conf", buf, sizeof buf);
    if (n <= 0) { out[0] = 0; return -1; }
    const char *t = buf;
    while (*t) {
        const char *line = t;
        while (*t && *t != '\n') t++;
        const char *eol = t;
        if (*t == '\n') t++;
        const char *p = line;
        while (p < eol && *p == ' ') p++;
        if (p + 11 < eol && p[0] == 'n' && p[1] == 'a' && p[2] == 'm' &&
            p[3] == 'e' && p[4] == 's' && p[5] == 'e' && p[6] == 'r' &&
            p[7] == 'v' && p[8] == 'e' && p[9] == 'r' && p[10] == ' ') {
            const char *ip = p + 11;
            while (ip < eol && *ip == ' ') ip++;
            int o = 0;
            while (ip < eol && *ip != ' ' && *ip != '\n' && *ip != '\r' &&
                   o < max - 1) {
                out[o++] = *ip++;
            }
            out[o] = 0;
            return o > 0 ? 0 : -1;
        }
    }
    out[0] = 0;
    return -1;
}

/* Encode "foo.bar.baz" as DNS labels: 3foo3bar3baz0 — 0-byte
 * terminates.  Returns total bytes written including the 0. */
static int dns_encode_name(const char *name, unsigned char *out, int max) {
    int o = 0;
    const char *s = name;
    while (*s && o < max - 1) {
        const char *lab = s;
        while (*s && *s != '.') s++;
        int len = (int)(s - lab);
        if (len <= 0 || len > 63 || o + 1 + len >= max) return -1;
        out[o++] = (unsigned char)len;
        for (int i = 0; i < len; i++) out[o++] = (unsigned char)lab[i];
        if (*s == '.') s++;
    }
    out[o++] = 0;
    return o;
}

static int run_dns(int argc, char **argv) {
    /* Accept `dns NAME` or shell-tokenised `dns NAME` (single arg). */
    char namebuf[256];
    const char *name = 0;
    if (argc >= 2 && argv[1] && argv[1][0]) {
        int o = 0;
        for (int z = 0; argv[1][z] && o < (int)sizeof namebuf - 1; z++) {
            char c = argv[1][z];
            if (c == ' ' || c == '\t') break;
            namebuf[o++] = c;
        }
        namebuf[o] = 0;
        if (namebuf[0]) name = namebuf;
    }
    if (!name) {
        wr(2, "dns: usage: dns NAME\n", 21);
        return 2;
    }

    paint_desktop();
    chrome("DNS — A-record lookup");
    body_clear();
    char buf[256];
    int p, y = 2;

    char ns[64];
    if (dns_first_nameserver(ns, sizeof ns) < 0) {
        body_at(2, y++, "no nameserver in /etc/resolv.conf",
                SCREEN_W - 4);
        body_at(2, y++, "(jail's chroot has no resolv.conf — DNS unreachable)",
                SCREEN_W - 4);
        status(" any key returns ");
        fbflush();
        term_raw_polling();
        unsigned char k[4]; read_key(k, sizeof k);
        term_cooked();
        return 1;
    }

    p = 0;
    p = sapp(buf, p, "name:       ");
    p = sapp(buf, p, name);
    buf[p] = 0;
    body_at(2, y++, buf, SCREEN_W - 4);
    p = 0;
    p = sapp(buf, p, "nameserver: ");
    p = sapp(buf, p, ns);
    buf[p] = 0;
    body_at(2, y++, buf, SCREEN_W - 4);
    y++;

    unsigned ns_ip = probe_parse_ipv4(ns);
    if (ns_ip == 0) {
        body_at(2, y++, "nameserver isn't dotted-quad; aborting",
                SCREEN_W - 4);
        status(" any key returns ");
        fbflush();
        term_raw_polling();
        unsigned char k[4]; read_key(k, sizeof k);
        term_cooked();
        return 1;
    }

    /* Build DNS query: 12-byte header + question. */
    unsigned char pkt[512];
    int pi = 0;
    /* id (random-ish from time) */
    long t_now = time_();
    pkt[pi++] = (unsigned char)((t_now >> 8) & 0xff);
    pkt[pi++] = (unsigned char)(t_now & 0xff);
    /* flags: 0x0100 = standard query, recursion desired */
    pkt[pi++] = 0x01; pkt[pi++] = 0x00;
    /* qdcount=1, ancount=0, nscount=0, arcount=0 */
    pkt[pi++] = 0; pkt[pi++] = 1;
    pkt[pi++] = 0; pkt[pi++] = 0;
    pkt[pi++] = 0; pkt[pi++] = 0;
    pkt[pi++] = 0; pkt[pi++] = 0;
    int nl = dns_encode_name(name, pkt + pi, (int)sizeof pkt - pi - 4);
    if (nl < 0) {
        body_at(2, y++, "name too long", SCREEN_W - 4);
        status(" any key returns "); fbflush();
        term_raw_polling(); unsigned char k[4]; read_key(k, sizeof k);
        term_cooked();
        return 1;
    }
    pi += nl;
    /* QTYPE=A=1, QCLASS=IN=1 */
    pkt[pi++] = 0; pkt[pi++] = 1;
    pkt[pi++] = 0; pkt[pi++] = 1;

    long fd = sys3(SYS_socket, AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) {
        body_at(2, y++, "socket() failed", SCREEN_W - 4);
        status(" any key returns "); fbflush();
        term_raw_polling(); unsigned char k[4]; read_key(k, sizeof k);
        term_cooked();
        return 1;
    }
    struct probe_tv tv = { 3, 0 };
    sys5(SYS_setsockopt, fd, SOL_SOCKET, SO_RCVTIMEO, (long)&tv, (long)sizeof tv);
    sys5(SYS_setsockopt, fd, SOL_SOCKET, SO_SNDTIMEO, (long)&tv, (long)sizeof tv);

    struct http_sin sa;
    mset(&sa, 0, sizeof sa);
    sa.sin_family = AF_INET;
    sa.sin_port = htons16_(53);
    sa.sin_addr = ns_ip;
    /* sendto needs 6 args (sockfd, buf, len, flags, *addr, addrlen);
     * x86_64 ABI puts arg4 in r10, arg5 in r8, arg6 in r9.  We only
     * have sys3-sys5 wrappers in this fork, so inline the 6-arg
     * syscall once here for DNS. */
    long sent;
    {
        long r;
        register long r10 __asm__("r10") = 0;
        register long r8  __asm__("r8")  = (long)&sa;
        register long r9  __asm__("r9")  = (long)sizeof sa;
        long n = SYS_sendto;
        long fdl = fd;
        __asm__ volatile ("syscall" : "=a"(r)
                          : "0"(n), "D"(fdl), "S"((long)pkt), "d"((long)pi),
                            "r"(r10), "r"(r8), "r"(r9)
                          : "rcx", "r11", "memory");
        sent = r;
    }
    if (sent < 0) {
        p = 0; p = sapp(buf, p, "sendto failed: errno=");
        p += utoa((unsigned)(-sent), buf + p);
        buf[p] = 0;
        body_at(2, y++, buf, SCREEN_W - 4);
        cl((int)fd);
        status(" any key returns "); fbflush();
        term_raw_polling(); unsigned char k[4]; read_key(k, sizeof k);
        term_cooked();
        return 1;
    }

    unsigned char rsp[1024];
    /* recvfrom is 6-arg too; sys4 leaves r8/r9 uninitialised which the
     * kernel reads as src_addr/addrlen pointers and EFAULTs (errno 14).
     * Force r8 = r9 = 0 (NULL src_addr) explicitly. */
    long rn;
    {
        long r;
        register long r10 __asm__("r10") = 0;
        register long r8  __asm__("r8")  = 0;
        register long r9  __asm__("r9")  = 0;
        long nrn = SYS_recvfrom;
        long fdl = fd;
        __asm__ volatile ("syscall" : "=a"(r)
                          : "0"(nrn), "D"(fdl), "S"((long)rsp),
                            "d"((long)sizeof rsp),
                            "r"(r10), "r"(r8), "r"(r9)
                          : "rcx", "r11", "memory");
        rn = r;
    }
    cl((int)fd);
    if (rn < 12) {
        p = 0; p = sapp(buf, p, "no response (timeout or rn=");
        if (rn < 0) { buf[p++] = '-'; p += utoa((unsigned)(-rn), buf + p); }
        else        p += utoa((unsigned)rn, buf + p);
        buf[p++] = ')'; buf[p] = 0;
        body_at(2, y++, buf, SCREEN_W - 4);
    } else {
        int ancount = (rsp[6] << 8) | rsp[7];
        int rcode = rsp[3] & 0x0f;
        p = 0; p = sapp(buf, p, "rcode=");
        p += utoa((unsigned)rcode, buf + p);
        p = sapp(buf, p, "  answers=");
        p += utoa((unsigned)ancount, buf + p);
        buf[p] = 0;
        body_at(2, y++, buf, SCREEN_W - 4);

        /* Skip header (12) + question.  Question name length = our
         * encoded length nl; QTYPE+QCLASS = 4 bytes. */
        int off = 12 + nl + 4;
        for (int a = 0; a < ancount && off < (int)rn && y < SCREEN_H - 2; a++) {
            /* Answer name: usually a 2-byte pointer (0xC0xx).  Skip. */
            if (off < (int)rn && (rsp[off] & 0xc0) == 0xc0) off += 2;
            else {
                while (off < (int)rn && rsp[off]) off += rsp[off] + 1;
                off++;
            }
            if (off + 10 > (int)rn) break;
            int atype = (rsp[off] << 8) | rsp[off + 1]; off += 2;
            off += 2;                                                   /* class */
            off += 4;                                                   /* TTL */
            int rdlen = (rsp[off] << 8) | rsp[off + 1]; off += 2;
            if (off + rdlen > (int)rn) break;
            if (atype == 1 && rdlen == 4) {
                p = 0; p = sapp(buf, p, "  A   ");
                p += utoa((unsigned)rsp[off],     buf + p); buf[p++] = '.';
                p += utoa((unsigned)rsp[off + 1], buf + p); buf[p++] = '.';
                p += utoa((unsigned)rsp[off + 2], buf + p); buf[p++] = '.';
                p += utoa((unsigned)rsp[off + 3], buf + p);
                buf[p] = 0;
                body_at(2, y++, buf, SCREEN_W - 4);
            } else if (atype == 5) {
                body_at(2, y++, "  CNAME (not decoded)", SCREEN_W - 4);
            } else {
                p = 0; p = sapp(buf, p, "  type ");
                p += utoa((unsigned)atype, buf + p);
                p = sapp(buf, p, " (skipped)");
                buf[p] = 0;
                body_at(2, y++, buf, SCREEN_W - 4);
            }
            off += rdlen;
        }
    }

    status(" any key returns ");
    fbflush();
    term_raw_polling();
    unsigned char k[4]; read_key(k, sizeof k);
    term_cooked();
    return 0;
}


/* Blocking-listener variant for FTP's PASV data ports.  http_start
 * uses SOCK_NONBLOCK because the control loop polls accept alongside
 * the keyboard; the data port wants to *wait* for the client to
 * connect, so accept blocks naturally with this variant. */
static int ftp_data_start(int port) {
    long fd = sys3(SYS_socket, AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return (int)fd;
    int one = 1;
    sys5(SYS_setsockopt, fd, SOL_SOCKET, SO_REUSEADDR, (long)&one, 4);
    /* 5-second send/recv timeout so a stalled client doesn't wedge. */
    struct probe_tv tv = { 5, 0 };
    sys5(SYS_setsockopt, fd, SOL_SOCKET, SO_RCVTIMEO, (long)&tv, (long)sizeof tv);
    sys5(SYS_setsockopt, fd, SOL_SOCKET, SO_SNDTIMEO, (long)&tv, (long)sizeof tv);
    struct http_sin a;
    mset(&a, 0, sizeof a);
    a.sin_family = AF_INET;
    a.sin_port   = htons16_((unsigned short)port);
    a.sin_addr   = 0;
    if (sys3(SYS_bind, fd, (long)&a, sizeof a) < 0)   { cl((int)fd); return -1; }
    if (sys3(SYS_listen, fd, 1, 0) < 0)               { cl((int)fd); return -1; }
    return (int)fd;
}


/* ── tier-4 FTP server ─────────────────────────────────
 * Minimal anonymous FTP serving four virtual files: /id, /status,
 * /ports, /hostname.  Supports USER/PASS (any), SYST, PWD, CWD,
 * TYPE, PASV, LIST, RETR, QUIT.  No real filesystem, no PORT mode
 * (active), no resume, no upload.  Diagnostic surface only. */

static int ftp_send_line(int cfd, const char *s) {
    int n = slen(s);
    return wr(cfd, s, n);
}
static int ftp_send_code(int cfd, const char *line) {
    return ftp_send_line(cfd, line);
}

/* Build virtual file body by name.  Returns bytes written. */
static int ftp_build_virtual(const char *name, char *body, int max) {
    int b = 0;
    if (scmp(name, "id") == 0) {
        b = sapp(body, b, "instance: ");
        b = sapp(body, b, g_instance_token[0] ? g_instance_token : "(host)");
        b = sapp(body, b, "\npid: ");
        b += utoa((unsigned)getpid_(), body + b);
        body[b++] = '\n';
    } else if (scmp(name, "status") == 0) {
        b = sapp(body, b, "office63 status\ninstance: ");
        b = sapp(body, b, g_instance_token[0] ? g_instance_token : "(host)");
        b = sapp(body, b, "\npid: ");
        b += utoa((unsigned)getpid_(), body + b);
        body[b++] = '\n';
        char nsbuf[80];
        const char *paths[5] = {
            "/proc/self/ns/user", "/proc/self/ns/pid", "/proc/self/ns/net",
            "/proc/self/ns/mnt", "/proc/self/ns/uts" };
        for (int z = 0; z < 5; z++) {
            net_readlink(paths[z], nsbuf, sizeof nsbuf);
            b = sapp(body, b, "ns ");
            b = sapp(body, b, nsbuf);
            body[b++] = '\n';
        }
    } else if (scmp(name, "ports") == 0) {
        b = http_build_ports(body, max);
    } else if (scmp(name, "hostname") == 0) {
        char uts[6 * 65]; mset(uts, 0, sizeof uts);
        if (sys3(SYS_uname, (long)uts, 0, 0) == 0) {
            int hi = 0;
            while (hi < 64 && uts[65 + hi] && b < max - 1)
                body[b++] = uts[65 + hi++];
        }
        body[b++] = '\n';
    } else {
        return -1;
    }
    return b;
}

static int run_ftp(int argc, char **argv) {
    int port = srv_parse_port(argc, argv, 7021);
    int lfd = http_start(port);
    if (lfd < 0) {
        char m[80]; int p = 0;
        p = sapp(m, p, "ftp: cannot bind port ");
        p += utoa((unsigned)port, m + p);
        m[p++] = '\n'; m[p] = 0;
        wr(2, m, p);
        return 1;
    }

    current_ms = &ms_shell;
    term_raw_polling();
    int hits = 0, redraw = 1, running = 1;

    while (running) {
        if (redraw) {
            paint_desktop();
            chrome("FTP — minimal anon server");
            body_clear();
            char buf[160];
            int p, y = 2;
            p = 0;
            p = sapp(buf, p, "listening on 0.0.0.0:");
            p += utoa((unsigned)port, buf + p);
            p = sapp(buf, p, "   instance ");
            p = sapp(buf, p, g_instance_token[0] ? g_instance_token : "(host)");
            p = sapp(buf, p, "   sessions: ");
            p += utoa((unsigned)hits, buf + p);
            buf[p] = 0;
            body_at(2, y++, buf, SCREEN_W - 4); y++;
            body_at(2, y++, "virtual files: id  status  ports  hostname",
                    SCREEN_W - 4); y++;
            body_at(2, y++, "session log:", SCREEN_W - 4);
            int nl = http_log_n;
            int start = (http_log_idx - nl + 8) & 7;
            for (int z = 0; z < nl && y < SCREEN_H - 2; z++) {
                int ix = (start + z) & 7;
                p = 0;
                p = sapp(buf, p, "  ");
                p = sapp(buf, p, http_log_lines[ix]);
                buf[p] = 0;
                body_at(2, y++, buf, SCREEN_W - 4);
            }
            status(" q quit · try: curl -s ftp://127.0.0.1:port/id ");
            fbflush();
            redraw = 0;
        }

        unsigned char k[8];
        int kn = read_key(k, sizeof k);
        if (kn > 0) {
            if (k[0] == 'q' || k[0] == 'Q' || k[0] == 0x1b) { running = 0; break; }
        }

        long cfd = sys3(SYS_accept, lfd, 0, 0);
        if (cfd < 0) continue;

        /* Per-session: the rest of this iteration runs synchronously.
         * Greeting, command loop, optional data conn, close. */
        int c = (int)cfd;
        ftp_send_code(c, "220 office63 FTP (anon ok)\r\n");

        int data_listen = -1;       /* PASV listen fd */
        int data_port = 0;
        int session_alive = 1;

        while (session_alive) {
            char line[256];
            long n = rd(c, line, sizeof line - 1);
            if (n <= 0) break;
            line[n] = 0;
            /* Strip CRLF. */
            int ll = (int)n;
            while (ll > 0 && (line[ll - 1] == '\r' || line[ll - 1] == '\n'))
                ll--;
            line[ll] = 0;

            /* Cmd is up to first space; arg is rest. */
            int sp = 0;
            while (sp < ll && line[sp] != ' ') sp++;
            char cmd[8];
            int cn = sp < (int)sizeof cmd - 1 ? sp : (int)sizeof cmd - 1;
            for (int i = 0; i < cn; i++) {
                char x = line[i];
                cmd[i] = (x >= 'a' && x <= 'z') ? x - 32 : x;
            }
            cmd[cn] = 0;
            const char *arg = (sp < ll) ? line + sp + 1 : "";

            if (scmp(cmd, "USER") == 0) {
                ftp_send_code(c, "331 any password\r\n");
            } else if (scmp(cmd, "PASS") == 0) {
                ftp_send_code(c, "230 logged in\r\n");
            } else if (scmp(cmd, "SYST") == 0) {
                ftp_send_code(c, "215 UNIX Type: L8\r\n");
            } else if (scmp(cmd, "FEAT") == 0) {
                ftp_send_code(c, "211-features\r\n PASV\r\n211 end\r\n");
            } else if (scmp(cmd, "PWD")  == 0 || scmp(cmd, "XPWD") == 0) {
                ftp_send_code(c, "257 \"/\"\r\n");
            } else if (scmp(cmd, "CWD")  == 0) {
                ftp_send_code(c, "250 ok\r\n");
            } else if (scmp(cmd, "TYPE") == 0) {
                ftp_send_code(c, "200 ok\r\n");
            } else if (scmp(cmd, "EPSV") == 0) {
                /* We don't bother with EPSV; advertise PASV instead. */
                ftp_send_code(c, "500 use PASV\r\n");
            } else if (scmp(cmd, "PASV") == 0) {
                if (data_listen >= 0) cl(data_listen);
                /* Sequential port pool 7050-7099.  Real FTP servers
                 * bind ephemeral and read back via getsockname() —
                 * we don't have getsockname in our syscall set, so a
                 * sequential pool is simpler and gives reproducible
                 * port numbers in PASV replies. */
                static int next_data_port = 7050;
                data_listen = -1;
                int tries = 0;
                while (tries < 50 && data_listen < 0) {
                    next_data_port++;
                    if (next_data_port > 7099) next_data_port = 7050;
                    data_listen = ftp_data_start(next_data_port);
                    tries++;
                }
                if (data_listen < 0) {
                    ftp_send_code(c, "425 no free data port\r\n");
                    data_port = 0;
                } else {
                    data_port = next_data_port;
                    char rep[80]; int rp = 0;
                    rp = sapp(rep, rp, "227 Entering Passive Mode (127,0,0,1,");
                    rp += utoa((unsigned)(data_port >> 8), rep + rp);
                    rep[rp++] = ',';
                    rp += utoa((unsigned)(data_port & 0xff), rep + rp);
                    rp = sapp(rep, rp, ")\r\n");
                    rep[rp] = 0;
                    ftp_send_code(c, rep);
                }
            } else if (scmp(cmd, "LIST") == 0 || scmp(cmd, "NLST") == 0) {
                if (data_listen < 0) {
                    ftp_send_code(c, "425 PASV first\r\n");
                } else {
                    ftp_send_code(c, "150 here we go\r\n");
                    /* Blocking accept on the data port — kernel queues
                     * the client's connect; we wait up to the listener's
                     * SO_RCVTIMEO (5 s) for it to land. */
                    long dfd = sys3(SYS_accept, data_listen, 0, 0);
                    if (dfd >= 0) {
                        const char *names[4] = { "id", "status", "ports", "hostname" };
                        char lbuf[120];
                        for (int i = 0; i < 4; i++) {
                            int q = 0;
                            if (scmp(cmd, "NLST") == 0) {
                                q = sapp(lbuf, q, names[i]);
                                lbuf[q++] = '\r'; lbuf[q++] = '\n';
                            } else {
                                q = sapp(lbuf, q, "-rw-r--r-- 1 office office     0 ");
                                q = sapp(lbuf, q, "Jan  1 00:00 ");
                                q = sapp(lbuf, q, names[i]);
                                lbuf[q++] = '\r'; lbuf[q++] = '\n';
                            }
                            wr((int)dfd, lbuf, q);
                        }
                        cl((int)dfd);
                    }
                    cl(data_listen); data_listen = -1;
                    ftp_send_code(c, dfd >= 0 ? "226 ok\r\n"
                                              : "426 data conn timeout\r\n");
                }
            } else if (scmp(cmd, "RETR") == 0) {
                if (data_listen < 0) {
                    ftp_send_code(c, "425 PASV first\r\n");
                } else {
                    const char *fname = arg;
                    while (*fname == '/') fname++;
                    char body[2048];
                    int bn = ftp_build_virtual(fname, body, sizeof body);
                    if (bn < 0) {
                        ftp_send_code(c, "550 no such file\r\n");
                        cl(data_listen); data_listen = -1;
                    } else {
                        ftp_send_code(c, "150 data\r\n");
                        long dfd = sys3(SYS_accept, data_listen, 0, 0);
                        if (dfd >= 0) {
                            wr((int)dfd, body, bn);
                            cl((int)dfd);
                        }
                        cl(data_listen); data_listen = -1;
                        ftp_send_code(c, dfd >= 0 ? "226 ok\r\n"
                                                  : "426 data conn timeout\r\n");
                    }
                }
            } else if (scmp(cmd, "QUIT") == 0) {
                ftp_send_code(c, "221 bye\r\n");
                session_alive = 0;
            } else if (scmp(cmd, "NOOP") == 0) {
                ftp_send_code(c, "200 ok\r\n");
            } else {
                ftp_send_code(c, "502 not implemented\r\n");
            }
        }

        if (data_listen >= 0) cl(data_listen);
        cl(c);
        /* Log it. */
        char *dst = http_log_lines[http_log_idx];
        int q = 0;
        q = sapp(dst, q, "ftp session #");
        q += utoa((unsigned)hits + 1, dst + q);
        dst[q] = 0;
        http_log_idx = (http_log_idx + 1) & 7;
        if (http_log_n < 8) http_log_n++;
        hits++;
        redraw = 1;
    }

    cl(lfd);
    term_cooked();
    return 0;
}


/* ── tier-5 SSH-honeypot / telnet hybrid ───────────────
 * One listener that peeks the first 4 bytes a client sends.  If the
 * bytes are "SSH-", we reply with a real-looking SSH-2.0 banner and
 * a short fake KEXINIT, then close — looks like a flaky SSH server
 * to scanners + Shodan.  Anything else (raw nc, telnet client) drops
 * into a tiny line-shell with the office diag commands.  No crypto,
 * no auth, no real session — the SSH path is a road to nowhere by
 * design.
 *
 * The peek uses MSG_PEEK on a 6-arg recvfrom so the bytes stay in
 * the socket buffer for the per-mode read that follows. */

#define MSG_PEEK 2

static long sshtel_recv_peek(int fd, void *buf, int len) {
    long r;
    register long r10 __asm__("r10") = MSG_PEEK;
    register long r8  __asm__("r8")  = 0;
    register long r9  __asm__("r9")  = 0;
    long n = SYS_recvfrom;
    long fdl = fd;
    __asm__ volatile ("syscall" : "=a"(r)
                      : "0"(n), "D"(fdl), "S"((long)buf), "d"((long)len),
                        "r"(r10), "r"(r8), "r"(r9)
                      : "rcx", "r11", "memory");
    return r;
}

static int sshtel_handle_ssh(int cfd) {
    /* Banner */
    const char *banner = "SSH-2.0-office64-honeypot\r\n";
    wr(cfd, banner, slen(banner));
    /* Slurp whatever the client sends back (its banner + KEXINIT)
     * then close.  Real ssh clients will fail at our missing real
     * KEXINIT, which is the desired "broken SSH" effect. */
    char buf[1024];
    struct probe_tv tv = { 1, 0 };
    sys5(SYS_setsockopt, cfd, SOL_SOCKET, SO_RCVTIMEO, (long)&tv, (long)sizeof tv);
    rd(cfd, buf, sizeof buf);
    cl(cfd);
    return 0;
}

static int sshtel_send(int cfd, const char *s) {
    return wr(cfd, s, slen(s));
}

/* Strip telnet IAC negotiation (0xFF + 2 bytes), CR, and trailing LF
 * from the client's input line.  Returns the new length. */
static int sshtel_clean(unsigned char *buf, int n) {
    int w = 0;
    for (int i = 0; i < n; ) {
        if (buf[i] == 0xff && i + 2 < n) { i += 3; continue; }
        if (buf[i] == '\r' || buf[i] == '\n') { i++; continue; }
        buf[w++] = buf[i++];
    }
    return w;
}

static int sshtel_handle_telnet(int cfd) {
    /* Set 30-second receive timeout so an idle session gets cleaned. */
    struct probe_tv tv = { 30, 0 };
    sys5(SYS_setsockopt, cfd, SOL_SOCKET, SO_RCVTIMEO, (long)&tv, (long)sizeof tv);

    sshtel_send(cfd, "office64 telnet shell — diagnostic only.\r\n");
    sshtel_send(cfd, "type 'help' for commands.\r\n");

    while (1) {
        sshtel_send(cfd, "$ ");
        unsigned char line[256];
        long n = rd(cfd, line, sizeof line - 1);
        if (n <= 0) break;
        int ll = sshtel_clean(line, (int)n);
        line[ll] = 0;
        if (ll == 0) continue;

        /* Tokenise on first space. */
        int sp = 0;
        while (sp < ll && line[sp] != ' ') sp++;
        unsigned char cmd[16] = {0};
        int cn = sp < (int)sizeof cmd - 1 ? sp : (int)sizeof cmd - 1;
        for (int i = 0; i < cn; i++) {
            char c = (char)line[i];
            cmd[i] = (c >= 'A' && c <= 'Z') ? c + 32 : c;
        }
        const char *arg = (sp < ll) ? (const char *)line + sp + 1 : "";

        if (scmp((const char *)cmd, "help") == 0) {
            sshtel_send(cfd, "  id        instance / pid / hostname\r\n");
            sshtel_send(cfd, "  status    full identity dump\r\n");
            sshtel_send(cfd, "  ports     listening tcp4 ports\r\n");
            sshtel_send(cfd, "  hostname  uname's nodename\r\n");
            sshtel_send(cfd, "  date      epoch seconds\r\n");
            sshtel_send(cfd, "  echo X    echo X back\r\n");
            sshtel_send(cfd, "  exit      close session\r\n");
        } else if (scmp((const char *)cmd, "exit") == 0 ||
                   scmp((const char *)cmd, "quit") == 0) {
            sshtel_send(cfd, "bye\r\n");
            break;
        } else if (scmp((const char *)cmd, "echo") == 0) {
            wr(cfd, arg, slen(arg));
            sshtel_send(cfd, "\r\n");
        } else if (scmp((const char *)cmd, "date") == 0) {
            char b[32]; int p = 0;
            p += utoa((unsigned)time_(), b + p);
            b[p++] = '\r'; b[p++] = '\n';
            wr(cfd, b, p);
        } else if (scmp((const char *)cmd, "id") == 0 ||
                   scmp((const char *)cmd, "status") == 0 ||
                   scmp((const char *)cmd, "ports") == 0 ||
                   scmp((const char *)cmd, "hostname") == 0) {
            char body[2048];
            int bn = ftp_build_virtual((const char *)cmd, body, sizeof body);
            if (bn > 0) wr(cfd, body, bn);
        } else {
            sshtel_send(cfd, cmd[0] ? "?\r\n" : "\r\n");
        }
    }

    cl(cfd);
    return 0;
}

static int run_sshtel(int argc, char **argv) {
    int port = srv_parse_port(argc, argv, 7022);
    int lfd = http_start(port);
    if (lfd < 0) {
        char m[80]; int p = 0;
        p = sapp(m, p, "sshtel: cannot bind port ");
        p += utoa((unsigned)port, m + p);
        m[p++] = '\n'; m[p] = 0;
        wr(2, m, p);
        return 1;
    }
    current_ms = &ms_shell;
    term_raw_polling();

    int hits = 0, ssh_hits = 0, redraw = 1, running = 1;
    while (running) {
        if (redraw) {
            paint_desktop();
            chrome("SSH/telnet hybrid (honeypot)");
            body_clear();
            char buf[160];
            int p, y = 2;
            p = 0;
            p = sapp(buf, p, "listening on 0.0.0.0:");
            p += utoa((unsigned)port, buf + p);
            p = sapp(buf, p, "   instance ");
            p = sapp(buf, p, g_instance_token[0] ? g_instance_token : "(host)");
            buf[p] = 0;
            body_at(2, y++, buf, SCREEN_W - 4);

            p = 0;
            p = sapp(buf, p, "sessions: ");
            p += utoa((unsigned)hits, buf + p);
            p = sapp(buf, p, " total   ssh-banner: ");
            p += utoa((unsigned)ssh_hits, buf + p);
            p = sapp(buf, p, "   telnet: ");
            p += utoa((unsigned)(hits - ssh_hits), buf + p);
            buf[p] = 0;
            body_at(2, y++, buf, SCREEN_W - 4);
            y++;
            body_at(2, y++, "first-byte sniff: 'SSH-' → banner-only honeypot",
                    SCREEN_W - 4);
            body_at(2, y++, "                  anything else → telnet line shell",
                    SCREEN_W - 4); y++;

            body_at(2, y++, "session log:", SCREEN_W - 4);
            int nl = http_log_n;
            int start = (http_log_idx - nl + 8) & 7;
            for (int z = 0; z < nl && y < SCREEN_H - 2; z++) {
                int ix = (start + z) & 7;
                p = 0;
                p = sapp(buf, p, "  ");
                p = sapp(buf, p, http_log_lines[ix]);
                buf[p] = 0;
                body_at(2, y++, buf, SCREEN_W - 4);
            }

            status(" q quit · try: nc 127.0.0.1 <port> ");
            fbflush();
            redraw = 0;
        }

        unsigned char k[8];
        int kn = read_key(k, sizeof k);
        if (kn > 0) {
            if (k[0] == 'q' || k[0] == 'Q' || k[0] == 0x1b) { running = 0; break; }
        }

        long cfd = sys3(SYS_accept, lfd, 0, 0);
        if (cfd < 0) continue;

        /* Peek the first 4 bytes (with brief blocking).  If the kernel
         * hasn't delivered the client's first packet yet, spin briefly
         * — the peek itself blocks if nothing is buffered. */
        unsigned char peek[4] = {0};
        struct probe_tv pt = { 1, 0 };
        sys5(SYS_setsockopt, (int)cfd, SOL_SOCKET, SO_RCVTIMEO,
             (long)&pt, (long)sizeof pt);
        long pn = sshtel_recv_peek((int)cfd, peek, 4);
        char *dst = http_log_lines[http_log_idx];
        int dq = 0;
        if (pn >= 4 && peek[0] == 'S' && peek[1] == 'S' &&
            peek[2] == 'H' && peek[3] == '-') {
            dq = sapp(dst, dq, "ssh-banner #");
            dq += utoa((unsigned)hits + 1, dst + dq);
            sshtel_handle_ssh((int)cfd);
            ssh_hits++;
        } else {
            dq = sapp(dst, dq, "telnet #");
            dq += utoa((unsigned)hits + 1, dst + dq);
            sshtel_handle_telnet((int)cfd);
        }
        dst[dq] = 0;
        http_log_idx = (http_log_idx + 1) & 7;
        if (http_log_n < 8) http_log_n++;
        hits++;
        redraw = 1;
    }

    cl(lfd);
    term_cooked();
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
    /* Per-instance identity.  jail.c (sibling tool) sethostname()s
     * the new UTS NS to "garden-XXXXXXXX" before exec, where the
     * 8 hex chars are a per-launch token.  Pull that suffix into
     * g_instance_token so home + net panels can show stable identity
     * even though getpid() returns 1 inside the pid-ns.  Outside the
     * jail the hostname won't start with "garden-" and the token
     * stays empty. */
    {
        char uts[6 * 65];
        mset(uts, 0, sizeof uts);
        if (sys3(SYS_uname, (long)uts, 0, 0) == 0) {
            const char *node = uts + 65;       /* nodename field */
            if (node[0] == 'g' && node[1] == 'a' && node[2] == 'r' &&
                node[3] == 'd' && node[4] == 'e' && node[5] == 'n' &&
                node[6] == '-') {
                int t = 0;
                const char *v = node + 7;
                while (v[t] && t < (int)sizeof g_instance_token - 1) {
                    g_instance_token[t] = v[t]; t++;
                }
                g_instance_token[t] = 0;
            }
        }
    }

    const char *cmd = (argc > 0) ? basename_(argv[0]) : "office";
    int sub_argc = argc;
    char **sub_argv = argv;
    /* officerpg v0.1: when invoked as "officerpg", skip the office
     * shell entirely and launch directly into the rpg.  q/ESC inside
     * the rpg drops back to the (mostly-empty) shell, which the
     * user can then `q` again to exit.
     *
     * v0.2: also expose `./officerpg saver` (or `screensaver`) as a
     * subcommand that runs the journey-planner screensaver instead
     * — same code path as office's saver app, just reachable from
     * the standalone build so --gc-sections keeps it in. */
    if (scmp(cmd, "officerpg") == 0) {
        /* v0.2: --help / -h before all other subcommands so a
         * stale CLI invocation always lands on something
         * informative.  We deliberately don't accept '-h' alone
         * since lowercase 'h' inside run_rpg toggles halos and
         * users muscle-memorying that key shouldn't quit. */
        if (sub_argc > 1 &&
            (scmp(sub_argv[1], "--help") == 0 ||
             scmp(sub_argv[1], "help")   == 0)) {
            static const char H[] =
                "officerpg — hex CA + L-system rpg (ANSI-C v1.2)\n"
                "\n"
                "  ./officerpg              run interactive rpg\n"
                "  ./officerpg saver        run journey-mode screensaver\n"
                "  ./officerpg test [opts]  deterministic walk + report\n"
                "    --steps N              walk N moves (default 30)\n"
                "    --seed N               LCG seed (default 0xdeadbeef)\n"
                "    --per-cell-rules       enable rule pool before walk\n"
                "    --ga-rounds N          force N pool-GA rounds after walk\n"
                "    --lsys-rounds N        force N L-system GA rounds after walk\n"
                "    --no-io                skip bundle + shot writes\n"
                "  ./officerpg --help       print this help\n"
                "  ./officerpg --version    print version\n"
                "\n"
                "interactive keys:\n"
                "  wadezx        offset-r hex move\n"
                "  i             inventory\n"
                "  m             cast zap\n"
                "  l             toggle live animation\n"
                "  k             open speed-settings panel\n"
                "  0-3           bend terrain (cost MP)\n"
                "  4-7           recolour palette (cost MP)\n"
                "  S             save world bundle (officerpg-state.bin)\n"
                "  L             load world bundle\n"
                "  E             ANSI screenshot (officerpg-shot.ans)\n"
                "  b             pc-speaker chime / BEL fallback\n"
                "  h             toggle animal action halos (off by default)\n"
                "  u  U          toggle per-cell rule pool / reseed\n"
                "  M             toggle mood-modulated music (pc-speaker)\n"
                "  G             toggle L-system GA (sprite library drift)\n"
                "  q  ESC        quit\n";
            wr(1, H, sizeof H - 1);
            return 0;
        }
        if (sub_argc > 1 &&
            (scmp(sub_argv[1], "--version") == 0 ||
             scmp(sub_argv[1], "version")   == 0)) {
            static const char V[] = "officerpg ANSI-C v1.2\n";
            wr(1, V, sizeof V - 1);
            return 0;
        }
        if (sub_argc > 1 &&
            (scmp(sub_argv[1], "saver")       == 0 ||
             scmp(sub_argv[1], "screensaver") == 0))
            return run_screensaver(sub_argc - 1, sub_argv + 1);
        /* v0.2: non-interactive `test` subcommand — runs N
         * deterministic moves from a seed, then writes the
         * bundle + ANSI shot before exiting cleanly.  Lets
         * scripted regressions drive the binary without a
         * human at the keyboard, paired with the terminalshot
         * decoder for output verification. */
        if (sub_argc > 1 && scmp(sub_argv[1], "test") == 0) {
            int steps = 30;
            unsigned long seed = 0xdeadbeefUL;
            int per_cell_rules = 0;
            int ga_rounds = 0;
            int lsys_rounds = 0;
            int no_io = 0;
            for (int a = 2; a < sub_argc; a++) {
                if (scmp(sub_argv[a], "--steps") == 0 && a + 1 < sub_argc) {
                    steps = (int)atoi_(sub_argv[++a]);
                } else if (scmp(sub_argv[a], "--seed") == 0 && a + 1 < sub_argc) {
                    seed = (unsigned long)atoi_(sub_argv[++a]);
                } else if (scmp(sub_argv[a], "--per-cell-rules") == 0) {
                    per_cell_rules = 1;
                } else if (scmp(sub_argv[a], "--ga-rounds") == 0 && a + 1 < sub_argc) {
                    ga_rounds = (int)atoi_(sub_argv[++a]);
                } else if (scmp(sub_argv[a], "--lsys-rounds") == 0 && a + 1 < sub_argc) {
                    lsys_rounds = (int)atoi_(sub_argv[++a]);
                } else if (scmp(sub_argv[a], "--no-io") == 0) {
                    no_io = 1;
                }
            }
            if (steps < 1)    steps = 1;
            if (steps > 9999) steps = 9999;
            if (ga_rounds < 0) ga_rounds = 0;
            if (ga_rounds > 9999) ga_rounds = 9999;
            if (lsys_rounds < 0) lsys_rounds = 0;
            if (lsys_rounds > 9999) lsys_rounds = 9999;
            /* v1.2: seed rpg_lsys_rng from the test seed so
             * --lsys-rounds is deterministic across runs. */
            rpg_lsys_rng = (unsigned long)seed | 1UL;
            hx_active_init();
            /* v1.0: hx_active_init uses rdtsc when there's no
             * hxhnt.seed file, so the embedded genome differs per
             * run.  Override with a seed-derived genome + palette
             * so `test --seed N` is reproducible across processes
             * regardless of host state. */
            hx_rng_state = (unsigned long long)seed | 1ULL;
            hx_random_genome(hx_seed_genome);
            hx_invent_palette(hx_seed_pal);
            rpg_sprites_init();
            mset(rpg_world_pos, 0, sizeof rpg_world_pos);
            int px = RPG_TILE_W / 2;
            int py = RPG_TILE_H / 2;
            rpg_load_overworld(px, py);
            rpg_player_init();
            rpg_preload_invalidate();
            /* v1.0: optional per-cell rules toggle.  Enabled here
             * (after init, before the walk) so the deterministic
             * walk's terrain renders pull from the pool — exercises
             * rpg_ensure_rule_pool + rpg_get_cell_ruleset on every
             * cell that gets computed. */
            if (per_cell_rules) {
                rpg_ensure_rule_pool();
                rpg_per_cell_rules_on = 1;
            }
            static const char dirs[6] = { 'a','d','w','e','z','x' };
            unsigned long s = seed | 1UL;
            char action[80]; action[0] = 0;
            for (int t = 0; t < steps; t++) {
                s = s * 6364136223846793005UL + 1442695040888963407UL;
                char c = dirs[(s >> 33) % 6];
                action[0] = 0;
                rpg_move(&px, &py, c, action);
                rpg_path_tick(px, py);
                rpg_preload_advance_one(px, py);
                int mdx = 0, mdy = 0;
                if (px <  RPG_MAP_W)         mdx = -1;
                else if (px >= 2 * RPG_MAP_W)mdx =  1;
                if (py <  RPG_MAP_H)         mdy = -1;
                else if (py >= 2 * RPG_MAP_H)mdy =  1;
                if (mdx || mdy) {
                    px -= mdx * RPG_MAP_W;
                    py -= mdy * RPG_MAP_H;
                    int meta_dx = mdx, meta_dy = mdy;
                    int hdx = 0, hdy = 0;
                    rpg_hex_meta_shift(c, rpg_world_pos[0][1], &hdx, &hdy);
                    if (hdx || hdy) { meta_dx = hdx; meta_dy = hdy; }
                    rpg_shift_mosaic(meta_dx, meta_dy, px, py, c);
                }
            }
            /* v1.0: optional GA rounds.  Forces consecutive ticks
             * past the period gate so each call actually mutates
             * the pool.  Only meaningful with --per-cell-rules. */
            for (int g = 0; g < ga_rounds; g++) {
                rpg_pool_ga_last_frame = -1;
                rpg_pool_ga_tick(0);
            }
            /* v1.2: optional L-system GA rounds.  Same trick — bypass
             * the period gate.  Toggles GA on for the duration so
             * the internal short-circuit doesn't fire. */
            if (lsys_rounds > 0) {
                rpg_lsys_ga_on = 1;
                for (int g = 0; g < lsys_rounds; g++) {
                    rpg_lsys_ga_last_frame = -1;
                    rpg_lsys_ga_tick(0);
                }
                rpg_lsys_ga_on = 0;
            }
            if (!no_io) {
                rpg_save_bundle(NULL);
                /* Render once into the framebuffer so the shot file
                 * captures the post-walk state.  Don't fbflush — the
                 * shot path reads fb directly and we're not actually
                 * showing this frame on a tty. */
                paint_desktop();
                chrome("rpg");
                rpg_render_view(px, py);
                rpg_save_shot_to_file();
            }
            /* v1.0: report deterministic state to stdout so a CI
             * harness can diff output across builds. */
            char rep[160]; int rl = 0;
            rl = sapp(rep, rl, "test ok · steps=");
            rl += utoa((unsigned)steps, rep + rl);
            rl = sapp(rep, rl, " · pos=");
            rl += utoa((unsigned)px, rep + rl); rep[rl++] = ',';
            rl += utoa((unsigned)py, rep + rl);
            rl = sapp(rep, rl, " · pool=");
            rep[rl++] = rpg_rule_pool_built ? 'Y' : 'N';
            rl = sapp(rep, rl, " · per-cell=");
            rep[rl++] = rpg_per_cell_rules_on ? 'Y' : 'N';
            rl = sapp(rep, rl, " · ga=");
            rl += utoa((unsigned)rpg_pool_ga_rounds, rep + rl);
            rl = sapp(rep, rl, " · lsys=");
            rl += utoa((unsigned)rpg_lsys_ga_rounds, rep + rl);
            rep[rl++] = '\n';
            wr(1, rep, rl);
            return 0;
        }
        return run_rpg(sub_argc, sub_argv);
    }
    /* office61: programmatic prefix match — if cmd is "office" or
     * "officeN" for any decimal N, peel argv[0] and treat argv[1] as
     * the subcommand.  Replaces the office..office50 long-if from
     * earlier forks, which silently regressed every time a new fork
     * was added without updating the list. */
    {
        int is_office_wrapper = 0;
        if (cmd[0] == 'o' && cmd[1] == 'f' && cmd[2] == 'f' &&
            cmd[3] == 'i' && cmd[4] == 'c' && cmd[5] == 'e') {
            const char *t = cmd + 6;
            if (*t == 0) is_office_wrapper = 1;
            else {
                int all_digit = 1;
                while (*t) {
                    if (*t < '0' || *t > '9') { all_digit = 0; break; }
                    t++;
                }
                is_office_wrapper = all_digit;
            }
        }
        if (is_office_wrapper && argc > 1) {
            cmd = argv[1];
            sub_argv = argv + 1;
            sub_argc = argc - 1;
            goto skip_legacy_basename_chain;
        }
    }
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
         scmp(cmd, "office41") == 0 ||
         scmp(cmd, "office42") == 0 ||
         scmp(cmd, "office43") == 0 ||
         scmp(cmd, "office44") == 0 ||
         scmp(cmd, "office45") == 0 ||
         scmp(cmd, "office46") == 0 ||
         scmp(cmd, "office47") == 0 ||
         scmp(cmd, "office48") == 0 ||
         scmp(cmd, "office49") == 0 ||
         scmp(cmd, "office50") == 0) && argc > 1) {
        cmd = argv[1];
        sub_argv = argv + 1;
        sub_argc = argc - 1;
    }
skip_legacy_basename_chain:
    (void)0;
#if OFFICE_FEATURE_NOTEPAD
    if (scmp(cmd, "notepad") == 0) return run_notepad(sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_SHEET
    if (scmp(cmd, "sheet")   == 0) return run_sheet  (sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_HEX
    if (scmp(cmd, "hex")     == 0) return run_hex    (sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_FILES
    if (scmp(cmd, "files")   == 0) return run_files  (sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_CALC
    if (scmp(cmd, "calc")    == 0) return run_calc   (sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_ASK
    if (scmp(cmd, "ask")     == 0) return run_ask    (sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_GARDEN
    if (scmp(cmd, "garden")  == 0) return run_garden (sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_HXHNT
    if (scmp(cmd, "hxhnt")   == 0) return run_hxhnt  (sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_RPG
    if (scmp(cmd, "rpg")     == 0) return run_rpg    (sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_LSYS
    if (scmp(cmd, "lsys")    == 0) return run_lsys   (sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_SCREENSAVER
    if (scmp(cmd, "saver") == 0 || scmp(cmd, "screensaver") == 0)
        return run_screensaver(sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_NET
    if (scmp(cmd, "net")     == 0) return run_net    (sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_HTTP
    if (scmp(cmd, "http")    == 0) return run_http   (sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_ECHO
    if (scmp(cmd, "echo")    == 0) return run_echo   (sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_FINGER
    if (scmp(cmd, "finger")  == 0) return run_finger (sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_GOPHER
    if (scmp(cmd, "gopher")  == 0) return run_gopher (sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_PROBE
    if (scmp(cmd, "probe")   == 0) return run_probe  (sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_DNS
    if (scmp(cmd, "dns")     == 0) return run_dns    (sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_FTP
    if (scmp(cmd, "ftp")     == 0) return run_ftp    (sub_argc, sub_argv);
#endif
#if OFFICE_FEATURE_SSHTEL
    if (scmp(cmd, "sshtel")  == 0) return run_sshtel (sub_argc, sub_argv);
#endif
    if (scmp(cmd, "preview-genome") == 0) return run_preview_genome(sub_argc, sub_argv);
    if (scmp(cmd, "view-genome")    == 0) return run_view_genome   (sub_argc, sub_argv);
    /* An exported hxh-* binary launched by name lands here.  Default
     * to display-mode hxhnt so the embedded tail's genome animates,
     * matching the original hunter's launch behaviour. */
#if OFFICE_FEATURE_HXHNT
    if (cmd[0] == 'h' && cmd[1] == 'x' && cmd[2] == 'h')
        return run_hxhnt(sub_argc, sub_argv);
#endif
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
