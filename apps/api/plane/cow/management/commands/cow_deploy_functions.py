# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.core.management.base import BaseCommand

from plane.cow.adapter import cow_lib


class Command(BaseCommand):
    help = "Deploy agent-cow PL/pgSQL helper functions to the database (one-time setup)."

    def add_arguments(self, parser):
        parser.add_argument("--database", default="default", help="Django DB alias")

    def handle(self, *args, **options):
        using = options["database"]
        self.stdout.write(f"Deploying COW functions to {using}...")
        cow_lib.deploy_cow_functions(using=using)
        self.stdout.write(self.style.SUCCESS("COW functions deployed."))
