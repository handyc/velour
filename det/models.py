"""Det — deterministic engine, counterpart to Oracle / Identity / Evolution.

Scope is deliberately TBD at scaffold time; see memory note
`project_det_app_backlog`. When the shape of the app firms up, the first
model probably wants to capture a *rule* (inputs → output) so it can be
replayed byte-for-byte. Keep it in the spirit of: Identity is poetry,
Oracle is judgment, Evolution is search — Det is the thing that, given
the same inputs, always returns the same answer.
"""

from django.db import models  # noqa: F401 — intentional, models arrive later
