from __future__ import annotations

from typing import Dict, List, Tuple

from django.core.management import BaseCommand, CommandError, call_command
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader


MigrationName = Tuple[str, str]


class Command(BaseCommand):
    help = (
        "Validate DB and migration health (connection, conflicts, unapplied migrations, "
        "and model drift)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default="default",
            help="Database alias to inspect (default: default).",
        )
        parser.add_argument(
            "--skip-model-check",
            action="store_true",
            help="Skip makemigrations drift check.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Fail when unapplied migrations exist.",
        )

    def handle(self, *args, **options):
        db_alias = options["database"]
        strict = options["strict"]
        skip_model_check = options["skip_model_check"]

        connection = connections[db_alias]
        self.stdout.write(self.style.NOTICE(f"Database: {db_alias} ({connection.vendor})"))

        hard_issues: List[str] = []
        soft_issues: List[str] = []

        # 1) DB connectivity
        try:
            connection.ensure_connection()
            self.stdout.write(self.style.SUCCESS("OK: Database connection established."))
        except Exception as exc:
            raise CommandError(f"Database connection failed: {exc}") from exc

        # 2) Migration graph health and conflicts
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        conflicts: Dict[str, List[str]] = loader.detect_conflicts()
        if conflicts:
            formatted = "; ".join(
                f"{app}: {', '.join(names)}" for app, names in sorted(conflicts.items())
            )
            hard_issues.append(f"Migration conflicts detected: {formatted}")
        else:
            self.stdout.write(self.style.SUCCESS("OK: No migration conflicts detected."))

        # 3) Unapplied migrations
        executor = MigrationExecutor(connection)
        leaf_nodes = executor.loader.graph.leaf_nodes()
        plan = executor.migration_plan(leaf_nodes)
        unapplied: List[MigrationName] = [
            (migration.app_label, migration.name)
            for migration, backwards in plan
            if not backwards
        ]

        if unapplied:
            preview = ", ".join(f"{app}.{name}" for app, name in unapplied[:10])
            message = (
                f"Unapplied migrations: {len(unapplied)} pending"
                + (f" ({preview}{'...' if len(unapplied) > 10 else ''})" if preview else "")
            )
            if strict:
                hard_issues.append(message)
            else:
                soft_issues.append(message)
        else:
            self.stdout.write(self.style.SUCCESS("OK: No unapplied migrations."))

        # 4) Model drift (makemigrations --check --dry-run)
        if not skip_model_check:
            try:
                call_command(
                    "makemigrations",
                    check=True,
                    dry_run=True,
                    interactive=False,
                    verbosity=0,
                )
                self.stdout.write(self.style.SUCCESS("OK: No model drift (makemigrations clean)."))
            except SystemExit as exc:  # pragma: no cover - defensive for command exit
                code = int(exc.code or 1)
                if code != 0:
                    hard_issues.append(
                        "Model drift detected: makemigrations --check reported pending changes."
                    )
            except Exception as exc:
                hard_issues.append(f"Model drift check failed: {exc}")

        for issue in soft_issues:
            self.stdout.write(self.style.WARNING(f"WARN: {issue}"))

        if hard_issues:
            for issue in hard_issues:
                self.stdout.write(self.style.ERROR(f"ERROR: {issue}"))
            raise CommandError("DB healthcheck failed.")

        self.stdout.write(self.style.SUCCESS("DB healthcheck passed."))
