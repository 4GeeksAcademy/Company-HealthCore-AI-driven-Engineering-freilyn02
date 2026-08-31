"""Seed script for Milestone 5 — Inventory Management (HealthCore).

Populates Supabase with the minimum data required by the CONTEXT: 6 medical
supplies, 4+ deliveries, 3+ consumptions (at least one clinical_use and one
expiry_waste). Idempotent: skips a supply if its SKU already exists.

Run with: uv run python seed_inventory.py
"""
from sqlmodel import Session, select

from database import engine
from inventory_models import MedicalSupply, SupplyConsumption, SupplyDelivery

# The TinyDB user id that "confirmed" every seeded delivery/consumption.
# Replace with a real user id from your own TinyDB instance if different.
SEED_USER_UUID = "6"

SUPPLIES = [
    {"name": "Nitrile gloves (box of 100)", "sku": "HCR-PPE-001", "category": "ppe", "unit": "box", "country": "US"},
    {"name": "Surgical mask (pack of 50)", "sku": "HCR-PPE-002", "category": "ppe", "unit": "pack", "country": "UK"},
    {"name": "Adhesive wound dressing", "sku": "HCR-WND-001", "category": "wound_care", "unit": "box", "country": "US"},
    {"name": "Rapid strep test kit", "sku": "HCR-DIAG-001", "category": "diagnostics", "unit": "unit", "country": "US"},
    {"name": "Blood glucose test strips (50)", "sku": "HCR-DIAG-002", "category": "diagnostics", "unit": "box", "country": "UK"},
    {"name": "0.9% Saline solution 500ml", "sku": "HCR-MED-001", "category": "medications", "unit": "vial", "country": "US"},
]


def seed_supplies(session: Session) -> dict[str, MedicalSupply]:
    """Insert supplies if they don't exist yet; return sku -> MedicalSupply."""
    by_sku: dict[str, MedicalSupply] = {}
    for data in SUPPLIES:
        existing = session.exec(
            select(MedicalSupply).where(MedicalSupply.sku == data["sku"])
        ).first()
        if existing:
            by_sku[data["sku"]] = existing
            continue
        supply = MedicalSupply(**data)
        session.add(supply)
        session.commit()
        session.refresh(supply)
        by_sku[data["sku"]] = supply
    return by_sku


def seed_deliveries(session: Session, by_sku: dict[str, MedicalSupply]) -> None:
    # Skip if deliveries already exist — keeps the script idempotent.
    if session.exec(select(SupplyDelivery)).first() is not None:
        print("Deliveries already seeded, skipping.")
        return

    deliveries = [
        {"sku": "HCR-PPE-001", "quantity": 200, "vendor_name": "MedLine Industries", "clinic_id": 1},
        {"sku": "HCR-PPE-001", "quantity": 150, "vendor_name": "Bound Tree Medical", "clinic_id": 4},
        {"sku": "HCR-PPE-002", "quantity": 100, "vendor_name": "Cardinal Health UK", "clinic_id": 11},
        {"sku": "HCR-WND-001", "quantity": 80, "vendor_name": "MedLine Industries", "clinic_id": 2},
        {"sku": "HCR-DIAG-001", "quantity": 50, "vendor_name": "Bound Tree Medical", "clinic_id": 5},
        {"sku": "HCR-MED-001", "quantity": 120, "vendor_name": "MedLine Industries", "clinic_id": 1},
    ]
    for d in deliveries:
        supply = by_sku[d["sku"]]
        session.add(
            SupplyDelivery(
                supply_id=supply.id,
                quantity=d["quantity"],
                vendor_name=d["vendor_name"],
                clinic_id=d["clinic_id"],
                user_uuid=SEED_USER_UUID,
            )
        )
    session.commit()
    print(f"Inserted {len(deliveries)} deliveries.")


def seed_consumptions(session: Session, by_sku: dict[str, MedicalSupply]) -> None:
    if session.exec(select(SupplyConsumption)).first() is not None:
        print("Consumptions already seeded, skipping.")
        return

    consumptions = [
        {"sku": "HCR-PPE-001", "quantity": 60, "consumption_type": "clinical_use", "clinic_id": 1},
        {"sku": "HCR-WND-001", "quantity": 15, "consumption_type": "clinical_use", "clinic_id": 2},
        {"sku": "HCR-DIAG-001", "quantity": 5, "consumption_type": "expiry_waste", "clinic_id": 5},
    ]
    for c in consumptions:
        supply = by_sku[c["sku"]]
        session.add(
            SupplyConsumption(
                supply_id=supply.id,
                quantity=c["quantity"],
                consumption_type=c["consumption_type"],
                clinic_id=c["clinic_id"],
                user_uuid=SEED_USER_UUID,
            )
        )
    session.commit()
    print(f"Inserted {len(consumptions)} consumptions.")


def main() -> None:
    with Session(engine) as session:
        by_sku = seed_supplies(session)
        print(f"Ensured {len(by_sku)} medical supplies exist.")
        seed_deliveries(session, by_sku)
        seed_consumptions(session, by_sku)


if __name__ == "__main__":
    main()