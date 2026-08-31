"""Centralized TinyDB initialization for the HealthCore API.
Uses a separate data file per environment via the SUPPLIER_DB_FILE
env var, so dev and test data never mix.
"""
import os
from pathlib import Path
from tinydb import TinyDB

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_FILENAME = os.getenv("SUPPLIER_DB_FILE", "db.json")
DB_PATH = DATA_DIR / DB_FILENAME
db = TinyDB(DB_PATH)

suppliers_table = db.table("suppliers")
users_table = db.table("users")
profiles_table = db.table("profiles")
incidents_table = db.table("incidents")