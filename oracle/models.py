"""Oracle app models.

Phase 1 of the Oracle app is deliberately schema-free — decisions,
inference, and trained trees all live as JSON files on disk. Phase 2
will add an OracleLabel model here so operators can provide feedback
('this decision was wrong') for re-training. For now this module is
just a placeholder so Django's app machinery has something to import.
"""

# from django.db import models  # uncomment when Phase 2 lands
