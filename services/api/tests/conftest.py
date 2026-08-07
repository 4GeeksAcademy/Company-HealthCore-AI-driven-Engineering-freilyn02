"""Points the app at a dedicated test database before any app module loads,
so tests never touch the real dev data file."""
import os
import sys
from pathlib import Path

os.environ["SUPPLIER_DB_FILE"] = "test_db.json"

sys.path.insert(0, str(Path(__file__).parent.parent))
