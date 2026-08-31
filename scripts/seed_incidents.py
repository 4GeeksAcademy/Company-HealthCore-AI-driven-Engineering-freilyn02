"""
Seed the Incident model from the official incidents-healthcore.csv dataset
(the same CSV used by the incidents-file-analysis project).

Usage:
    cd services/api
    python -m scripts.seed_incidents
    (or: python ../../scripts/seed_incidents.py, run from services/api)

Idempotent: re-running this script does not duplicate rows. Matching is done
on the CSV's incident_id, which is used ONLY as an internal seed-tracking key
(_seed_source_id) — it is never exposed through the public Incident model or
any API response.
"""

import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make services/api importable when running this script directly from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from tinydb import Query  # noqa: E402

from app.validation.incidents import separate_valid_invalid, ValidatedIncidentRow  # noqa: E402
from database import incidents_table  # noqa: E402


CSV_PATH = Path(__file__).resolve().parent / "incidents-healthcore.csv"


# --- Mappings, verbatim from CONTEXT-healthcore.es.md -----------------------

STATUS_MAP = {
    "OPEN": "open",
    "CLOSED": "resolved",
    "DISCARDED": "discarded",
}

CATEGORY_MAP = {
    "APPOINTMENT": "patient_experience",
    "BILLING": "billing_error",
    "CLINICAL_CARE": "patient_experience",
    "ACCESSIBILITY": "patient_experience",
    "ADMINISTRATIVE": "other",
}

CLINIC_TO_BRANCH = {
    "US-TX-01": "central",
    "US-TX-02": "austin_north",
    "US-TX-03": "houston_med_center",
    "US-FL-01": "miami_brickell",
    "US-FL-02": "orlando_east",
    "US-FL-03": "tampa_bay",
    "US-GA-01": "atlanta_midtown",
    "US-GA-02": "atlanta_midtown",
    "US-GA-03": "savannah",
    "UK-LON-01": "london_city",
    "UK-LON-02": "london_west",
    "UK-MAN-01": "manchester_central",
}

DEFAULT_BRANCH = "central"
TITLE_MAX_LENGTH = 120


def transform_row(row: ValidatedIncidentRow) -> dict | None:
    """Apply the CSV -> model transformation for one already-validated row.
    Returns None if the row must be discarded after transformation (e.g. an
    empty title once trimmed)."""

    title = row.description.strip()[:TITLE_MAX_LENGTH].strip()
    if not title:
        return None

    created_at = datetime.combine(row.incident_date, datetime.min.time(), tzinfo=timezone.utc)

    return {
        # internal only — never exposed via the Incident model / API
        "_seed_source_id": row.incident_id,
        "title": title,
        "description": row.description,
        "category": CATEGORY_MAP.get(row.category),
        "status": STATUS_MAP.get(row.status),
        "origin": "customer",
        "branch": CLINIC_TO_BRANCH.get(row.clinic_id, DEFAULT_BRANCH),
        "created_at": created_at.isoformat(),
        "updated_at": created_at.isoformat(),
    }


def load_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def seed() -> None:
    if not CSV_PATH.exists():
        print(f"CSV not found at {CSV_PATH}")
        return

    raw_rows = load_csv_rows(CSV_PATH)
    valid_rows, invalid_rows = separate_valid_invalid(raw_rows)

    transformed: list[dict] = []
    skipped_after_transform = 0
    for row in valid_rows:
        doc = transform_row(row)
        if doc is None:
            skipped_after_transform += 1
            continue
        transformed.append(doc)

    IncidentQuery = Query()
    inserted = 0
    already_present = 0
    for doc in transformed:
        exists = incidents_table.get(IncidentQuery._seed_source_id == doc["_seed_source_id"])
        if exists:
            already_present += 1
            continue
        incidents_table.insert(doc)
        inserted += 1

    # --- Report: never print patient_id or any patient-identifying field ---
    print("=== Incident seed report ===")
    print(f"Source CSV:         {CSV_PATH.name}")
    print(f"Total rows in CSV:  {len(raw_rows)}")
    print(f"Valid rows:         {len(valid_rows)}")
    print(f"Invalid rows:       {len(invalid_rows)}")

    if invalid_rows:
        by_reason: dict[str, int] = {}
        for _raw, err in invalid_rows:
            by_reason[err.reason] = by_reason.get(err.reason, 0) + 1
        print("Invalid rows by reason:")
        for reason, count in sorted(by_reason.items()):
            print(f"  - {reason}: {count}")

    if skipped_after_transform:
        print(f"Skipped after transform (empty title): {skipped_after_transform}")

    print(f"Inserted this run:  {inserted}")
    print(f"Already present:    {already_present}")
    print(f"Table size now:     {len(incidents_table)}")


if __name__ == "__main__":
    seed()