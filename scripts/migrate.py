#!/usr/bin/env python3
"""
Database migration runner for polyMad.

Usage:
    python scripts/migrate.py                  # apply all pending migrations
    python scripts/migrate.py --dry-run        # show pending migrations without applying
    python scripts/migrate.py --status         # list all migrations and their status
    python scripts/migrate.py --rollback 002   # (future) rollback a specific migration

Requirements:
    DATABASE_URL env var — PostgreSQL connection string.
    Format:  postgresql://user:password@host:5432/dbname
    Supabase: find it in Project Settings → Database → Connection string (URI mode).
    Tip: copy the "URI" value and replace [YOUR-PASSWORD] with your db password.

    pip install psycopg2-binary   (or add to requirements-dev.txt)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: psycopg2-binary is not installed.")
    print("       Run: pip install psycopg2-binary")
    sys.exit(1)

# ── Paths ──────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "migrations"

# ── Migration tracking table ───────────────────────────────────────────────
_BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS _migrations (
    version     TEXT        PRIMARY KEY,
    filename    TEXT        NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

# ── Helpers ────────────────────────────────────────────────────────────────

def _connect() -> "psycopg2.connection":
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL environment variable is not set.")
        print("       Export it before running migrations:")
        print("       export DATABASE_URL='postgresql://postgres:<password>@db.<ref>.supabase.co:5432/postgres'")
        sys.exit(1)
    try:
        return psycopg2.connect(url)
    except psycopg2.OperationalError as exc:
        print(f"ERROR: Could not connect to database.\n       {exc}")
        sys.exit(1)


def _bootstrap(conn: "psycopg2.connection") -> None:
    """Ensure the _migrations tracking table exists."""
    with conn.cursor() as cur:
        cur.execute(_BOOTSTRAP_SQL)
    conn.commit()


def _applied_versions(conn: "psycopg2.connection") -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM _migrations ORDER BY version;")
        return {row[0] for row in cur.fetchall()}


def _load_migration_files() -> list[tuple[str, Path]]:
    """
    Return sorted list of (version, path) for all *.sql files in migrations/.
    Version is the numeric prefix, e.g. '001' from '001_initial_schema.sql'.
    """
    files: list[tuple[str, Path]] = []
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        m = re.match(r"^(\d+)", p.name)
        if m:
            files.append((m.group(1), p))
    return files


def _apply(conn: "psycopg2.connection", version: str, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
        cur.execute(
            "INSERT INTO _migrations (version, filename) VALUES (%s, %s);",
            (version, path.name),
        )
    conn.commit()


# ── Commands ───────────────────────────────────────────────────────────────

def cmd_status(conn: "psycopg2.connection") -> None:
    applied = _applied_versions(conn)
    files = _load_migration_files()

    if not files:
        print("No migration files found in migrations/")
        return

    print(f"{'Version':<10} {'Status':<12} Filename")
    print("-" * 60)
    for version, path in files:
        status = "✅ applied" if version in applied else "⏳ pending"
        print(f"{version:<10} {status:<12} {path.name}")


def cmd_migrate(conn: "psycopg2.connection", dry_run: bool = False) -> None:
    applied = _applied_versions(conn)
    files = _load_migration_files()
    pending = [(v, p) for v, p in files if v not in applied]

    if not pending:
        print("Nothing to migrate — all migrations are up to date.")
        return

    print(f"{'DRY RUN — ' if dry_run else ''}Pending migrations ({len(pending)}):")
    for version, path in pending:
        print(f"  {version}  {path.name}")

    if dry_run:
        return

    print()
    for version, path in pending:
        print(f"  Applying {version} — {path.name} ... ", end="", flush=True)
        try:
            _apply(conn, version, path)
            print("done")
        except Exception as exc:
            conn.rollback()
            print(f"FAILED\n\nERROR: {exc}")
            sys.exit(1)

    print(f"\n{len(pending)} migration(s) applied successfully.")


# ── Entry point ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="polyMad database migration runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dry-run", action="store_true", help="Show pending migrations without applying")
    parser.add_argument("--status",  action="store_true", help="List all migrations and their status")
    args = parser.parse_args()

    conn = _connect()
    _bootstrap(conn)

    try:
        if args.status:
            cmd_status(conn)
        else:
            cmd_migrate(conn, dry_run=args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
