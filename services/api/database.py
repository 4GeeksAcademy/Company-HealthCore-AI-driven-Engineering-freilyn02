import os

from tinydb import TinyDB

# Allow overriding the DB file path in tests (mirrors the Supplier Directory
# pattern: SUPPLIER_DB_FILE -> INCIDENT_DB_FILE), so pytest can point to an
# isolated test database instead of the real one.
DB_FILE = os.environ.get("INCIDENT_DB_FILE", "data/db.json")

db = TinyDB(DB_FILE)

incidents_table = db.table("incidents")