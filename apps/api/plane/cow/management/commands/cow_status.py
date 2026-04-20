# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json

from django.core.management.base import BaseCommand

from plane.cow.adapter import cow_lib


class Command(BaseCommand):
    help = "Print the schema-wide Copy-On-Write status."

    def add_arguments(self, parser):
        parser.add_argument("--database", default="default", help="Django DB alias")

    def handle(self, *args, **options):
        status = cow_lib.get_cow_status(using=options["database"])
        self.stdout.write(json.dumps(status, indent=2, default=str))
