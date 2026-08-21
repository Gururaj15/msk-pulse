"""Shared helpers for analysis scripts: connect to the dbt-built warehouse."""
import os
from pathlib import Path

import duckdb

WAREHOUSE_DIR = Path(__file__).resolve().parent.parent / "warehouse"
WAREHOUSE_DB = WAREHOUSE_DIR / "msk_pulse.duckdb"


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    """Open the warehouse DB.

    The dbt-duckdb source views are defined with a path relative to the
    warehouse/ folder (e.g. ../data/raw/visits.parquet). DuckDB resolves
    relative paths in a view definition against the process's current
    working directory at *query* time, not view-creation time -- so this
    changes the process cwd to warehouse/ and leaves it there for the rest
    of the script's run (each analysis script is a short-lived process, so
    this is safe and keeps every caller simple: just `con = connect()`).
    """
    if not WAREHOUSE_DB.exists():
        raise FileNotFoundError(
            f"{WAREHOUSE_DB} not found. Run `dbt build --profiles-dir .` "
            f"from the warehouse/ folder first."
        )
    os.chdir(WAREHOUSE_DIR)
    return duckdb.connect(str(WAREHOUSE_DB.name), read_only=read_only)
