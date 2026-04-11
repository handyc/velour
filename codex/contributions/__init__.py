"""Codex periodic-report contribution modules.

Each module under this package exposes a `contribute(start_dt, end_dt)`
function that returns a list of `SectionContribution` instances. The
`build_report` management command walks the configured contributors
for a recipe, calls each one, and assembles the result into a Manual.

The contribution functions live here (in codex) rather than in each
contributing app's directory because we want apps to remain unaware
of codex. The coupling runs in only one direction: codex imports
from other apps; other apps don't import from codex.

Adding a new contributor: drop a `codex/contributions/<slug>.py`
exposing `contribute(start_dt, end_dt)`. Then add `<slug>` to a
recipe's `contributors` field via the admin or the seeder.
"""

from dataclasses import dataclass, field


@dataclass
class SectionContribution:
    title: str
    body: str = ''
    sidenotes: str = ''
    sort_offset: int = 0     # finer-grained ordering within the contributor's slot
