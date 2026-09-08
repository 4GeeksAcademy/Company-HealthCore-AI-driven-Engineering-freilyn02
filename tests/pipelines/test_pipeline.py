"""Unit tests for the Monthly Clinic Supply Performance pipeline.

Per Milestone 6 Part 3's evaluation checklist, these tests target PURE
transformation helpers in data/process/transforms.py - no live DB, no
Prefect runtime. Run with:

    python -m pytest tests/pipelines/test_pipeline.py -v
"""
import sys
from pathlib import Path

import pytest

# --- sys.path bootstrap -----------------------------------------------------
# Mirrors the bootstrap in data/pipelines/pipeline.py so these tests resolve
# `from data.process.transforms import ...` regardless of how pytest is
# invoked (editor Run button, `pytest` from repo root, etc.).
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data.process.transforms import (
    aggregate_monthly_kpis,
    compute_critical_stockout_count,
    compute_expiry_risk_count,
    compute_supply_consumption_count,
    compute_total_supply_cost,
    month_start,
    normalize_event_payload,
    target_months,
    validate_supply_events,
)


# --- Fixtures shaped like company telemetry -------------------------------

@pytest.fixture
def austin_events():
    """A small, hand-checkable set of events for one US clinic
    (austin_north), covering all four CONTEXT KPIs in a single month."""
    return [
        {
            "event_type": "inbound_order_created",
            "clinic_id": "austin_north",
            "created_at": "2026-07-03T09:00:00+00:00",
            "properties": {"total_cost": 1200.50},
        },
        {
            "event_type": "inbound_order_created",
            "clinic_id": "austin_north",
            "created_at": "2026-07-15T09:00:00+00:00",
            "properties": {"total_cost": 349.50},
        },
        {
            "event_type": "outbound_order_created",
            "clinic_id": "austin_north",
            "created_at": "2026-07-05T09:00:00+00:00",
            "properties": {"quantity": 20},
        },
        {
            "event_type": "outbound_order_created",
            "clinic_id": "austin_north",
            "created_at": "2026-07-06T09:00:00+00:00",
            "properties": {"quantity": 15},
        },
        {
            "event_type": "stock_threshold_triggered",
            "clinic_id": "austin_north",
            "created_at": "2026-07-10T09:00:00+00:00",
            "properties": {"severity": "critical"},
        },
        {
            "event_type": "stock_threshold_triggered",
            "clinic_id": "austin_north",
            "created_at": "2026-07-12T09:00:00+00:00",
            "properties": {"severity": "warning"},
        },
        {
            "event_type": "supply_expiry_flagged",
            "clinic_id": "austin_north",
            "created_at": "2026-07-20T09:00:00+00:00",
            "properties": {"days_to_expiry": 5},
        },
    ]


# --- Transform tests (>=3 required) -----------------------------------------

def test_compute_total_supply_cost_for_known_inputs(austin_events):
    """Hand-calculated: 1200.50 + 349.50 = 1550.00 (CONTEXT section 4:
    "total_supply_cost - sum of inbound_order_created costs for the
    month")."""
    assert compute_total_supply_cost(austin_events, clinic_id="austin_north") == 1550.00


def test_compute_supply_consumption_count_for_known_inputs(austin_events):
    """Hand-calculated: 2 outbound_order_created events (CONTEXT section 4:
    "supply_consumption_count - count of outbound_order_created for the
    month")."""
    assert compute_supply_consumption_count(austin_events, clinic_id="austin_north") == 2


def test_compute_critical_stockout_count_ignores_warning_severity(austin_events):
    """Hand-calculated: 1 'critical' event; the 'warning' one must NOT be
    counted (CONTEXT section 4: "critical_stockout_count - count of
    stock_threshold_triggered for the month" - the reference pipeline only
    escalates 'critical' severity, matching Marcus/Claire's patient-safety
    concern, not every threshold event)."""
    assert compute_critical_stockout_count(austin_events, clinic_id="austin_north") == 1


def test_compute_expiry_risk_count_for_known_inputs(austin_events):
    """Hand-calculated: 1 supply_expiry_flagged event (CONTEXT section 4:
    "expiry_risk_count - count of supply_expiry_flagged for the month")."""
    assert compute_expiry_risk_count(austin_events, clinic_id="austin_north") == 1


# --- Defensive test (>=1 required) -------------------------------------------

def test_rejects_malformed_timestamp_raises():
    """A malformed event (timestamp/created_at missing or None) must raise,
    not silently produce a bad row - CONTEXT section 3 requires a cost value
    on inbound_order_created, and more generally every event needs a usable
    timestamp to be assigned to a month_start bucket."""
    raw = {"event_type": "stock_threshold_triggered", "clinic_id": "austin_north", "created_at": None}
    with pytest.raises(ValueError):
        normalize_event_payload(raw)


def test_rejects_event_missing_clinic_id():
    """A malformed event missing clinic_id must also raise - it cannot be
    assigned a country/currency (CONTEXT section 4 dimensions)."""
    raw = {"event_type": "supply_expiry_flagged", "created_at": "2026-07-01T00:00:00+00:00"}
    with pytest.raises(ValueError):
        normalize_event_payload(raw)


def test_validate_supply_events_drops_inbound_order_missing_total_cost():
    """validate_supply_events (used by the pipeline's own validation @task)
    silently drops - rather than raises on - an inbound_order_created event
    missing total_cost, per CONTEXT section 3's schema prerequisite."""
    events = [
        {
            "event_type": "inbound_order_created",
            "clinic_id": "austin_north",
            "created_at": "2026-07-01T00:00:00+00:00",
            "properties": {},  # no total_cost
        }
    ]
    assert validate_supply_events(events) == []


def test_validate_supply_events_drops_unknown_clinic():
    """An event for a clinic_id not in CLINIC_BRANCHES (e.g. 'central', the
    non-physical catch-all excluded per pipeline.py's docstring) must be
    dropped, not crash the aggregation."""
    events = [
        {
            "event_type": "supply_expiry_flagged",
            "clinic_id": "central",
            "created_at": "2026-07-01T00:00:00+00:00",
            "properties": {},
        }
    ]
    assert validate_supply_events(events) == []


# --- Hand-calculated KPI vs CONTEXT definition (>=1 required) ----------------

def test_aggregate_monthly_kpis_matches_hand_calc_for_austin(austin_events):
    """Full aggregation hand-checked against CONTEXT section 2 & 4
    definitions, for a single clinic/month:
      - total_supply_cost:       1200.50 + 349.50 = 1550.00
      - supply_consumption_count: 2
      - critical_stockout_count:  1 (warning excluded)
      - expiry_risk_count:        1
      - country/currency:         US / USD (CLINIC_BRANCHES lookup)
      - month_start:               2026-07-01 (grain: first day of month)
    """
    result = aggregate_monthly_kpis(austin_events)

    assert len(result) == 1  # single clinic, single month -> single row
    row = result[0]

    assert row["clinic_id"] == "austin_north"
    assert row["month_start"] == "2026-07-01"
    assert row["country"] == "US"
    assert row["currency"] == "USD"
    assert row["total_supply_cost"] == 1550.00
    assert row["supply_consumption_count"] == 2
    assert row["critical_stockout_count"] == 1
    assert row["expiry_risk_count"] == 1


def test_aggregate_monthly_kpis_never_mixes_currencies():
    """CONTEXT section 7 business constraint: 'Never mix currencies in a
    single aggregate row - USD (US clinics) and GBP (UK clinics) are
    reported separately, side by side, not summed together.' A US clinic
    and a UK clinic in the same month must produce two separate rows, each
    with its own currency - never merged."""
    events = [
        {
            "event_type": "inbound_order_created",
            "clinic_id": "austin_north",  # US / USD
            "created_at": "2026-07-01T00:00:00+00:00",
            "properties": {"total_cost": 500.0},
        },
        {
            "event_type": "inbound_order_created",
            "clinic_id": "london_city",  # UK / GBP
            "created_at": "2026-07-01T00:00:00+00:00",
            "properties": {"total_cost": 300.0},
        },
    ]
    result = aggregate_monthly_kpis(events)

    assert len(result) == 2
    by_clinic = {row["clinic_id"]: row for row in result}
    assert by_clinic["austin_north"]["currency"] == "USD"
    assert by_clinic["austin_north"]["total_supply_cost"] == 500.0
    assert by_clinic["london_city"]["currency"] == "GBP"
    assert by_clinic["london_city"]["total_supply_cost"] == 300.0


# --- Grain / watermark helpers ----------------------------------------------

def test_month_start_normalizes_to_first_of_month():
    """CONTEXT section 4: 'Grain: one row per clinic_id per calendar month
    (month_start = the first day of the month, UTC).'"""
    from datetime import datetime, timezone

    dt = datetime(2026, 7, 17, 14, 30, tzinfo=timezone.utc)
    assert month_start(dt) == "2026-07-01"


def test_target_months_returns_current_and_previous_month():
    """PIPELINE_DESIGN.md section 5's 2-month reprocessing window: given a
    reference date, target_months must return exactly [previous, current]."""
    from datetime import datetime, timezone

    reference = datetime(2026, 7, 17, tzinfo=timezone.utc)
    assert target_months(reference) == ["2026-06-01", "2026-07-01"]
