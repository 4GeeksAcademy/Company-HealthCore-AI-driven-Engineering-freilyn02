"""Centralized database initialization for the HealthCore API.

Two separate databases, per the Milestone 5 architecture:
- TinyDB: users, profiles, suppliers, incidents (existing, unchanged).
- Supabase/PostgreSQL via SQLModel: inventory (MedicalSupply, SupplyDelivery,
  SupplyConsumption) — new for this milestone.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlmodel import Session, create_engine
from tinydb import TinyDB

load_dotenv()

# ---- TinyDB (auth, suppliers, incidents) ----
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_FILENAME = os.getenv("SUPPLIER_DB_FILE", "db.json")
DB_PATH = DATA_DIR / DB_FILENAME
db = TinyDB(DB_PATH)

suppliers_table = db.table("suppliers")
users_table = db.table("users")
profiles_table = db.table("profiles")
incidents_table = db.table("incidents")

# ---- Supabase / PostgreSQL via SQLModel (inventory) ----
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, echo=False)


def get_db():
    """Yields a SQLModel session per request. Never a global session."""
    with Session(engine) as session:
        yield session