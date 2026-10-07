"""Pydantic models: Incidents, Suppliers, and Auth (Users/Profiles) for the HealthCore API."""
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ============================================================================
# Incidents (Centralized Incident Manager)
# ============================================================================

# --- Enums (mirror CONTEXT.md exactly — see CONTEXT-healthcore.es.md) ------

class IncidentCategory(str, Enum):
    CLINICAL_EQUIPMENT = "clinical_equipment"
    IT_SYSTEM = "it_system"
    BILLING_ERROR = "billing_error"
    COMPLIANCE_BREACH = "compliance_breach"
    PATIENT_EXPERIENCE = "patient_experience"
    STAFF_ISSUE = "staff_issue"
    FACILITY_ISSUE = "facility_issue"
    REFERRAL_ISSUE = "referral_issue"
    OTHER = "other"


class IncidentStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    DISCARDED = "discarded"


class IncidentOrigin(str, Enum):
    CUSTOMER = "customer"
    BRANCH = "branch"
    INTERNAL = "internal"


class IncidentBranch(str, Enum):
    CENTRAL = "central"
    AUSTIN_NORTH = "austin_north"
    DALLAS_UPTOWN = "dallas_uptown"
    HOUSTON_MED_CENTER = "houston_med_center"
    SAN_ANTONIO_WEST = "san_antonio_west"
    MIAMI_BRICKELL = "miami_brickell"
    MIAMI_DORAL = "miami_doral"
    ORLANDO_EAST = "orlando_east"
    TAMPA_BAY = "tampa_bay"
    ATLANTA_MIDTOWN = "atlanta_midtown"
    SAVANNAH = "savannah"
    LONDON_CITY = "london_city"
    LONDON_WEST = "london_west"
    MANCHESTER_CENTRAL = "manchester_central"


# Display labels — UI must always show these, never the raw enum value
BRANCH_LABELS: dict[str, str] = {
    IncidentBranch.CENTRAL: "Central — Austin Main Clinic",
    IncidentBranch.AUSTIN_NORTH: "Austin — North",
    IncidentBranch.DALLAS_UPTOWN: "Dallas Uptown",
    IncidentBranch.HOUSTON_MED_CENTER: "Houston Medical Center",
    IncidentBranch.SAN_ANTONIO_WEST: "San Antonio West",
    IncidentBranch.MIAMI_BRICKELL: "Miami Brickell",
    IncidentBranch.MIAMI_DORAL: "Miami Doral",
    IncidentBranch.ORLANDO_EAST: "Orlando East",
    IncidentBranch.TAMPA_BAY: "Tampa Bay",
    IncidentBranch.ATLANTA_MIDTOWN: "Atlanta Midtown",
    IncidentBranch.SAVANNAH: "Savannah",
    IncidentBranch.LONDON_CITY: "London City",
    IncidentBranch.LONDON_WEST: "London West End",
    IncidentBranch.MANCHESTER_CENTRAL: "Manchester Central",
}

CATEGORY_LABELS: dict[str, str] = {
    IncidentCategory.CLINICAL_EQUIPMENT: "Clinical Equipment",
    IncidentCategory.IT_SYSTEM: "IT System",
    IncidentCategory.BILLING_ERROR: "Billing Error",
    IncidentCategory.COMPLIANCE_BREACH: "Compliance Breach",
    IncidentCategory.PATIENT_EXPERIENCE: "Patient Experience",
    IncidentCategory.STAFF_ISSUE: "Staff Issue",
    IncidentCategory.FACILITY_ISSUE: "Facility Issue",
    IncidentCategory.REFERRAL_ISSUE: "Referral Issue",
    IncidentCategory.OTHER: "Other",
}

STATUS_LABELS: dict[str, str] = {
    IncidentStatus.OPEN: "Open",
    IncidentStatus.IN_PROGRESS: "In Progress",
    IncidentStatus.RESOLVED: "Resolved",
    IncidentStatus.DISCARDED: "Discarded",
}

# Valid lifecycle transitions — enforced in the PATCH /status endpoint
VALID_STATUS_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.OPEN: {IncidentStatus.IN_PROGRESS, IncidentStatus.DISCARDED},
    IncidentStatus.IN_PROGRESS: {IncidentStatus.RESOLVED, IncidentStatus.DISCARDED},
    IncidentStatus.RESOLVED: set(),
    IncidentStatus.DISCARDED: set(),
}


# --- Request / response models ---------------------------------------------

class IncidentCreate(BaseModel):
    """Payload for POST /api/incidents. `title` and `description` must never
    contain patient-identifying data — this is enforced only client-side via
    the visible warning; the API itself does not (and cannot) detect PII."""

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    category: IncidentCategory
    origin: IncidentOrigin
    branch: IncidentBranch

    @field_validator("title", "description")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class IncidentStatusUpdate(BaseModel):
    status: IncidentStatus


class Incident(BaseModel):
    id: str
    title: str
    description: str
    category: IncidentCategory
    status: IncidentStatus
    origin: IncidentOrigin
    branch: IncidentBranch
    created_at: datetime
    updated_at: datetime


class IncidentSummary(BaseModel):
    by_status: dict[str, int]
    by_category: dict[str, int]
    by_origin: dict[str, int]
    by_branch: dict[str, int]


class ValidationErrorBody(BaseModel):
    """Shape required by the reference solution for 400 responses."""

    field: str
    message: str


# ============================================================================
# Suppliers (Supplier Directory)
# ============================================================================
# Input and output schemas are kept separate: `updated_at` and `id`
# are server-managed and never accepted from clients.

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


# ============================================================================
# Users & Profiles (Authentication)
# ============================================================================

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