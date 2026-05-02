# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.core.management.base import BaseCommand

from agentcow.postgres.adapters.django import cow_lib
from plane.cow.excludes import PLANE_EXCLUDED_APPS, PLANE_EXCLUDED_TABLES


class Command(BaseCommand):
    help = "Enable Copy-On-Write on every eligible app table (FK-topo order)."

    def add_arguments(self, parser):
        parser.add_argument("--database", default="default", help="Django DB alias")
        parser.add_argument(
            "--exclude-app",
            action="append",
            default=[],
            help="Extra Django app_label to exclude. May be repeated.",
        )
        parser.add_argument(
            "--exclude-table",
            action="append",
            default=[],
            help="Extra db_table to exclude. May be repeated.",
        )

    def handle(self, *args, **options):
        enabled = cow_lib.enable_cow_for_all_models(
            extra_excluded_apps=set(options["exclude_app"]) | PLANE_EXCLUDED_APPS,
            extra_excluded_tables=set(options["exclude_table"]) | PLANE_EXCLUDED_TABLES,
            using=options["database"],
        )
        self.stdout.write(self.style.SUCCESS(f"COW enabled on {len(enabled)} tables."))
        for name in enabled:
            self.stdout.write(f"  - {name}")
