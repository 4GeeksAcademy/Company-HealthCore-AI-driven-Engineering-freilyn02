"""SQLModel ORM tables for Milestone 5 — Inventory Management (HealthCore).

These are the only three tables that live in Supabase/PostgreSQL. Everything
else (users, profiles, suppliers, incidents) stays in TinyDB — see database.py.

No stored `current_stock` column on MedicalSupply: it is always computed as
SUM(SupplyDelivery.quantity) - SUM(SupplyConsumption.quantity). See
inventory_service.py (added in a later phase) for that calculation.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class MedicalSupply(SQLModel, table=True):
    __tablename__ = "medical_supplies"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    sku: str = Field(index=True, unique=True)
    category: str  # "ppe" | "wound_care" | "diagnostics" | "medications" | "consumables"
    unit: str  # "box" | "unit" | "pack" | "vial"
    country: str  # "US" | "UK" — regulatory jurisdiction


class SupplyDelivery(SQLModel, table=True):
    """A vendor shipment received at a HealthCore clinic (maps to InboundOrder)."""

    __tablename__ = "supply_deliveries"

    id: Optional[int] = Field(default=None, primary_key=True)
    supply_id: int = Field(foreign_key="medical_supplies.id")
    quantity: int
    vendor_name: str
    clinic_id: int  # 1-12, not a FK — clinic data is managed separately
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user_uuid: str  # references a TinyDB user id; no FK, TinyDB is a different DB


class SupplyConsumption(SQLModel, table=True):
    """A clinical use event: supplies consumed during patient care (maps to OutboundOrder)."""

    __tablename__ = "supply_consumptions"

    id: Optional[int] = Field(default=None, primary_key=True)
    supply_id: int = Field(foreign_key="medical_supplies.id")
    quantity: int
    consumption_type: str  # "clinical_use" | "expiry_waste" — validated in the Pydantic schema
    clinic_id: int  # 1-12, not a FK
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user_uuid: str  # references a TinyDB user id; no FK