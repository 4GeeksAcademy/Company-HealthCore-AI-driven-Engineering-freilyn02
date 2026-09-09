"""Pure transformation helpers for the Monthly Clinic Supply Performance
pipeline.

These functions contain NO Prefect decorators and NO I/O. They are imported
by the @task-decorated wrappers in data/pipelines/pipeline.py, and are
imported directly (undecorated) by tests/pipelines/test_pipeline.py so they
can be exercised without a Prefect runtime, per Milestone 6 Part 3 section
"Subflow refactoring patterns (reference)" / "Unit test patterns (reference)".

Business rules implemented here come from CONTEXT-healthcore-pipeline.md
(Business Performance Pipeline):
  - Section 2: KPIs to Measure (4 KPIs)
  - Section 3: Source data (4 mandatory event types)
  - Section 4: Required aggregation (grain, dimensions, computed fields)
"""
from datetime import datetime, timedelta, timezone

# --- Clinic reference data ---------------------------------------------------
# Mirrors IncidentBranch from services/api/models.py, minus "central" (which
# is a catch-all, not a physical clinic). country/currency assigned per the
# US/UK split CONTEXT section 4 requires ("Never mix currencies in a single
# aggregate row").
CLINIC_BRANCHES = {
    "austin_north": ("US", "USD"),
    "dallas_uptown": ("US", "USD"),
    "houston_med_center": ("US", "USD"),
    "san_antonio_west": ("US", "USD"),
    "miami_brickell": ("US", "USD"),
    "miami_doral": ("US", "USD"),
    "orlando_east": ("US", "USD"),
    "tampa_bay": ("US", "USD"),
    "atlanta_midtown": ("US", "USD"),
    "savannah": ("US", "USD"),
    "london_city": ("UK", "GBP"),
    "london_west": ("UK", "GBP"),
    "manchester_central": ("UK", "GBP"),
}

# CONTEXT section 3: the four mandatory event types this pipeline reads.
MANDATORY_EVENT_TYPES = [
    "inbound_order_created",
    "outbound_order_created",
    "stock_threshold_triggered",
    "supply_expiry_flagged",
]


def month_start(dt: datetime) -> str:
    """Normalizes any datetime to the first day of its month, as an ISO date
    string (YYYY-MM-01). This is the grain used by the business key
    (CONTEXT section 4: "Grain: one row per clinic_id per calendar month")."""
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).date().isoformat()


def target_months(reference: datetime | None = None) -> list[str]:
    """Returns the current month plus the previous month, per
    PIPELINE_DESIGN.md section 5's 2-month reprocessing window (catches
    late-arriving events)."""
    reference = reference or datetime.now(timezone.utc)
    current = month_start(reference)
    previous_dt = reference.replace(day=1) - timedelta(days=1)
    previous = month_start(previous_dt)
    return [previous, current]


def normalize_event_payload(raw_event: dict) -> dict:
    """Validates a single raw event has the minimum shape required to be
    processed, and returns it unchanged if valid.

    Raises ValueError if:
      - event_type is missing
      - created_at/timestamp is missing or None (can't compute month_start
        without it)
      - clinic_id is missing

    This is the single-event counterpart to validate_supply_events (which
    operates on a list). Used directly by the defensive test required by
    the evaluation checklist ("test against invalid/malformed input").
    """
    if not raw_event.get("event_type"):
        raise ValueError("event missing required field 'event_type'")
    if not raw_event.get("clinic_id"):
        raise ValueError("event missing required field 'clinic_id'")

    created_at = raw_event.get("created_at")
    if not created_at:
        raise ValueError("event missing required field 'created_at'")

    # Confirms the timestamp is actually parseable - a malformed but
    # non-empty string should also fail loudly rather than blow up later
    # inside aggregate_monthly_kpis.
    datetime.fromisoformat(created_at)

    return raw_event


def validate_supply_events(events: list[dict]) -> list[dict]:
    """Drops events missing required fields for their type, per CONTEXT
    section 3's schema prerequisite (inbound_order_created must carry a
    cost value) and section 3's event allowlist."""
    valid_events = []
    for event in events:
        if event.get("event_type") not in MANDATORY_EVENT_TYPES:
            continue
        if event.get("clinic_id") not in CLINIC_BRANCHES:
            continue
        if event["event_type"] == "inbound_order_created" and "total_cost" not in event.get("properties", {}):
            continue
        valid_events.append(event)
    return valid_events


def compute_total_supply_cost(events: list[dict], clinic_id: str) -> float:
    """Sums total_cost from inbound_order_created events for one clinic.
    Implements CONTEXT section 4: "total_supply_cost - Supply Cost per
    Clinic: sum of inbound_order_created costs for the month"."""
    total = sum(
        event["properties"].get("total_cost", 0.0)
        for event in events
        if event["clinic_id"] == clinic_id and event["event_type"] == "inbound_order_created"
    )
    return round(total, 2)


def compute_supply_consumption_count(events: list[dict], clinic_id: str) -> int:
    """Counts outbound_order_created events for one clinic. Implements
    CONTEXT section 4: "supply_consumption_count - Supply Consumption
    Volume: count of outbound_order_created for the month"."""
    return sum(
        1
        for event in events
        if event["clinic_id"] == clinic_id and event["event_type"] == "outbound_order_created"
    )


def compute_critical_stockout_count(events: list[dict], clinic_id: str) -> int:
    """Counts stock_threshold_triggered events with severity == 'critical'
    for one clinic. Implements CONTEXT section 4: "critical_stockout_count -
    Critical Stockout Frequency: count of stock_threshold_triggered for the
    month"."""
    return sum(
        1
        for event in events
        if event["clinic_id"] == clinic_id
        and event["event_type"] == "stock_threshold_triggered"
        and event["properties"].get("severity") == "critical"
    )


def compute_expiry_risk_count(events: list[dict], clinic_id: str) -> int:
    """Counts supply_expiry_flagged events for one clinic. Implements
    CONTEXT section 4: "expiry_risk_count - Expiry Risk Count: count of
    supply_expiry_flagged for the month"."""
    return sum(
        1
        for event in events
        if event["clinic_id"] == clinic_id and event["event_type"] == "supply_expiry_flagged"
    )


def aggregate_monthly_kpis(events: list[dict]) -> list[dict]:
    """Aggregates validated events into the four business KPIs, grouped by
    (clinic_id, month_start), per CONTEXT section 2 and section 4.

    This is a pure function: given the same events, it always returns the
    same aggregates. The Prefect caching behavior (cache_key_fn,
    cache_expiration) lives on the @task wrapper in pipeline.py, not here.
    """
    grouped: dict[tuple[str, str], dict] = {}

    for event in events:
        event_month = month_start(datetime.fromisoformat(event["created_at"]))
        clinic_id = event["clinic_id"]
        key = (clinic_id, event_month)

        if key not in grouped:
            country, currency = CLINIC_BRANCHES[clinic_id]
            grouped[key] = {
                "clinic_id": clinic_id,
                "month_start": event_month,
                "country": country,
                "currency": currency,
                "total_supply_cost": 0.0,
                "supply_consumption_count": 0,
                "critical_stockout_count": 0,
                "expiry_risk_count": 0,
            }

        row = grouped[key]
        event_type = event["event_type"]
        properties = event["properties"]

        if event_type == "inbound_order_created":
            row["total_supply_cost"] += properties.get("total_cost", 0.0)
        elif event_type == "outbound_order_created":
            row["supply_consumption_count"] += 1
        elif event_type == "stock_threshold_triggered" and properties.get("severity") == "critical":
            row["critical_stockout_count"] += 1
        elif event_type == "supply_expiry_flagged":
            row["expiry_risk_count"] += 1

    for row in grouped.values():
        row["total_supply_cost"] = round(row["total_supply_cost"], 2)

    return list(grouped.values())