# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""COW-aware wrapper around ``manage.py migrate``.

Runs the equivalent of ``cow_disable`` → ``migrate`` → ``cow_enable`` so
Django's schema editor sees plain tables instead of views. All extra args
after ``--`` are forwarded to ``migrate``.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand

from plane.cow.adapter import cow_lib
from plane.cow.excludes import PLANE_EXCLUDED_APPS, PLANE_EXCLUDED_TABLES


class Command(BaseCommand):
    help = (
        "Run Django migrations under Copy-On-Write: disable COW, migrate, re-enable."
    )

    def add_arguments(self, parser):
        parser.add_argument("--database", default="default", help="Django DB alias")
        parser.add_argument(
            "--skip-disable",
            action="store_true",
            help="Skip the initial cow_disable step (e.g. when COW is not yet enabled).",
        )
        parser.add_argument(
            "--skip-enable",
            action="store_true",
            help="Skip the final cow_enable step.",
        )
        parser.add_argument(
            "migrate_args",
            nargs="*",
            help="Positional arguments forwarded to `manage.py migrate`.",
        )

    def handle(self, *args, **options):
        using = options["database"]

        if not options["skip_disable"]:
            self.stdout.write("[cow_migrate] disabling COW...")
            cow_lib.disable_cow_for_all_models(
                extra_excluded_apps=PLANE_EXCLUDED_APPS,
                extra_excluded_tables=PLANE_EXCLUDED_TABLES,
                using=using,
            )
            self.stdout.write(self.style.SUCCESS("[cow_migrate] COW disabled."))

        self.stdout.write("[cow_migrate] running migrate...")
        call_command("migrate", *options["migrate_args"], database=using)

        if not options["skip_enable"]:
            self.stdout.write("[cow_migrate] re-enabling COW...")
            cow_lib.deploy_cow_functions(using=using)
            cow_lib.enable_cow_for_all_models(
                extra_excluded_apps=PLANE_EXCLUDED_APPS,
                extra_excluded_tables=PLANE_EXCLUDED_TABLES,
                using=using,
            )
            self.stdout.write(self.style.SUCCESS("[cow_migrate] COW re-enabled."))
