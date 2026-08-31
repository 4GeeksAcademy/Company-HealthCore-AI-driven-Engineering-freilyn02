"""Seeder for HealthCore suppliers.

Idempotent: running this multiple times will not duplicate suppliers
(checks the natural key name + country before inserting).

Usage: uv run python seed.py
"""
from models import SupplierCategory, SupplierCountry, SupplierCreate, SupplierStatus
import repository

INITIAL_SUPPLIERS = [
    SupplierCreate(
        name="Bristol MedSupply Ltd",
        country=SupplierCountry.UK,
        categories=[SupplierCategory.MEDICAL_EQUIPMENT, SupplierCategory.LAB_SUPPLIES],
        rate=245.50,
        status=SupplierStatus.ACTIVE,
    ),
    SupplierCreate(
        name="Tampa Bay Pharma Distributors",
        country=SupplierCountry.US,
        categories=[SupplierCategory.PHARMACEUTICALS],
        rate=1200.00,
        status=SupplierStatus.ACTIVE,
    ),
    SupplierCreate(
        name="Gulf Coast PPE Supply",
        country=SupplierCountry.US,
        categories=[SupplierCategory.PPE_CONSUMABLES],
        rate=89.99,
        status=SupplierStatus.ACTIVE,
    ),
    SupplierCreate(
        name="Avon Lab Equipment Co",
        country=SupplierCountry.UK,
        categories=[SupplierCategory.LAB_SUPPLIES],
        rate=430.00,
        status=SupplierStatus.SUSPENDED,
    ),
    SupplierCreate(
        name="Clearwater Telehealth Systems",
        country=SupplierCountry.US,
        categories=[SupplierCategory.IT_TELEHEALTH],
        rate=675.00,
        status=SupplierStatus.ACTIVE,
    ),
    SupplierCreate(
        name="London Facility Services",
        country=SupplierCountry.UK,
        categories=[SupplierCategory.FACILITY_MAINTENANCE, SupplierCategory.OFFICE_ADMIN],
        rate=310.25,
        status=SupplierStatus.ACTIVE,
    ),
]


def main() -> None:
    inserted_count = 0
    for supplier in INITIAL_SUPPLIERS:
        if repository.find_by_name_and_country(supplier.name, supplier.country.value):
            continue
        repository.create_supplier(supplier)
        inserted_count += 1

    print(f"Seed complete. Inserted {inserted_count} new supplier(s).")


if __name__ == "__main__":
    main()