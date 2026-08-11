"""Pydantic models for the Supplier Directory API.

Input and output schemas are kept separate: `updated_at` and `id`
are server-managed and never accepted from clients.
"""
from enum import Enum
from typing import List

from pydantic import BaseModel, Field


class SupplierStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class SupplierCategory(str, Enum):
    MEDICAL_EQUIPMENT = "Medical Equipment"
    PHARMACEUTICALS = "Pharmaceuticals"
    PPE_CONSUMABLES = "PPE & Medical Consumables"
    LAB_SUPPLIES = "Lab Supplies"
    IT_TELEHEALTH = "IT & Telehealth Equipment"
    FACILITY_MAINTENANCE = "Facility & Maintenance"
    OFFICE_ADMIN = "Office & Administrative Supplies"


class SupplierCountry(str, Enum):
    US = "US"
    UK = "UK"


# ---- Input schemas (what the client sends) ----
class SupplierCreate(BaseModel):
    name: str = Field(..., min_length=1)
    country: SupplierCountry
    categories: List[SupplierCategory] = Field(..., min_length=1)
    rate: float = Field(..., gt=0)
    status: SupplierStatus = SupplierStatus.ACTIVE


class SupplierRatePatch(BaseModel):
    rate: float = Field(..., gt=0)


class SupplierStatusPatch(BaseModel):
    status: SupplierStatus


# ---- Output schema (what the API returns) ----
class SupplierOut(BaseModel):
    id: int
    name: str
    country: SupplierCountry
    categories: List[SupplierCategory]
    rate: float
    status: SupplierStatus
    updated_at: str


# ---- User & Profile models (Authentication) ----
class UserRole(str, Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    USER = "user"


# ---- Input schemas (what the client sends) ----
class UserCreate(BaseModel):
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=8)
    name: str | None = None
    phone: str | None = None
    address: str | None = None


class UserCredentialsUpdate(BaseModel):
    email: str | None = None
    role: UserRole | None = None


class ProfileUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    address: str | None = None


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


# ---- Output schemas (what the API returns) ----
class ProfileOut(BaseModel):
    id: int
    user_id: int
    name: str | None = None
    phone: str | None = None
    address: str | None = None


class UserOut(BaseModel):
    id: int
    email: str
    is_active: bool
    role: UserRole
    created_at: str


class UserWithProfileOut(UserOut):
    profile: ProfileOut | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"