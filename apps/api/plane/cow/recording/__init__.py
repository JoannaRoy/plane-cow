# (b) Recording API — ground-truth and agent session tracking.
#
# These endpoints and models exist so Plane can store GT recordings and agent
# runs in its own DB. In a different deployment this entire sub-package could
# be replaced by equivalent storage in the harness — the only hard dependency
# on plane.cow.core is the session-operations endpoint used for scoring.
