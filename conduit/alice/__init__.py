"""ALICE HPC bundle protocol.

A 'bundle' is a self-contained directory tree under
``conduit/alice/bundles/<slug>/`` that an operator copies onto the ALICE
cluster, submits with ``sbatch``, and pulls back when results are ready.

The shape is intentionally pre-DB: every bundle is just files on disk so
the operator can read, edit, or refuse any of them before any compute
happens. The Conduit JobHandoff system can be layered on top later if we
want a web view of bundle status.

See ``conduit/alice/README.md`` for the protocol and the operator
workflow. Individual bundle generators live as siblings here
(e.g. ``metapact_ga.py``).
"""
