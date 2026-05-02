# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Copy-On-Write (COW) integration for Plane.

Layout
------

(a) core/        Runtime COW machinery — middleware, commit/discard endpoints,
                 session-operations query. ~230 lines. This is what any Django
                 project would need to replicate to adopt COW.

(b) recording/   GT and agent session tracking — models, CRUD endpoints, and
                 eval scoring helpers. ~400 lines. Could live in the harness
                 instead; included here for convenience.

(c) management/  Operational commands — deploy, enable, disable, migrate.
     commands/   ~160 lines. Deployment-specific; depends on your infra.

The framework-generic adapter layer (executor, middleware base, ORM helpers)
has been extracted to ``agentcow.postgres.adapters.django`` in the agent-cow library.
"""
