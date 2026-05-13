# DOOM (1993) vs. doom_ca (2026): a side-by-side

This document compares id Software's original DOOM (the Linux 1.10
source release at `/home/handyc/claubsh/doom-source/linuxdoom-1.10/`)
against the **doom_ca** Django app at `/home/handyc/claubsh/velour-dev/doom_ca/`.
The two share a name and a vocabulary — _monsters_, _shotgun_,
_medkits_, _exit_ — but underneath they could hardly be less alike:
one is a 30,000-line C codebase rendering a 2.5-D BSP-partitioned
world at 35 Hz, the other is ~2,300 lines of pure JavaScript running
on a 4-state hex cellular automaton whose rule lives inside a sealed
**spoeqi** Pact.

The point of this comparison isn't to belittle doom_ca for being
small — the point is to map _which Doom mechanics survive the
CA-substrate transplant, which dissolve into the substrate itself,
and which are simply absent and could be borrowed back_.

Source references use `path:line` notation throughout; both
codebases are checked out locally.


## 0. One-line summary

| dimension          | DOOM 1.10                                | doom_ca                                                  |
|--------------------|------------------------------------------|----------------------------------------------------------|
| language           | C                                        | JavaScript (ES5-ish) + Django                            |
| world model        | 2.5-D BSP sectors (linedefs/sidedefs)    | 4-state hex CA, axial-flat layout                        |
| screen             | 320 × 200 palettized framebuffer         | square HTML canvas, 21-cell viewport                     |
| world tick         | 35 Hz `TICRATE`                          | per-keypress turn + N CA generations per turn            |
| monsters           | 26 `mobjtype_t` variants, table-driven   | 1 type, identical-stat marker cell                       |
| weapons            | 9 (`wp_fist` … `wp_supershotgun`)        | 1 shotgun (auto-fired on adjacency)                      |
| RNG                | 256-entry `rndtable[]`, two indices      | xoshiro128 + mulberry32 keyed off pact seed byte         |
| determinism        | demo playback                            | full Pact-bound multiplayer parity                       |
| level source       | WAD files, hand-built                    | BFS-grown from a CA-seeded grid + GA-selected gene       |
| audio              | MUS soundtracks, 8-channel sample SFX    | CA-driven 16-meter, 8-voice wavetable synth              |
| evolution          | none — humans authored everything        | tournament GA over a multi-component fitness function    |


## 1. Player mechanics

### Doom

The player is a `mobjtype_t` (`MT_PLAYER`) with stats encoded in the
giant `mobjinfo[]` table at `linuxdoom-1.10/info.c:1108-1132`:
spawn health 100, radius 16, height 56, mass 100, flags include
`MF_SHOOTABLE | MF_DROPOFF | MF_PICKUP`.  Starting health is set
from `MAXHEALTH` in `linuxdoom-1.10/p_local.h:33`:

    #define MAXHEALTH 100

When a level begins, `G_PlayerReborn` (`linuxdoom-1.10/g_game.c:824-831`)
restores `p->health = MAXHEALTH` and copies the per-ammo `maxammo[]`
into the player struct.  The hard ceiling on health and armor
points is `200` — `P_TouchSpecialThing` at
`linuxdoom-1.10/p_inter.c:385-403` clamps both health bonuses and
soulspheres against the cap.

Movement is continuous in a 2-D plane (z handled implicitly through
sectors).  `P_PlayerThink` and `P_MovePlayer` in `p_user.c` integrate
ticcmd buttons (forward/strafe/turn/use) at 35 Hz.  Hard-coded
constants set walking/running speed, friction, view bob, and stair
step-up.  The famous `MELEERANGE` (`p_local.h:57`) is `64 * FRACUNIT`
fixed-point — 64 map units; `MISSILERANGE` (`p_local.h:58`) is
`32*64*FRACUNIT`.

The protagonist has no canonical name in 1.10 — fans call him
"Doomguy."  His sprite shows BJ Blazkowicz's face cameo on Wolfenstein
secret levels (`MT_KEEN` at `info.h:1188`), and the BJ corpse is itself
a tombstone `mobjtype_t`.

### doom_ca

The player is _not_ a CA cell type — at least, not most of the time.
In `overlay` mode (the default, see `doom_ca/models.py:28-30`), the
player lives entirely outside the cellular substrate, tracked as a
plain JS object:

    static/doom_ca/play_runtime.js:410-411

        player = {x: c, y: c, hp: 100, ammo: 0,
                  hasShotgun: false, hasKey: false, lastDir: 1};

Starting HP is hard-coded to 100, mirroring Doom's `MAXHEALTH`, but
without the doubled (200) cap — there's no soulsphere here yet, so
`Math.min(100, player.hp + 25)` at
`static/doom_ca/play_runtime.js:467` is the only health-grant.

In the three "pure-CA" modes (`shift`, `scent`, `evolved` — see
`doom_ca/models.py:31-37`), the player **is** encoded as cell state
`PLAYER = 2` inside the CA (`static/doom_ca/engine.js:11`).  Each of
the 16,384 rule-table entries whose centre cell is `PLAYER` is
hard-patched to preserve the player at its current cell — i.e. the
sealed pact rule cannot kill or move the player without an explicit
patch.  `buildShiftRule` at `static/doom_ca/engine.js:79-93`,
`buildScentRule` at `static/doom_ca/engine.js:95-119`, and
`buildEvolvedRule` at `static/doom_ca/engine.js:122-145` all begin
with the `u.s === PLAYER` carve-out.

Movement is grid-based and turn-based.  Keys map to six hex
directions through `cardinalToHex` at
`static/doom_ca/play_runtime.js:854-867` — `W` and `↑` are direction
0 (top-right), and so on around the hex.  There is **no** strafe,
no run, no view bob, no z-axis.  Each keypress steps once and
advances the world by `worldRate` (default 1) CA generations.

There is no BJ cameo.  There is, however, a CA pact backing every
playthrough — and two players holding the same Pact key can produce
the same playthrough byte-for-byte (see `doom_ca/models.py:9-11`).

### Comparison table

| aspect                | Doom                                   | doom_ca                                                  |
|-----------------------|----------------------------------------|----------------------------------------------------------|
| max HP                | 100 (200 with soulsphere)              | 100 (no overheal yet)                                    |
| max armor             | 200 (`p_inter.c:393`)                  | no armor                                                 |
| spawn health          | `MAXHEALTH` = 100 (`p_local.h:33`)     | hard-coded literal 100 (`play_runtime.js:411`)           |
| movement              | continuous, 35 Hz                      | hex-grid, per-keypress turns                             |
| weapons in hand       | up to 9 (`doomdef.h:182-190`)          | 1 shotgun (binary state `hasShotgun`)                    |
| representation        | `mobjinfo[MT_PLAYER]` table row        | JS object overlay (overlay) **or** CA state 2 (pure)     |
| facing/angle          | 32-bit `angle_t`                       | `lastDir` 0..5 (shotgun fires in this direction)         |


## 2. Monsters and enemy AI

### Doom

Doom 1.10 ships **26 distinct monster types** plus their projectiles,
all enumerated in `linuxdoom-1.10/info.h:1163-1303`:

| identifier      | nickname                         | spawnhealth | speed |
|-----------------|----------------------------------|-------------|-------|
| `MT_POSSESSED`  | zombieman                        | 20          | 8     |
| `MT_SHOTGUY`    | shotgun zombie                   | 30          | 8     |
| `MT_TROOP`      | imp                              | 60          | 8     |
| `MT_SERGEANT`   | demon (pinky)                    | 150         | 10    |
| `MT_HEAD`       | cacodemon                        | 400         | 8     |
| `MT_SKULL`      | lost soul                        | 100         | 8     |
| `MT_BRUISER`    | baron of hell                    | 1000        | 8     |
| `MT_KNIGHT`     | hell knight                      | 500         | 8     |
| `MT_SPIDER`     | spider mastermind                | 3000        | 12    |
| `MT_CYBORG`     | cyberdemon                       | 4000        | 16    |
| `MT_BABY`       | arachnotron (Doom II)            | 500         | 12    |
| `MT_VILE`       | arch-vile (Doom II)              | 700         | 15    |
| `MT_FATSO`      | mancubus                         | 600         | 8     |

Each entry in `mobjinfo[]` (`linuxdoom-1.10/info.c:1106+`) carries
`spawnhealth`, `seestate`, `painstate`, `meleestate`, `missilestate`,
`deathstate`, `speed`, `reactiontime`, `painchance`, hit-sounds,
death-sounds, mass, radius, height, damage, flags, and a
`raisestate` for arch-vile resurrection.

AI is state-machine driven.  `A_Look` (`linuxdoom-1.10/p_enemy.c:604-664`)
keeps a monster idle until it hears the player (`soundtarget`) or
sees them (`P_LookForPlayers`).  Once awake, `A_Chase`
(`linuxdoom-1.10/p_enemy.c:672-776`) does the heavy lifting:

* tracks `target` (the player, usually) and threshold timer
* turns toward `movedir`, divided into 8 cardinal directions
* invokes `P_CheckMeleeRange` if `meleestate` is set
  (`linuxdoom-1.10/p_enemy.c:725-732`)
* invokes `P_CheckMissileRange` for ranged attacks
* otherwise calls `P_NewChaseDir` to pick a new move direction
* occasionally plays `activesound` with `P_Random() < 3`
  (`linuxdoom-1.10/p_enemy.c:771-774`)

Each monster type has its own specialised attack action (`A_PosAttack`,
`A_SPosAttack`, `A_TroopAttack`, `A_HeadAttack`, `A_BruisAttack`,
`A_CyberAttack`, etc.), referenced from state pointers in
`info.c`.

### doom_ca

doom_ca has **one** monster type.  There is no painchance, no
seestate, no missile attack — only a marker cell value
(`MONSTER = 3` at `static/doom_ca/engine.js:11`) and one of two
movement rules depending on world mode.

In **overlay mode**, monsters live in a JS array
(`static/doom_ca/play_runtime.js:396`) and pursue the player greedily
each turn via `moveOverlayMonsters` at
`static/doom_ca/play_runtime.js:615-651`:

* For each alive monster, scan all 6 hex neighbours.
* Filter out walls (`isWallForOverlay`) and cells occupied by other
  monsters.
* Pick the neighbour with smallest `hexDist` to the player.
* On tie, break with the deterministic `tieBreakBytes` keystream
  from the pact (`play_runtime.js:639-642`) — so two players see the
  same tie-break.
* If the step lands on the player: deal 30 HP damage (or consume
  ammo if armed), and the monster dies in the collision —
  `play_runtime.js:645-648`.

In **scent mode**, there is no JS pursuit at all.  The monster-spread
emerges from a single hand-built rule
(`static/doom_ca/engine.js:95-119`):

> A `GROUND` cell whose neighbourhood contains ≥1 `MONSTER` and
> either a `PLAYER` neighbour or ≥2 `GROUND` neighbours becomes
> `MONSTER` next tick.

That's it — fluid-like spread toward the player with no per-monster
state.  Adjacent monsters then "bite" via `meleeAdjacent`
(`static/doom_ca/play_runtime.js:566-576`) at -10 HP per bite, or
auto-firing the shotgun if the player has ammo.

The headless simulator's `simulateGame` at
`static/doom_ca/engine.js:358` runs the same logic for the GA's
fitness eval — `meleeAdjacentMonsters` at `engine.js:570-589` and
`moveOverlayMonsters` at `engine.js:591-622`.

### Comparison table

| dimension                   | Doom (MT_TROOP / imp)                                    | doom_ca monster                              |
|-----------------------------|----------------------------------------------------------|----------------------------------------------|
| spawn health                | 60 HP                                                    | 1 hit kill                                   |
| representation              | `mobj_t` with full state machine                         | grid cell value or JS `{x,y,alive}`          |
| chase logic                 | `A_Chase` + `P_NewChaseDir`                              | greedy hex BFS toward player                 |
| ranged attack               | `A_TroopAttack` spawns `MT_TROOPSHOT` projectile         | none                                         |
| melee                       | claw frame `S_TROO_ATK3` → `P_DamageMobj`                | walk onto player = mutual kill, -30 HP       |
| pain state                  | flinches on hit if `P_Random() < painchance` (200)       | none                                         |
| death animation             | 5-frame `S_TROO_DIE1..5`                                 | cell cleared to GROUND                       |
| activesound                 | `sfx_bgact` every few hundred ticks                      | none (no SFX yet)                            |


## 3. Items and pickups

### Doom

`P_TouchSpecialThing` at `linuxdoom-1.10/p_inter.c:336-700` is one
of the most enumerated functions in the entire codebase — a switch
on `special->sprite` with ~28 distinct cases.  An abridged map:

| sprite       | effect                                                                  | code reference                     |
|--------------|-------------------------------------------------------------------------|------------------------------------|
| `SPR_ARM1`   | green armor +100 type-1 (`P_GiveArmor(player,1)`)                       | `p_inter.c:370`                    |
| `SPR_ARM2`   | blue armor +200 type-2                                                  | `p_inter.c:376`                    |
| `SPR_BON1`   | health bonus +1, can exceed 100 up to 200                               | `p_inter.c:383-389`                |
| `SPR_BON2`   | armor bonus +1, up to 200                                               | `p_inter.c:391-398`                |
| `SPR_SOUL`   | soulsphere +100 HP, exceeds normal cap                                  | `p_inter.c:400-407`                |
| `SPR_MEGA`   | megasphere (Doom II): 200 HP + 200 blue armor                           | `p_inter.c:409-417`                |
| `SPR_BKEY`   | blue keycard                                                            | `p_inter.c:421`                    |
| `SPR_YKEY`   | yellow keycard                                                          | `p_inter.c:429`                    |
| `SPR_RKEY`   | red keycard                                                             | `p_inter.c:437`                    |
| `SPR_BSKU`   | blue skull key                                                          | `p_inter.c:445`                    |
| `SPR_YSKU`   | yellow skull key                                                        | `p_inter.c:453`                    |
| `SPR_RSKU`   | red skull key                                                           | `p_inter.c:461`                    |
| `SPR_STIM`   | stimpack +10 HP                                                         | `p_inter.c:470`                    |
| `SPR_MEDI`   | medikit +25 HP                                                          | `p_inter.c:476`                    |
| `SPR_PINV`   | invulnerability sphere (30 s)                                           | `p_inter.c:488`                    |
| `SPR_PSTR`   | berserk pack — full heal + permanent fist boost                         | `p_inter.c:495`                    |
| `SPR_PINS`   | partial invisibility / "blursphere"                                     | `p_inter.c:504`                    |
| `SPR_SUIT`   | radiation suit (60 s)                                                   | `p_inter.c:511`                    |
| `SPR_PMAP`   | computer area map — automap reveal                                      | `p_inter.c:518`                    |
| `SPR_PVIS`   | light amplification visor                                               | `p_inter.c:525`                    |
| `SPR_CLIP`   | bullet clip — 10 (or 5 if dropped)                                      | `p_inter.c:533`                    |
| `SPR_AMMO`   | box of bullets — 50                                                     | `p_inter.c:547`                    |
| `SPR_ROCK`   | single rocket                                                           | `p_inter.c:553`                    |
| `SPR_BROK`   | box of rockets — 5                                                      | `p_inter.c:559`                    |
| `SPR_CELL`   | energy cell — 20                                                        | `p_inter.c:565`                    |
| `SPR_CELP`   | cell pack — 100                                                         | `p_inter.c:571`                    |
| `SPR_SHEL`   | 4 shells                                                                | `p_inter.c:577`                    |
| `SPR_SBOX`   | 20 shells                                                               | `p_inter.c:583`                    |
| `SPR_BPAK`   | backpack — doubles maxammo, refills all                                 | `p_inter.c:589-599`                |
| `SPR_BFUG`   | BFG 9000                                                                | `p_inter.c:602`                    |
| `SPR_MGUN`   | chaingun                                                                | `p_inter.c:609`                    |

Weapons themselves are pickup-able mobjs.  `weaponinfo[]` at
`linuxdoom-1.10/d_items.c:45-` defines all nine, each with
ammo-type, up/down/ready/attack/flash state pointers.

The ammo caps come from `maxammo[NUMAMMO] = {200, 50, 300, 50}` at
`linuxdoom-1.10/p_inter.c:58` — clips/shells/cells/rockets — and
clipammo `{10, 4, 20, 1}` for per-pickup amounts.

### doom_ca

doom_ca has **four** distinct pickups, all placed deterministically
by `placeLevel` at `static/doom_ca/engine.js:209-312`:

| type         | effect                                       | placement                                       |
|--------------|----------------------------------------------|-------------------------------------------------|
| `shotgun`    | `player.hasShotgun = true`, no damage stat   | always 1 if `gene.shotgun_count` (default 1)    |
| `medkit`     | +25 HP, capped at 100                        | `gene.health_pack_count` (default 3)            |
| `ammo`       | +3 shells                                    | `gene.ammo_pack_count` (default 3)              |
| key (single) | unlocks the one door                         | placed at farthest BFS point off the main path  |

Item pickup logic is in `pickupAt` at
`static/doom_ca/play_runtime.js:464-471`:

    if      (it.type === 'medkit')       player.hp = Math.min(100, player.hp + 25);
    else if (it.type === 'ammo')         player.ammo += 3;
    else if (it.type === 'shotgun')      player.hasShotgun = true;

Items live on an **overlay map** keyed by cell index (`items` at
`play_runtime.js:464`), so they don't disturb the CA's K=4
invariant.  This is the same trick Doom uses — sprites and
linedefs are not part of the BSP node geometry either; they're
overlay data — but applied much more strictly here because the
substrate has to remain a valid 4-state CA for the sealed pact rule.

### Comparison table

| category               | Doom distinct items | doom_ca distinct items |
|------------------------|---------------------|------------------------|
| health                 | 4 (bonus, stim, medkit, soulsphere) + mega | 1 (medkit) |
| armor                  | 4 (bonus, green, blue, mega)               | 0          |
| keys                   | 6 (3 cards + 3 skulls)                     | 1          |
| ammo                   | 8 (clip, box, rocket, boxrocket, cell, celpack, shells, boxshells) | 1 (ammo pack) |
| backpack               | 1                                          | 0          |
| weapons                | 7 pickup-able (fist + chainsaw start)      | 1 (shotgun) |
| power-ups              | 6 (invuln, berserk, blur, suit, map, visor) | 0 |
| **total pickup kinds** | **~31**                                    | **4**      |


## 4. Level structure

### Doom

A Doom level is a WAD-packaged collection of:

* `THINGS` — monster spawns, items, player starts (DoomEd numbers)
* `VERTEXES` — 2D world vertices
* `LINEDEFS` — segments connecting vertices, with flags (impassable,
  twosided, blocks-sound, secret), special action codes, and a
  sector tag
* `SIDEDEFS` — textures + offsets for each side of a linedef
* `SECTORS` — floor/ceiling heights, light level, special, tag
* `SEGS`, `SSECTORS`, `NODES` — BSP tree built by `BSP.EXE`
* `REJECT` — visibility lookup
* `BLOCKMAP` — 128×128 unit grid for collision broadphase

This data is rendered by a column-based software renderer (see the
`r_*.c` files: `r_main.c`, `r_segs.c`, `r_things.c`, `r_plane.c`).
There can be up to 6 keys per level (3 cards + 3 skulls), and an
exit linedef whose special action ends the level — switch types like
`Exit_Normal (11)` and walk-over types `WR_End_Level (52)`.

Each game can have multiple **episodes**, and each episode has up to
9 maps.  In `g_game.c`, `G_LoadGame` / `G_DoLoadLevel` switch between
them.  Levels are entirely hand-crafted in editors like DoomEd or
DEU.

### doom_ca

A doom_ca level is **generated** from three inputs:

1. A 64-byte pact seed (`pact.seed_hex`, one byte per component).
2. A 16,384-entry rule table (`pact.rules_hex`, the component slice).
3. The `GameSession` row's gene fields:
   `monster_count`, `wall_threshold`, `health_pack_count`,
   `ammo_pack_count`, `door_count`, `music_style_idx`.

The seed byte is splat through `splitmix64` to bootstrap an
xoshiro128 generator (`engine.js:25-54`), which fills the grid; cells
≥ `wall_threshold` become `WALL`, the rest become `GROUND`
(`engine.js:55-66` and `play_runtime.js:104-115`).

`placeLevel` at `static/doom_ca/engine.js:209-312` then:

1. Runs **BFS from the centre cell** (the spawn).
2. Picks the cell with the largest BFS distance as the **exit**
   (`engine.js:235-239`).
3. If `door_count > 0`: walks the spawn→exit path, places the door
   at the path midpoint (`engine.js:243-248`), reruns BFS with the
   door excluded, and places the **key** at the farthest reachable
   cell that isn't spawn/exit/door (`engine.js:249-258`).
4. Shuffles remaining reachable ground cells with a placement RNG
   keyed off `gene.seed_byte * 2654435761` (`engine.js:269-272`) and
   drops in the shotgun, medkits, and ammo packs.
5. Computes `openness` (reachable / total) and `corridorWidth`
   (mean non-wall neighbours / 6) and reports them so the GA can
   select on layout shape (`engine.js:288-307`).

The result is one playable map per gene per pact-component pair,
fully deterministic.  No human authoring.  There is also no
multi-episode structure — each `GameSession` is a single map.

### Comparison table

| dimension              | Doom                                                  | doom_ca                                                  |
|------------------------|-------------------------------------------------------|----------------------------------------------------------|
| world topology         | 2.5-D BSP polygonal sectors                           | 4-state hex CA, wrap-around torus                        |
| height                 | per-sector floor + ceiling                            | flat — no z axis                                         |
| number of keys         | up to 6 (3 cards + 3 skulls)                          | 0 or 1                                                   |
| number of exits        | usually 1 (sometimes secret exit too)                 | exactly 1, farthest BFS-reachable cell                   |
| level source           | WAD authored in DoomEd / DEU                          | generated from `(pact, gene)` via BFS                    |
| reachability proof     | implicit (designer's job)                             | explicit (BFS from spawn; unwinnable → null)             |
| level metadata exposed | sector counts, secret area count, etc.                | `openness`, `corridorWidth` (engine.js:288-307)          |


## 5. Combat resolution

### Doom

Doom distinguishes three damage modes:

1. **Hitscan** (`P_LineAttack` at `p_map.c`): an instantaneous
   trace from the shooter's eye along an angle out to `MISSILERANGE`
   (`p_local.h:58` = 32 × 64 fixed-point units, "2048 map units").
   Used by `A_FirePistol` (`p_pspr.c:644-662`), `A_FireShotgun`
   (`p_pspr.c:666-688` — fires 7 pellets), `A_FireShotgun2`
   (`p_pspr.c:693-726` — super-shotgun, 20 pellets with random spread),
   and chaingun `A_FireCGun`.

2. **Projectile** (`P_SpawnMissile`): launches a new `mobj_t` whose
   `MF_MISSILE` flag triggers explode-on-contact in `P_MobjThinker`.
   Used by rocket launcher, plasma rifle, BFG, and most monster
   ranged attacks (imp fireball, baron green fireball, cacodemon
   lightning, etc.).

3. **Splash damage**: when a `MF_MISSILE` mobj explodes,
   `P_RadiusAttack` damages everything within a radius scaled by the
   weapon's damage value.

`P_DamageMobj` is the central damage resolver.  Special effects:

* Bullet sparks spawn `MT_PUFF` on wall hits.
* Bleeding monsters spawn `MT_BLOOD` on flesh hits.
* If damage exceeds the negative-health gib threshold (typically
  -|spawnhealth|), the monster jumps to `xdeathstate` — the gory
  exploded death frames.

Doom's shotgun does `5 * (P_Random() % 3 + 1)` damage per pellet —
`p_pspr.c:718` (in `A_FireShotgun2`'s loop) — for ranges 5..15 per
pellet, ×7 or ×20 pellets per shot.

### doom_ca

doom_ca has exactly one combat motif: **adjacency**.  There is no
trace, no projectile, no splash.  The shotgun is a single-tile
hitscan that walks up to 4 hex cells in the player's `lastDir`:

    static/doom_ca/play_runtime.js:539-564

        function playerFire () {
          if (!player.hasShotgun) return;
          if (player.ammo <= 0) return;
          player.ammo--;
          var x = player.x, y = player.y;
          for (var step = 0; step < 4; step++) {
            var nb = neighbourCoord(x, y, player.lastDir);
            x = nb[0]; y = nb[1];
            ...
            if (c === MONSTER) { set(x, y, GROUND); break; }
          }
          ...
        }

But the more common case — and the one that gives the game its
shape — is the **reflexive auto-fire** in `playerMove` and
`moveOverlayMonsters`.  When the player would step onto (or be
stepped onto by) a monster, `autoFireAt` is called
(`play_runtime.js:456-462`):

* If the player has the shotgun and at least 1 ammo, **the player
  fires automatically**, consuming 1 ammo, killing the monster, and
  drawing the fire-flash line.
* If not, the player takes 30 HP damage and the monster still dies
  in the collision.

This means **a shotgun + ammo + adjacency** kills monsters with
zero HP cost.  **No ammo** means every contact is mutual destruction
at a steep 30 HP cost.  After ~3 unarmed contacts, the player is
dead.  This is a far cry from Doom's damage-roll system but it
gives doom_ca its own tempo: get the shotgun first; conserve ammo;
never let a monster touch you when you're empty.

The pure-CA modes substitute `meleeAdjacent` after the world tick
(`play_runtime.js:566-576` and `engine.js:570-589`):

    for (var d = 0; d < 6; d++) {
      var nb = neighbourCoord(player.x, player.y, d);
      if (get(nb[0], nb[1]) === MONSTER) {
        if (!autoFireAt(nb[0], nb[1])) player.hp -= 10;
        set(nb[0], nb[1], GROUND);
      }
    }

Note the milder -10 (vs overlay's -30) — because in scent/evolved
the rule itself spawns monsters fluid-like and contact is
high-frequency.

### Comparison table

| facet               | Doom                                          | doom_ca                                                  |
|---------------------|-----------------------------------------------|----------------------------------------------------------|
| damage roll         | `P_Random()` rolls weighted by weapon         | flat: 30 HP (overlay) or 10 HP (pure) per touch          |
| shotgun pellets     | 7 (`A_FireShotgun`)                           | 1 cell-walking ray, kills first hit                      |
| super-shotgun       | 20 pellets, random spread                     | none                                                     |
| projectiles         | rocket / plasma / BFG / monster fireballs     | none                                                     |
| splash damage       | `P_RadiusAttack`                              | none                                                     |
| reflexive fire      | no — player must press fire                   | yes (`autoFireAt` on monster contact)                    |
| gibbing             | `xdeathstate` if dmg ≥ -spawnhealth           | none — cell just becomes GROUND                          |
| blood / puffs       | `MT_BLOOD` / `MT_PUFF` mobjs                  | none                                                     |
| infighting          | hit-by-other-monster → retarget               | irrelevant — only 1 monster type                          |


## 6. Audio

### Doom

* **Music**: MUS format soundtracks composed by Bobby Prince.
  Stored as a custom MIDI-like binary in the WAD; played by
  `i_sound.c`'s MUS-to-MIDI translator.  E1M1's "At Doom's Gate"
  (a.k.a. "Untitled" / heavily Metallica-flavoured) is the
  best-known.
* **Sound effects**: ~108 entries in `sounds.h` (zombie pain
  `sfx_popain`, pistol `sfx_pistol`, shotgun `sfx_shotgn`, monster
  bark `sfx_posit1..3`, door open `sfx_doropn`, pickup chimes,
  etc.).  Played through 8 channels, sample-based, hard-panned
  stereo by the renderer.
* **Linkage**: each `mobjinfo_t` row carries `seesound`,
  `attacksound`, `painsound`, `deathsound`, `activesound`.  Doom
  monsters are noisy because everything they do triggers a sample.
  See `linuxdoom-1.10/p_enemy.c:631-661` — when an `A_Look` becomes
  `seeyou`, the `seesound` plays at the monster's position.

### doom_ca

doom_ca currently has **zero sound effects** — no footsteps, no
weapon report, no monster bark, no pickup chime.  Instead it has
something Doom didn't: **CA-driven generative music**.

`static/doom_ca/music.js` is a 556-line port of officerpg ev88's
musicCA / metaCA engine, retargeted at the doom_ca pact rule.  The
architecture mirrors what's documented in the file header
(`music.js:22-32`):

* Two 64×64 hex CAs — a **score CA** and a **conductor CA** — both
  ticking under the pact's 16,384-entry rule via `engine.js`'s
  `tickRule` (called from `music.js:262-273`).
* The conductor steps at 1/8 the score's rate (`META_BARS_PER_STEP`
  = 8 at `music.js:46`).
* 8 voices, each with octave / decay / volume in `MUSIC_VOICE_CFG`
  at `music.js:213-222`.
* A 16-entry `MUSIC_STYLES` table at `music.js:55-211` defines
  cultural meters: `common (4/4)`, `waltz (3/4)`, `Chinese
  (ping-pong)`, `Indian (Keherwa 8/4)`, `Russian (Trepak)`, `Bossa
  Nova`, `Pow-wow heartbeat`, `African 12/8`, `Celtic jig (6/8)`,
  `Maqsum (Arabic)`, `Japanese (5/4)`, `Flamenco (Soleá 12)`,
  `Reggae skank`, `Tango`, `Doom march (2/4 driving)`, `Ambient
  drift (4/4 slow)`.
* The Doom march at `music.js:193-203` is the closest tribute to
  E1M1: fast 4/4, bass on every beat, lead syncopated.
* Wavetable timbre is packed from 4 CA cells (2 bits each) into one
  8-bit sample, looped at note frequency — `buildWavetable` at
  `music.js:275-287`.
* Stereo split: **score on L, conductor on R**
  (`music.js:451-461`).
* `scheduleBar` (`music.js:304-364`) materialises one bar's worth
  of WebAudio `BufferSourceNode`s with attack/decay envelopes via
  `scheduleNote` (`music.js:289-302`).
* A look-ahead scheduler (`schedulerTick`, `music.js:366-387`) runs
  every 100 ms in a dedicated `Worker` so it survives tab-throttle
  (`ensureWorker`, `music.js:389-406`).
* **Mood smoother** (`updateSignals`, `music.js:522-546`): each turn
  the runtime feeds in HP, ammo, wall-adjacency, nearest-monster
  distance, and monsters-in-view; the music nudges its target
  pitch and intensity accordingly.  Cornered + low HP + close
  threat darkens the music down to `-5..-4` semitones; open +
  healthy + safe brightens it up to `+3..+4`.

The crucial property: **the same 16,384-entry rule that generates
the world also generates the music**.  Two players on the same
pact, the same component, the same gene hear the same soundtrack —
because the CA is deterministic from a sealed seed.

### Comparison table

| dimension             | Doom                                                | doom_ca                                                  |
|-----------------------|-----------------------------------------------------|----------------------------------------------------------|
| soundtrack source     | MUS files in WAD, composed by Bobby Prince          | live CA tick on pact rule, 8-voice wavetable             |
| meter                 | fixed per track                                     | 16 selectable + cyclable mid-game                        |
| channels / voices     | 8 sample channels                                   | 8 voices, stereo split (score L / conductor R)           |
| dynamic adaptation    | none (track loops)                                  | mood smoother on HP / threat / openness                  |
| SFX                   | ~108 sample SFX                                     | **none yet** (largest audio gap)                         |
| determinism           | track is byte-identical every play                  | CA-driven, deterministic from pact seed                  |
| total LOC             | i_sound.c + music libs ≈ 2000 LOC                   | music.js: 556 LOC                                        |


## 7. Art and rendering

### Doom

* **Resolution**: 320 × 200 (`linuxdoom-1.10/doomdef.h:110-112`),
  fixed.
* **Renderer**: column-based software rasteriser.  `r_main.c` walks
  the BSP from front to back, `r_segs.c` draws wall columns,
  `r_things.c` draws sprites, `r_plane.c` flat-fills floors and
  ceilings, `r_draw.c` is the pixel inner loop.
* **Palette**: a single 256-colour palette stored in the WAD's
  `PLAYPAL` lump.  14 different colourmaps remap that palette for
  light-diminishing — `r_data.c` loads `COLORMAP`.
* **Sprites**: rotation-aware.  Each monster has 8 angles
  (`SPR_TROO_A1..A8`) plus pain/death/etc. frames.  Frames carry
  a "mirror" flag so opposite angles share bitmaps.
* **Textures**: composed at load time from "patches" (`r_data.c`
  `R_GenerateLookup`).  Wall textures have hardcoded sizes 128×128
  typical; floors/ceilings are 64×64 "flats."
* **Lighting**: per-sector light level 0..255, picked into one of
  16 colourmaps at draw time by distance.  Sectors can flicker,
  flash, blink-fast, blink-slow, oscillate, or glow.

### doom_ca

* **Resolution**: dynamic — canvas resizes to `Math.floor(min(availW,
  availH))` in `recomputeRenderMetrics` at
  `static/doom_ca/play_runtime.js:220-234`.
* **Renderer**: 2-D top-down hex grid drawn cell-by-cell with
  `ctx.fillRect`.  21-cell viewport (`VIEW = 21` at
  `play_runtime.js:217`), camera follows the player so the player
  stays at the centre of the view (`draw` at
  `play_runtime.js:653-811`).
* **Palette**: 4 RGB triples per component, baked into the pact.
  The component palette is read at `play_runtime.js:241-249`:

      var componentPalette = isPerComponent(palette) ? palette[COMPONENT] : palette;
      var COL_WALL    = 'rgb(' + componentPalette[3].join(',') + ')';
      var COL_WALL_DK = 'rgb(' + componentPalette[2].join(',') + ')';
      var COL_GROUND  = '#1a1a1a';
      var COL_PLAYER  = '#58a6ff';
      var COL_MONSTER = '#f85149';

  Player blue and monster red are hard-coded — only walls actually
  use the pact's evolved colours.
* **Sprites**: there are no sprites.  Items are rendered as Unicode
  glyphs in monospace font: exit `⌂` at `play_runtime.js:706`, door
  `🔒` at `:717`, key `🔑` at `:726`, medkit `✚` at `:736`, ammo `●`
  at `:739`, shotgun `⌐` at `:742`.  Monsters are red filled circles
  at `:763-765`.  Player is a blue circle with a cross-hair cursor
  at `:770-783`.
* **Fire flash**: a yellow line from shooter to target persists 2
  frames, drawn at `play_runtime.js:784-810`.
* **Lighting**: none.  No diminishing, no sector lights, no day/night.

### Comparison table

| dimension        | Doom                                  | doom_ca                                                  |
|------------------|---------------------------------------|----------------------------------------------------------|
| resolution       | 320 × 200 fixed                       | dynamic canvas, ~21 cells across                         |
| viewport shape   | first-person 2.5-D projection         | top-down hex grid, camera-follow                         |
| palette          | 256-colour PLAYPAL                    | 4 RGB triples per component                              |
| sprite rotations | 8 angles per monster frame            | none (single circle)                                     |
| textures         | walls + flats + sprites               | flat-fill rects only                                     |
| lighting model   | 16 colourmaps × per-sector light      | flat — no lighting                                       |
| HUD              | status bar at `st_stuff.c`            | text readouts above canvas                               |


## 8. RNG

### Doom

Doom's RNG is famously a **256-byte fixed table** —
`linuxdoom-1.10/m_random.c:31-51`:

    unsigned char rndtable[256] = {
        0,   8, 109, 220, 222, 241, 149, 107,  75, 248, 254, 140, ...
    };

Two independent index variables — `prndindex` for "physics" RNG
(`P_Random`, the deterministic one used for damage rolls, monster
AI, demo playback) and `rndindex` for "misc" RNG (`M_Random`, used
for cosmetic effects).  Each call increments its index and returns
`rndtable[index]` (`m_random.c:57-67`):

    int P_Random (void) {
        prndindex = (prndindex+1) & 0xff;
        return rndtable[prndindex];
    }

`M_ClearRandom` (`m_random.c:69-72`) zeroes both indices at level
start.  This is what makes Doom demos byte-replayable: the
sequence of `P_Random()` outputs is fixed across the entire run.

### doom_ca

doom_ca uses two cryptographic-ish PRNGs, both deterministic from
the pact seed byte:

1. **xoshiro128** (`engine.js:25-54` and `play_runtime.js:74-103`),
   seeded by passing the seed byte through four `splitmix64`
   iterations.  Used to initialise the world grid in `seedGrid`
   (`engine.js:55-66`).
2. **mulberry32** (`engine.js:192-202` and `music.js:242-251`),
   seeded by `seed_byte * 2654435761` for item placement
   (`engine.js:366`) and by various derived seeds for monster
   placement / GA selection / tie-breaks.

Plus the spoeqi `keystream.tap` server-side API
(`doom_ca/views.py:153-162`) — when the live game launches, it
fetches a deterministic byte stream from the pact ("monster
placement bytes") that's identical for every player of the same
pact-component:

    n_bytes = session.monster_count * 4 + 32
    tap_bytes = keystream.tap(pact, session.component, 0, n_bytes)

These bytes choose monster positions and break AI movement ties
(`play_runtime.js:639-642`).  Result: **two players on the same
pact + same keypress sequence get a byte-identical playthrough** —
the same property Doom achieves for demo playback, but generalised
to live multiplayer parity.

### Comparison table

| property               | Doom                                    | doom_ca                                                  |
|------------------------|-----------------------------------------|----------------------------------------------------------|
| algorithm              | 256-byte LUT, single byte per call      | xoshiro128 (32-bit) + mulberry32                         |
| state size             | 8 bits (one index)                      | 128 bits (four 32-bit words) + per-RNG mulberry state    |
| period                 | 256 (lookup), but with stateful index  | xoshiro128: ~2^128                                       |
| seeded from            | hardcoded — `M_ClearRandom` zeroes      | pact seed byte (cryptographic provenance via spoeqi)     |
| determinism scope      | demo replay                              | full live-multiplayer parity                             |
| tie-break for AI       | `P_Random()` modulo                      | pact keystream byte modulo                               |


## 9. What doom_ca evolves that Doom doesn't

This is the axis where doom_ca diverges most sharply.  In Doom,
every level, every monster placement, every weapon balance was
hand-authored — by Romero, Petersen, McGee, Hall, Cloud.  In
doom_ca, **the genome is the level**, and a tournament GA in the
browser breeds it.

The gene shape lives implicitly throughout `engine.js` and
explicitly in the evolve page.  From `templates/doom_ca/evolve.html:689-721`,
the agent gene carries:

| field                   | role in the game                                          |
|-------------------------|-----------------------------------------------------------|
| `rule`                  | 16,384-byte CA rule table (the entire world's physics)    |
| `seed_byte`             | xoshiro seed → initial grid                               |
| `component_grid`        | side length (typically 16 → 256 cells)                    |
| `world_mode`            | overlay / shift / scent / evolved                         |
| `monster_count`         | how many to spawn                                         |
| `wall_threshold`        | which CA states count as wall                             |
| `pure_mode`             | whether the pact rule ticks between turns                 |
| `palette`               | 4 RGB triples (cosmetic, but reads to player as identity) |
| `health_pack_count`     | medkits placed                                            |
| `ammo_pack_count`       | ammo packs placed                                         |
| `door_count`            | 0 or 1                                                    |
| `shotgun_count`         | weapon-present flag (1 → has shotgun; 0 → unarmed level)  |
| `music_style_idx`       | which of the 16 meters plays                              |

Fitness is multi-component, weighted-summed
(`templates/doom_ca/evolve.html:561-590`):

* `playability` — does the AI survive ≥ 3 turns most of the time?
* `challenge` — does the survival rate sit near 0.5? (peak at 50/50)
* `engagement` — mean monsters visible in viewport
* `navigation` — inverse of mean walls bumped
* `exploration` — fraction of reachable ground visited
* `purity` — bonus for choosing pure-CA modes
* `completion` — fraction of sims that reach the exit
* `timeexit` — faster wins = higher fitness
* `hpend` — HP remaining at exit
* `openness` — reachable / total (level shape)
* `corridor` — mean unwalled-neighbour fraction (corridor vs chamber)

Hard-fail: if **any** sim flags `unwinnable` (no exit reachable),
fitness drops to 0 (`evolve.html:592`).

Selection: tournament-k random sample, winner clones with mutation
(`evolve.html:614-622`).  Best-ever list persisted across runs.

**Doom has none of this.**  Doom's level designers iterated by
hand, in editors, with playtesting and intuition.  Doom's only
"random" decisions are damage rolls and AI tie-breaks at runtime.
doom_ca treats the entire (level + rule + meter + palette) as a
single evolvable genome and lets a fitness function pick.

This is the deepest substrate-level difference: Doom is a
**hand-built artefact**, doom_ca is a **breedable genus**.


## 10. Gaps and opportunities

What could doom_ca borrow from Doom that it doesn't currently have?
Roughly in order of how much they'd add per line of code:

### 10a. Sound effects

The single biggest missing piece.  Doom's audio is what _sells_ the
threat — the imp's `sfx_bgsit1` bark coming from somewhere off-screen
turns an abstract sprite into a presence.  doom_ca has 556 lines of
beautiful generative music and **zero** SFX.

A minimal SFX set, all 1-3-second WebAudio renders, all CA-derived
to stay in-substrate:

* `sfx_shotgn` — shotgun discharge (already triggered via `fireFlash`)
* `sfx_pickup` — generic item-up chime
* `sfx_dooropn` — when a door opens
* `sfx_keypickup` — distinct from generic pickup
* `sfx_posit` — monster bark on spawn / on adjacency
* `sfx_plpain` — player taking damage
* `sfx_pldth` — player dying
* `sfx_exitswitch` — reaching the exit

Implementation sketch: generate sample buffers from CA cells (same
trick as `buildWavetable` at `music.js:275-287`), trigger with
sub-100ms attack envelopes, route through `musicMaster` so the
soundtrack ducks under SFX.

### 10b. Multiple monster classes

Right now every monster is a 1-HP marker cell.  Borrowing the
Doom `mobjinfo[]` schema, doom_ca could add 2-3 classes:

| name (suggested) | spawnhealth | speed                | behaviour                                  |
|------------------|-------------|----------------------|--------------------------------------------|
| crawler          | 1           | every turn           | current greedy hex pursuer                 |
| brute            | 2           | every other turn     | slower but takes 2 shotgun hits            |
| skitter          | 1           | every turn + 1       | fast, alternates 2-step burst with pause   |

Encoding: in overlay mode, add a `class` field to the monster JS
object.  In pure-CA mode, this requires either extending K=4 to
K=8 (which breaks the pact substrate) or stealing 1-bit class info
from the overlay layer alongside items.  The latter preserves
spoeqi compatibility.

### 10c. Damage typing (hitscan vs projectile)

A monster type that fires a projectile would be a real shift in
combat tempo.  Spawn a `projectile` overlay entry travelling at 1
cell per CA tick in the direction toward the player at fire time;
on contact deal damage and remove.  This adds the "find cover"
tactic that doom_ca completely lacks — currently the only tactic
is "shoot first."

### 10d. Armor pickups

Two-line change in `pickupAt`:

    else if (it.type === 'armor')  player.armor = Math.min(100, player.armor + 50);

And in damage code: `dmg = Math.max(0, dmg - player.armor/3); player.armor = Math.max(0, player.armor - dmg/2);`
This roughly mirrors Doom's green-armor 1/3 absorption (see
`P_DamageMobj` in `p_inter.c`).  Adds a new dial for the GA to
play with (`armor_count` gene field).

### 10e. Automap / minimap

Doom's `SPR_PMAP` pickup reveals the entire map (`p_inter.c:518`).
doom_ca could add a small minimap canvas showing the BFS-reachable
region, fogged until visited, with the exit always marked once a
`map` pickup is collected.  The reachability data is already
computed by `placeLevel` (`engine.js:288-307`) — just needs to be
exposed to the runtime.

### 10f. Exit switch puzzle

Currently the exit is **walk-onto-cell-to-win**
(`play_runtime.js:531`).  Doom's exits are sometimes **switches**
(`SPR_BAR1` etc., with linedef special 11).  A trivial extension:
make the exit cell require a "use key" press (Space already exists
but is mapped to fire) to actually trigger the win.  Adds 30
seconds of "where do I go from here?" reading time per level.

### 10g. Light levels per cell

A `light` overlay field per cell — derived from CA tick density at
that cell, perhaps — would let doom_ca render fog-of-war that
breathes with the CA.  Walls in dim rooms could fade to
`COL_WALL_DK` (already in the palette at
`play_runtime.js:245`) at a per-cell distance threshold.  Two
lines in `draw`, one new array.

### 10h. Berserk pack

Borrowing Doom's `SPR_PSTR` (`p_inter.c:495-502`): a pickup that
fully heals and grants a temporary "fist mode" — close-combat
adjacency kills monsters at zero ammo cost for ~10 turns.  Already
matches the way doom_ca treats unarmed-kills (one mutual hit kills
the monster).  Just add a `berserk_turns_remaining` counter, skip
the `player.hp -= 30` damage while it's > 0.

### 10i. Episode chaining

Doom episodes are 9 connected maps with a story crawl between.
doom_ca's natural episode would be **one playthrough across all
64 pact components**, in order — each component being a "map" with
its own rule, palette, meter, and difficulty curve.  The
`tap_url_template` mechanic already supports per-component
indexing; only the front-end needs to chain `play.html` redirects
on `gameOver === 'won'`.

### 10j. Mobile / touch controls

Doom had Boom controls.  doom_ca's keyboard layout works on desktop
but is hostile to mobile.  Six on-screen hex-direction buttons plus
fire/wait/reset would cover everything.

### 10k. The reverse direction

It's worth noting what _doom_ca already has that Doom doesn't_:

* A 4-state hex CA backing every pixel.
* 16 cultural music meters cyclable at runtime.
* Deterministic live multiplayer parity (not just demos).
* A breedable genome and tournament GA.
* A sealed-pact substrate that any party with the pact key can
  reproduce.
* Per-game soundtrack composed at runtime from the same rule that
  draws the walls.

In other words, doom_ca is not a partial Doom remake — it's a Doom
shaped to a different substrate.  The borrowing list above is about
which Doom-shaped affordances would translate well; doom_ca is also
exploring affordances Doom never had access to.


## Next steps

In rough order of value-per-effort:

1. **SFX layer in `music.js`** — wire a generic
   `DoomMusic.triggerSfx(name)` that schedules a short envelope-shaped
   note from the CA-derived wavetable.  Hooks: `playerFire`,
   `pickupAt`, monster contact, door open, level win/loss.
   ~80 LOC.
2. **Armor + bonus pickups** — extend `placeLevel` candidates list,
   add gene fields, add damage absorption.  ~30 LOC across
   `engine.js` and `play_runtime.js`.
3. **Multiple monster classes via overlay class field** — keep CA
   K=4 invariant.  ~120 LOC.
4. **Automap reveal** — small canvas to the right of the main
   canvas, BFS dist already known.  ~60 LOC of pure rendering.
5. **Exit switch instead of walk-onto** — one new keybind, two
   conditionals.  ~20 LOC.
6. **Episode chaining** — `play.html` reads
   `?next_component=N+1` on win, redirects via `views.py`.
   ~40 LOC.
7. **Berserk pack** — pickup type + turn counter + damage skip.
   ~25 LOC.
8. **Per-cell light overlay** — derive from CA tick density,
   feed into wall colour.  ~50 LOC.
9. **Touch controls** — six hex direction buttons + fire / wait /
   reset.  ~100 LOC of HTML + handlers.
10. **Projectile monsters** — overlay projectile entries moving 1
    cell per tick.  ~150 LOC.  Highest game-feel impact, highest
    integration cost.

Anything that requires breaking the K=4 pact substrate (more cell
states, per-cell HP encoded in the CA) is **out of scope** —
doom_ca's whole identity is "Doom that runs on a sealed spoeqi
pact rule," and the K=4 invariant is what keeps two players able
to reproduce each other's playthroughs.
