# (a) Core COW functionality — everything needed for COW to operate at runtime.
#
# This is the minimal surface any Django project would replicate to adopt COW:
# commit/discard/status endpoints and the single session-operations query the
# harness uses to retrieve operation IDs for scoring.
