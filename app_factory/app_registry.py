"""Registry of Velour apps for the selective-clone flow.

Two buckets:

- CORE_APPS: always included in any clone. These are the operating
  substrate — Identity, Codex, the dashboard chrome, mail, security,
  the system-management UIs. Removing any of them breaks the boot or
  the basic admin experience.

- OPTIONAL_APPS: feature/creative apps. Each carries a ``depends_on``
  list of *other OPTIONAL apps* (CORE deps are implicit). Selecting an
  OPTIONAL app via the create-form checkboxes implies selecting its
  declared deps; ``compute_closure`` does the walk.

The intent is for clones to ship with the full Velour by default, and
let operators trim down by un-checking apps they don't need. A node
running just `naiad` + `nodes` + the CORE is a perfectly reasonable
"sensor-only" Velour that can still talk to a fuller Velour elsewhere.

This registry is data, not code — extending it is one entry per new
app, plus an honest dependency declaration. Inter-app imports that
aren't declared here will silently break a stripped-down clone, so be
generous with deps when in doubt.
"""

# Operating substrate — included in every clone, no checkbox shown.
# Channels + daphne are infrastructure (WebSocket terminal); identity +
# codex are universal substrate that almost every other app touches.
CORE_APPS = [
    'channels',
    'daphne',
    'identity',
    'codex',
    'dashboard',
    'landingpage',
    'sysinfo',
    'mail',
    'terminal',
    'security',
    'services',
    'logs',
    'app_factory',
    'hosts',
    'maintenance',
    'graphs',
    'backups',
    'databases',
    'winctl',
]


# Feature/creative apps. Each gets a checkbox in the clone form; the
# closure of the selection (via depends_on) is what ends up in the clone.
# depends_on lists OTHER OPTIONAL apps; CORE is implicit.
OPTIONAL_APPS = [
    # --- Time / sky / environment ----------------------------------
    {'slug': 'chronos',       'name': 'Chronos',
     'description': 'Calendar, sky tracking, weather, briefing.',
     'depends_on': []},

    # --- Fleet / IoT -----------------------------------------------
    {'slug': 'experiments',   'name': 'Experiments',
     'description': 'Sensor-experiment tables.',
     'depends_on': []},
    {'slug': 'nodes',         'name': 'Nodes (ESP fleet)',
     'description': 'Field-node provisioning, OTA, telemetry.',
     'depends_on': ['experiments', 'oracle']},
    {'slug': 'bodymap',       'name': 'Bodymap',
     'description': 'Wearable mesh + ATtiny workshop.',
     'depends_on': ['experiments', 'nodes']},

    # --- Data plumbing ---------------------------------------------
    {'slug': 'datalift',      'name': 'Datalift',
     'description': 'Lift legacy MySQL/WordPress sites into Django.',
     'depends_on': []},
    {'slug': 'helix',         'name': 'Helix (genome viewer)',
     'description': 'DNA/RNA viewer + annotator for FASTA / GenBank.',
     'depends_on': []},
    {'slug': 'conduit',       'name': 'Conduit',
     'description': 'Pipelines + Slurm/local job routing.',
     'depends_on': []},
    {'slug': 'cartography',   'name': 'Cartography',
     'description': 'Multi-scale maps.',
     'depends_on': []},
    {'slug': 'hpc',           'name': 'HPC',
     'description': 'SSH/SLURM cluster access.',
     'depends_on': []},

    # --- Lab tools -------------------------------------------------
    {'slug': 'naiad',         'name': 'Naiad',
     'description': 'Water purification system designer.',
     'depends_on': ['nodes', 'conduit']},
    {'slug': 'powerlab',      'name': 'Power Lab',
     'description': 'Schematics for tiny-device power.',
     'depends_on': []},
    {'slug': 'roomplanner',   'name': 'Room Planner',
     'description': 'Lab room layout (uses Aether for 3D wireframes).',
     'depends_on': ['aether']},

    # --- Creative / generative engines -----------------------------
    {'slug': 'aether',        'name': 'Aether (3D worlds)',
     'description': 'Browser-based 3D worlds with NPCs and portals.',
     'depends_on': ['grammar_engine', 'legolith', 'attic', 'bridge',
                    'lsystem', 'zoetrope']},
    {'slug': 'lsystem',       'name': 'L-System Plants',
     'description': 'Procedural plant species.',
     'depends_on': ['aether']},
    {'slug': 'legolith',      'name': 'Legolith',
     'description': 'Studded-brick worlds + worksheets.',
     'depends_on': ['lsystem']},
    {'slug': 'tiles',         'name': 'Tiles',
     'description': 'Wang tiles (square + hexagonal).',
     'depends_on': ['attic']},
    {'slug': 'automaton',     'name': 'Automaton',
     'description': 'Hex cellular automata.',
     'depends_on': ['tiles']},
    {'slug': 'det',           'name': 'Det',
     'description': 'Pattern detection on automaton output.',
     'depends_on': ['automaton', 'conduit', 'evolution']},
    {'slug': 'evolution',     'name': 'Evolution',
     'description': 'Recursive GA populations.',
     'depends_on': ['grammar_engine', 'lsystem']},
    {'slug': 'grammar_engine','name': 'Grammar Engine',
     'description': 'Shared speech engine.',
     'depends_on': []},
    {'slug': 'casting',       'name': 'Casting',
     'description': 'Model-search experiments + C/JS ports.',
     'depends_on': []},
    {'slug': 'lingua',        'name': 'Lingua',
     'description': 'Project-wide translations + flashcards + TTS.',
     'depends_on': ['muka']},
    {'slug': 'muka',          'name': 'Muka',
     'description': 'Face-related tooling.',
     'depends_on': ['lingua']},
    {'slug': 'agents',        'name': 'Agents',
     'description': 'Persistent NPCs (towns, hex grid).',
     'depends_on': ['aether']},

    # --- Documentation / publishing --------------------------------
    {'slug': 'displacer',     'name': 'Displacer',
     'description': 'Zotonic-clone CMS (Displacement).',
     'depends_on': []},
    {'slug': 'attic',         'name': 'Attic',
     'description': 'Media library (images / video / audio).',
     'depends_on': []},
    {'slug': 'zoetrope',      'name': 'Zoetrope',
     'description': 'Reels from Attic frames.',
     'depends_on': ['attic', 'aether', 'grammar_engine']},

    # --- Spaceflight / play ----------------------------------------
    {'slug': 'bridge',        'name': 'Bridge',
     'description': 'Spaceflight commander console.',
     'depends_on': ['aether', 'grammar_engine']},

    # --- Toys / smaller --------------------------------------------
    {'slug': 'agricola',      'name': 'Agricola',
     'description': 'Game.',
     'depends_on': []},
    {'slug': 'reckoner',      'name': 'Reckoner',
     'description': 'Compute cost from picojoules to exajoules.',
     'depends_on': []},
    {'slug': 'oneliner',      'name': 'Oneliner',
     'description': 'Sub-80-col C programs.',
     'depends_on': []},
    {'slug': 'condenser',     'name': 'Condenser',
     'description': 'Progressive distillation pipeline (backlog scaffold).',
     'depends_on': ['aether', 'automaton', 'bodymap', 'chronos',
                    'nodes', 'tiles']},
    {'slug': 'screen_gubi',   'name': 'Screen Gubi',
     'description': 'Screen aesthetic helpers.',
     'depends_on': ['aether', 'lsystem']},
    {'slug': 'oracle',        'name': 'Oracle',
     'description': 'Decision-tree judgment service.',
     'depends_on': []},
    {'slug': 'isolation',     'name': 'Isolation',
     'description': 'One-click hex-class scratch.',
     'depends_on': []},
    {'slug': 'agora',         'name': 'Agora',
     'description': 'University master framework.',
     'depends_on': []},
    {'slug': 'studious',      'name': 'Studious',
     'description': 'Studying tools.',
     'depends_on': []},
    {'slug': 'aggregator',    'name': 'Aggregator',
     'description': 'Cross-source aggregation.',
     'depends_on': []},
    {'slug': 'camlfornia',    'name': 'CAMLfornia',
     'description': 'CAML-flavoured experiments.',
     'depends_on': []},
    {'slug': 'radiant',       'name': 'Radiant',
     'description': 'Radiant scratch.',
     'depends_on': []},
]


OPTIONAL_BY_SLUG = {a['slug']: a for a in OPTIONAL_APPS}


def all_known_slugs():
    return set(CORE_APPS) | set(OPTIONAL_BY_SLUG)


def compute_closure(selected_slugs):
    """Return the set of OPTIONAL apps to actually include given the
    operator's selection. Walks ``depends_on`` transitively. Unknown
    slugs are silently ignored — the registry is the source of truth.
    """
    out = set()
    stack = [s for s in selected_slugs if s in OPTIONAL_BY_SLUG]
    while stack:
        slug = stack.pop()
        if slug in out:
            continue
        out.add(slug)
        for dep in OPTIONAL_BY_SLUG[slug].get('depends_on', []):
            if dep not in out and dep in OPTIONAL_BY_SLUG:
                stack.append(dep)
    return out


def included_apps(selected_optional_slugs):
    """The full set of apps that should end up in the clone — CORE plus
    the closure of the operator-selected optional apps."""
    return set(CORE_APPS) | compute_closure(selected_optional_slugs)
