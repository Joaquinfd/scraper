#!/usr/bin/env python3
"""Ejecuta una migración SQL contra la base de datos de DATABASE_URL.

Uso:
    python migrations/run_migration.py migrations/v2_product_details.sql
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text
from sqlmodel import create_engine

load_dotenv()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1

    sql_path = Path(sys.argv[1])
    if not sql_path.exists():
        print(f"No existe: {sql_path}")
        return 1

    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://") or (
        url.startswith("postgresql://") and not url.startswith("postgresql+psycopg://")
    ):
        url = "postgresql+psycopg" + url[url.index("://"):]

    engine = create_engine(url)
    statements = [s.strip() for s in sql_path.read_text(encoding="utf-8").split(";") if s.strip()]

    with engine.begin() as conn:
        for stmt in statements:
            print(f"-> {stmt.splitlines()[0][:80]} ...")
            conn.execute(text(stmt))

    print(f"\nOK: {len(statements)} sentencias ejecutadas desde {sql_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
