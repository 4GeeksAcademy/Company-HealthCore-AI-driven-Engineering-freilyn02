"""
Shared validation logic for the official incidents-healthcore.csv dataset.

Used by:
- scripts/seed_incidents.py (seeds the Incident model from the raw CSV)
- services/api routers (if the raw CSV is ever re-validated via an endpoint)

IMPORTANT: this module must NEVER return or log patient_id alongside any
other identifying field. Rows are validated and transformed, but patient_id
is only used internally as a stable identity key for idempotent seeding —
it is never surfaced in API responses or console output.
"""

from dataclasses import dataclass
from datetime import date, datetime


# --- Official CONTEXT-healthcore.md constants -------------------------------

VALID_CLINIC_IDS = {
    "US-TX-01", "US-TX-02", "US-TX-03",
    "US-FL-01", "US-FL-02", "US-FL-03",
    "US-GA-01", "US-GA-02", "US-GA-03",
    "UK-LON-01", "UK-LON-02", "UK-MAN-01",
}

VALID_COUNTRIES = {"US", "UK"}

# clinic_id prefix -> expected country
CLINIC_COUNTRY_PREFIX = {"US": "US", "UK": "UK"}

VALID_CATEGORIES = {
    "APPOINTMENT",
    "BILLING",
    "CLINICAL_CARE",
    "ACCESSIBILITY",
    "ADMINISTRATIVE",
}

VALID_STATUSES = {"OPEN", "CLOSED", "DISCARDED"}

MIN_SATISFACTION_SCORE = 1
MAX_SATISFACTION_SCORE = 5


# --- Exceptions ---------------------------------------------------------

class IncidentValidationError(Exception):
    """Base class for a single-row validation failure. Carries a machine-
    readable `reason` code used to group invalid rows in the report."""

    def __init__(self, reason: str, message: str):
        self.reason = reason
        super().__init__(message)


class MissingRequiredFieldError(IncidentValidationError):
    def __init__(self, field: str):
        super().__init__(
            reason=f"missing_{field}",
            message=f"Missing required field: {field}",
        )


class InvalidClinicIdError(IncidentValidationError):
    def __init__(self, clinic_id: str):
        super().__init__(
            reason="invalid_clinic_id",
            message=f"Unknown clinic_id: {clinic_id!r}",
        )


class ClinicCountryMismatchError(IncidentValidationError):
    def __init__(self, clinic_id: str, country: str):
        super().__init__(
            reason="clinic_country_mismatch",
            message=f"clinic_id {clinic_id!r} does not belong to country {country!r}",
        )


class InvalidCategoryError(IncidentValidationError):
    def __init__(self, category: str):
        super().__init__(
            reason="invalid_category",
            message=f"Invalid category: {category!r}",
        )


class InvalidStatusError(IncidentValidationError):
    def __init__(self, status: str):
        super().__init__(
            reason="invalid_status",
            message=f"Invalid status: {status!r}",
        )


class InvalidDescriptionError(IncidentValidationError):
    def __init__(self):
        super().__init__(
            reason="empty_description",
            message="Description must be at least 5 characters",
        )


class ClosedWithoutScoreError(IncidentValidationError):
    def __init__(self):
        super().__init__(
            reason="closed_without_score",
            message="status is CLOSED but satisfaction_score is missing",
        )


class InvalidSatisfactionScoreError(IncidentValidationError):
    def __init__(self, raw_value: str):
        super().__init__(
            reason="invalid_satisfaction_score",
            message=f"satisfaction_score out of range or malformed: {raw_value!r}",
        )


class InvalidDateError(IncidentValidationError):
    def __init__(self, raw_value: str):
        super().__init__(
            reason="invalid_date",
            message=f"date is not a valid ISO date: {raw_value!r}",
        )


# --- Row shape after validation -----------------------------------------

@dataclass(frozen=True)
class ValidatedIncidentRow:
    incident_id: str
    incident_date: date
    clinic_id: str
    country: str
    category: str
    description: str
    status: str
    patient_id: str  # internal identity key only — never expose downstream
    satisfaction_score: int | None


# --- Validation ------------------------------------------------------------

def validate_row(raw: dict[str, str]) -> ValidatedIncidentRow:
    """
    Validate one raw CSV row (already parsed into a dict of strings).
    Raises the first applicable IncidentValidationError subclass.
    Never returns a row without checking every rule below, so the caller
    always gets a specific `reason` for rejected rows.
    """

    incident_id = (raw.get("incident_id") or "").strip()
    if not incident_id:
        raise MissingRequiredFieldError("incident_id")

    raw_date = (raw.get("date") or "").strip()
    if not raw_date:
        raise MissingRequiredFieldError("date")
    try:
        incident_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise InvalidDateError(raw_date) from exc

    clinic_id = (raw.get("clinic_id") or "").strip()
    if not clinic_id:
        raise MissingRequiredFieldError("clinic_id")
    if clinic_id not in VALID_CLINIC_IDS:
        raise InvalidClinicIdError(clinic_id)

    country = (raw.get("country") or "").strip()
    if not country:
        raise MissingRequiredFieldError("country")
    if country not in VALID_COUNTRIES:
        raise ClinicCountryMismatchError(clinic_id, country)
    if not clinic_id.startswith(CLINIC_COUNTRY_PREFIX[country]):
        raise ClinicCountryMismatchError(clinic_id, country)

    category = (raw.get("category") or "").strip()
    if not category:
        raise MissingRequiredFieldError("category")
    if category not in VALID_CATEGORIES:
        raise InvalidCategoryError(category)

    description = (raw.get("description") or "").strip()
    if len(description) < 5:
        raise InvalidDescriptionError()

    status = (raw.get("status") or "").strip()
    if not status:
        raise MissingRequiredFieldError("status")
    if status not in VALID_STATUSES:
        raise InvalidStatusError(status)

    patient_id = (raw.get("patient_id") or "").strip()
    if not patient_id:
        raise MissingRequiredFieldError("patient_id")

    raw_score = (raw.get("satisfaction_score") or "").strip()
    satisfaction_score: int | None = None
    if raw_score:
        try:
            satisfaction_score = int(raw_score)
        except ValueError as exc:
            raise InvalidSatisfactionScoreError(raw_score) from exc
        if not (MIN_SATISFACTION_SCORE <= satisfaction_score <= MAX_SATISFACTION_SCORE):
            raise InvalidSatisfactionScoreError(raw_score)

    if status == "CLOSED" and satisfaction_score is None:
        raise ClosedWithoutScoreError()

    return ValidatedIncidentRow(
        incident_id=incident_id,
        incident_date=incident_date,
        clinic_id=clinic_id,
        country=country,
        category=category,
        description=description,
        status=status,
        patient_id=patient_id,
        satisfaction_score=satisfaction_score,
    )


def separate_valid_invalid(
    rows: list[dict[str, str]],
) -> tuple[list[ValidatedIncidentRow], list[tuple[dict[str, str], IncidentValidationError]]]:
    """Split raw rows into (valid, invalid) — invalid rows are paired with
    the specific error that rejected them, so the caller can report counts
    grouped by reason without ever printing patient_id."""

    valid: list[ValidatedIncidentRow] = []
    invalid: list[tuple[dict[str, str], IncidentValidationError]] = []

    for raw in rows:
        try:
            valid.append(validate_row(raw))
        except IncidentValidationError as err:
            invalid.append((raw, err))

    return valid, invalid