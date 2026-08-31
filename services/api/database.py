"""Centralized TinyDB initialization for the HealthCore API.
Uses a separate data file per environment via the SUPPLIER_DB_FILE
env var, so dev and test data never mix.
"""
import os
from pathlib import Path
feature/error-handling-audit

from tinydb import TinyDB

# Allow overriding the DB file path in tests (mirrors the Supplier Directory
# pattern: SUPPLIER_DB_FILE -> INCIDENT_DB_FILE), so pytest can point to an
# isolated test database instead of the real one.
DB_FILE = os.environ.get("INCIDENT_DB_FILE", "data/db.json")

# Ensure the containing directory exists before TinyDB tries to open/create
# the file — a fresh clone won't have data/ until something creates it.
Path(DB_FILE).parent.mkdir(parents=True, exist_ok=True)

db = TinyDB(DB_FILE)

from tinydb import TinyDB

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_FILENAME = os.getenv("SUPPLIER_DB_FILE", "db.json")
DB_PATH = DATA_DIR / DB_FILENAME
db = TinyDB(DB_PATH)
main

suppliers_table = db.table("suppliers")
users_table = db.table("users")
profiles_table = db.table("profiles")
incidents_table = db.table("incidents")