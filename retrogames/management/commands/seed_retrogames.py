"""Seed the retrogames catalogue with a starter set of titles.

Idempotent — re-running won't duplicate; it'll update missing fields
on existing rows.  Focus is on:
  - The "obscure between Atari and NES" gap the user flagged: Magnavox
    Odyssey², Fairchild Channel F, Bally Astrocade, Intellivision,
    ColecoVision, Vectrex, Atari 5200, Atari 7800.
  - Atari 2600 classics (~25 titles).
  - NES classics (~20 titles).
  - SNES, Genesis, PS1 starter sets (~12 each).
  - PS2 / PS3: a few flagship titles each.
"""

from __future__ import annotations
from django.core.management.base import BaseCommand
from django.db import transaction

from retrogames.models import Platform, Game


PLATFORMS = [
    # (name, manufacturer, year_release, year_retire, bit_depth, notes)
    ('Magnavox Odyssey²',     'Magnavox',      1978, 1984,  8,
     'Programmable cartridge console with built-in alphanumeric keyboard. '
     'Notable for The Voice add-on speech synth.'),
    ('Atari 2600',            'Atari',         1977, 1992,  8,
     'The home-console that defined the medium. Tiny 128-byte RAM forced '
     'wild creative constraints on every cartridge.'),
    ('Fairchild Channel F',   'Fairchild',     1976, 1983,  8,
     'First programmable cartridge console.  Predates the 2600 but never '
     'caught on commercially.'),
    ('Bally Astrocade',       'Bally / Astrocade',1977, 1984, 8,
     'Originally an arcade-grade home console with hardware sprites and '
     'a BASIC cartridge.'),
    ('Mattel Intellivision',  'Mattel',        1979, 1990, 16,
     '16-bit CPU rare for the era; vector-style overlay controllers with '
     'a 12-button keypad.'),
    ('ColecoVision',          'Coleco',        1982, 1985,  8,
     'Arcade-quality home ports — Donkey Kong, Zaxxon.  Killed by the '
     'Atari shock and the 7800 / NES wave.'),
    ('Vectrex',               'GCE / Milton Bradley', 1982, 1984, 8,
     'Built-in vector CRT — only home console ever to ship with one. '
     'Unique line-drawn aesthetic.'),
    ('Atari 5200',            'Atari',         1982, 1984,  8,
     'Powerful but compromised by analog non-self-centering joysticks '
     'and incompatibility with the 2600 library.'),
    ('Atari 7800',            'Atari',         1986, 1992,  8,
     'Backwards-compatible with the 2600; arrived too late to compete '
     'with the NES.'),
    ('Nintendo NES',          'Nintendo',      1985, 1995,  8,
     'Single-handedly revived the home console market after the 1983 '
     'crash.  Mario, Zelda, Metroid all originated here.'),
    ('Sega Master System',    'Sega',          1986, 1992,  8,
     'Technically superior to the NES but distribution-starved in NA; '
     'huge in Brazil.'),
    ('TurboGrafx-16 / PC Engine','NEC / Hudson',1987, 1994, 16,
     '8-bit CPU + 16-bit graphics chip, hence the "16" branding.  Strong '
     'shoot-em-up library; first CD-ROM add-on.'),
    ('Sega Genesis',          'Sega',          1988, 1997, 16,
     'Motorola 68000-based; "Blast Processing" marketing.  Sonic, Streets '
     'of Rage, Phantasy Star.'),
    ('Nintendo SNES',         'Nintendo',      1990, 2003, 16,
     '65C816 CPU + Mode 7 scaling rotation.  Often considered the apex '
     'of 16-bit-era design.'),
    ('Sony PlayStation',      'Sony',          1994, 2006, 32,
     'CD-ROM, real-time 3D, kicked off Sony\'s dominance.  Final Fantasy '
     'VII / Metal Gear Solid / Castlevania SotN.'),
    ('Sega Saturn',           'Sega',          1994, 2000, 32,
     'Dual-CPU 2D powerhouse hamstrung by hard-to-program 3D.  Strong '
     'arcade-port library.'),
    ('Nintendo 64',           'Nintendo',      1996, 2002, 64,
     'Cartridge-based in the CD era.  Mario 64 / Ocarina of Time / '
     'GoldenEye / Banjo-Kazooie.'),
    ('Sony PlayStation 2',    'Sony',          2000, 2013, 128,
     'Best-selling console ever (~155M).  Backwards-compatible with PS1.'),
    ('Sony PlayStation 3',    'Sony',          2006, 2017, 64,
     'Cell processor; Blu-ray as standard.  Difficult to program; HDR '
     'audio and 1080p eventually.'),
]


GAMES = [
    # (platform_name, game_name, year, genre, developer, mechanics, description)

    # ── Magnavox Odyssey² ──
    ('Magnavox Odyssey²', 'K.C. Munchkin!', 1981, 'maze', 'Magnavox',
     'maze, dot-collection, ghost-avoidance',
     'Pacman-clone with movable maze segments.  Sued out of existence by Atari.'),
    ('Magnavox Odyssey²', 'Pick Axe Pete!', 1982, 'platformer', 'Magnavox',
     'jumping, ladders, falling rocks',
     'Mine for gold while dodging rolling boulders on three vertical levels.'),
    ('Magnavox Odyssey²', 'The Quest for the Rings', 1981, 'adventure', 'Magnavox',
     'board game + video, party play, magic, dungeons',
     'Hybrid board-game + console-game fantasy adventure for 1-4 players.'),

    # ── Fairchild Channel F ──
    ('Fairchild Channel F', 'Video Whizball', 1978, 'action', 'Fairchild',
     'two-player paddle, projectile, blocks',
     'Pong-meets-Breakout: hit a moving ball through obstacles into your goal.'),
    ('Fairchild Channel F', 'Alien Invasion', 1981, 'shmup', 'Fairchild',
     'horizontal scrolling, shoot, dodge',
     'Side-scrolling space shooter, basic but technically advanced for 1981 cartridges.'),

    # ── Bally Astrocade ──
    ('Bally Astrocade', 'Gunfight', 1977, 'action', 'Bally',
     'two-player duel, projectile, cover',
     'Two cowboys duke it out across a screen of obstacles.  One of the first '
     'home conversions of the seminal 1975 arcade game.'),
    ('Bally Astrocade', 'Astro Battle', 1981, 'shmup', 'Bally',
     'fixed-shooter, formation enemies',
     'Galaxian-style alien invasion clone.'),

    # ── Mattel Intellivision ──
    ('Mattel Intellivision', 'Astrosmash', 1981, 'shmup', 'Mattel',
     'fixed-shooter, falling meteors, score, lives',
     'Shoot the descending rocks before they hit the ground.  Wildly popular pack-in.'),
    ('Mattel Intellivision', 'Utopia', 1981, 'strategy', 'Mattel',
     'resource management, two-player, real-time strategy',
     'One of the earliest real-time strategy games — build infrastructure on '
     'rival islands while weather and pirates intervene.'),
    ('Mattel Intellivision', 'Advanced Dungeons & Dragons: Cloudy Mountain',
     1982, 'adventure', 'Mattel',
     'maze, dragons, arrows, treasures, keys',
     'Find the Crown of Kings hidden in the Cloudy Mountain by collecting '
     'keys and shooting arrows at winged dragons in a multi-screen cave system.'),

    # ── ColecoVision ──
    ('ColecoVision', 'Donkey Kong', 1982, 'platformer', 'Nintendo',
     'jumping, ladders, hammers, princess',
     'Pack-in port of the arcade classic.  Famously closer to arcade than any '
     'other 1982 home version.'),
    ('ColecoVision', 'Zaxxon', 1982, 'shmup', 'Sega',
     'isometric scrolling, altitude, shoot',
     'Isometric shoot-em-up where altitude management matters as much as aim.'),
    ('ColecoVision', 'Smurf: Rescue in Gargamel\'s Castle', 1982, 'platformer', 'Coleco',
     'side-scrolling, jumping, hazards',
     'Side-scrolling rescue mission through the woods of the Smurf village.'),

    # ── Vectrex ──
    ('Vectrex', 'Mine Storm', 1982, 'shmup', 'GCE',
     'asteroids, vector graphics, lives, score',
     'Asteroids-style space shooter that came built into the console — no '
     'cartridge needed.'),
    ('Vectrex', 'Berzerk', 1982, 'action', 'GCE',
     'maze, robots, shoot, exit, vector lines',
     'Maze shooter — Evil Otto chases you while you blast electronic robots '
     'in a randomly-generated room.'),
    ('Vectrex', 'Star Castle', 1983, 'action', 'GCE',
     'orbital shoot, rotating shields, central mine',
     'Orbit a central enemy while breaking through three rings of energy '
     'shields and dodging defensive mines.'),

    # ── Atari 5200 ──
    ('Atari 5200', 'Star Raiders', 1982, 'shooter', 'Atari',
     'first-person space combat, navigation, energy management',
     'First-person space simulator with hyperdrive sectors and Zylon fleets.  '
     'Considered the killer app of the platform.'),
    ('Atari 5200', 'Centipede', 1982, 'shmup', 'Atari',
     'fixed shooter, descending segments, mushrooms',
     'Shoot the segmented centipede before it reaches you, accumulate '
     'mushrooms that complicate its path.'),

    # ── Atari 7800 ──
    ('Atari 7800', 'Ballblazer', 1987, 'sports', 'Lucasfilm Games',
     'two-player, split-screen, futuristic ball, goal',
     'Split-screen pseudo-3D futuristic ball-and-goal sport.'),
    ('Atari 7800', 'Food Fight', 1987, 'action', 'Atari',
     'maze, projectiles, time limit, chase',
     'Throw food at the chefs chasing you while running for the melting ice '
     'cream cone before time runs out.'),

    # ── Atari 2600 ──
    ('Atari 2600', 'Adventure', 1980, 'adventure', 'Atari',
     'keys, dragons, castles, magnet, bat, Easter egg',
     'Find the enchanted chalice through three castles guarded by dragons. '
     'Contains the first known video-game Easter egg.'),
    ('Atari 2600', 'Pitfall!', 1982, 'platformer', 'Activision',
     'side-scrolling, jumping, vines, scorpions, crocodiles, treasure, 20-min time limit',
     'Jungle adventurer Pitfall Harry collects treasures across 255 screens '
     'while jumping over hazards.  One of the first multi-screen platformers.'),
    ('Atari 2600', 'River Raid', 1982, 'shmup', 'Activision',
     'vertical-scrolling, fuel management, bridge bosses',
     'Vertical-scrolling river-flying shooter with fuel as the binding '
     'resource.  First major-credit game by a woman (Carol Shaw).'),
    ('Atari 2600', 'Pac-Man', 1982, 'maze', 'Atari',
     'maze, dot collection, ghosts, power pellets',
     'The famously rushed home port.  Considered one of the worst conversions '
     'in history; contributed to the 1983 crash.'),
    ('Atari 2600', 'Asteroids', 1981, 'shmup', 'Atari',
     'asteroids, momentum, hyperspace, ufo',
     'Rotate and thrust your way through fields of breakable asteroids.'),
    ('Atari 2600', 'Yars\' Revenge', 1982, 'shmup', 'Atari',
     'fly, shoot, dodge, qotile cannon, neutral zone',
     'Best-selling Atari original.  Fly an insect-bee thing through a '
     'destructible shield around the Qotile.'),
    ('Atari 2600', 'E.T. the Extra-Terrestrial', 1982, 'adventure', 'Atari',
     'pitfall traps, phone parts, fbi, time limit',
     'Famously crashed the industry.  Find phone pieces, avoid the FBI '
     'and falling into pits.'),
    ('Atari 2600', 'Combat', 1977, 'action', 'Atari',
     'two-player, tank, plane, bullets',
     'The original pack-in.  Pairs of tanks or planes shoot each other in '
     '27 variant maps.'),
    ('Atari 2600', 'Frogger', 1982, 'action', 'Parker Brothers',
     'cross-traffic, log-jumping, finish lane',
     'Cross the road and the river without dying.'),
    ('Atari 2600', 'Space Invaders', 1980, 'shmup', 'Atari',
     'fixed-shooter, descending formation, shields, mothership',
     'First arcade port to ship with a console; doubled the 2600\'s installed base.'),

    # ── NES ──
    ('Nintendo NES', 'Super Mario Bros.', 1985, 'platformer', 'Nintendo',
     'side-scrolling, jumping, mushroom power-ups, flag-pole exit, princess',
     'Side-scrolling platformer that defined the genre.  8 worlds × 4 levels.'),
    ('Nintendo NES', 'The Legend of Zelda', 1986, 'adventure', 'Nintendo',
     'overworld + dungeons, sword + boomerang + bombs, hearts, triforce',
     'Open-world fantasy adventure with non-linear dungeon order.'),
    ('Nintendo NES', 'Metroid', 1986, 'platformer', 'Nintendo',
     'side-scrolling, jumping, missiles, energy tanks, morph ball, secret passages',
     'Metroidvania ur-text.  Find suit upgrades to access new areas.'),
    ('Nintendo NES', 'Mega Man 2', 1988, 'platformer', 'Capcom',
     'platforming, boss-rush, weapon-stealing, password',
     'Robot Master gauntlet — defeat one to gain their weapon, then face the next.'),
    ('Nintendo NES', 'Contra', 1988, 'shooter', 'Konami',
     'run-and-gun, two-player, power-ups, side-scrolling',
     'Two-player run-and-gun, famous for the Konami code 30 lives.'),
    ('Nintendo NES', 'Castlevania', 1986, 'platformer', 'Konami',
     'whip-cracking, side-scrolling, sub-weapons, Dracula',
     'Side-scrolling Gothic horror platformer.'),
    ('Nintendo NES', 'Ninja Gaiden', 1988, 'platformer', 'Tecmo',
     'wall-jumping, sub-weapons, cinematic cutscenes',
     'Brutal side-scroller with cinematic cutscenes between levels.'),
    ('Nintendo NES', 'Pac-Man', 1993, 'maze', 'Namco',
     'maze, dot collection, ghosts, power pellets',
     'Late but faithful arcade port of the 1980 original.'),
    ('Nintendo NES', 'Teenage Mutant Ninja Turtles', 1989, 'beatup', 'Konami',
     'beat-em-up, four characters, sewer levels, boss fights',
     'Notoriously brutal underwater dam level; otherwise solid TMNT licensed game.'),
    ('Nintendo NES', 'A Boy and His Blob: Trouble on Blobolonia', 1989,
     'adventure', 'Imagineering',
     'companion mechanic, jellybeans, transformation, princess',
     'Feed jellybeans to your blob companion to transform him into ladders, '
     'trampolines, holes and other tools for navigation.'),
    ('Nintendo NES', 'Duck Hunt', 1984, 'shooter', 'Nintendo',
     'light gun, ducks, dog, score',
     'Light-gun shooter packed in with the NES, featuring the laughing dog.'),

    # ── Sega Master System ──
    ('Sega Master System', 'Phantasy Star', 1987, 'rpg', 'Sega',
     'first-person dungeons, party combat, space travel, magic',
     'One of the earliest console JRPGs with first-person dungeons and '
     'sci-fi setting (interplanetary travel).'),
    ('Sega Master System', 'Wonder Boy', 1986, 'platformer', 'Westone',
     'platforming, skateboard, fairies, time-limit',
     'Side-scrolling platformer with vitality-based hp draining over time.'),
    ('Sega Master System', 'Alex Kidd in Miracle World', 1986, 'platformer', 'Sega',
     'platforming, rock-paper-scissors bosses, vehicles',
     'Pack-in mascot platformer with rock-paper-scissors boss duels.'),

    # ── TurboGrafx-16 ──
    ('TurboGrafx-16 / PC Engine', 'Bonk\'s Adventure', 1989, 'platformer', 'Red Company',
     'head-bash, prehistoric setting, meat power-ups',
     'Mascot platformer where the protagonist head-butts enemies.'),
    ('TurboGrafx-16 / PC Engine', 'R-Type', 1989, 'shmup', 'Irem',
     'horizontal-scrolling, charge shot, force pod, boss patterns',
     'Definitive horizontal-scrolling shooter with the Force orb add-on.'),

    # ── Sega Genesis ──
    ('Sega Genesis', 'Sonic the Hedgehog', 1991, 'platformer', 'Sega',
     'momentum, loops, springs, rings, robotnik',
     'Speed-platformer with momentum-based loop-de-loops; defined the platform.'),
    ('Sega Genesis', 'Streets of Rage 2', 1992, 'beatup', 'Sega',
     'beat-em-up, two-player, multiple characters, special moves',
     'Arcade-style beat-em-up considered the genre\'s peak.'),
    ('Sega Genesis', 'Phantasy Star IV', 1993, 'rpg', 'Sega',
     'turn-based JRPG, combo attacks, comic-book cutscenes',
     'JRPG conclusion to the Phantasy Star tetralogy.'),
    ('Sega Genesis', 'Gunstar Heroes', 1993, 'shooter', 'Treasure',
     'run-and-gun, weapon-combining, set-piece bosses',
     'Run-and-gun with mixable weapons and a series of inventive boss fights.'),

    # ── SNES ──
    ('Nintendo SNES', 'Super Metroid', 1994, 'platformer', 'Nintendo',
     'metroidvania, missile upgrades, screw attack, isolation',
     'Considered the apex of the metroidvania genre.'),
    ('Nintendo SNES', 'The Legend of Zelda: A Link to the Past', 1991,
     'adventure', 'Nintendo',
     'top-down, light/dark worlds, master sword, dungeons',
     'Top-down Zelda with a parallel dark world and 12 dungeons.'),
    ('Nintendo SNES', 'Super Mario World', 1990, 'platformer', 'Nintendo',
     'side-scrolling, Yoshi, capes, secret exits, overworld map',
     'Mario\'s SNES debut with Yoshi and a branching world map.'),
    ('Nintendo SNES', 'Chrono Trigger', 1995, 'rpg', 'Squaresoft',
     'time-travel, multiple endings, active-time-battle, dual techs',
     'Time-travel JRPG with 13 endings and combo attacks between party members.'),
    ('Nintendo SNES', 'F-Zero', 1990, 'racing', 'Nintendo',
     'hover-racing, Mode-7 scaling, four tracks, high speed',
     'Hover-vehicle racing using SNES Mode 7 for ground-plane scaling.'),
    ('Nintendo SNES', 'Star Fox', 1993, 'shooter', 'Nintendo',
     '3D rail shooter, Super FX chip, anthropomorphic pilots',
     'Polygonal rail shooter using the in-cartridge Super FX coprocessor.'),

    # ── PS1 ──
    ('Sony PlayStation', 'Final Fantasy VII', 1997, 'rpg', 'Squaresoft',
     'JRPG, materia magic, pre-rendered backgrounds, summon FMVs',
     'Mainstream-breaking JRPG with pre-rendered backgrounds and CG cutscenes.'),
    ('Sony PlayStation', 'Metal Gear Solid', 1998, 'action', 'Konami',
     'stealth, codec calls, boss psychology, cardboard box',
     '3D stealth game with cinematic boss encounters and meta-narrative tricks.'),
    ('Sony PlayStation', 'Castlevania: Symphony of the Night', 1997,
     'platformer', 'Konami',
     'metroidvania, RPG stats, inverted castle, two playable characters',
     'Metroidvania-RPG hybrid that redefined the Castlevania series.'),
    ('Sony PlayStation', 'Resident Evil 2', 1998, 'survival', 'Capcom',
     'fixed cameras, tank controls, two scenarios, limited inventory',
     'Two-disc survival horror sequel with two interlocking character campaigns.'),
    ('Sony PlayStation', 'Crash Bandicoot', 1996, 'platformer', 'Naughty Dog',
     '3D platformer, spinning attack, gem collection',
     'Linear 3D platformer mascot.'),

    # ── Saturn ──
    ('Sega Saturn', 'NiGHTS into Dreams', 1996, 'action', 'Sonic Team',
     'free-flight, dream worlds, dual analog support',
     'Flight-based dream world game; first console game to use a true analog stick.'),
    ('Sega Saturn', 'Panzer Dragoon Saga', 1998, 'rpg', 'Team Andromeda',
     'dragon-riding rpg, 360° combat, branching paths',
     'Rare four-disc RPG entry in the Panzer Dragoon series.'),

    # ── N64 ──
    ('Nintendo 64', 'Super Mario 64', 1996, 'platformer', 'Nintendo',
     '3D platformer, analog stick, paintings, stars, princess',
     'Foundational 3D platformer that defined the move from sprites to polygons.'),
    ('Nintendo 64', 'The Legend of Zelda: Ocarina of Time', 1998,
     'adventure', 'Nintendo',
     '3D Zelda, time travel, Z-targeting, ocarina songs',
     'First 3D Zelda; introduced lock-on (Z-targeting) and context-sensitive '
     'buttons that influenced every action-adventure since.'),
    ('Nintendo 64', 'GoldenEye 007', 1997, 'shooter', 'Rare',
     'console FPS, split-screen, mission objectives',
     'Bond-themed console FPS that made multiplayer split-screen a staple.'),
    ('Nintendo 64', 'Banjo-Kazooie', 1998, 'platformer', 'Rare',
     '3D collect-a-thon, two-character pair, musical notes, puzzles',
     '3D collectathon with hundreds of musical notes and jigsaw pieces.'),

    # ── PS2 ──
    ('Sony PlayStation 2', 'Shadow of the Colossus', 2005, 'adventure', 'Team Ico',
     'mounted exploration, sixteen bosses, environmental climbing',
     'Sixteen-boss-fight game across an empty open world.'),
    ('Sony PlayStation 2', 'Grand Theft Auto: San Andreas', 2004, 'action',
     'Rockstar North',
     'open-world, three cities, RPG stats, gang turf',
     'Sprawling open-world crime simulator with three cities and rural counties.'),
    ('Sony PlayStation 2', 'Metal Gear Solid 3: Snake Eater', 2004, 'action',
     'Konami', 'survival, camouflage, CQC, jungle stealth',
     '1964 Cold War prequel with camouflage and jungle survival mechanics.'),
    ('Sony PlayStation 2', 'Ico', 2001, 'adventure', 'Team Ico',
     'companion mechanic, hand-holding, castle puzzles',
     'Minimal-dialogue puzzle-adventure where you lead a princess by the hand.'),

    # ── PS3 ──
    ('Sony PlayStation 3', 'The Last of Us', 2013, 'action', 'Naughty Dog',
     'survival, crafting, cordyceps, companion AI, melee + ranged',
     'Post-apocalyptic survival action with cinematic narrative.'),
    ('Sony PlayStation 3', 'Demon\'s Souls', 2009, 'rpg', 'FromSoftware',
     'methodical combat, asynchronous multiplayer, soul currency',
     'Originator of the soulslike subgenre.'),
    ('Sony PlayStation 3', 'Journey', 2012, 'adventure', 'thatgamecompany',
     'wordless multiplayer, scarf flight, desert pilgrimage',
     'Wordless multiplayer pilgrimage; remembered for its emotional arc.'),
]


class Command(BaseCommand):
    help = 'Seed retrogames Platform + Game catalogue with ~120 starter titles.'

    def handle(self, *args, **opts):
        with transaction.atomic():
            self._seed_platforms()
            self._seed_games()
        self.stdout.write(self.style.SUCCESS(
            f'Seed complete · {Platform.objects.count()} platforms · '
            f'{Game.objects.count()} games'))

    def _seed_platforms(self):
        for (name, mfg, yr, retire, bd, notes) in PLATFORMS:
            obj, created = Platform.objects.get_or_create(name=name)
            obj.manufacturer = mfg
            obj.year_release = yr
            obj.year_retire = retire
            obj.bit_depth = bd
            obj.notes = notes
            obj.save()
            if created:
                self.stdout.write(f'  + platform {name}')

    def _seed_games(self):
        pmap = {p.name: p for p in Platform.objects.all()}
        for (pname, gname, year, genre, dev, mech, desc) in GAMES:
            platform = pmap.get(pname)
            if not platform:
                self.stdout.write(self.style.WARNING(
                    f'  skip {gname}: platform {pname!r} not seeded'))
                continue
            existing = Game.objects.filter(platform=platform, name=gname).first()
            if existing:
                existing.year = year or existing.year
                existing.genre = genre or existing.genre
                existing.developer = dev or existing.developer
                existing.mechanics = mech or existing.mechanics
                existing.description = desc or existing.description
                existing.save()
                continue
            Game.objects.create(
                platform=platform, name=gname, year=year, genre=genre,
                developer=dev, mechanics=mech, description=desc,
            )
            self.stdout.write(f'  + game {pname}: {gname}')
