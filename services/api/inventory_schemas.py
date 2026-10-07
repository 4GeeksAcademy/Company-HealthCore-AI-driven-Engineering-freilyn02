"""Pydantic request/response schemas for Milestone 5 — Inventory Management.

Kept separate from inventory_models.py (SQLModel/ORM) per the project README.
current_stock is computed and only ever appears in MedicalSupplyRead — never
accepted as input, never stored.
"""
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SupplyCategory(str, Enum):
    PPE = "ppe"
    WOUND_CARE = "wound_care"
    DIAGNOSTICS = "diagnostics"
    MEDICATIONS = "medications"
    CONSUMABLES = "consumables"


class SupplyUnit(str, Enum):
    BOX = "box"
    UNIT = "unit"
    PACK = "pack"
    VIAL = "vial"


class SupplyCountry(str, Enum):
    US = "US"
    UK = "UK"


class ConsumptionType(str, Enum):
    CLINICAL_USE = "clinical_use"
    EXPIRY_WASTE = "expiry_waste"


# ---- MedicalSupply ----
class MedicalSupplyCreate(BaseModel):
    name: str = Field(..., min_length=1)
    sku: str = Field(..., min_length=1)
    category: SupplyCategory
    unit: SupplyUnit
    country: SupplyCountry


class MedicalSupplyRead(BaseModel):
    id: int
    name: str
    sku: str
    category: SupplyCategory
    unit: SupplyUnit
    country: SupplyCountry
    current_stock: int  # computed — never stored, never accepted as input


# ---- SupplyDelivery (inbound) ----
class SupplyDeliveryCreate(BaseModel):
    supply_id: int
    quantity: int = Field(..., gt=0)
    vendor_name: str = Field(..., min_length=1)
    clinic_id: int = Field(..., ge=1, le=12)


class SupplyDeliveryRead(BaseModel):
    id: int
    supply_id: int
    quantity: int
    vendor_name: str
    clinic_id: int
    created_at: datetime
    user_uuid: str


# ---- SupplyConsumption (outbound) ----
class SupplyConsumptionCreate(BaseModel):
    supply_id: int
    quantity: int = Field(..., gt=0)
    consumption_type: ConsumptionType
    clinic_id: int = Field(..., ge=1, le=12)


class SupplyConsumptionRead(BaseModel):
    id: int
    supply_id: int
    quantity: int
    consumption_type: ConsumptionType
    clinic_id: int
    created_at: datetime
    user_uuid: str


# ---- Combined list item for GET /inventory/orders ----
class InventoryOrderRead(BaseModel):
    id: int
    order_type: str  # "inbound" | "outbound"
    supply_id: int
    supply_name: str
    supply_sku: str
    quantity: int
    clinic_id: int
    user_uuid: str
    created_at: datetime
    # inbound-only
    vendor_name: str | None = None
    # outbound-only
    consumption_type: str | None = None
    