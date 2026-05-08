/* officeagent.c -- toy "Claude Code" classroom build.  Linux x86_64.
 * No libc.  64 KB cap.
 *
 *   shell  sheet(+calc merged)  xpg  ask  prompt  coder
 *
 * Five visible apps.  Notepad, hex, and files are still in the
 * source (supercell carry-over) but dropped from menus + dispatch;
 * --gc-sections strips the unreachable bodies.  Standalone hxhnt
 * and lsys are dropped too — the rpg → xpg merge from officex is
 * applied here, so all CA + GA + L-system logic is reachable only
 * through xpg.
 *
 * coder is the headline new app: an iterative LLM-driven code
 * generator.  The user types a goal; coder builds a prompt from
 * (a) the personality bank, (b) the project bank, (c) the recent
 * + longterm banks (full inclusion in v1; selective tag-bitmap
 * retrieval is queued for v2), plus (d) the previous compile
 * error if any.  It calls the LLM via ask's existing curl
 * machinery, extracts the code from the response, writes it to
 * /tmp/coder_attempt.c, runs cc, and feeds any error back into
 * the next iteration's prompt until the configured target is met
 * or the iteration cap is hit.
 *
 *     target  good_enough  cc compiles cleanly (no -Wall, no run)
 *     target  clean        cc -Wall -Wextra clean (no warnings)
 *     target  perfect      clean + program runs without crashing
 *
 * Persistent memory: 4 banks × 4 KB (cwd-relative).  All four are
 * included in every LLM prompt as system-prompt context, so the
 * agent's "personality" + recent failures + long-term plans +
 * project structure travel together.  Banks are loaded lazily and
 * written back when coder exits.
 *
 *     personality.bin  4 KB   tone, persona, do/don't preferences
 *     recent.bin       4 KB   most recent failures + fixes
 *     longterm.bin     4 KB   durable patterns / lessons
 *     project.bin      4 KB   current project / task structure
 *
 * Free-tier LLM stitching: ask's existing config (api_key,
 * endpoint, model in office_ask.conf) is the only required key.
 * On a 429 / network error the coder retries up to 3 times with
 * a 2-second back-off; multi-provider key-pool rotation is queued
 * for v2.  In v1 we lean on the pekpik proxy that ask already
 * prefers — same provider behaviour as ask.
 *
 * Persistent DB: a TinyDB-style B-tree node store at ./coder.db
 * (vendored + ported from Penge666/TinyDB).  Each failed
 * iteration inserts a row tagged by 64-bit token-hash bitmap;
 * each subsequent prompt does top-K retrieval against the
 * current goal+error to surface relevant prior failures even
 * after the recent.bin bank has rolled over.  16 rows max in
 * v1 (single root leaf, no node splitting).
 *
 * Calc is merged into sheet — typing `=2^32` in any cell evaluates
 * with the same 64-bit feval_* chain calc used.  `calc` is kept
 * as an alias for `sheet`.  `rpg`, `hxhnt`, and `lsys` all alias
 * to `xpg` so old shell history continues to work.
 *
 * Inherited from office59 — 64-bit math in calc + sheet evaluator.
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
#define APP_NAME    "office64"
#define APP_VERSION "41"

/* Embedded 25 K-parameter int8 transformer for the `soul` app —
 * port of gizmo64k/soulplayer-c64.  Weights + tokenizer ship as
 * static const arrays so the soul travels with the binary. */
#include "soul_data.h"


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
#define SYS_dup2   33
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
#define O_RDWR   2
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
#define dup2_(o, n)        sys3(SYS_dup2, (long)(o), (long)(n), 0)
#define lseek_(f, off, w)  sys3(SYS_lseek, (long)(f), (long)(off), (long)(w))
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

#define MA_NEW         0x0e   /* ^N */
#define MA_SAVE        0x13   /* ^S */
#define MA_PROMPT_SYNC 0x10   /* ^P — ask: send personality as hidden primer */
#define MA_QUIT        0x11   /* ^Q */
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
/* ask: New = clear chat, Sync = primer-send personality, Settings,
 * Quit.  "Sync" sends the personality bank as a hidden user-role
 * message + captures the LLM's ack as a hidden assistant message,
 * both kept in the conversation context for subsequent turns but
 * never rendered. */
static const MI mF_ask[]   = {{"New     ^N", MA_NEW},
                              {"Sync    ^P", MA_PROMPT_SYNC},
                              {"Settings^E", MA_SETTINGS},
                              {"Quit    ^Q", MA_QUIT}};
static const MS ms_ask     = { mF_ask, NA(mF_ask), 0, 0,
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
static int run_ask(int, char**);
static int run_prompt(int, char**);
static int run_coder(int, char**);
static int run_soul(int, char**);
static int run_xpg(int, char**);

/* Soul helpers — defined alongside run_soul further down.  Forward-
 * declared here so the coder can call sl_generate as a curl
 * fallback and sl_save_test to auto-promote successful goals into
 * the soul's evolution test set. */
static int sl_generate(const char *text, char *out, int out_cap, int max_new);
static void sl_save_test(const char *prompt, const char *expected);

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
        chrome("OfficeAgent");
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
                buf[p++] = ' '; buf[p++] = '·'; buf[p++] = ' ';
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
        body_at(2, 3, "Welcome to OfficeAgent. Built-in commands:", SCREEN_W - 4);
        body_at(2, 4, "  sheet  xpg  ask  prompt  coder  soul  exit",
                SCREEN_W - 4);
        body_at(2, 5, "  (coder = iterative LLM code generator; soul = on-board",
                SCREEN_W - 4);
        body_at(2, 6, "   25 K transformer + GA evolution; prompt edits 4 KB banks.)",
                SCREEN_W - 4);
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
            show_about("OfficeAgent");
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
            if (scmp(cmd, "sheet") == 0 || scmp(cmd, "calc") == 0)
                                               rc = run_sheet(sub_argc, sub_argv);
            else if (scmp(cmd, "ask") == 0)    rc = run_ask(sub_argc, sub_argv);
            else if (scmp(cmd, "prompt") == 0) rc = run_prompt(sub_argc, sub_argv);
            else if (scmp(cmd, "coder") == 0)  rc = run_coder(sub_argc, sub_argv);
            else if (scmp(cmd, "soul") == 0)   rc = run_soul(sub_argc, sub_argv);
            /* xpg subsumes rpg + hxhnt + lsys.  Aliases route here. */
            else if (scmp(cmd, "xpg")   == 0 || scmp(cmd, "rpg") == 0 ||
                     scmp(cmd, "hxhnt") == 0 || scmp(cmd, "lsys") == 0)
                                               rc = run_xpg(sub_argc, sub_argv);
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
            /* n-ary, left-folded: OP(a, b, c, …) = OP(OP(OP(a, b), c), …)
             * 2-arg invocations are unchanged.  3+ args chain through
             * the same truth table, e.g. AND(A1, B1, C1) is a 3-way
             * conjunction; XOR over 4 args is parity; for the
             * non-associative ops (NIA, NIB, IMP, CIMP) left-fold is
             * the consistent reading. */
            long long acc = feval_expr(depth);
            while (1) {
                fskip_ws();
                if (*fp != ',') break;
                fp++;
                long long b = feval_expr(depth);
                acc = binlog(acc, b, LOG_OPS[i].tt);
            }
            fskip_ws(); if (*fp == ')') fp++;
            return acc;
        }
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
    /* Wipe only the active sheet — A/B/C survive each other's loads. */
    mset(cell[cur_sheet], 0, sizeof cell[cur_sheet]);
    int r = 0, c = 0, i = 0;
    for (int o = 0; o < blen && r < SHEET_ROWS; o++) {
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
    int eidx = 0;

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
        char hint[80] = { 0 };
        int hn = 0;
        const char *h = editing
            ? "  editing — enter commits, esc cancels  (=A1+B2 for formulas)"
            : "  arrows|type=replace|e edit|tab/1-3|M A.B|K A(x)B|s save|q back";
        while (h[hn]) { hint[hn] = h[hn]; hn++; }
        status(hint);
        fbflush();

        unsigned char k[8];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;

        if (editing) {
            if (k[0] == '\r' || k[0] == '\n') {
                cell[cur_sheet][cellrow][cellcol][eidx] = 0;
                editing = 0;
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
            if (k[0] == 0x18) cell[cur_sheet][cellrow][cellcol][0] = 0;
        }
        if (k[0] == 0x16) {                              /* paste cell */
            int put = cb_n; if (put > 15) put = 15;
            int j = 0;
            for (int i = 0; i < put; i++) {
                if (cb[i] >= 32 && cb[i] < 127) cell[cur_sheet][cellrow][cellcol][j++] = cb[i];
            }
            cell[cur_sheet][cellrow][cellcol][j] = 0;
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
            k[0] != 'q' && k[0] != 's' && k[0] != 'e' &&
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
static unsigned char ask_msg_hidden[ASK_MAX_MSGS]; /* 1 = skip in renderer */
static int  ask_n_msgs;

static int sapp(char *dst, int at, const char *s) {
    int n = slen(s);
    mcpy(dst + at, s, n);
    return at + n;
}

static void ask_msg_add2(int role, const char *text, int tlen, int hidden) {
    if (tlen > ASK_BUF_CAP - 16) tlen = ASK_BUF_CAP - 16;
    /* drop oldest until it fits */
    while ((ask_buf_use + tlen > ASK_BUF_CAP || ask_n_msgs >= ASK_MAX_MSGS)
            && ask_n_msgs > 0) {
        int dlen = ask_msg_len[0];
        for (int i = 0; i < ask_buf_use - dlen; i++)
            ask_buf[i] = ask_buf[i + dlen];
        ask_buf_use -= dlen;
        for (int i = 1; i < ask_n_msgs; i++) {
            ask_msg_off[i-1]    = ask_msg_off[i] - dlen;
            ask_msg_len[i-1]    = ask_msg_len[i];
            ask_msg_role[i-1]   = ask_msg_role[i];
            ask_msg_hidden[i-1] = ask_msg_hidden[i];
        }
        ask_n_msgs--;
    }
    ask_msg_off[ask_n_msgs]    = ask_buf_use;
    ask_msg_len[ask_n_msgs]    = tlen;
    ask_msg_role[ask_n_msgs]   = role;
    ask_msg_hidden[ask_n_msgs] = (unsigned char)(hidden ? 1 : 0);
    mcpy(ask_buf + ask_buf_use, text, tlen);
    ask_buf_use += tlen;
    ask_n_msgs++;
}

static void ask_msg_add(int role, const char *text, int tlen) {
    ask_msg_add2(role, text, tlen, 0);
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

/* ── 4-bank persistent memory ──────────────────────────────
 * Four 4 KB banks, one file each, all in cwd.  The personality
 * bank is what `ask` prepends as a system prompt to every chat
 * completion (matches supercell's behaviour).  The other three
 * banks are for the `coder` agent's working memory: recent
 * failures + their fixes, durable long-term plans, and the
 * structure of the current project / task.  Loaded on demand
 * by ask + coder; written back when the user edits them. */
#define BANK_BYTES        4096
#define BANK_PERSONALITY  0
#define BANK_RECENT       1
#define BANK_LONGTERM     2
#define BANK_PROJECT      3
#define BANK_COUNT        4
#define PROMPT_MAX        BANK_BYTES   /* legacy alias for ask */

static const char *BANK_FILE[BANK_COUNT] = {
    "personality.bin", "recent.bin", "longterm.bin", "project.bin",
};
static const char *BANK_LABEL[BANK_COUNT] = {
    "personality", "recent", "long-term", "project",
};

static char g_bank[BANK_COUNT][BANK_BYTES];
static int  g_bank_len[BANK_COUNT];

/* Personality bank is the legacy prompt slot.  ask reads through
 * these aliases so its existing JSON-build code stays unchanged. */
#define g_llm_prompt      (g_bank[BANK_PERSONALITY])
#define g_llm_prompt_len  (g_bank_len[BANK_PERSONALITY])

static void bank_load(int b) {
    g_bank_len[b] = 0;
    int fd = (int)op(BANK_FILE[b], O_RDONLY, 0);
    if (fd < 0) return;
    long n = rd(fd, g_bank[b], BANK_BYTES - 1);
    cl(fd);
    if (n < 0) n = 0;
    g_bank_len[b] = (int)n;
    g_bank[b][g_bank_len[b]] = 0;
    /* Trim trailing whitespace from the personality bank only —
     * the other banks are coder-formatted and may rely on layout. */
    if (b == BANK_PERSONALITY) {
        while (g_bank_len[b] > 0) {
            char c = g_bank[b][g_bank_len[b] - 1];
            if (c == ' ' || c == '\n' || c == '\r' || c == '\t')
                g_bank_len[b]--;
            else break;
        }
    }
}

static void bank_save(int b) {
    int fd = (int)op(BANK_FILE[b], O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return;
    wr(fd, g_bank[b], (size_t)g_bank_len[b]);
    cl(fd);
}

static void bank_load_all(void) {
    for (int b = 0; b < BANK_COUNT; b++) bank_load(b);
}

/* Compatibility shim: ask used to call prompt_load() before each
 * request.  Now it just reloads the personality bank — same effect. */
static void prompt_load(void) { bank_load(BANK_PERSONALITY); }

static int ask_build_request(char *out, int cap) {
    (void)cap;
    prompt_load();
    int at = 0;
    int prov = ask_provider();
    int has_sys = (g_llm_prompt_len > 0);
    if (prov == ASK_PROV_GEMINI) {
        /* Gemini: {"systemInstruction":{"parts":[{"text":"…"}]},
         *          "contents":[{"role":"user|model","parts":[{"text":"…"}]}]} */
        at = sapp(out, at, "{");
        if (has_sys) {
            at = sapp(out, at, "\"systemInstruction\":{\"parts\":[{\"text\":\"");
            at = ask_json_esc(out, at, g_llm_prompt, g_llm_prompt_len);
            at = sapp(out, at, "\"}]},");
        }
        at = sapp(out, at, "\"contents\":[");
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
     * just pass it through.  System prompt: OpenAI takes a
     * {"role":"system"} message; Anthropic prefers a top-level
     * "system" field but also tolerates the system role inside
     * messages[] via OpenAI-compat proxies, which is what most of
     * the keys in the wild are anyway. */
    at = sapp(out, at, "{\"model\":\"");
    at = ask_json_esc(out, at, ask_model, slen(ask_model));
    /* office50 — always cap max_tokens.  Anthropic *requires* it; for
     * OpenAI / proxies it's optional, but the pekpik proxy was
     * applying a very large default per call against GPT-5.5 keys
     * (eating the whole rate-limit budget on every message). */
    at = sapp(out, at, "\",\"max_tokens\":1024");
    if (has_sys) {
        at = sapp(out, at, ",\"system\":\"");
        at = ask_json_esc(out, at, g_llm_prompt, g_llm_prompt_len);
        at = sapp(out, at, "\"");
    }
    at = sapp(out, at, ",\"messages\":[");
    if (has_sys) {
        /* Belt and suspenders: also include the prompt as a system
         * message for OpenAI-compat endpoints that ignore "system". */
        at = sapp(out, at, "{\"role\":\"system\",\"content\":\"");
        at = ask_json_esc(out, at, g_llm_prompt, g_llm_prompt_len);
        at = sapp(out, at, "\"},");
    }
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
        if (ask_msg_hidden[i]) continue;
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
        if (ask_msg_hidden[i]) continue;
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

/* Call the LLM up to ASK_RETRY_MAX times.  On every miss (curl
 * failure, empty body, missing content/text, provider error JSON)
 * fetch a fresh random key from the upstream README and try again —
 * the same auto-retry loop coder uses, so an expired/rate-limited
 * key in office_ask.conf doesn't ground a chat.  On success after
 * at least one retry, ask_save_conf() persists the working key.
 * Returns extracted content length, or -1 with fail_reason filled. */
static int ask_send_retrying(char *content_out, int content_cap,
                             char *fail_reason_out, int fr_cap) {
    #define ASK_RETRY_MAX 3
    static char resp[ASK_RESP_CAP];
    int succeeded_after_retry = 0;
    fail_reason_out[0] = 0;
    for (int attempt = 0; attempt < ASK_RETRY_MAX; attempt++) {
        if (attempt > 0) {
            char st[96]; int sp = 0;
            sp = sapp(st, sp, "ask: provider rejected — fresh key (try ");
            sp += utoa((unsigned)(attempt + 1), st + sp);
            sp = sapp(st, sp, "/");
            sp += utoa((unsigned)ASK_RETRY_MAX, st + sp);
            sp = sapp(st, sp, ")"); st[sp] = 0;
            status(st); fbflush();
            ask_fetch_random_key();
            succeeded_after_retry = 1;
        }
        int rc = ask_call_curl();
        if (rc < 0) {
            int p = sapp(fail_reason_out, 0, "curl failed");
            fail_reason_out[p < fr_cap - 1 ? p : fr_cap - 1] = 0;
            continue;
        }
        int fd = (int)op(ASK_RESP_FILE, O_RDONLY, 0);
        if (fd < 0) {
            int p = sapp(fail_reason_out, 0, "no response file");
            fail_reason_out[p < fr_cap - 1 ? p : fr_cap - 1] = 0;
            continue;
        }
        int rn = (int)rd(fd, resp, sizeof resp - 1);
        cl(fd);
        if (rn <= 0) {
            int p = sapp(fail_reason_out, 0,
                         "empty response — likely 429 / rate-limited");
            fail_reason_out[p < fr_cap - 1 ? p : fr_cap - 1] = 0;
            continue;
        }
        resp[rn] = 0;
        int cn = ask_extract_content(resp, rn, content_out, content_cap);
        if (cn < 0) {
            char emsg[256];
            int en = ask_extract_error(resp, rn, emsg, sizeof emsg);
            int p;
            if (en > 0) {
                p = sapp(fail_reason_out, 0, "api: ");
                int take = en;
                if (p + take > fr_cap - 1) take = fr_cap - 1 - p;
                mcpy(fail_reason_out + p, emsg, take);
                p += take;
            } else {
                p = sapp(fail_reason_out, 0, "no content/text in response");
            }
            if (p > fr_cap - 1) p = fr_cap - 1;
            fail_reason_out[p] = 0;
            continue;
        }
        if (succeeded_after_retry) ask_save_conf();
        return cn;
    }
    #undef ASK_RETRY_MAX
    return -1;
}

/* bash-style ↑/↓ history.  Persists across run_ask invocations
 * (static), capped at ASK_HIST_MAX entries × ASK_HIST_ENTRY bytes.
 * Long pastes are silently truncated on push.  hist[0] is the most
 * recent entry. */
#define ASK_HIST_MAX    8
#define ASK_HIST_ENTRY  1024
static char ask_hist[ASK_HIST_MAX][ASK_HIST_ENTRY];
static int  ask_hist_len[ASK_HIST_MAX];
static int  ask_hist_n = 0;

static void ask_hist_push(const char *text, int tlen) {
    if (tlen <= 0) return;
    if (tlen > ASK_HIST_ENTRY - 1) tlen = ASK_HIST_ENTRY - 1;
    /* Skip exact duplicates of the most recent entry. */
    if (ask_hist_n > 0 && ask_hist_len[0] == tlen) {
        int eq = 1;
        for (int i = 0; i < tlen; i++)
            if (ask_hist[0][i] != text[i]) { eq = 0; break; }
        if (eq) return;
    }
    int last = ask_hist_n < ASK_HIST_MAX ? ask_hist_n : ASK_HIST_MAX - 1;
    for (int i = last; i > 0; i--) {
        mcpy(ask_hist[i], ask_hist[i-1], ask_hist_len[i-1]);
        ask_hist_len[i] = ask_hist_len[i-1];
    }
    mcpy(ask_hist[0], text, tlen);
    ask_hist_len[0] = tlen;
    if (ask_hist_n < ASK_HIST_MAX) ask_hist_n++;
}

static int run_ask(int argc, char **argv) {
    (void)argc; (void)argv;
    current_ms = &ms_ask;
    ask_load_conf();

    static char input[ASK_INPUT_CAP];
    int inlen = 0;
    static char errmsg[256];
    static char notice[128];
    errmsg[0] = 0;
    notice[0] = 0;
    /* Per-session history cursor.  -1 = at the live draft (no
     * history selected); 0..ask_hist_n-1 = walking backwards. */
    int hist_pos = -1;
    static char hist_draft[ASK_INPUT_CAP];
    int hist_draft_len = 0;

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
        } else if (notice[0]) {
            sgrbgfg(COL_BAR_BG, 28);
            status(notice);
            sgrbgfg(COL_BAR_BG, COL_BAR_FG);
            notice[0] = 0;
        } else if (!ask_api_key[0]) {
            status("no api_key set — File > Settings (Alt+F)");
        } else {
            status("ENTER send | ^N clear | ^P sync | ^E settings | ^Q quit");
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
        if (act == MA_PROMPT_SYNC) k[0] = 0x10;   /* fall through to ^P */

        if (k[0] == 0x11) break;                                     /* ^Q */
        if (k[0] == 0x0e) { ask_n_msgs = 0; ask_buf_use = 0; continue; } /* ^N */
        if (k[0] == 0x05) { ask_settings_modal(); continue; }            /* ^E */
        if (k[0] == 0x10) {                                          /* ^P sync */
            if (!ask_api_key[0]) {
                int el = sapp(errmsg, 0, "no api_key set — open Settings");
                errmsg[el] = 0;
                continue;
            }
            prompt_load();
            if (g_llm_prompt_len <= 0) {
                int el = sapp(errmsg, 0,
                              "personality bank empty — fill via prompt 1");
                errmsg[el] = 0;
                continue;
            }
            /* Checkpoint so we can roll back on failure. */
            int ck_n = ask_n_msgs, ck_use = ask_buf_use;
            ask_msg_add2(0, g_llm_prompt, g_llm_prompt_len, 1);

            cup(0, SCREEN_H - 3);
            sgrbgfg(COL_BAR_BG, 8);
            for (int x = 0; x < SCREEN_W; x++) fbs("-");
            cup(0, SCREEN_H - 2);
            sgrbgfg(15, 0);
            fbs(" > "); blanks(SCREEN_W - 3);
            sgrbgfg(COL_BAR_BG, COL_BAR_FG);
            status("syncing personality ...");
            fbflush();

            static char content[ASK_BUF_CAP];
            char fail_reason[160];
            int cn = ask_send_retrying(content, sizeof content,
                                       fail_reason, sizeof fail_reason);
            if (cn < 0) {
                ask_n_msgs = ck_n; ask_buf_use = ck_use;
                int p = sapp(errmsg, 0, "sync failed: ");
                int take = (int)slen(fail_reason);
                if (p + take > (int)sizeof errmsg - 1)
                    take = sizeof errmsg - 1 - p;
                mcpy(errmsg + p, fail_reason, take);
                errmsg[p + take] = 0;
                continue;
            }
            ask_msg_add2(1, content, cn, 1);
            int p = sapp(notice, 0, "personality synced (");
            p += utoa((unsigned)g_llm_prompt_len, notice + p);
            p = sapp(notice, p, " B sent, ");
            p += utoa((unsigned)cn, notice + p);
            p = sapp(notice, p, " B ack — both hidden)");
            notice[p] = 0;
            continue;
        }

        if (k[0] == '\r' || k[0] == '\n') {
            if (inlen == 0) continue;
            if (!ask_api_key[0]) {
                int el = sapp(errmsg, 0, "no api_key set — open Settings");
                errmsg[el] = 0;
                continue;
            }
            ask_hist_push(input, inlen);
            hist_pos = -1;
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

            static char content[ASK_BUF_CAP];
            char fail_reason[160];
            int cn = ask_send_retrying(content, sizeof content,
                                       fail_reason, sizeof fail_reason);
            if (cn >= 0) {
                ask_msg_add(1, content, cn);
            } else {
                int p = sapp(errmsg, 0, fail_reason);
                if (p > (int)sizeof errmsg - 1) p = sizeof errmsg - 1;
                errmsg[p] = 0;
            }
            continue;
        }
        if (k[0] == 0x7f || k[0] == 8) {
            if (inlen > 0) inlen--;
            input[inlen] = 0;
            continue;
        }
        if (n >= 3 && k[0] == 0x1b && k[1] == '[' && k[2] == 'A') {
            /* ↑ — recall older entry.  On the first press, snapshot
             * whatever is currently in the input box so ↓ can return
             * to it. */
            if (ask_hist_n == 0) continue;
            if (hist_pos == -1) {
                int t = inlen < ASK_INPUT_CAP - 1 ? inlen : ASK_INPUT_CAP - 1;
                mcpy(hist_draft, input, t);
                hist_draft_len = t;
                hist_pos = 0;
            } else if (hist_pos < ask_hist_n - 1) {
                hist_pos++;
            } else {
                continue;            /* already at oldest */
            }
            inlen = ask_hist_len[hist_pos];
            mcpy(input, ask_hist[hist_pos], inlen);
            input[inlen] = 0;
            continue;
        }
        if (n >= 3 && k[0] == 0x1b && k[1] == '[' && k[2] == 'B') {
            /* ↓ — walk forward.  At the newest entry, one more press
             * restores the live draft. */
            if (hist_pos < 0) continue;
            if (hist_pos > 0) {
                hist_pos--;
                inlen = ask_hist_len[hist_pos];
                mcpy(input, ask_hist[hist_pos], inlen);
                input[inlen] = 0;
            } else {
                hist_pos = -1;
                inlen = hist_draft_len;
                mcpy(input, hist_draft, inlen);
                input[inlen] = 0;
            }
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


/* ── prompt: edit any one of the 4 KB memory banks ─────────
 * `prompt` with no args lists the four banks; pressing 1..4
 * picks one and drops into the notepad UI pinned to that
 * bank's file.  `prompt 1` (or 2/3/4) jumps straight to a
 * bank.  The personality bank is the one ask reads as a
 * system message; the other three feed the coder agent. */
static int run_prompt_edit_bank(int b) {
    if (b < 0 || b >= BANK_COUNT) return -1;
    current_ms = &ms_notepad;
    int fd = (int)op(BANK_FILE[b], O_RDONLY, 0);
    if (fd >= 0) {
        blen = (int)rd(fd, buf, BUF_CAP - 1);
        if (blen < 0) blen = 0;
        cl(fd);
    } else {
        blen = 0;
    }
    int j = 0;
    while (BANK_FILE[b][j] && j < (int)sizeof fname - 1) {
        fname[j] = BANK_FILE[b][j]; j++;
    }
    fname[j] = 0;
    bcur = 0; btop = 0;
    char title[48];
    int tn = 0;
    tn = sapp(title, tn, "Bank: ");
    tn = sapp(title, tn, BANK_LABEL[b]);
    tn = sapp(title, tn, " (4 KB cap)");
    title[tn] = 0;
    int rc = notepad_loop(title);
    /* Truncate on-disk to BANK_BYTES-1 so the LLM caller can't
     * overflow its request buffer with a runaway bank. */
    if (blen > BANK_BYTES - 1) {
        int fd2 = (int)op(BANK_FILE[b],
                          O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (fd2 >= 0) {
            wr(fd2, buf, (size_t)(BANK_BYTES - 1));
            cl(fd2);
        }
    }
    bank_load(b);
    return rc;
}

static int run_prompt(int argc, char **argv) {
    /* `prompt N` (1..4) → edit bank N-1 directly. */
    if (argc > 1 && argv[1][0] >= '1' && argv[1][0] <= '4' && argv[1][1] == 0) {
        return run_prompt_edit_bank(argv[1][0] - '1');
    }
    /* Otherwise show a chooser. */
    current_ms = &ms_notepad;
    while (1) {
        bank_load_all();
        paint_desktop();
        chrome("Memory Banks");
        body_clear();
        body_at(2, 3, "Pick a bank to edit:", SCREEN_W - 4);
        for (int b = 0; b < BANK_COUNT; b++) {
            char ln[80];
            int p = 2;
            ln[0] = ' '; ln[1] = ' ';
            ln[p++] = '['; ln[p++] = '1' + b; ln[p++] = ']'; ln[p++] = ' ';
            p = sapp(ln, p, BANK_LABEL[b]);
            while (p < 24) ln[p++] = ' ';
            p = sapp(ln, p, " (");
            p += utoa((unsigned)g_bank_len[b], ln + p);
            p = sapp(ln, p, "/4096 B,  ");
            p = sapp(ln, p, BANK_FILE[b]);
            p = sapp(ln, p, ")");
            ln[p] = 0;
            body_at(2, 5 + b, ln, SCREEN_W - 4);
        }
        body_at(2, 5 + BANK_COUNT + 1,
                "ENTER 1-4 picks a bank.  q quits.", SCREEN_W - 4);
        status("memory bank chooser");
        fbflush();
        unsigned char k[16];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;
        if (k[0] == 'q' || k[0] == 0x1b) break;
        if (k[0] >= '1' && k[0] <= '4') {
            run_prompt_edit_bank(k[0] - '1');
        }
    }
    return 0;
}


/* ── coder.db: TinyDB-style B-tree node store ──────────────
 *
 * Vendored + ported from Penge666/TinyDB
 * (https://github.com/Penge666/TinyDB), which is itself a
 * SQLite tutorial-style implementation: paged file layout,
 * one fixed-size leaf-node root, sorted insert with binary
 * search, no node-splitting yet.  We strip out the SQL
 * front-end + libc dependencies and replace the user-row
 * (id/username/email) with a memory-node row tailored for
 * the agent: { id, bank, timestamp, tag_bitmap, body[] }.
 *
 * coder_log_recent() inserts a row each time an iteration
 * fails; coder_build_prompt() scans the table and picks the
 * top-K rows whose tag_bitmap overlaps the current prompt
 * for inclusion as context.  The DB file is `coder.db` in
 * cwd; it travels next to the binary so jail.c-cloned
 * children inherit the same memory.
 *
 * Layout (every page is PAGE_SIZE = 4096 bytes):
 *   common header  6 B  (type, is_root, parent_pointer)
 *   leaf header    4 B  (num_cells)
 *   N × cells      244 B each (4-byte key + 240-byte row)
 * Max cells per leaf = (4096 - 14) / 244 = 16.
 *
 * v1 has one root leaf and no splitting.  When the leaf
 * fills, the oldest row (lowest id) is evicted to make room.
 * Multi-page B-tree splitting is a v2 feature. */

#define TDB_PAGE_SIZE         4096
#define TDB_MAX_PAGES         8
#define TDB_NODE_TYPE_OFFSET  0
#define TDB_IS_ROOT_OFFSET    1
#define TDB_PARENT_OFFSET     2
#define TDB_HEADER_COMMON     6
#define TDB_NUM_CELLS_OFFSET  TDB_HEADER_COMMON
#define TDB_HEADER_LEAF       (TDB_HEADER_COMMON + 4)

#define TDB_KEY_SIZE          4
#define TDB_BANK_OFFSET       0
#define TDB_PAD_OFFSET        1
#define TDB_TIMESTAMP_OFFSET  4
#define TDB_TAGBITS_OFFSET    8
#define TDB_BODY_OFFSET       16
#define TDB_BODY_SIZE         224
#define TDB_ROW_SIZE          240
#define TDB_CELL_SIZE         (TDB_KEY_SIZE + TDB_ROW_SIZE)
#define TDB_MAX_CELLS         ((TDB_PAGE_SIZE - TDB_HEADER_LEAF) / TDB_CELL_SIZE)

typedef struct {
    unsigned int  bank;          /* 0..3 = BANK_PERSONALITY..PROJECT */
    unsigned int  timestamp;
    unsigned long long tag_bitmap;
    int           body_len;
    char          body[TDB_BODY_SIZE];
} TdbRow;

static int            g_tdb_fd = -1;
static unsigned int   g_tdb_num_pages;
static unsigned int   g_tdb_next_id;
static unsigned char  g_tdb_pages[TDB_MAX_PAGES][TDB_PAGE_SIZE];
static unsigned char  g_tdb_loaded[TDB_MAX_PAGES];   /* 0 = not loaded */
static unsigned char  g_tdb_dirty [TDB_MAX_PAGES];

static unsigned int tdb_load_u32(const unsigned char *p) {
    return (unsigned int)p[0] | ((unsigned int)p[1] << 8) |
           ((unsigned int)p[2] << 16) | ((unsigned int)p[3] << 24);
}
static void tdb_store_u32(unsigned char *p, unsigned int v) {
    p[0] = (unsigned char)(v & 0xff);
    p[1] = (unsigned char)((v >> 8) & 0xff);
    p[2] = (unsigned char)((v >> 16) & 0xff);
    p[3] = (unsigned char)((v >> 24) & 0xff);
}
static unsigned long long tdb_load_u64(const unsigned char *p) {
    unsigned long long v = 0;
    for (int i = 0; i < 8; i++) v |= ((unsigned long long)p[i]) << (i * 8);
    return v;
}
static void tdb_store_u64(unsigned char *p, unsigned long long v) {
    for (int i = 0; i < 8; i++) p[i] = (unsigned char)((v >> (i * 8)) & 0xff);
}

static unsigned char *tdb_get_page(unsigned int page_num) {
    if (page_num >= TDB_MAX_PAGES) return 0;
    if (g_tdb_loaded[page_num]) return g_tdb_pages[page_num];
    /* Default: zero-init; if the page exists on disk, read it in. */
    mset(g_tdb_pages[page_num], 0, TDB_PAGE_SIZE);
    if (g_tdb_fd >= 0 && page_num < g_tdb_num_pages) {
        lseek_(g_tdb_fd, (long)page_num * TDB_PAGE_SIZE, 0);
        rd(g_tdb_fd, g_tdb_pages[page_num], TDB_PAGE_SIZE);
    } else if (page_num == 0) {
        /* Brand-new root: leaf, root, num_cells = 0. */
        g_tdb_pages[0][TDB_NODE_TYPE_OFFSET] = 1; /* leaf */
        g_tdb_pages[0][TDB_IS_ROOT_OFFSET] = 1;
        tdb_store_u32(g_tdb_pages[0] + TDB_NUM_CELLS_OFFSET, 0);
    }
    g_tdb_loaded[page_num] = 1;
    return g_tdb_pages[page_num];
}

static unsigned char *tdb_leaf_cell(unsigned char *node, unsigned int i) {
    return node + TDB_HEADER_LEAF + i * TDB_CELL_SIZE;
}

static unsigned int tdb_leaf_num_cells(unsigned char *node) {
    return tdb_load_u32(node + TDB_NUM_CELLS_OFFSET);
}

static void tdb_leaf_set_num_cells(unsigned char *node, unsigned int n) {
    tdb_store_u32(node + TDB_NUM_CELLS_OFFSET, n);
}

/* Binary search for the cell index where `key` would live (insert
 * point or match position).  Mirrors TinyDB's leaf_node_find. */
static unsigned int tdb_leaf_find(unsigned char *node, unsigned int key) {
    unsigned int n = tdb_leaf_num_cells(node);
    unsigned int lo = 0, hi = n;
    while (lo != hi) {
        unsigned int mid = (lo + hi) / 2;
        unsigned int kmid = tdb_load_u32(tdb_leaf_cell(node, mid));
        if (kmid == key) return mid;
        if (key < kmid) hi = mid; else lo = mid + 1;
    }
    return lo;
}

static void tdb_open(void) {
    if (g_tdb_fd >= 0) return;
    int fd = (int)op("coder.db", O_RDWR | O_CREAT, 0644);
    if (fd < 0) {
        /* Read-only fallback so a missing-file scenario still works. */
        fd = (int)op("coder.db", O_RDONLY, 0);
    }
    g_tdb_fd = fd;
    g_tdb_num_pages = 0;
    g_tdb_next_id = 1;
    for (int i = 0; i < TDB_MAX_PAGES; i++) {
        g_tdb_loaded[i] = 0; g_tdb_dirty[i] = 0;
    }
    if (fd >= 0) {
        long len = lseek_(fd, 0, 2);   /* SEEK_END */
        lseek_(fd, 0, 0);
        if (len > 0) g_tdb_num_pages = (unsigned int)(len / TDB_PAGE_SIZE);
        if (g_tdb_num_pages > TDB_MAX_PAGES) g_tdb_num_pages = TDB_MAX_PAGES;
    }
    /* Force the root page in so a fresh DB has one initialised leaf. */
    unsigned char *root = tdb_get_page(0);
    if (g_tdb_num_pages == 0) {
        g_tdb_num_pages = 1;
        g_tdb_dirty[0] = 1;
    }
    /* Seed the auto-id counter from the highest existing key. */
    unsigned int n = tdb_leaf_num_cells(root);
    if (n > 0) {
        unsigned int last = tdb_load_u32(tdb_leaf_cell(root, n - 1));
        if (last >= g_tdb_next_id) g_tdb_next_id = last + 1;
    }
}

static void tdb_close(void) {
    if (g_tdb_fd < 0) return;
    for (unsigned int p = 0; p < g_tdb_num_pages && p < TDB_MAX_PAGES; p++) {
        if (!g_tdb_loaded[p] || !g_tdb_dirty[p]) continue;
        lseek_(g_tdb_fd, (long)p * TDB_PAGE_SIZE, 0);
        wr(g_tdb_fd, g_tdb_pages[p], TDB_PAGE_SIZE);
        g_tdb_dirty[p] = 0;
    }
    cl(g_tdb_fd);
    g_tdb_fd = -1;
}

/* Insert a row with auto-generated key.  If the leaf is full, evict
 * the lowest-key row first (simple FIFO eviction — first-id-wins is
 * also first-inserted-wins because ids are auto-increment). */
static int tdb_insert(const TdbRow *row) {
    tdb_open();
    unsigned char *node = tdb_get_page(0);
    unsigned int n = tdb_leaf_num_cells(node);
    if (n >= TDB_MAX_CELLS) {
        /* Drop the head cell. */
        for (unsigned int i = 1; i < n; i++) {
            mcpy((char *)tdb_leaf_cell(node, i - 1),
                 (char *)tdb_leaf_cell(node, i), TDB_CELL_SIZE);
        }
        n--;
        tdb_leaf_set_num_cells(node, n);
    }
    unsigned int key = g_tdb_next_id++;
    unsigned int pos = tdb_leaf_find(node, key);   /* always == n */
    if (pos < n) {
        for (unsigned int i = n; i > pos; i--) {
            mcpy((char *)tdb_leaf_cell(node, i),
                 (char *)tdb_leaf_cell(node, i - 1), TDB_CELL_SIZE);
        }
    }
    unsigned char *cell = tdb_leaf_cell(node, pos);
    tdb_store_u32(cell, key);
    unsigned char *body = cell + TDB_KEY_SIZE;
    body[TDB_BANK_OFFSET] = (unsigned char)row->bank;
    body[TDB_PAD_OFFSET]   = 0;
    body[TDB_PAD_OFFSET+1] = 0;
    body[TDB_PAD_OFFSET+2] = 0;
    tdb_store_u32(body + TDB_TIMESTAMP_OFFSET, row->timestamp);
    tdb_store_u64(body + TDB_TAGBITS_OFFSET,   row->tag_bitmap);
    int blen = row->body_len;
    if (blen > TDB_BODY_SIZE) blen = TDB_BODY_SIZE;
    if (blen < 0) blen = 0;
    mcpy((char *)body + TDB_BODY_OFFSET, row->body, blen);
    /* zero-pad the tail so old data doesn't bleed into the new cell */
    if (blen < TDB_BODY_SIZE)
        mset(body + TDB_BODY_OFFSET + blen, 0, TDB_BODY_SIZE - blen);
    tdb_leaf_set_num_cells(node, n + 1);
    g_tdb_dirty[0] = 1;
    return (int)key;
}

/* Read row N (0..num_cells-1) from the root leaf into `out`.
 * Returns 0 on success, -1 if out of range. */
static int tdb_read(unsigned int idx, TdbRow *out) {
    tdb_open();
    unsigned char *node = tdb_get_page(0);
    unsigned int n = tdb_leaf_num_cells(node);
    if (idx >= n) return -1;
    unsigned char *cell = tdb_leaf_cell(node, idx);
    unsigned char *body = cell + TDB_KEY_SIZE;
    out->bank      = body[TDB_BANK_OFFSET];
    out->timestamp = tdb_load_u32(body + TDB_TIMESTAMP_OFFSET);
    out->tag_bitmap= tdb_load_u64(body + TDB_TAGBITS_OFFSET);
    int blen = TDB_BODY_SIZE;
    while (blen > 0 && body[TDB_BODY_OFFSET + blen - 1] == 0) blen--;
    out->body_len = blen;
    mcpy(out->body, (char *)body + TDB_BODY_OFFSET, blen);
    return 0;
}

static unsigned int tdb_count(void) {
    tdb_open();
    return tdb_leaf_num_cells(tdb_get_page(0));
}

/* Build a 64-bit tag bitmap by hashing alphanumeric tokens.  Same
 * function used at insert and at retrieval, so two strings overlap
 * iff they share any token modulo bucket collisions. */
static unsigned long long tdb_tag_bitmap(const char *txt, int len) {
    unsigned long long bits = 0;
    int i = 0;
    while (i < len) {
        while (i < len) {
            char c = txt[i];
            int alnum = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                        (c >= '0' && c <= '9');
            if (alnum) break;
            i++;
        }
        if (i >= len) break;
        unsigned int h = 5381;
        while (i < len) {
            char c = txt[i];
            int alnum = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                        (c >= '0' && c <= '9');
            if (!alnum) break;
            if (c >= 'A' && c <= 'Z') c = (char)(c + 32);
            h = h * 33 + (unsigned char)c;
            i++;
        }
        bits |= 1ULL << (h & 63);
    }
    return bits;
}

/* popcount for 64-bit values without -mpopcnt — small enough that
 * GCC at -Os might inline a swar-style implementation anyway. */
static int tdb_popcount(unsigned long long v) {
    int c = 0;
    while (v) { c += (int)(v & 1); v >>= 1; }
    return c;
}


/* ── coder: iterative LLM-driven code generator ─────────────
 *
 * The user enters a goal; coder builds a prompt from the four
 * memory banks + previous draft + previous compile error,
 * fires the LLM via ask's curl machinery, extracts the C source
 * from the response, runs cc, and feeds any error back into the
 * next iteration's prompt.  Stops when the configured target is
 * met or the iteration cap is hit.
 *
 * Targets:
 *   0  good_enough  cc compiles cleanly (no -Wall, no run)
 *   1  clean        cc -Wall -Wextra clean (no warnings)
 *   2  perfect      clean + program runs without crashing
 *
 * Output paths: /tmp/coder_attempt.c (source), /tmp/coder_attempt
 * (binary), /tmp/coder_err.txt (compile output), /tmp/coder_run.txt
 * (runtime output for `perfect` target).
 */

#define CODER_GOAL_CAP   256
#define CODER_DRAFT_CAP  16384
#define CODER_ERR_CAP    4096
#define CODER_MAX_ITERS  8

static const char *CODER_TARGET_NAME[3] = {
    "good_enough", "clean", "perfect"
};

static char g_coder_goal[CODER_GOAL_CAP];
static int  g_coder_goal_len;
static char g_coder_draft[CODER_DRAFT_CAP];
static int  g_coder_draft_len;
static char g_coder_err[CODER_ERR_CAP];
static int  g_coder_err_len;
static int  g_coder_target;     /* 0..2 */
static int  g_coder_iter;       /* iteration counter */

/* Run cc on /tmp/coder_attempt.c.  Returns 0 = clean, 1 = warn-or-err.
 * Captures cc's stderr+stdout into /tmp/coder_err.txt. */
static int coder_compile(int strict) {
    long pid = forkk();
    if (pid < 0) return 1;
    if (pid == 0) {
        int fd = (int)op("/tmp/coder_err.txt",
                         O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (fd >= 0) {
            dup2_(fd, 1);
            dup2_(fd, 2);
            cl(fd);
        }
        char *argv_[12];
        int ai = 0;
        argv_[ai++] = (char *)"cc";
        if (strict) {
            argv_[ai++] = (char *)"-Wall";
            argv_[ai++] = (char *)"-Wextra";
        }
        argv_[ai++] = (char *)"-o";
        argv_[ai++] = (char *)"/tmp/coder_attempt";
        argv_[ai++] = (char *)"/tmp/coder_attempt.c";
        argv_[ai++] = 0;
        execvee("/usr/bin/cc",       argv_, g_envp);
        execvee("/usr/bin/gcc",      argv_, g_envp);
        execvee("/usr/local/bin/cc", argv_, g_envp);
        qu(127);
    }
    int status = 0;
    wait4_(&status);
    return ((status & 0xff00) >> 8) == 0 ? 0 : 1;
}

/* Run /tmp/coder_attempt and capture stdout+stderr to coder_run.txt.
 * Returns the child's exit status (0 = clean run). */
static int coder_runtest(void) {
    long pid = forkk();
    if (pid < 0) return 1;
    if (pid == 0) {
        int fd = (int)op("/tmp/coder_run.txt",
                         O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (fd >= 0) {
            dup2_(fd, 1);
            dup2_(fd, 2);
            cl(fd);
        }
        char *argv_[2];
        argv_[0] = (char *)"/tmp/coder_attempt";
        argv_[1] = 0;
        execvee("/tmp/coder_attempt", argv_, g_envp);
        qu(127);
    }
    int status = 0;
    wait4_(&status);
    return (status & 0xff00) >> 8;
}

/* Build the user-message prompt for the LLM call.  Returns its length.
 * Layout: persona instructions, then each non-empty bank under a
 * labelled header, then the goal, the previous draft (if any), the
 * previous compile output (if any), and a closing instruction. */
static int coder_build_prompt(char *out, int cap) {
    int p = 0;
    p = sapp(out, p,
             "You are a C code generator running inside a 64 KB "
             "office app.  Output ONLY a complete C program inside "
             "a fenced code block (```c ... ```).  No commentary "
             "outside the fence.  The program must compile with cc "
             "on Linux x86_64.\n\n");
    if (g_coder_target == 1)
        p = sapp(out, p,
                 "Target: clean.  cc -Wall -Wextra must produce zero "
                 "warnings as well as zero errors.\n\n");
    else if (g_coder_target == 2)
        p = sapp(out, p,
                 "Target: perfect.  cc -Wall -Wextra clean AND the "
                 "compiled program must run without crashing or "
                 "printing diagnostics.\n\n");
    else
        p = sapp(out, p, "Target: good-enough.  cc must compile.\n\n");
    /* Banks: project + longterm get full inclusion (user-curated,
     * static-ish).  recent gets DB-backed top-K retrieval — pull
     * the rows whose tag_bitmap overlaps the current goal+error
     * the most, regardless of whether they're still in the bank
     * file (they may have been evicted by the rolling buffer). */
    for (int b = 2; b < BANK_COUNT; b++) {   /* longterm + project */
        if (g_bank_len[b] <= 0) continue;
        if (p + 64 + g_bank_len[b] > cap - 1024) break;
        p = sapp(out, p, "[");
        p = sapp(out, p, BANK_LABEL[b]);
        p = sapp(out, p, " bank]\n");
        mcpy(out + p, g_bank[b], g_bank_len[b]);
        p += g_bank_len[b];
        out[p++] = '\n'; out[p++] = '\n';
    }
    /* Top-K node retrieval from coder.db keyed by tag overlap with
     * the current goal + previous error.  K = 4 by default; each
     * row is up to 224 B body so the worst-case context add is
     * ~1 KB. */
    {
        unsigned long long q = tdb_tag_bitmap(g_coder_goal, g_coder_goal_len) |
                               tdb_tag_bitmap(g_coder_err,  g_coder_err_len);
        unsigned int n = tdb_count();
        int K = 4;
        int picked[16]; int scores[16];
        unsigned int idxs[16];
        int found = 0;
        for (unsigned int i = 0; i < n && found < (int)(sizeof picked / sizeof picked[0]); i++) {
            TdbRow r;
            if (tdb_read(i, &r) != 0) continue;
            int s = tdb_popcount(q & r.tag_bitmap);
            if (s == 0) continue;
            picked[found] = 1;
            scores[found] = s;
            idxs[found] = i;
            found++;
        }
        /* Cheap O(K·N): pick the K highest-scoring rows.  N≤16, fine. */
        if (found > 0 && p < cap - 256) {
            p = sapp(out, p, "[recent (top-K from coder.db)]\n");
            for (int k = 0; k < K; k++) {
                int best = -1, best_s = 0;
                for (int j = 0; j < found; j++) {
                    if (picked[j] != 1) continue;
                    if (scores[j] > best_s) { best_s = scores[j]; best = j; }
                }
                if (best < 0) break;
                picked[best] = 0;
                TdbRow r;
                if (tdb_read(idxs[best], &r) != 0) continue;
                if (p + r.body_len + 32 > cap - 256) break;
                p = sapp(out, p, "  · ");
                mcpy(out + p, r.body, r.body_len);
                p += r.body_len;
                if (out[p-1] != '\n') out[p++] = '\n';
            }
            out[p++] = '\n';
        }
    }
    /* Goal */
    p = sapp(out, p, "[goal]\n");
    if (g_coder_goal_len > 0) {
        mcpy(out + p, g_coder_goal, g_coder_goal_len);
        p += g_coder_goal_len;
    } else {
        p = sapp(out, p, "(no goal entered)");
    }
    out[p++] = '\n'; out[p++] = '\n';
    /* Previous draft */
    if (g_coder_draft_len > 0 && p + g_coder_draft_len < cap - 512) {
        p = sapp(out, p, "[previous attempt]\n```c\n");
        mcpy(out + p, g_coder_draft, g_coder_draft_len);
        p += g_coder_draft_len;
        p = sapp(out, p, "\n```\n\n");
    }
    /* Compile output */
    if (g_coder_err_len > 0 && p + g_coder_err_len < cap - 256) {
        p = sapp(out, p, "[compile output]\n");
        mcpy(out + p, g_coder_err, g_coder_err_len);
        p += g_coder_err_len;
        out[p++] = '\n'; out[p++] = '\n';
    }
    p = sapp(out, p,
             "Now produce the next draft.  Address any errors above "
             "and respect the target.");
    return p;
}

/* Extract the largest fenced ```c ... ``` block from `src` into out.
 * If no fence is found, copies the whole thing as a fallback.
 * Returns the byte count written. */
static int coder_extract_code(const char *src, int sn, char *out, int cap) {
    int best_start = -1, best_end = -1;
    for (int i = 0; i + 4 <= sn; i++) {
        if (src[i] == '`' && src[i+1] == '`' && src[i+2] == '`') {
            int j = i + 3;
            while (j < sn && src[j] != '\n') j++;   /* skip lang tag */
            if (j >= sn) break;
            j++;
            int s = j;
            int e = -1;
            for (int k = s; k + 3 <= sn; k++) {
                if (src[k] == '`' && src[k+1] == '`' && src[k+2] == '`') {
                    e = k; break;
                }
            }
            if (e < 0) e = sn;
            int len = e - s;
            if (len > best_end - best_start) {
                best_start = s; best_end = e;
            }
            if (e + 3 < sn) i = e + 2;
            else break;
        }
    }
    if (best_start < 0) {
        int n = sn < cap - 1 ? sn : cap - 1;
        mcpy(out, src, n);
        out[n] = 0;
        return n;
    }
    int n = best_end - best_start;
    if (n > cap - 1) n = cap - 1;
    mcpy(out, src + best_start, n);
    out[n] = 0;
    return n;
}

/* One iteration: build prompt, call LLM, extract code, compile,
 * (optionally run).  Updates g_coder_draft + g_coder_err.
 * Returns 0 on success at the configured target, 1 otherwise. */
static int coder_iterate(void) {
    static char prompt_buf[24576];
    int pn = coder_build_prompt(prompt_buf, sizeof prompt_buf);
    /* Free-tier API keys on the upstream alistaitsacle/free-llm-api-keys
     * README rotate hour-by-hour as old keys hit their quota and new
     * ones get added.  So a key that worked yesterday almost certainly
     * doesn't today.  When curl/content fails, grab a fresh key from
     * the README and retry — up to CODER_RETRY_MAX attempts.  Only
     * after all retries fail do we fall through to the on-board soul.
     * On success after a retry, persist the working key to
     * office_ask.conf so the next iteration starts warm. */
    #define CODER_RETRY_MAX 3
    static char raw[ASK_RESP_CAP];
    static char content[ASK_BUF_CAP];
    int cn = -1;
    const char *fail_reason = "(curl failed — check ask config)";
    int succeeded_after_retry = 0;
    for (int attempt = 0; attempt < CODER_RETRY_MAX; attempt++) {
        if (attempt > 0) {
            /* Show progress; the retry message lives in the status bar
             * until the next coder_paint() after iterate returns. */
            char st[80]; int sp = 0;
            sp = sapp(st, sp, "coder: provider rejected — fetching fresh key (try ");
            sp += utoa((unsigned)(attempt + 1), st + sp);
            sp = sapp(st, sp, "/");
            sp += utoa((unsigned)CODER_RETRY_MAX, st + sp);
            sp = sapp(st, sp, ")…"); st[sp] = 0;
            status(st); fbflush();
            ask_fetch_random_key();
            succeeded_after_retry = 1;
        }
        /* Re-build the messages each pass — ask_call_curl mutates the
         * temp request file, but ask_buf is preserved.  We reset
         * defensively so a half-finished prior call can't corrupt
         * the new attempt. */
        ask_n_msgs = 0;
        ask_buf_use = 0;
        ask_msg_add(0, prompt_buf, pn);
        bank_load(BANK_PERSONALITY);
        if (ask_call_curl() != 0) {
            fail_reason = "(curl failed)";
            continue;
        }
        int fd = (int)op(ASK_RESP_FILE, O_RDONLY, 0);
        if (fd < 0) { fail_reason = "(no response file)"; continue; }
        long n = rd(fd, raw, sizeof raw);
        cl(fd);
        if (n <= 0) {
            fail_reason = "(empty response — likely 429 / rate-limited)";
            continue;
        }
        cn = ask_extract_content(raw, (int)n, content, sizeof content);
        if (cn < 0) {
            fail_reason = "(no 'content' or 'text' field — provider error?)";
            continue;
        }
        /* Got a real response.  If we burned a retry to find a working
         * key, save it to disk so the next iteration starts here. */
        if (succeeded_after_retry) ask_save_conf();
        break;
    }

    if (cn < 0) {
        /* All retries exhausted — fall back to the soul so the user
         * sees something useful instead of a bare error.  The soul
         * produces chat-style output (not C code), so we only surface
         * it in the err panel; the previous draft (if any) stays
         * intact for the next iteration. */
        int p = sapp(g_coder_err, 0, fail_reason);
        p = sapp(g_coder_err, p, " (after ");
        p += utoa((unsigned)CODER_RETRY_MAX, g_coder_err + p);
        p = sapp(g_coder_err, p, " retries)");
        if (g_coder_goal_len > 0) {
            char gz[CODER_GOAL_CAP];
            int gl = g_coder_goal_len < CODER_GOAL_CAP - 1
                     ? g_coder_goal_len : CODER_GOAL_CAP - 1;
            mcpy(gz, g_coder_goal, gl); gz[gl] = 0;
            char reply[256];
            int rl = sl_generate(gz, reply, sizeof reply, 16);
            p = sapp(g_coder_err, p, "\n  soul says: ");
            int take = rl;
            if (p + take > CODER_ERR_CAP - 1) take = CODER_ERR_CAP - 1 - p;
            mcpy(g_coder_err + p, reply, take);
            p += take;
        }
        g_coder_err[p] = 0;
        g_coder_err_len = p;
        return 1;
    }
    #undef CODER_RETRY_MAX
    g_coder_draft_len = coder_extract_code(content, cn,
                                           g_coder_draft, CODER_DRAFT_CAP);
    /* Write source + compile. */
    int wfd = (int)op("/tmp/coder_attempt.c",
                      O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (wfd >= 0) {
        wr(wfd, g_coder_draft, (size_t)g_coder_draft_len);
        cl(wfd);
    }
    int strict = (g_coder_target >= 1);
    int comp_rc = coder_compile(strict);
    g_coder_err_len = 0;
    int efd = (int)op("/tmp/coder_err.txt", O_RDONLY, 0);
    if (efd >= 0) {
        long en = rd(efd, g_coder_err, CODER_ERR_CAP - 1);
        cl(efd);
        if (en > 0) g_coder_err_len = (int)en;
        g_coder_err[g_coder_err_len] = 0;
    }
    if (comp_rc != 0) return 1;
    /* Auto-promote: when an iteration meets the target, insert a
     * (goal, keyword) row into coder.db with bank=BANK_SOUL_TESTS so
     * the soul's GA picks it up.  Keyword = the longest alphabetic
     * word ≥ 4 chars from the goal (e.g. "fizzbuzz" from "write a
     * fizzbuzz program" → soul learns to mention 'fizzbuzz' on that
     * prompt).  Skipped if no usable word, so single-letter goals
     * don't pollute the test set. */
    #define CODER_PROMOTE_SUCCESS() do {                                    \
        if (g_coder_goal_len > 0) {                                         \
            int _bs = -1, _bl = 0;                                          \
            int _i = 0;                                                     \
            while (_i < g_coder_goal_len) {                                 \
                while (_i < g_coder_goal_len && !((g_coder_goal[_i]>='a'&&g_coder_goal[_i]<='z')||(g_coder_goal[_i]>='A'&&g_coder_goal[_i]<='Z'))) _i++; \
                int _s = _i;                                                \
                while (_i < g_coder_goal_len && ((g_coder_goal[_i]>='a'&&g_coder_goal[_i]<='z')||(g_coder_goal[_i]>='A'&&g_coder_goal[_i]<='Z'))) _i++; \
                int _len = _i - _s;                                         \
                if (_len >= 4 && _len > _bl) { _bs = _s; _bl = _len; }      \
            }                                                               \
            if (_bs >= 0) {                                                 \
                char _goal[80], _exp[24];                                   \
                int _gl = g_coder_goal_len < 79 ? g_coder_goal_len : 79;    \
                mcpy(_goal, g_coder_goal, _gl); _goal[_gl] = 0;             \
                int _el = _bl < 23 ? _bl : 23;                              \
                for (int _k = 0; _k < _el; _k++) {                          \
                    char _c = g_coder_goal[_bs + _k];                       \
                    if (_c >= 'A' && _c <= 'Z') _c += 32;                   \
                    _exp[_k] = _c;                                          \
                }                                                           \
                _exp[_el] = 0;                                              \
                tdb_open();                                                 \
                sl_save_test(_goal, _exp);                                  \
                tdb_close();                                                \
            }                                                               \
        }                                                                   \
    } while (0)

    /* good_enough success on compile. */
    if (g_coder_target == 0) { CODER_PROMOTE_SUCCESS(); return 0; }
    /* clean: warnings show up as non-empty err even on clean exit. */
    if (g_coder_target == 1) {
        if (g_coder_err_len > 0) return 1;
        CODER_PROMOTE_SUCCESS();
        return 0;
    }
    /* perfect: also try to run. */
    int run_rc = coder_runtest();
    if (run_rc != 0) {
        int rfd = (int)op("/tmp/coder_run.txt", O_RDONLY, 0);
        if (rfd >= 0) {
            long rn = rd(rfd, g_coder_err, CODER_ERR_CAP - 1);
            cl(rfd);
            if (rn > 0) {
                g_coder_err_len = (int)rn;
                g_coder_err[g_coder_err_len] = 0;
            }
        }
        return 1;
    }
    CODER_PROMOTE_SUCCESS();
    #undef CODER_PROMOTE_SUCCESS
    return 0;
}

/* Append the most recent (goal,error,draft-snippet) trio to the
 * recent bank for human reading, AND insert a tagged row into the
 * coder.db node store for the agent's own context retrieval.
 * The bank version is plain text so the user can browse it via
 * the prompt editor; the DB version carries a tag bitmap so the
 * next prompt build can pull the most relevant prior failures
 * even after the bank has rolled over. */
static void coder_log_recent(void) {
    /* Compose a one-line summary of (iter, goal, error). */
    char rec[1024];
    int p = 0;
    p = sapp(rec, p, "--- iter ");
    p += utoa((unsigned)g_coder_iter, rec + p);
    p = sapp(rec, p, " (target=");
    p = sapp(rec, p, CODER_TARGET_NAME[g_coder_target]);
    p = sapp(rec, p, ")\ngoal: ");
    int gn = g_coder_goal_len; if (gn > 96) gn = 96;
    mcpy(rec + p, g_coder_goal, gn); p += gn;
    p = sapp(rec, p, "\nerror: ");
    int en = g_coder_err_len; if (en > 320) en = 320;
    mcpy(rec + p, g_coder_err, en); p += en;
    rec[p++] = '\n';
    if (p > BANK_BYTES - 1) p = BANK_BYTES - 1;
    /* Bank: drop oldest lines until it fits. */
    while (g_bank_len[BANK_RECENT] + p > BANK_BYTES - 1) {
        int i = 0;
        while (i < g_bank_len[BANK_RECENT] && g_bank[BANK_RECENT][i] != '\n') i++;
        if (i >= g_bank_len[BANK_RECENT]) { g_bank_len[BANK_RECENT] = 0; break; }
        i++;
        for (int k = 0; k < g_bank_len[BANK_RECENT] - i; k++)
            g_bank[BANK_RECENT][k] = g_bank[BANK_RECENT][k + i];
        g_bank_len[BANK_RECENT] -= i;
    }
    mcpy(g_bank[BANK_RECENT] + g_bank_len[BANK_RECENT], rec, p);
    g_bank_len[BANK_RECENT] += p;
    /* DB: insert a row tagged by goal + error tokens. */
    TdbRow row;
    row.bank = BANK_RECENT;
    row.timestamp = (unsigned int)time_();
    row.tag_bitmap = tdb_tag_bitmap(g_coder_goal, g_coder_goal_len) |
                     tdb_tag_bitmap(g_coder_err,  g_coder_err_len);
    int dlen = p; if (dlen > TDB_BODY_SIZE) dlen = TDB_BODY_SIZE;
    mcpy(row.body, rec, dlen);
    row.body_len = dlen;
    tdb_insert(&row);
}

static void coder_paint(const char *status_msg) {
    paint_desktop();
    chrome("coder · agentic LLM");
    body_clear();
    /* Goal */
    {
        char ln[80];
        int p = 0;
        p = sapp(ln, p, "Goal: ");
        int gn = g_coder_goal_len;
        int avail = SCREEN_W - 4 - p;
        if (gn > avail) gn = avail;
        mcpy(ln + p, g_coder_goal, gn); p += gn;
        ln[p] = 0;
        body_at(2, 3, ln, SCREEN_W - 4);
    }
    /* Status row */
    {
        char ln[80];
        int p = 0;
        p = sapp(ln, p, "Target: ");
        p = sapp(ln, p, CODER_TARGET_NAME[g_coder_target]);
        while (p < 24) ln[p++] = ' ';
        p = sapp(ln, p, "Iter: ");
        p += utoa((unsigned)g_coder_iter, ln + p);
        while (p < 36) ln[p++] = ' ';
        p = sapp(ln, p, "Status: ");
        if (status_msg) p = sapp(ln, p, status_msg);
        ln[p] = 0;
        body_at(2, 4, ln, SCREEN_W - 4);
    }
    /* Draft (last few lines) */
    body_at(2, 6, "[draft]", SCREEN_W - 4);
    {
        int row = 7;
        int line_start = 0;
        int n_lines = 0;
        for (int i = 0; i <= g_coder_draft_len && row < 16; i++) {
            if (i == g_coder_draft_len || g_coder_draft[i] == '\n') {
                int len = i - line_start;
                if (len > SCREEN_W - 4) len = SCREEN_W - 4;
                char tmp[80];
                mcpy(tmp, g_coder_draft + line_start, len);
                tmp[len] = 0;
                body_at(2, row++, tmp, SCREEN_W - 4);
                line_start = i + 1;
                n_lines++;
            }
        }
        if (n_lines == 0) body_at(2, 7, "  (no draft yet)", SCREEN_W - 4);
    }
    /* Error */
    body_at(2, 16, "[compile output]", SCREEN_W - 4);
    {
        int row = 17;
        int line_start = 0;
        int n_lines = 0;
        for (int i = 0; i <= g_coder_err_len && row < 21; i++) {
            if (i == g_coder_err_len || g_coder_err[i] == '\n') {
                int len = i - line_start;
                if (len > SCREEN_W - 4) len = SCREEN_W - 4;
                char tmp[80];
                mcpy(tmp, g_coder_err + line_start, len);
                tmp[len] = 0;
                body_at(2, row++, tmp, SCREEN_W - 4);
                line_start = i + 1;
                n_lines++;
            }
        }
        if (n_lines == 0) body_at(2, 17, "  (none)", SCREEN_W - 4);
    }
    /* Banks summary + coder.db row count */
    {
        char ln[80];
        int p = 0;
        p = sapp(ln, p, "Banks: ");
        for (int b = 0; b < BANK_COUNT; b++) {
            ln[p++] = '[';
            ln[p++] = "PRLS"[b];
            ln[p++] = ' ';
            p += utoa((unsigned)g_bank_len[b], ln + p);
            ln[p++] = '/';
            p += utoa((unsigned)BANK_BYTES, ln + p);
            ln[p++] = ']';
            ln[p++] = ' ';
        }
        p = sapp(ln, p, " db: ");
        p += utoa((unsigned)tdb_count(), ln + p);
        p = sapp(ln, p, "/");
        p += utoa((unsigned)TDB_MAX_CELLS, ln + p);
        ln[p] = 0;
        body_at(2, 22, ln, SCREEN_W - 4);
    }
    status("e=goal ENT=ask a=auto x=exec t=target 1-4=bank r=log s=save q=quit");
    fbflush();
}

static int coder_input_goal(void) {
    /* Single-line entry on row 3. */
    while (1) {
        coder_paint("editing goal — ENTER to confirm");
        cup(8, 3);
        sgrbgfg(15, 0);
        fbw(g_coder_goal, g_coder_goal_len);
        fbs(" ");
        fbflush();
        unsigned char k[16];
        int n = read_key(k, sizeof k);
        if (n <= 0) continue;
        if (k[0] == '\r' || k[0] == '\n') return 0;
        if (k[0] == 0x1b) return -1;
        if ((k[0] == 0x7f || k[0] == 8) && g_coder_goal_len > 0) {
            g_coder_goal_len--;
            continue;
        }
        if (k[0] >= 32 && k[0] < 127 && g_coder_goal_len < CODER_GOAL_CAP - 1) {
            g_coder_goal[g_coder_goal_len++] = (char)k[0];
            g_coder_goal[g_coder_goal_len] = 0;
        }
    }
}

static int run_coder(int argc, char **argv) {
    (void)argc; (void)argv;
    bank_load_all();
    tdb_open();
    /* Restore saved state if present. */
    {
        int fd = (int)op("coder_state.bin", O_RDONLY, 0);
        if (fd >= 0) {
            char hdr[8];
            int hn = (int)rd(fd, hdr, 4);
            if (hn == 4) {
                g_coder_target = hdr[0] & 3;
                int gn = (int)((unsigned char)hdr[1] |
                               ((unsigned char)hdr[2] << 8));
                if (gn > CODER_GOAL_CAP - 1) gn = CODER_GOAL_CAP - 1;
                int rn = (int)rd(fd, g_coder_goal, gn);
                if (rn > 0) g_coder_goal_len = rn;
                g_coder_goal[g_coder_goal_len] = 0;
            }
            cl(fd);
        }
    }
    current_ms = &ms_shell;
    term_raw();
    coder_paint("ready");
    while (1) {
        unsigned char k[16];
        int n = read_key(k, sizeof k);
        if (n < 0) continue;
        if (n == 0) break;          /* tty closed / pipe EOF */
        if (k[0] == 'q') break;
        if (k[0] == 'e') { coder_input_goal(); coder_paint("ready"); continue; }
        if (k[0] == 't') {
            g_coder_target = (g_coder_target + 1) % 3;
            coder_paint("target changed");
            continue;
        }
        if (k[0] >= '1' && k[0] <= '4') {
            int b = k[0] - '1';
            term_cooked();
            run_prompt_edit_bank(b);
            term_raw();
            coder_paint("bank edited");
            continue;
        }
        if (k[0] == 'r') {
            coder_log_recent();
            bank_save(BANK_RECENT);
            coder_paint("logged to recent");
            continue;
        }
        if (k[0] == 'x') {
            /* Execute the latest /tmp/coder_attempt and show its
             * stdout+stderr on a dedicated full-body panel — the
             * compile-output strip is only 4 lines tall, so longer
             * programs (10-line counters, multi-step demos) had
             * their output truncated to a single visible row. */
            int probe = (int)op("/tmp/coder_attempt", O_RDONLY, 0);
            if (probe < 0) {
                coder_paint("no binary — press ENTER to build first");
                continue;
            }
            cl(probe);
            coder_paint("running /tmp/coder_attempt …");
            int exit_code = coder_runtest();

            paint_desktop();
            {
                char title[64];
                int tp = sapp(title, 0, "coder · runtime · exit=");
                tp += utoa((unsigned)exit_code, title + tp);
                title[tp] = 0;
                chrome(title);
            }
            body_clear();

            static char rb[8192];
            int rn = 0;
            int rfd = (int)op("/tmp/coder_run.txt", O_RDONLY, 0);
            if (rfd >= 0) {
                rn = (int)rd(rfd, rb, sizeof rb - 1);
                if (rn < 0) rn = 0;
                cl(rfd);
            }
            rb[rn] = 0;

            int last_row = SCREEN_H - 4;   /* leave status bar room */
            if (rn == 0) {
                body_at(2, 4, "(no output captured)", SCREEN_W - 4);
            } else {
                int row = 3;
                int line_start = 0;
                int extra = 0;
                for (int i = 0; i <= rn; i++) {
                    if (i == rn || rb[i] == '\n') {
                        int len = i - line_start;
                        if (len > SCREEN_W - 4) len = SCREEN_W - 4;
                        if (row < last_row) {
                            char tmp[256];
                            int tl = len;
                            if (tl > (int)sizeof tmp - 1) tl = sizeof tmp - 1;
                            mcpy(tmp, rb + line_start, tl);
                            tmp[tl] = 0;
                            body_at(2, row++, tmp, SCREEN_W - 4);
                        } else {
                            extra++;
                        }
                        line_start = i + 1;
                    }
                }
                if (extra > 0) {
                    char ln[80];
                    int q = sapp(ln, 0, "(+");
                    q += utoa((unsigned)extra, ln + q);
                    q = sapp(ln, q, " more lines — buffer is 8 KB)");
                    ln[q] = 0;
                    body_at(2, last_row, ln, SCREEN_W - 4);
                }
            }
            status(" press any key to return ");
            fbflush();

            for (;;) {
                unsigned char kk[8];
                int kn = read_key(kk, sizeof kk);
                if (kn > 0) break;
            }

            char st[64];
            int p = sapp(st, 0, "ran (exit=");
            p += utoa((unsigned)exit_code, st + p);
            st[p++] = ')'; st[p] = 0;
            coder_paint(st);
            continue;
        }
        if (k[0] == 's') {
            int fd = (int)op("coder_state.bin",
                             O_WRONLY | O_CREAT | O_TRUNC, 0644);
            if (fd >= 0) {
                char hdr[4];
                hdr[0] = (char)g_coder_target;
                hdr[1] = (char)(g_coder_goal_len & 0xff);
                hdr[2] = (char)((g_coder_goal_len >> 8) & 0xff);
                hdr[3] = 0;
                wr(fd, hdr, 4);
                wr(fd, g_coder_goal, (size_t)g_coder_goal_len);
                cl(fd);
            }
            coder_paint("state saved");
            continue;
        }
        if (k[0] == '\r' || k[0] == '\n') {
            if (g_coder_goal_len == 0) {
                coder_paint("(no goal — press e to enter one)");
                continue;
            }
            g_coder_iter++;
            coder_paint("calling LLM…");
            int rc = coder_iterate();
            if (rc != 0) coder_log_recent();
            coder_paint(rc == 0 ? "✓ target met" : "× failed — see compile output");
            continue;
        }
        if (k[0] == 'a') {
            if (g_coder_goal_len == 0) {
                coder_paint("(no goal — press e to enter one)");
                continue;
            }
            int local_iter = 0;
            while (local_iter < CODER_MAX_ITERS) {
                g_coder_iter++; local_iter++;
                coder_paint("auto: calling LLM…");
                int rc = coder_iterate();
                if (rc == 0) {
                    coder_paint("auto: ✓ target met");
                    break;
                }
                coder_log_recent();
                coder_paint("auto: × failed, retrying…");
            }
            if (local_iter >= CODER_MAX_ITERS) {
                coder_paint("auto: gave up after max iters");
            }
            continue;
        }
    }
    /* Persist all banks + flush the DB on exit. */
    for (int b = 0; b < BANK_COUNT; b++) bank_save(b);
    tdb_close();
    term_cooked();
    return 0;
}


/* ── soul: 25 K-parameter int8 transformer ──────────────────
 *
 * Port of gizmo64k/soulplayer-c64.  Two transformer layers,
 * 4 attention heads × 8 dims, 32-d embeddings, 64-unit FFN,
 * 64-token context window (PE has 64 rows in soul.bin), 128-
 * token vocab.  Same arithmetic as the upstream's numerics.py.
 *
 * Two extras over a vanilla port:
 *   1. The 24 per-tensor shifts are *runtime mutable* via a
 *      24-byte delta array (g_sl_dlt) loaded from
 *      coder_shifts.bin at startup, so a soulgen-style GA can
 *      tune the soul without recompiling.
 *   2. A `g` hotkey inside `soul` runs the GA in-place: pop=16,
 *      gens=20, fitness from coder.db rows tagged bank==4 (with
 *      a built-in fallback test set if the DB is empty).
 *      Winning shifts persist to coder_shifts.bin on save.
 *
 * Coder hook: when ask_call_curl fails (timeout, 429, etc.),
 * the coder calls sl_generate() instead and surfaces the
 * soul's reply where the LLM's response would have gone. */

#define SL_VS         128
#define SL_ED          32
#define SL_NH           4
#define SL_HD           8
#define SL_FF          64
#define SL_NL_LAY       2
#define SL_CTX         64
#define SL_ACT_SHIFT    8
#define SL_N_SHIFTS    24

#define SL_PAD 0
#define SL_SEP 1
#define SL_UNK 2
#define SL_END 3

/* coder.db rows tagged with this bank value are mined as soul-
 * evolution test cases (body = "prompt\nexpected"). */
#define BANK_SOUL_TESTS 4

typedef struct { const signed char *q; int rows, cols; int base_s; int idx; } SLW8;
typedef struct { const short        *q; int rows, cols; int base_s; int idx; } SLW16;

static SLW8  SL_M_te, SL_M_pe, SL_M_norm, SL_M_out;
typedef struct {
    SLW8  n1, q, k, v, proj, n2, fc1_w, fc2_w;
    SLW16 fc1_b, fc2_b;
} SLLayer;
static SLLayer SL_Lyr[SL_NL_LAY];
static int     SL_off;
static int     SL_loaded = 0;

/* 24 signed-int8 shift deltas, applied on top of each tensor's
 * baseline shift.  All-zeros = use the soul as trained.  Persisted
 * to coder_shifts.bin between sessions. */
static signed char g_sl_dlt[SL_N_SHIFTS];
static int         g_sl_idx_seq;

static int  sl_u8 (void) { return SOUL_BIN_DATA[SL_off++]; }
static int  sl_u16(void) {
    int lo = SOUL_BIN_DATA[SL_off++];
    int hi = SOUL_BIN_DATA[SL_off++];
    return lo | (hi << 8);
}
static int  sl_i8 (void) {
    int v = SOUL_BIN_DATA[SL_off++];
    return v >= 128 ? v - 256 : v;
}

static void sl_load_w8 (SLW8  *m, int rows, int cols) {
    sl_u8(); sl_u16(); sl_u16();
    int s = sl_i8();
    m->q = (const signed char *)(SOUL_BIN_DATA + SL_off);
    m->base_s = s;
    m->rows = rows; m->cols = cols;
    m->idx = g_sl_idx_seq++;
    SL_off += rows * cols;
}
static void sl_load_w16(SLW16 *m, int n) {
    sl_u8(); sl_u16(); sl_u16();
    int s = sl_i8();
    m->q = (const short *)(SOUL_BIN_DATA + SL_off);
    m->base_s = s;
    m->rows = n; m->cols = 1;
    m->idx = g_sl_idx_seq++;
    SL_off += n * 2;
}

static void sl_open(void) {
    if (SL_loaded) return;
    SL_off = 0;
    g_sl_idx_seq = 0;
    sl_load_w8(&SL_M_te, SL_VS, SL_ED);
    sl_load_w8(&SL_M_pe, SL_CTX, SL_ED);
    for (int L = 0; L < SL_NL_LAY; L++) {
        SLLayer *ly = &SL_Lyr[L];
        sl_load_w8 (&ly->n1,    SL_ED, 1);
        sl_load_w8 (&ly->q,     SL_ED, SL_ED);
        sl_load_w8 (&ly->k,     SL_ED, SL_ED);
        sl_load_w8 (&ly->v,     SL_ED, SL_ED);
        sl_load_w8 (&ly->proj,  SL_ED, SL_ED);
        sl_load_w8 (&ly->n2,    SL_ED, 1);
        sl_load_w8 (&ly->fc1_w, SL_FF, SL_ED);
        sl_load_w16(&ly->fc1_b, SL_FF);
        sl_load_w8 (&ly->fc2_w, SL_ED, SL_FF);
        sl_load_w16(&ly->fc2_b, SL_ED);
    }
    sl_load_w8(&SL_M_norm, SL_ED, 1);
    sl_load_w8(&SL_M_out,  SL_VS, SL_ED);
    SL_loaded = 1;
}

/* Load shift deltas from coder_shifts.bin (if present). */
static void sl_dlt_load(void) {
    for (int i = 0; i < SL_N_SHIFTS; i++) g_sl_dlt[i] = 0;
    int fd = (int)op("coder_shifts.bin", O_RDONLY, 0);
    if (fd < 0) return;
    rd(fd, g_sl_dlt, SL_N_SHIFTS);
    cl(fd);
}
static void sl_dlt_save(void) {
    int fd = (int)op("coder_shifts.bin",
                     O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return;
    wr(fd, g_sl_dlt, SL_N_SHIFTS);
    cl(fd);
}
static int sl_eff_shift(const SLW8 *m) {
    int s = m->base_s + (int)g_sl_dlt[m->idx];
    if (s < -128) s = -128;
    if (s >  127) s =  127;
    return s;
}
static int sl_eff_shift_w16(const SLW16 *m) {
    int s = m->base_s + (int)g_sl_dlt[m->idx];
    if (s < -128) s = -128;
    if (s >  127) s =  127;
    return s;
}

/* arithmetic */
static int sl_sat16(int v) {
    if (v >  32767) return  32767;
    if (v < -32768) return -32768;
    return v;
}
static int sl_sar32(int v, int sh) {
    if (sh >= 0) return v >> sh;
    return v << (-sh);
}
static unsigned sl_isqrt_u32(unsigned v) {
    if (v == 0) return 0;
    unsigned r = 0, b = 1u << 30;
    while (b > v) b >>= 2;
    while (b) {
        if (v >= r + b) { v -= r + b; r = (r >> 1) + b; }
        else r >>= 1;
        b >>= 2;
    }
    return r;
}

static const unsigned char SL_EXP_LUT[128] = {
    255, 240, 225, 212, 199, 187, 175, 165,
    155, 146, 137, 128, 121, 113, 107, 100,
     94,  88,  83,  78,  73,  69,  64,  60,
     57,  53,  50,  47,  44,  41,  39,  36,
     34,  32,  30,  28,  26,  25,  23,  22,
     21,  19,  18,  17,  16,  15,  14,  13,
     12,  12,  11,  10,  10,   9,   8,   8,
      8,   7,   7,   6,   6,   5,   5,   5,
      5,   4,   4,   4,   4,   3,   3,   3,
      3,   3,   3,   2,   2,   2,   2,   2,
      2,   2,   2,   2,   2,   1,   1,   1,
      1,   1,   1,   1,   1,   1,   1,   1,
      1,   1,   1,   1,   1,   1,   1,   1,
      1,   1,   1,   1,   1,   1,   1,   1,
      1,   1,   1,   1,   1,   1,   1,   1,
      1,   1,   1,   1,   1,   1,   1,   0,
};

static int sl_deshift(int v, int s) {
    int diff = SL_ACT_SHIFT - s;
    if (diff >= 0) return v << diff;
    return v >> (-diff);
}

static void sl_matvec(const SLW8 *Wm, const short *x, int rows, int cols,
                      int post_shift, short *out) {
    int total = sl_eff_shift(Wm) + post_shift;
    for (int r = 0; r < rows; r++) {
        const signed char *row = Wm->q + r * cols;
        int acc = 0;
        for (int c = 0; c < cols; c++) acc += (int)row[c] * (int)x[c];
        out[r] = (short)sl_sat16(sl_sar32(acc, total));
    }
}
static void sl_matvec_b(const SLW8 *Wm, const SLW16 *bm, const short *x,
                        int rows, int cols, int post_shift, short *out) {
    int total = sl_eff_shift(Wm) + post_shift;
    (void)bm;
    int s_b __attribute__((unused)) = sl_eff_shift_w16(bm);
    for (int r = 0; r < rows; r++) {
        const signed char *row = Wm->q + r * cols;
        int acc = bm->q[r];
        for (int c = 0; c < cols; c++) acc += (int)row[c] * (int)x[c];
        out[r] = (short)sl_sat16(sl_sar32(acc, total));
    }
}
static void sl_rms_norm(const short *x, const SLW8 *gain, int n, short *out) {
    int sum_sq = 0;
    for (int i = 0; i < n; i++) {
        int xs = ((int)x[i]) >> 4;
        sum_sq += xs * xs;
    }
    int mean_sq = sum_sq / n;
    if (mean_sq < 1) mean_sq = 1;
    unsigned rms = sl_isqrt_u32((unsigned)mean_sq);
    if (rms < 1) rms = 1;
    unsigned inv = (1u << 19) / rms;
    if (inv > 32767) inv = 32767;
    int s_g = sl_eff_shift(gain);
    for (int i = 0; i < n; i++) {
        int y_raw = (((int)x[i]) * (int)inv) >> 15;
        int y = (y_raw * (int)gain->q[i]) >> s_g;
        out[i] = (short)sl_sat16(y);
    }
}
static void sl_softmax_ws(const int *scores, int n,
                          const short *vals, int hd, short *out) {
    int sf[SL_CTX];
    int max_sf = -2000000000;
    for (int i = 0; i < n; i++) {
        sf[i] = scores[i] >> 14;
        if (sf[i] > max_sf) max_sf = sf[i];
    }
    unsigned char w[SL_CTX];
    int w_sum = 0;
    for (int i = 0; i < n; i++) {
        int d = max_sf - sf[i];
        if (d < 0) d = 0;
        if (d > 127) d = 127;
        w[i] = SL_EXP_LUT[d];
        w_sum += w[i];
    }
    if (w_sum == 0) w_sum = 1;
    for (int j = 0; j < hd; j++) {
        int acc = 0;
        for (int i = 0; i < n; i++) acc += (int)w[i] * (int)vals[i * hd + j];
        out[j] = (short)sl_sat16(acc / w_sum);
    }
}

static short SL_h    [SL_CTX][SL_ED];
static short SL_qall [SL_CTX][SL_ED];
static short SL_kall [SL_CTX][SL_ED];
static short SL_vall [SL_CTX][SL_ED];
static short SL_attn [SL_CTX][SL_ED];

static int sl_forward(const int *ids, int T) {
    int s_te = sl_eff_shift(&SL_M_te);
    int s_pe = sl_eff_shift(&SL_M_pe);
    for (int t = 0; t < T; t++) {
        int tok = ids[t];
        for (int d = 0; d < SL_ED; d++) {
            int v = sl_deshift(SL_M_te.q[tok * SL_ED + d], s_te) +
                    sl_deshift(SL_M_pe.q[t   * SL_ED + d], s_pe);
            SL_h[t][d] = (short)sl_sat16(v);
        }
    }
    for (int L = 0; L < SL_NL_LAY; L++) {
        SLLayer *ly = &SL_Lyr[L];
        for (int t = 0; t < T; t++) {
            short xn[SL_ED];
            sl_rms_norm(SL_h[t], &ly->n1, SL_ED, xn);
            sl_matvec(&ly->q, xn, SL_ED, SL_ED, 1, SL_qall[t]);
            sl_matvec(&ly->k, xn, SL_ED, SL_ED, 1, SL_kall[t]);
            sl_matvec(&ly->v, xn, SL_ED, SL_ED, 1, SL_vall[t]);
        }
        for (int tq = 0; tq < T; tq++) {
            for (int head = 0; head < SL_NH; head++) {
                int off = head * SL_HD;
                int n_keys = tq + 1;
                int scores[SL_CTX];
                short v_head[SL_CTX * SL_HD];
                for (int tk = 0; tk < n_keys; tk++) {
                    int s = 0;
                    for (int d = 0; d < SL_HD; d++)
                        s += (int)SL_qall[tq][off + d] *
                             (int)SL_kall[tk][off + d];
                    scores[tk] = s;
                    for (int d = 0; d < SL_HD; d++)
                        v_head[tk * SL_HD + d] = SL_vall[tk][off + d];
                }
                short out_head[SL_HD];
                sl_softmax_ws(scores, n_keys, v_head, SL_HD, out_head);
                for (int d = 0; d < SL_HD; d++)
                    SL_attn[tq][off + d] = out_head[d];
            }
        }
        for (int t = 0; t < T; t++) {
            short att_proj[SL_ED];
            sl_matvec(&ly->proj, SL_attn[t], SL_ED, SL_ED, 1, att_proj);
            for (int d = 0; d < SL_ED; d++)
                SL_h[t][d] = (short)sl_sat16((int)SL_h[t][d] + (int)att_proj[d]);
        }
        for (int t = 0; t < T; t++) {
            short yn[SL_ED], z[SL_FF], w2[SL_ED];
            sl_rms_norm(SL_h[t], &ly->n2, SL_ED, yn);
            sl_matvec_b(&ly->fc1_w, &ly->fc1_b, yn, SL_FF, SL_ED, 1, z);
            for (int i = 0; i < SL_FF; i++) if (z[i] < 0) z[i] = 0;
            sl_matvec_b(&ly->fc2_w, &ly->fc2_b, z, SL_ED, SL_FF, 1, w2);
            for (int d = 0; d < SL_ED; d++)
                SL_h[t][d] = (short)sl_sat16((int)SL_h[t][d] + (int)w2[d]);
        }
    }
    short y[SL_ED], logits[SL_VS];
    sl_rms_norm(SL_h[T - 1], &SL_M_norm, SL_ED, y);
    sl_matvec(&SL_M_out, y, SL_VS, SL_ED, 0, logits);
    int best = 4, best_v = logits[4];
    for (int i = 5; i < SL_VS; i++) {
        if (logits[i] > best_v) { best_v = logits[i]; best = i; }
    }
    return best;
}

static int sl_vocab_lookup(const char *s, int len) {
    for (int i = 0; i < SL_VS; i++) {
        if (VOCAB_LEN_TBL[i] != len) continue;
        const unsigned char *str = VOCAB_STR_BLOB + VOCAB_OFFSETS[i];
        int eq = 1;
        for (int j = 0; j < len; j++) {
            if (str[j] != (unsigned char)s[j]) { eq = 0; break; }
        }
        if (eq) return i;
    }
    return -1;
}
static int sl_encode(const char *text, int *ids, int cap) {
    int n = 0;
    for (int i = 0; text[i] && n < cap; i++) {
        char c = text[i];
        if (c >= 'A' && c <= 'Z') c = (char)(c + 32);
        int id = sl_vocab_lookup(&c, 1);
        if (id >= 0) ids[n++] = id;
    }
    for (int m = 0; m < MERGES_N; m++) {
        int a = MERGES_AB[m][0], b = MERGES_AB[m][1], id = MERGES_ID[m];
        int w = 0;
        for (int r = 0; r < n; ) {
            if (r + 1 < n && ids[r] == a && ids[r+1] == b) {
                ids[w++] = id; r += 2;
            } else {
                ids[w++] = ids[r++];
            }
        }
        n = w;
    }
    return n;
}

/* One-shot generation — used by ask as a fallback when curl fails,
 * by the GA fitness function, and by the soul's REPL. */
static int sl_generate(const char *text, char *out, int out_cap, int max_new) {
    sl_open();
    sl_dlt_load();
    int ids[SL_CTX];
    int n = 0;
    ids[n++] = SL_SEP;
    int body[SL_CTX];
    int bn = sl_encode(text, body, SL_CTX - 2);
    for (int i = 0; i < bn && n < SL_CTX - 1; i++) ids[n++] = body[i];
    ids[n++] = SL_SEP;
    int o = 0;
    for (int gen = 0; gen < max_new && n < SL_CTX; gen++) {
        int tok = sl_forward(ids, n);
        if (tok == SL_PAD || tok == SL_SEP || tok == SL_END) break;
        int len = VOCAB_LEN_TBL[tok];
        if (o + len >= out_cap - 1) break;
        const unsigned char *str = VOCAB_STR_BLOB + VOCAB_OFFSETS[tok];
        for (int i = 0; i < len; i++) out[o++] = (char)str[i];
        ids[n++] = tok;
    }
    out[o] = 0;
    return o;
}


/* ── soulgen: in-process GA over per-tensor shifts ──────────
 *
 * Genome = 24 signed-int8 deltas (mirrors g_sl_dlt[] layout).
 * Mutation = ±1 to a random index, clamped to ±4.  Crossover =
 * single-cut blend.  Tournament-2 selection, breed bottom half.
 * Fitness = sum of longest-common-substring lengths between the
 * soul's reply and the expected substring across a test set.
 *
 * Test source priority:
 *   1. coder.db rows tagged bank == BANK_SOUL_TESTS, body =
 *      "prompt\nexpected"
 *   2. Built-in fallback test set (below) if the DB is empty.
 *
 * Press 't' inside the soul UI to add a new (prompt, expected)
 * row to the DB; tests survive across sessions because coder.db
 * does. */

typedef struct { const char *prompt; const char *expected; } SLTest;
static const SLTest SL_BUILTIN_TESTS[] = {
    { "hi",                "welcome" },
    { "hello",             "ready" },
    { "what is velour",    "meta" },
    { "what is office",    "under" },
    { "what is xpg",       "hexca" },
    { "who are you",       "soul" },
    { "i'm sad",           "soldering" },
    { "tell me something", "tiny" },
    { "give me advice",    "commit" },
    { "i'm coding",        "break" },
    { "my code crashed",   "stack" },
    { "bye",               "iron" },
};
#define SL_BUILTIN_N (int)(sizeof SL_BUILTIN_TESTS / sizeof SL_BUILTIN_TESTS[0])

#define SL_GA_MAX_TESTS 32
static char  SL_test_p[SL_GA_MAX_TESTS][80];
static char  SL_test_e[SL_GA_MAX_TESTS][80];
static int   SL_n_tests;

static void sl_load_tests(void) {
    SL_n_tests = 0;
    /* Mine coder.db for rows tagged BANK_SOUL_TESTS. */
    tdb_open();
    unsigned int n = tdb_count();
    for (unsigned int i = 0; i < n && SL_n_tests < SL_GA_MAX_TESTS; i++) {
        TdbRow r;
        if (tdb_read(i, &r) != 0) continue;
        if (r.bank != BANK_SOUL_TESTS) continue;
        /* split body on first newline */
        int nl = -1;
        for (int j = 0; j < r.body_len; j++) {
            if (r.body[j] == '\n') { nl = j; break; }
        }
        if (nl < 0) continue;
        int pn = nl;
        if (pn > (int)sizeof SL_test_p[0] - 1) pn = sizeof SL_test_p[0] - 1;
        mcpy(SL_test_p[SL_n_tests], r.body, pn);
        SL_test_p[SL_n_tests][pn] = 0;
        int en = r.body_len - nl - 1;
        if (en > (int)sizeof SL_test_e[0] - 1) en = sizeof SL_test_e[0] - 1;
        if (en > 0) mcpy(SL_test_e[SL_n_tests], r.body + nl + 1, en);
        SL_test_e[SL_n_tests][en > 0 ? en : 0] = 0;
        SL_n_tests++;
    }
    /* Fallback: built-in tests if the DB has nothing. */
    if (SL_n_tests == 0) {
        for (int i = 0; i < SL_BUILTIN_N; i++) {
            int p = 0;
            const char *pp = SL_BUILTIN_TESTS[i].prompt;
            while (pp[p] && p < (int)sizeof SL_test_p[0] - 1) {
                SL_test_p[i][p] = pp[p]; p++;
            }
            SL_test_p[i][p] = 0;
            int e = 0;
            const char *ee = SL_BUILTIN_TESTS[i].expected;
            while (ee[e] && e < (int)sizeof SL_test_e[0] - 1) {
                SL_test_e[i][e] = ee[e]; e++;
            }
            SL_test_e[i][e] = 0;
        }
        SL_n_tests = SL_BUILTIN_N;
    }
}

/* Save a (prompt, expected) row into coder.db with bank=4 so the
 * GA picks it up next time. */
static void sl_save_test(const char *prompt, const char *expected) {
    TdbRow r;
    r.bank = BANK_SOUL_TESTS;
    r.timestamp = (unsigned int)time_();
    r.tag_bitmap = tdb_tag_bitmap(prompt, slen((char *)prompt)) |
                   tdb_tag_bitmap(expected, slen((char *)expected));
    int p = 0;
    int pl = slen((char *)prompt);
    if (pl > 80) pl = 80;
    mcpy(r.body, prompt, pl); p += pl;
    r.body[p++] = '\n';
    int el = slen((char *)expected);
    if (p + el > TDB_BODY_SIZE) el = TDB_BODY_SIZE - p;
    mcpy(r.body + p, expected, el); p += el;
    r.body_len = p;
    tdb_insert(&r);
}

static int sl_substr_overlap(const char *expected, const char *actual) {
    int el = slen((char *)expected), al = slen((char *)actual);
    if (el == 0 || al == 0) return 0;
    int best = 0;
    for (int len = el; len >= 1 && len > best; len--) {
        for (int i = 0; i + len <= el; i++) {
            for (int j = 0; j + len <= al; j++) {
                int k = 0;
                while (k < len) {
                    char a = expected[i+k], b = actual[j+k];
                    if (a >= 'A' && a <= 'Z') a += 32;
                    if (b >= 'A' && b <= 'Z') b += 32;
                    if (a != b) break;
                    k++;
                }
                if (k == len) { if (len > best) best = len; goto found; }
            }
        }
        found: ;
    }
    return best;
}

static int sl_fitness(int max_new) {
    int score = 0;
    for (int i = 0; i < SL_n_tests; i++) {
        char actual[256];
        sl_generate(SL_test_p[i], actual, sizeof actual, max_new);
        score += sl_substr_overlap(SL_test_e[i], actual);
    }
    return score;
}

#define SL_POP 16
typedef struct { signed char d[SL_N_SHIFTS]; int score; } SLIndiv;

static unsigned SL_rng = 1;
static unsigned sl_rnd(void) {
    SL_rng ^= SL_rng << 13; SL_rng ^= SL_rng >> 17; SL_rng ^= SL_rng << 5;
    return SL_rng;
}
static int sl_rnd_n(int n) { return (int)(sl_rnd() % (unsigned)n); }
static void sl_apply(const SLIndiv *g) {
    for (int i = 0; i < SL_N_SHIFTS; i++) g_sl_dlt[i] = g->d[i];
}
static void sl_mutate(SLIndiv *g, int hits) {
    for (int h = 0; h < hits; h++) {
        int i = sl_rnd_n(SL_N_SHIFTS);
        int delta = (int)(sl_rnd() % 3) - 1;
        int v = g->d[i] + delta;
        if (v < -4) v = -4; if (v > 4) v = 4;
        g->d[i] = (signed char)v;
    }
}
static void sl_xover(const SLIndiv *a, const SLIndiv *b, SLIndiv *out) {
    int cut = sl_rnd_n(SL_N_SHIFTS);
    for (int i = 0; i < SL_N_SHIFTS; i++)
        out->d[i] = (i < cut) ? a->d[i] : b->d[i];
}
static int sl_cmp_desc(const SLIndiv *a, const SLIndiv *b) {
    return b->score - a->score;
}

/* GA loop with per-generation UI updates.  `gens` controls effort.
 * Returns the final best score; updates g_sl_dlt + saves to disk. */
static int sl_evolve(int gens, void (*on_gen)(int g, int best, const SLIndiv *bi)) {
    sl_open(); sl_dlt_load(); sl_load_tests();
    SLIndiv P[SL_POP], N[SL_POP], best;
    /* Seed: first individual = current g_sl_dlt[], rest = mutated copies. */
    for (int i = 0; i < SL_N_SHIFTS; i++) P[0].d[i] = g_sl_dlt[i];
    P[0].score = 0;
    for (int i = 1; i < SL_POP; i++) { P[i] = P[0]; sl_mutate(&P[i], 2); }
    sl_apply(&P[0]);
    P[0].score = sl_fitness(16);
    best = P[0];

    for (int g = 0; g < gens; g++) {
        for (int i = 0; i < SL_POP; i++) {
            sl_apply(&P[i]);
            P[i].score = sl_fitness(16);
            if (P[i].score > best.score) best = P[i];
        }
        if (on_gen) on_gen(g, best.score, &best);
        /* Tournament + breed (insertion-sort by score desc; SL_POP=16 is small). */
        for (int i = 1; i < SL_POP; i++) {
            SLIndiv tmp = P[i]; int j = i;
            while (j > 0 && sl_cmp_desc(&P[j-1], &tmp) > 0) { P[j] = P[j-1]; j--; }
            P[j] = tmp;
        }
        int keep = SL_POP / 2;
        for (int i = 0; i < keep; i++) N[i] = P[i];
        for (int i = keep; i < SL_POP; i++) {
            int a = sl_rnd_n(keep), b = sl_rnd_n(keep);
            int pa = P[a].score >= P[b].score ? a : b;
            int c = sl_rnd_n(keep), d = sl_rnd_n(keep);
            int pb = P[c].score >= P[d].score ? c : d;
            sl_xover(&P[pa], &P[pb], &N[i]);
            sl_mutate(&N[i], 1 + sl_rnd_n(2));
        }
        for (int i = 0; i < SL_POP; i++) P[i] = N[i];
    }
    sl_apply(&best);
    sl_dlt_save();
    return best.score;
}


/* ── soul UI: chat + evolve modes ───────────────────────────── */

static void sl_paint_chat_chrome(int row_seed) {
    paint_desktop();
    chrome("Soul Chat (25 K params · evolved shifts loaded)");
    body_clear();
    body_at(2, 3, "  .---------.", SCREEN_W - 4);
    body_at(2, 4, " |  O     O  |", SCREEN_W - 4);
    body_at(2, 5, " |     V     |", SCREEN_W - 4);
    body_at(2, 6, " |..|-----|..|", SCREEN_W - 4);
    body_at(2, 8, "Type a message + ENTER.  g=evolve, t=add test, q=quit.",
            SCREEN_W - 4);
    {
        char ln[80]; int p = 0;
        p = sapp(ln, p, "shifts: ");
        int sum = 0;
        for (int i = 0; i < SL_N_SHIFTS; i++) {
            int v = g_sl_dlt[i]; if (v < 0) v = -v; sum += v;
        }
        p += utoa((unsigned)sum, ln + p);
        p = sapp(ln, p, " bits from baseline");
        ln[p] = 0;
        body_at(2, 9, ln, SCREEN_W - 4);
    }
    status("soul: 64-token context · int8 weights");
    fbflush();
    (void)row_seed;
}

static void sl_evolve_paint(int g, int best, const SLIndiv *bi) {
    char ln[80]; int p = 0;
    p = sapp(ln, p, "gen ");
    p += utoa((unsigned)g, ln + p);
    while (p < 8) ln[p++] = ' ';
    p = sapp(ln, p, "best score: ");
    p += utoa((unsigned)best, ln + p);
    p = sapp(ln, p, "  delta sum: ");
    int sum = 0;
    for (int i = 0; i < SL_N_SHIFTS; i++) {
        int v = bi->d[i]; if (v < 0) v = -v; sum += v;
    }
    p += utoa((unsigned)sum, ln + p);
    ln[p] = 0;
    int row = 6 + (g % 14);
    body_at(2, row, ln, SCREEN_W - 4);
    fbflush();
}

static int run_soul(int argc, char **argv) {
    (void)argc; (void)argv;
    sl_open();
    sl_dlt_load();
    /* Capture tty so term_cooked has something real to restore.  Same
     * fix as officesoul — without this the sub-app exits immediately
     * on stdin reads when the terminal hadn't been touched yet. */
    io(0, TCGETS, &term_orig);
    {
        struct ti t = term_orig;
        t.lflag |= ICANON | ECHO;
        t.iflag |= ICRNL;
        io(0, TCSETS, &t);
    }
    sl_paint_chat_chrome(11);

    int row = 11;
    char line[256];
    while (1) {
        cup(2, row);
        sgrbgfg(COL_BAR_BG, COL_BAR_FG);
        fbs("YOU> ");
        fbflush();
        int li = 0;
        while (li < (int)sizeof line - 1) {
            unsigned char ch[1];
            int n = (int)rd(0, ch, 1);
            if (n <= 0) { line[li] = 0; goto sl_quit; }
            if (ch[0] == '\n' || ch[0] == '\r') break;
            line[li++] = (char)ch[0];
        }
        line[li] = 0;
        if (li == 0) continue;
        if (li == 1 && (line[0] == 'q' || line[0] == 'Q')) break;

        if (li == 1 && (line[0] == 'g' || line[0] == 'G')) {
            /* Evolve mode: GA with live UI. */
            paint_desktop();
            chrome("Soul · evolving");
            body_clear();
            body_at(2, 3, "Running GA over per-tensor shifts...", SCREEN_W - 4);
            sl_load_tests();
            char nt[64]; int p = 0;
            p = sapp(nt, p, "tests: ");
            p += utoa((unsigned)SL_n_tests, nt + p);
            p = sapp(nt, p, "  pop: ");
            p += utoa((unsigned)SL_POP, nt + p);
            p = sapp(nt, p, "  gens: 20");
            nt[p] = 0;
            body_at(2, 4, nt, SCREEN_W - 4);
            fbflush();
            int score = sl_evolve(20, sl_evolve_paint);
            char done[80]; int q = 0;
            q = sapp(done, q, "done · best score = ");
            q += utoa((unsigned)score, done + q);
            q = sapp(done, q, " (saved to coder_shifts.bin)");
            done[q] = 0;
            body_at(2, 22, done, SCREEN_W - 4);
            status("press any key to return to chat");
            fbflush();
            unsigned char k[16];
            rd(0, k, 1);
            sl_paint_chat_chrome(11);
            row = 11;
            continue;
        }

        if (li == 1 && (line[0] == 't' || line[0] == 'T')) {
            /* Add a test pair to coder.db. */
            cup(2, row + 1);
            fbs("test prompt> ");
            fbflush();
            char tp[80]; int tpi = 0;
            while (tpi < (int)sizeof tp - 1) {
                unsigned char ch[1];
                if ((int)rd(0, ch, 1) <= 0) goto sl_quit;
                if (ch[0] == '\n' || ch[0] == '\r') break;
                tp[tpi++] = (char)ch[0];
            }
            tp[tpi] = 0;
            cup(2, row + 2);
            fbs("expected substring> ");
            fbflush();
            char te[80]; int tei = 0;
            while (tei < (int)sizeof te - 1) {
                unsigned char ch[1];
                if ((int)rd(0, ch, 1) <= 0) goto sl_quit;
                if (ch[0] == '\n' || ch[0] == '\r') break;
                te[tei++] = (char)ch[0];
            }
            te[tei] = 0;
            if (tpi > 0 && tei > 0) {
                tdb_open();
                sl_save_test(tp, te);
                tdb_close();
                cup(2, row + 3);
                fbs("(test saved to coder.db)");
                fbflush();
            }
            row += 4;
            if (row >= SCREEN_H - 3) { sl_paint_chat_chrome(11); row = 11; }
            continue;
        }

        /* Default: chat. */
        int ids[SL_CTX];
        int n = 0;
        ids[n++] = SL_SEP;
        int body[SL_CTX];
        int bn = sl_encode(line, body, SL_CTX - 2);
        for (int i = 0; i < bn && n < SL_CTX - 1; i++) ids[n++] = body[i];
        ids[n++] = SL_SEP;
        /* Track column + row so we can wrap a long reply onto multiple
         * lines instead of letting the tty's auto-wrap stomp on the
         * next YOU> prompt.  Continuation lines indent under the C64>
         * prefix.  When the response would run off the bottom of the
         * page, repaint the chrome and continue from row 12. */
        int resp_row = row + 1;
        cup(2, resp_row);
        fbs("C64> ");
        fbflush();
        int col = 7;                       /* col after "  C64> " */
        const int margin = SCREEN_W - 2;   /* don't write past col 78 */
        for (int gen = 0; gen < SL_CTX && n < SL_CTX; gen++) {
            int tok = sl_forward(ids, n);
            if (tok == SL_PAD || tok == SL_SEP || tok == SL_END) break;
            int len = VOCAB_LEN_TBL[tok];
            if (col + len > margin) {
                resp_row++;
                if (resp_row >= SCREEN_H - 2) {
                    sl_paint_chat_chrome(11);
                    resp_row = 12;
                }
                cup(4, resp_row);          /* hanging indent under C64> */
                col = 4;
            }
            fbw((const char *)(VOCAB_STR_BLOB + VOCAB_OFFSETS[tok]),
                VOCAB_LEN_TBL[tok]);
            col += len;
            fbflush();
            ids[n++] = tok;
        }
        fbflush();
        row = resp_row + 2;                /* one blank line, then YOU> */
        if (row >= SCREEN_H - 3) { sl_paint_chat_chrome(11); row = 11; }
    }
sl_quit:
    sl_dlt_save();
    paint_desktop();
    chrome("Soul Chat");
    body_clear();
    body_at(2, 3, "  -- the only winning move is love!", SCREEN_W - 4);
    fbflush();
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

/* Derive a 4-colour palette for one overworld from its seed.  The 4
 * terrain classes anchor on the *current* hx_seed_pal — the same
 * palette hxhnt's V-viewer shows and that 'r' randomises / GA evolves
 * — decoded from xterm-256 to 24-bit RGB.  Each panel then drifts
 * ~±32 per channel from those anchors, so different sub-worlds
 * visibly differ while still all reading as the same hxhnt-flavoured
 * world.  Replacing/randomising hx_seed_pal in the V viewer takes
 * effect immediately on return because xpg invalidates rpg_cell_done
 * and re-runs rpg_palettes_refresh. */
static void rpg_palette_for_seed(unsigned long s, struct RpgRGB out[4]) {
    struct RpgRGB anchor[4];
    for (int i = 0; i < 4; i++) {
        int r, g, b;
        xterm256_to_rgb(hx_seed_pal[i], &r, &g, &b);
        anchor[i].r = (unsigned char)r;
        anchor[i].g = (unsigned char)g;
        anchor[i].b = (unsigned char)b;
    }
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
                    rpg_step_grid(hx_seed_genome, state, rpg_inner_b);
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
    rpg_anim_reset();
}

/* office51 — shift the 3×3 mosaic by (dx, dy) ∈ {-1,0,+1}².  Fast
 * path (when the shadow has every NEW panel for this direction):
 * memmove the 4-6 reused panels into their new slots and splat the
 * pre-computed shadow into the 3-5 new slots — pure memcpy, no CA
 * stepping, imperceptible.  Slow fallback (shadow incomplete or
 * direction mismatch): full 9-panel regen, same as office50. */
static void rpg_shift_mosaic(int dx, int dy, int spawn_x, int spawn_y) {
    if (dx == 0 && dy == 0) return;
    rpg_world_advance(dx, dy);

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

static int run_xpg(int argc, char **argv) {
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
        }

        paint_desktop();
        chrome("xpg");
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
        if (k[0] == 'V') {
            /* Drop into hxhnt's classic 64×64 live CA viewer for the
             * current mother ruleset.  Same UI office64 had: 'g' to
             * run a GA, 'h' to hunt, '['/']' to nudge mutation rate,
             * 'r' to randomise palette, 'd' to save, 'x' to splice-
             * export, 'q' to come back to xpg.  After return, refresh
             * xpg's caches in case the user evolved the rule. */
            int act = hx_display_seed(hx_seed_genome, hx_seed_pal,
                                      (unsigned int)time_());
            if (act == 'g') {
                unsigned int gseed = (unsigned int)(time_() ^ (long)hx_rand());
                hx_run_ga(20, 20, gseed);
            } else if (act == 'h') {
                hx_run_continuous_hunt();
            }
            rpg_palettes_refresh();
            rpg_genome_live_cache = -1;
            mset(rpg_cell_done, 0, sizeof rpg_cell_done);
            rpg_anim_reset();
            rt.cc[6] = rpg_animating ? 0 : 1;
            rt.cc[5] = rpg_animating ? 1 : 0;
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
        /* office51 — pre-load the projected new edge panels into the
         * shadow buffer one panel per tick whenever the player is
         * within RPG_PRELOAD_MARGIN cells of a central-panel boundary.
         * By the time the cross fires below, most/all of the work is
         * already done off-screen. */
        rpg_preload_advance_one(px, py);
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

    const char *cmd = (argc > 0) ? basename_(argv[0]) : "officeagent";
    int sub_argc = argc;
    char **sub_argv = argv;
    /* If cmd is "officeagent" / "supercell" (or any officeN wrapper,
     * kept for jail.c parity), peel argv[0] and treat argv[1] as
     * the subcommand. */
    {
        int is_wrapper = 0;
        if (scmp(cmd, "officeagent") == 0 ||
            scmp(cmd, "supercell")   == 0) is_wrapper = 1;
        if (cmd[0] == 'o' && cmd[1] == 'f' && cmd[2] == 'f' &&
            cmd[3] == 'i' && cmd[4] == 'c' && cmd[5] == 'e') {
            const char *t = cmd + 6;
            if (*t == 0) is_wrapper = 1;
            else {
                int all_digit = 1;
                while (*t) {
                    if (*t < '0' || *t > '9') { all_digit = 0; break; }
                    t++;
                }
                is_wrapper = is_wrapper || all_digit;
            }
        }
        if (is_wrapper && argc > 1) {
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
    if (scmp(cmd, "sheet")   == 0 || scmp(cmd, "calc") == 0)
                                   return run_sheet  (sub_argc, sub_argv);
    if (scmp(cmd, "ask")     == 0) return run_ask    (sub_argc, sub_argv);
    if (scmp(cmd, "prompt")  == 0) return run_prompt (sub_argc, sub_argv);
    if (scmp(cmd, "coder")   == 0) return run_coder  (sub_argc, sub_argv);
    if (scmp(cmd, "soul")    == 0) return run_soul   (sub_argc, sub_argv);
    /* xpg subsumes rpg + hxhnt + lsys. */
    if (scmp(cmd, "xpg")     == 0 || scmp(cmd, "rpg")   == 0 ||
        scmp(cmd, "hxhnt")   == 0 || scmp(cmd, "lsys")  == 0)
        return run_xpg(sub_argc, sub_argv);
    /* An exported hxh-* binary launched by name lands here.  Route
     * to xpg too — same embedded-ruleset behaviour. */
    if (cmd[0] == 'h' && cmd[1] == 'x' && cmd[2] == 'h')
        return run_xpg(sub_argc, sub_argv);
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
